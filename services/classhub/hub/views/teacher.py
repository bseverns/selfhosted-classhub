"""Teacher portal endpoint callables under /teach/*."""

import base64
import re
import tempfile
import zipfile
from datetime import datetime, time as dt_time, timedelta
from io import BytesIO
from pathlib import Path
from urllib.parse import urlencode, urlparse

import qrcode
from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.core import signing
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.db import IntegrityError, models
from django.db.utils import OperationalError, ProgrammingError
from django.http import FileResponse, HttpResponse
from django.shortcuts import redirect, render
from django.utils.safestring import mark_safe
from django.utils import timezone
from django.views.decorators.http import require_POST
from django_otp.plugins.otp_totp.models import TOTPDevice
from qrcode.image.svg import SvgPathImage

from ..models import (
    Class,
    LessonAsset,
    LessonAssetFolder,
    LessonRelease,
    LessonVideo,
    Material,
    Module,
    StudentEvent,
    StudentIdentity,
    Submission,
    gen_class_code,
)
from ..services.content_links import build_asset_url, parse_course_lesson_url
from ..services.filenames import safe_filename
from ..services.markdown_content import load_lesson_markdown, load_teacher_material_html
from ..services.authoring_templates import generate_authoring_templates
from ..services.audit import log_audit_event
from ..services.release_state import (
    lesson_release_override_map,
    lesson_release_state,
    parse_release_date,
)
from .content import _build_allowed_topics, _build_lesson_topics, iter_course_lesson_options


_TEMPLATE_SLUG_RE = re.compile(r"^[a-z0-9_-]+$")
_AUTHORING_TEMPLATE_SUFFIXES = {
    "teacher_plan_md": "teacher-plan-template.md",
    "teacher_plan_docx": "teacher-plan-template.docx",
    "public_overview_md": "public-overview-template.md",
    "public_overview_docx": "public-overview-template.docx",
}
_TEACHER_2FA_TOKEN_SALT = "classhub.teacher-2fa-setup"


def _teacher_2fa_device_name() -> str:
    configured = (getattr(settings, "TEACHER_2FA_DEVICE_NAME", "teacher-primary") or "").strip()
    return configured or "teacher-primary"


def _teacher_invite_max_age_seconds() -> int:
    raw = int(getattr(settings, "TEACHER_2FA_INVITE_MAX_AGE_SECONDS", 72 * 3600) or 0)
    return raw if raw > 0 else 72 * 3600


def _build_teacher_setup_token(user) -> str:
    payload = {
        "uid": int(user.id),
        "email": (user.email or "").strip().lower(),
        "username": (user.get_username() or "").strip(),
    }
    return signing.dumps(payload, salt=_TEACHER_2FA_TOKEN_SALT)


def _resolve_teacher_setup_user(token: str):
    if not token:
        return None, "Missing setup token."
    try:
        payload = signing.loads(
            token,
            salt=_TEACHER_2FA_TOKEN_SALT,
            max_age=_teacher_invite_max_age_seconds(),
        )
    except signing.SignatureExpired:
        return None, "This setup link expired. Ask an admin to send a new invite."
    except signing.BadSignature:
        return None, "Invalid setup link."

    try:
        user_id = int(payload.get("uid") or 0)
    except Exception:
        user_id = 0
    email = (payload.get("email") or "").strip().lower()
    username = (payload.get("username") or "").strip()
    if not user_id or not email or not username:
        return None, "Invalid setup link payload."

    User = get_user_model()
    user = User.objects.filter(
        id=user_id,
        username=username,
        email__iexact=email,
        is_staff=True,
        is_active=True,
    ).first()
    if not user:
        return None, "Invite is no longer valid for an active teacher account."
    return user, ""


def _totp_secret_base32(device: TOTPDevice) -> str:
    return base64.b32encode(device.bin_key).decode("ascii").rstrip("=")


def _format_base32_for_display(secret: str) -> str:
    groups = [secret[idx : idx + 4] for idx in range(0, len(secret), 4)]
    return " ".join(groups)


def _totp_qr_svg(config_url: str) -> str:
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=2,
    )
    qr.add_data(config_url)
    qr.make(fit=True)
    img = qr.make_image(image_factory=SvgPathImage)
    stream = BytesIO()
    img.save(stream)
    return stream.getvalue().decode("utf-8")


def _send_teacher_onboarding_email(request, *, user, setup_url: str, starting_password: str = ""):
    app_host = request.get_host()
    login_url = request.build_absolute_uri("/admin/login/")
    from_email = (getattr(settings, "TEACHER_INVITE_FROM_EMAIL", "") or "").strip() or getattr(
        settings, "DEFAULT_FROM_EMAIL", "classhub@localhost"
    )
    include_password = bool(starting_password)
    lines = [
        f"Hi {user.first_name or user.username},",
        "",
        "Your Class Hub teacher account is ready.",
        "",
        f"Username: {user.username}",
    ]
    if include_password:
        lines.extend(
            [
                f"Temporary password: {starting_password}",
                "",
                "Change your password after first sign-in.",
            ]
        )
    lines.extend(
        [
            "",
            "Finalize two-factor setup here:",
            setup_url,
            "",
            "What to do:",
            "1) Open the setup link.",
            "2) Scan the QR code in your authenticator app.",
            "3) Enter the 6-digit code to confirm.",
            "",
            f"Admin login: {login_url}",
            f"Host: {app_host}",
        ]
    )
    send_mail(
        subject="Complete your Class Hub teacher 2FA setup",
        message="\n".join(lines),
        from_email=from_email,
        recipient_list=[user.email],
        fail_silently=False,
    )


def teacher_logout(request):
    # Teacher/admin auth uses Django auth session, so call auth_logout first.
    auth_logout(request)
    # Also flush generic session keys to keep student and staff states cleanly separate.
    request.session.flush()
    return redirect("/admin/login/")


def _title_from_video_filename(filename: str) -> str:
    stem = Path(filename or "").stem
    stem = re.sub(r"[_-]+", " ", stem)
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem[:200] or "Untitled video"


def _next_lesson_video_order(course_slug: str, lesson_slug: str) -> int:
    try:
        max_idx = (
            LessonVideo.objects.filter(course_slug=course_slug, lesson_slug=lesson_slug)
            .aggregate(models.Max("order_index"))
            .get("order_index__max")
        )
    except (OperationalError, ProgrammingError) as exc:
        if "hub_lessonvideo" in str(exc).lower():
            return 0
        raise
    return int(max_idx) + 1 if max_idx is not None else 0


def _normalize_order(qs, field: str = "order_index"):
    """Normalize order_index values to 0..N-1 in current QS order."""
    for i, obj in enumerate(qs):
        if getattr(obj, field) != i:
            setattr(obj, field, i)
            obj.save(update_fields=[field])


def _material_submission_counts(material_ids: list[int]) -> dict[int, int]:
    counts = {}
    if not material_ids:
        return counts
    rows = (
        Submission.objects.filter(material_id__in=material_ids)
        .values("material_id", "student_id")
        .distinct()
    )
    for row in rows:
        material_id = int(row["material_id"])
        counts[material_id] = counts.get(material_id, 0) + 1
    return counts


def _material_latest_upload_map(material_ids: list[int]) -> dict[int, timezone.datetime]:
    latest = {}
    if not material_ids:
        return latest
    rows = (
        Submission.objects.filter(material_id__in=material_ids)
        .values("material_id")
        .annotate(last_uploaded_at=models.Max("uploaded_at"))
    )
    for row in rows:
        latest[int(row["material_id"])] = row["last_uploaded_at"]
    return latest


def _build_class_digest_rows(classes: list[Class], *, since: timezone.datetime) -> list[dict]:
    class_ids = [int(c.id) for c in classes if c and c.id]
    if not class_ids:
        return []

    student_totals: dict[int, int] = {}
    for row in (
        StudentIdentity.objects.filter(classroom_id__in=class_ids)
        .values("classroom_id")
        .annotate(total=models.Count("id"))
    ):
        student_totals[int(row["classroom_id"])] = int(row["total"] or 0)

    students_with_submissions: dict[int, int] = {}
    for row in (
        Submission.objects.filter(student__classroom_id__in=class_ids)
        .values("student__classroom_id")
        .annotate(total=models.Count("student_id", distinct=True))
    ):
        students_with_submissions[int(row["student__classroom_id"])] = int(row["total"] or 0)

    submission_totals_since: dict[int, int] = {}
    for row in (
        Submission.objects.filter(
            material__module__classroom_id__in=class_ids,
            uploaded_at__gte=since,
        )
        .values("material__module__classroom_id")
        .annotate(total=models.Count("id"))
    ):
        submission_totals_since[int(row["material__module__classroom_id"])] = int(row["total"] or 0)

    helper_events_since: dict[int, int] = {}
    for row in (
        StudentEvent.objects.filter(
            classroom_id__in=class_ids,
            event_type=StudentEvent.EVENT_HELPER_CHAT_ACCESS,
            created_at__gte=since,
        )
        .values("classroom_id")
        .annotate(total=models.Count("id"))
    ):
        helper_events_since[int(row["classroom_id"])] = int(row["total"] or 0)

    new_students_since: dict[int, int] = {}
    for row in (
        StudentIdentity.objects.filter(
            classroom_id__in=class_ids,
            created_at__gte=since,
        )
        .values("classroom_id")
        .annotate(total=models.Count("id"))
    ):
        new_students_since[int(row["classroom_id"])] = int(row["total"] or 0)

    last_submission_at: dict[int, timezone.datetime] = {}
    for row in (
        Submission.objects.filter(material__module__classroom_id__in=class_ids)
        .values("material__module__classroom_id")
        .annotate(last_uploaded_at=models.Max("uploaded_at"))
    ):
        class_id = int(row["material__module__classroom_id"])
        last_submission_at[class_id] = row["last_uploaded_at"]

    rows: list[dict] = []
    for classroom in classes:
        classroom_id = int(classroom.id)
        student_total = int(student_totals.get(classroom_id, 0))
        with_submissions = int(students_with_submissions.get(classroom_id, 0))
        students_without_submissions = max(student_total - with_submissions, 0)
        rows.append(
            {
                "classroom": classroom,
                "student_total": student_total,
                "new_students_since": int(new_students_since.get(classroom_id, 0)),
                "submission_total_since": int(submission_totals_since.get(classroom_id, 0)),
                "helper_access_total_since": int(helper_events_since.get(classroom_id, 0)),
                "students_without_submissions": students_without_submissions,
                "last_submission_at": last_submission_at.get(classroom_id),
            }
        )
    return rows


def _local_day_window() -> tuple[timezone.datetime, timezone.datetime]:
    today = timezone.localdate()
    zone = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(today, dt_time.min), zone)
    end = start + timedelta(days=1)
    return start, end


def _build_lesson_tracker_rows(request, classroom_id: int, modules: list[Module], student_count: int) -> list[dict]:
    rows: list[dict] = []
    upload_material_ids = []
    module_materials_map: dict[int, list[Material]] = {}
    teacher_material_html_by_lesson: dict[tuple[str, str], str] = {}
    lesson_title_by_lesson: dict[tuple[str, str], str] = {}
    lesson_release_by_lesson: dict[tuple[str, str], dict] = {}
    helper_defaults_by_lesson: dict[tuple[str, str], dict] = {}
    release_override_map = lesson_release_override_map(classroom_id)

    for module in modules:
        mats = list(module.materials.all())
        mats.sort(key=lambda m: (m.order_index, m.id))
        module_materials_map[module.id] = mats
        for mat in mats:
            if mat.type == Material.TYPE_UPLOAD:
                upload_material_ids.append(mat.id)

    submission_counts = _material_submission_counts(upload_material_ids)
    latest_upload_map = _material_latest_upload_map(upload_material_ids)

    for module in modules:
        mats = module_materials_map.get(module.id, [])
        dropboxes = []
        for mat in mats:
            if mat.type != Material.TYPE_UPLOAD:
                continue
            submitted = submission_counts.get(mat.id, 0)
            dropboxes.append(
                {
                    "id": mat.id,
                    "title": mat.title,
                    "submitted": submitted,
                    "missing": max(student_count - submitted, 0),
                    "last_uploaded_at": latest_upload_map.get(mat.id),
                }
            )

        review_dropbox = None
        if dropboxes:
            review_dropbox = max(dropboxes, key=lambda d: (d["missing"], d["submitted"], -int(d["id"])))

        if review_dropbox and review_dropbox["missing"] > 0:
            review_url = f"/teach/material/{review_dropbox['id']}/submissions?show=missing"
            review_label = f"Review missing now ({review_dropbox['missing']})"
        elif review_dropbox:
            review_url = f"/teach/material/{review_dropbox['id']}/submissions"
            review_label = "Review submissions"
        else:
            review_url = ""
            review_label = ""

        seen_lessons = set()
        for mat in mats:
            if mat.type != Material.TYPE_LINK:
                continue
            parsed = parse_course_lesson_url(mat.url)
            if not parsed:
                continue
            lesson_key = parsed
            if lesson_key in seen_lessons:
                continue
            seen_lessons.add(lesson_key)
            course_slug, lesson_slug = parsed

            if lesson_key not in teacher_material_html_by_lesson:
                teacher_material_html_by_lesson[lesson_key] = load_teacher_material_html(course_slug, lesson_slug)
                try:
                    front_matter, _body_markdown, lesson_meta = load_lesson_markdown(course_slug, lesson_slug)
                except ValueError:
                    front_matter = {}
                    lesson_meta = {}
                lesson_title_by_lesson[lesson_key] = (
                    str(front_matter.get("title") or "").strip() or mat.title
                )
                helper_defaults_by_lesson[lesson_key] = {
                    "context": str(front_matter.get("title") or lesson_slug).strip() or lesson_slug,
                    "topics": _build_lesson_topics(front_matter),
                    "allowed_topics": _build_allowed_topics(front_matter),
                    "reference": str(lesson_meta.get("helper_reference") or "").strip(),
                }
                lesson_release_by_lesson[lesson_key] = lesson_release_state(
                    request,
                    front_matter,
                    lesson_meta,
                    classroom_id=classroom_id,
                    course_slug=course_slug,
                    lesson_slug=lesson_slug,
                    override_map=release_override_map,
                    respect_staff_bypass=False,
                )

            release_override = release_override_map.get(lesson_key)
            helper_context_override = (getattr(release_override, "helper_context_override", "") or "").strip()
            helper_topics_override = (getattr(release_override, "helper_topics_override", "") or "").strip()
            helper_allowed_topics_override = (getattr(release_override, "helper_allowed_topics_override", "") or "").strip()
            helper_reference_override = (getattr(release_override, "helper_reference_override", "") or "").strip()
            has_helper_override = bool(
                helper_context_override
                or helper_topics_override
                or helper_allowed_topics_override
                or helper_reference_override
            )

            helper_defaults = helper_defaults_by_lesson.get(
                lesson_key,
                {"context": lesson_slug, "topics": [], "allowed_topics": [], "reference": ""},
            )
            rows.append(
                {
                    "module": module,
                    "lesson_title": lesson_title_by_lesson.get(lesson_key, mat.title),
                    "lesson_url": mat.url,
                    "course_slug": course_slug,
                    "lesson_slug": lesson_slug,
                    "dropboxes": dropboxes,
                    "review_url": review_url,
                    "review_label": review_label,
                    "teacher_material_html": teacher_material_html_by_lesson.get(lesson_key, ""),
                    "release_state": lesson_release_by_lesson.get(lesson_key, {}),
                    "helper_tuning": {
                        "has_override": has_helper_override,
                        "context_value": helper_context_override,
                        "topics_value": helper_topics_override,
                        "allowed_topics_value": helper_allowed_topics_override,
                        "reference_value": helper_reference_override,
                        "default_context": helper_defaults.get("context", ""),
                        "default_topics": helper_defaults.get("topics", []),
                        "default_allowed_topics": helper_defaults.get("allowed_topics", []),
                        "default_reference": helper_defaults.get("reference", ""),
                    },
                }
            )

    return rows


def _safe_teacher_return_path(raw: str, fallback: str) -> str:
    parsed = urlparse((raw or "").strip())
    if parsed.scheme or parsed.netloc:
        return fallback
    if not parsed.path.startswith("/teach"):
        return fallback
    return (raw or "").strip() or fallback


def _with_notice(path: str, notice: str = "", error: str = "", extra: dict | None = None) -> str:
    params = {}
    if notice:
        params["notice"] = notice
    if error:
        params["error"] = error
    for key, value in (extra or {}).items():
        if value is None:
            continue
        text = str(value).strip()
        if text:
            params[key] = text
    if not params:
        return path
    sep = "&" if "?" in path else "?"
    return f"{path}{sep}{urlencode(params)}"


def _audit(request, *, action: str, summary: str = "", classroom=None, target_type: str = "", target_id: str = "", metadata=None):
    log_audit_event(
        request,
        action=action,
        summary=summary,
        classroom=classroom,
        target_type=target_type,
        target_id=target_id,
        metadata=metadata or {},
    )


def _lesson_video_redirect_params(course_slug: str, lesson_slug: str, class_id: int = 0, notice: str = "") -> str:
    query = {"course_slug": course_slug, "lesson_slug": lesson_slug}
    if class_id:
        query["class_id"] = str(class_id)
    if notice:
        query["notice"] = notice
    return urlencode(query)


def _normalize_optional_slug_tag(raw: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_-]+", "-", (raw or "").strip().lower())
    return value.strip("-_")


def _parse_positive_int(raw: str, *, min_value: int, max_value: int) -> int | None:
    value = (raw or "").strip()
    if not value:
        return None
    try:
        parsed = int(value)
    except Exception:
        return None
    if parsed < min_value or parsed > max_value:
        return None
    return parsed


def _split_helper_topics_text(raw: str) -> list[str]:
    parts: list[str] = []
    normalized = (raw or "").replace("\r\n", "\n").replace("\r", "\n")
    for line in normalized.split("\n"):
        for segment in line.split("|"):
            token = segment.strip()
            if token:
                parts.append(token)
    return parts


def _normalize_helper_topics_text(raw: str) -> str:
    return "\n".join(_split_helper_topics_text(raw))


def _authoring_template_output_dir() -> Path:
    return Path(getattr(settings, "CLASSHUB_AUTHORING_TEMPLATE_DIR", "/uploads/authoring_templates"))


def _authoring_template_file_path(slug: str, kind: str) -> Path | None:
    suffix = _AUTHORING_TEMPLATE_SUFFIXES.get(kind)
    if not suffix:
        return None
    return _authoring_template_output_dir() / f"{slug}-{suffix}"


def _lesson_asset_redirect_params(folder_id: int = 0, course_slug: str = "", lesson_slug: str = "", status: str = "all", notice: str = "") -> str:
    query = {"status": status or "all"}
    if folder_id:
        query["folder_id"] = str(folder_id)
    if course_slug:
        query["course_slug"] = course_slug
    if lesson_slug:
        query["lesson_slug"] = lesson_slug
    if notice:
        query["notice"] = notice
    return urlencode(query)


@staff_member_required
def teach_videos(request):
    try:
        class_id = int((request.GET.get("class_id") or request.POST.get("class_id") or "0").strip())
    except Exception:
        class_id = 0

    all_options = iter_course_lesson_options()
    by_course: dict[str, dict] = {}
    for row in all_options:
        course_slug = row["course_slug"]
        if course_slug not in by_course:
            by_course[course_slug] = {
                "course_slug": course_slug,
                "course_title": row["course_title"],
                "lessons": [],
            }
        by_course[course_slug]["lessons"].append(
            {
                "lesson_slug": row["lesson_slug"],
                "lesson_title": row["lesson_title"],
                "session": row["session"],
            }
        )

    course_rows = list(by_course.values())
    course_rows.sort(key=lambda c: (c["course_title"].lower(), c["course_slug"]))
    for course_row in course_rows:
        course_row["lessons"].sort(key=lambda l: ((l["session"] or 0), l["lesson_title"].lower(), l["lesson_slug"]))

    selected_course_slug = (request.GET.get("course_slug") or request.POST.get("course_slug") or "").strip()
    if not selected_course_slug and course_rows:
        selected_course_slug = course_rows[0]["course_slug"]

    selected_course = next((c for c in course_rows if c["course_slug"] == selected_course_slug), None)
    lesson_rows = selected_course["lessons"] if selected_course else []
    selected_lesson_slug = (request.GET.get("lesson_slug") or request.POST.get("lesson_slug") or "").strip()
    if not selected_lesson_slug and lesson_rows:
        selected_lesson_slug = lesson_rows[0]["lesson_slug"]

    notice = (request.GET.get("notice") or "").strip()
    error = ""

    try:
        LessonVideo.objects.only("id").first()
        lesson_video_table_available = True
    except (OperationalError, ProgrammingError) as exc:
        if "hub_lessonvideo" in str(exc).lower():
            lesson_video_table_available = False
        else:
            raise

    if not lesson_video_table_available:
        class_back_link = f"/teach/class/{class_id}" if class_id else "/teach/lessons"
        return render(
            request,
            "teach_videos.html",
            {
                "course_rows": course_rows,
                "selected_course_slug": selected_course_slug,
                "selected_lesson_slug": selected_lesson_slug,
                "lesson_rows": lesson_rows,
                "lesson_video_rows": [],
                "published_count": 0,
                "draft_count": 0,
                "class_id": class_id,
                "class_back_link": class_back_link,
                "notice": notice,
                "error": "Lesson video table is missing. Run `python manage.py migrate` in `classhub_web`.",
            },
        )

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        if not selected_course_slug or not selected_lesson_slug:
            error = "Select a course + lesson first."
        elif action == "add":
            title = (request.POST.get("title") or "").strip()[:200]
            minutes_raw = (request.POST.get("minutes") or "").strip()
            outcome = (request.POST.get("outcome") or "").strip()[:300]
            source_url = (request.POST.get("source_url") or "").strip()
            video_file = request.FILES.get("video_file")
            is_active = (request.POST.get("is_active") or "1").strip() == "1"

            if not title:
                error = "Title is required."
            elif not source_url and not video_file:
                error = "Provide either a video URL or upload a video file."
            elif source_url and video_file:
                error = "Use URL or file upload, not both."
            else:
                minutes = None
                if minutes_raw:
                    try:
                        minutes = max(int(minutes_raw), 0)
                    except Exception:
                        error = "Minutes must be a whole number."

                if not error:
                    row = LessonVideo.objects.create(
                        course_slug=selected_course_slug,
                        lesson_slug=selected_lesson_slug,
                        title=title,
                        minutes=minutes,
                        outcome=outcome,
                        source_url=source_url,
                        video_file=video_file,
                        order_index=_next_lesson_video_order(selected_course_slug, selected_lesson_slug),
                        is_active=is_active,
                    )
                    _audit(
                        request,
                        action="lesson_video.add",
                        target_type="LessonVideo",
                        target_id=str(row.id),
                        summary=f"Added lesson video {selected_course_slug}/{selected_lesson_slug}",
                        metadata={"course_slug": selected_course_slug, "lesson_slug": selected_lesson_slug, "is_active": is_active},
                    )
                    notice = "Video saved." if is_active else "Video saved as draft."
        elif action == "bulk_upload":
            files = [f for f in request.FILES.getlist("video_files") if (getattr(f, "name", "") or "").strip()]
            title_prefix = (request.POST.get("title_prefix") or "").strip()[:80]
            is_active = (request.POST.get("bulk_is_active") or "1").strip() == "1"

            if not files:
                error = "Select one or more video files to upload."
            else:
                next_order = _next_lesson_video_order(selected_course_slug, selected_lesson_slug)
                added = 0
                for file_obj in files:
                    file_title = _title_from_video_filename(file_obj.name)
                    if title_prefix:
                        file_title = f"{title_prefix}: {file_title}"[:200]
                    row = LessonVideo.objects.create(
                        course_slug=selected_course_slug,
                        lesson_slug=selected_lesson_slug,
                        title=file_title,
                        source_url="",
                        video_file=file_obj,
                        order_index=next_order,
                        is_active=is_active,
                    )
                    _audit(
                        request,
                        action="lesson_video.bulk_add_item",
                        target_type="LessonVideo",
                        target_id=str(row.id),
                        summary=f"Bulk uploaded lesson video {selected_course_slug}/{selected_lesson_slug}",
                        metadata={"course_slug": selected_course_slug, "lesson_slug": selected_lesson_slug, "is_active": is_active},
                    )
                    next_order += 1
                    added += 1
                status_label = "published" if is_active else "draft"
                notice = f"Uploaded {added} video file(s) as {status_label}."
        elif action == "delete":
            try:
                video_id = int(request.POST.get("video_id") or 0)
            except Exception:
                video_id = 0
            item = LessonVideo.objects.filter(
                id=video_id,
                course_slug=selected_course_slug,
                lesson_slug=selected_lesson_slug,
            ).first()
            if item:
                item_id = item.id
                item.delete()
                _audit(
                    request,
                    action="lesson_video.delete",
                    target_type="LessonVideo",
                    target_id=str(item_id),
                    summary=f"Removed lesson video {selected_course_slug}/{selected_lesson_slug}",
                    metadata={"course_slug": selected_course_slug, "lesson_slug": selected_lesson_slug},
                )
                notice = "Video removed."
        elif action == "set_active":
            try:
                video_id = int(request.POST.get("video_id") or 0)
            except Exception:
                video_id = 0
            should_be_active = (request.POST.get("active") or "0").strip() == "1"
            item = LessonVideo.objects.filter(
                id=video_id,
                course_slug=selected_course_slug,
                lesson_slug=selected_lesson_slug,
            ).first()
            if item:
                item.is_active = should_be_active
                item.save(update_fields=["is_active", "updated_at"])
                _audit(
                    request,
                    action="lesson_video.set_active",
                    target_type="LessonVideo",
                    target_id=str(item.id),
                    summary=f"Set lesson video active={should_be_active}",
                    metadata={"course_slug": selected_course_slug, "lesson_slug": selected_lesson_slug, "is_active": should_be_active},
                )
                notice = "Video published." if should_be_active else "Video moved to draft."
        elif action == "move":
            try:
                video_id = int(request.POST.get("video_id") or 0)
            except Exception:
                video_id = 0
            direction = (request.POST.get("direction") or "").strip()
            rows = list(
                LessonVideo.objects.filter(course_slug=selected_course_slug, lesson_slug=selected_lesson_slug)
                .order_by("order_index", "id")
            )
            idx = next((i for i, row in enumerate(rows) if row.id == video_id), None)
            if idx is not None:
                if direction == "up" and idx > 0:
                    rows[idx - 1], rows[idx] = rows[idx], rows[idx - 1]
                elif direction == "down" and idx < len(rows) - 1:
                    rows[idx + 1], rows[idx] = rows[idx], rows[idx + 1]
                for i, row in enumerate(rows):
                    if row.order_index != i:
                        row.order_index = i
                        row.save(update_fields=["order_index"])
                _audit(
                    request,
                    action="lesson_video.reorder",
                    target_type="LessonVideo",
                    target_id=str(video_id),
                    summary=f"Reordered lesson videos for {selected_course_slug}/{selected_lesson_slug}",
                    metadata={"course_slug": selected_course_slug, "lesson_slug": selected_lesson_slug, "direction": direction},
                )
                notice = "Video order updated."

        if not error:
            query = _lesson_video_redirect_params(selected_course_slug, selected_lesson_slug, class_id, notice)
            return redirect(f"/teach/videos?{query}")

    lesson_video_rows = list(
        LessonVideo.objects.filter(course_slug=selected_course_slug, lesson_slug=selected_lesson_slug)
        .order_by("order_index", "id")
    ) if selected_course_slug and selected_lesson_slug else []
    for row in lesson_video_rows:
        row.stream_url = build_asset_url(f"/lesson-video/{row.id}/stream")
    published_count = sum(1 for row in lesson_video_rows if row.is_active)
    draft_count = max(len(lesson_video_rows) - published_count, 0)

    class_back_link = f"/teach/class/{class_id}" if class_id else "/teach/lessons"
    return render(
        request,
        "teach_videos.html",
        {
            "course_rows": course_rows,
            "selected_course_slug": selected_course_slug,
            "selected_lesson_slug": selected_lesson_slug,
            "lesson_rows": lesson_rows,
            "lesson_video_rows": lesson_video_rows,
            "published_count": published_count,
            "draft_count": draft_count,
            "class_id": class_id,
            "class_back_link": class_back_link,
            "notice": notice,
            "error": error,
        },
    )


@staff_member_required
def teach_assets(request):
    """Teacher-managed reference file library with optional lesson tags."""
    try:
        selected_folder_id = int((request.GET.get("folder_id") or request.POST.get("folder_id") or "0").strip())
    except Exception:
        selected_folder_id = 0

    selected_course_slug = _normalize_optional_slug_tag(
        (request.GET.get("course_slug") or request.POST.get("course_slug") or "").strip()
    )
    selected_lesson_slug = _normalize_optional_slug_tag(
        (request.GET.get("lesson_slug") or request.POST.get("lesson_slug") or "").strip()
    )
    status = (request.GET.get("status") or request.POST.get("status") or "all").strip().lower()
    if status not in {"all", "active", "inactive"}:
        status = "all"

    notice = (request.GET.get("notice") or "").strip()
    error = (request.GET.get("error") or "").strip()

    try:
        LessonAssetFolder.objects.only("id").first()
        LessonAsset.objects.only("id").first()
        lesson_asset_tables_available = True
    except (OperationalError, ProgrammingError) as exc:
        if "hub_lessonasset" in str(exc).lower():
            lesson_asset_tables_available = False
        else:
            raise

    if not lesson_asset_tables_available:
        return render(
            request,
            "teach_assets.html",
            {
                "folder_rows": [],
                "asset_rows": [],
                "selected_folder_id": selected_folder_id,
                "selected_course_slug": selected_course_slug,
                "selected_lesson_slug": selected_lesson_slug,
                "status": status,
                "active_count": 0,
                "inactive_count": 0,
                "notice": notice,
                "error": "Lesson asset tables are missing. Run `python manage.py migrate` in `classhub_web`.",
            },
        )

    folder_rows = list(LessonAssetFolder.objects.all().order_by("path", "id"))
    if not any(row.id == selected_folder_id for row in folder_rows):
        selected_folder_id = 0

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()

        if action == "create_folder":
            folder_path = (request.POST.get("folder_path") or "").strip()
            display_name = (request.POST.get("display_name") or "").strip()[:120]
            if not folder_path:
                error = "Folder path is required."
            else:
                folder = LessonAssetFolder(path=folder_path, display_name=display_name)
                try:
                    folder.save()
                except IntegrityError:
                    error = "That folder path already exists."
                else:
                    selected_folder_id = folder.id
                    _audit(
                        request,
                        action="lesson_asset_folder.create",
                        target_type="LessonAssetFolder",
                        target_id=str(folder.id),
                        summary=f"Created lesson asset folder {folder.path}",
                        metadata={"path": folder.path},
                    )
                    notice = f"Folder created: {folder.path}"

        elif action == "upload":
            try:
                upload_folder_id = int((request.POST.get("folder_id") or "0").strip())
            except Exception:
                upload_folder_id = 0
            folder = LessonAssetFolder.objects.filter(id=upload_folder_id).first()
            file_obj = request.FILES.get("asset_file")
            title = (request.POST.get("title") or "").strip()[:200]
            description = (request.POST.get("description") or "").strip()
            upload_course_slug = _normalize_optional_slug_tag((request.POST.get("course_slug") or "").strip())
            upload_lesson_slug = _normalize_optional_slug_tag((request.POST.get("lesson_slug") or "").strip())
            is_active = (request.POST.get("is_active") or "1").strip() == "1"

            if folder is None:
                error = "Select a folder before uploading."
            elif not file_obj:
                error = "Choose a file to upload."
            else:
                if not title:
                    title = _title_from_video_filename(getattr(file_obj, "name", ""))[:200]
                row = LessonAsset.objects.create(
                    folder=folder,
                    course_slug=upload_course_slug,
                    lesson_slug=upload_lesson_slug,
                    title=title,
                    description=description,
                    original_filename=(getattr(file_obj, "name", "") or "")[:255],
                    file=file_obj,
                    is_active=is_active,
                )
                _audit(
                    request,
                    action="lesson_asset.upload",
                    target_type="LessonAsset",
                    target_id=str(row.id),
                    summary=f"Uploaded lesson asset {row.title}",
                    metadata={
                        "folder": folder.path,
                        "course_slug": upload_course_slug,
                        "lesson_slug": upload_lesson_slug,
                        "is_active": is_active,
                    },
                )
                selected_folder_id = folder.id
                selected_course_slug = upload_course_slug
                selected_lesson_slug = upload_lesson_slug
                notice = "Asset uploaded."

        elif action == "set_active":
            try:
                asset_id = int((request.POST.get("asset_id") or "0").strip())
            except Exception:
                asset_id = 0
            should_be_active = (request.POST.get("active") or "0").strip() == "1"
            item = LessonAsset.objects.select_related("folder").filter(id=asset_id).first()
            if item:
                item.is_active = should_be_active
                item.save(update_fields=["is_active", "updated_at"])
                _audit(
                    request,
                    action="lesson_asset.set_active",
                    target_type="LessonAsset",
                    target_id=str(item.id),
                    summary=f"Set lesson asset active={should_be_active}",
                    metadata={"folder": item.folder.path, "is_active": should_be_active},
                )
                notice = "Asset is now visible to students." if should_be_active else "Asset moved to hidden draft."
                selected_folder_id = item.folder_id

        elif action == "delete":
            try:
                asset_id = int((request.POST.get("asset_id") or "0").strip())
            except Exception:
                asset_id = 0
            item = LessonAsset.objects.select_related("folder").filter(id=asset_id).first()
            if item:
                selected_folder_id = item.folder_id
                item_id = item.id
                folder_path = item.folder.path
                item.delete()
                _audit(
                    request,
                    action="lesson_asset.delete",
                    target_type="LessonAsset",
                    target_id=str(item_id),
                    summary="Deleted lesson asset",
                    metadata={"folder": folder_path},
                )
                notice = "Asset deleted."

        else:
            error = "Unknown action."

        if not error:
            query = _lesson_asset_redirect_params(
                folder_id=selected_folder_id,
                course_slug=selected_course_slug,
                lesson_slug=selected_lesson_slug,
                status=status,
                notice=notice,
            )
            return redirect(f"/teach/assets?{query}")

    asset_qs = LessonAsset.objects.select_related("folder").all()
    if selected_folder_id:
        asset_qs = asset_qs.filter(folder_id=selected_folder_id)
    if selected_course_slug:
        asset_qs = asset_qs.filter(course_slug=selected_course_slug)
    if selected_lesson_slug:
        asset_qs = asset_qs.filter(lesson_slug=selected_lesson_slug)
    if status == "active":
        asset_qs = asset_qs.filter(is_active=True)
    elif status == "inactive":
        asset_qs = asset_qs.filter(is_active=False)
    asset_rows = list(asset_qs.order_by("folder__path", "-updated_at", "id"))
    for row in asset_rows:
        row.download_url = build_asset_url(f"/lesson-asset/{row.id}/download")

    active_count = sum(1 for row in asset_rows if row.is_active)
    inactive_count = max(len(asset_rows) - active_count, 0)

    return render(
        request,
        "teach_assets.html",
        {
            "folder_rows": folder_rows,
            "asset_rows": asset_rows,
            "selected_folder_id": selected_folder_id,
            "selected_course_slug": selected_course_slug,
            "selected_lesson_slug": selected_lesson_slug,
            "status": status,
            "active_count": active_count,
            "inactive_count": inactive_count,
            "notice": notice,
            "error": error,
        },
    )


@staff_member_required
def teach_home(request):
    """Teacher landing page (outside /admin)."""
    notice = (request.GET.get("notice") or "").strip()
    error = (request.GET.get("error") or "").strip()
    template_slug = (request.GET.get("template_slug") or "").strip()
    template_title = (request.GET.get("template_title") or "").strip()
    template_sessions = (request.GET.get("template_sessions") or "").strip()
    template_duration = (request.GET.get("template_duration") or "").strip()
    teacher_username = (request.GET.get("teacher_username") or "").strip()
    teacher_email = (request.GET.get("teacher_email") or "").strip()
    teacher_first_name = (request.GET.get("teacher_first_name") or "").strip()
    teacher_last_name = (request.GET.get("teacher_last_name") or "").strip()
    teacher_invite_active = bool(
        teacher_username or teacher_email or teacher_first_name or teacher_last_name
    )

    classes = list(Class.objects.all().order_by("name", "id"))
    digest_since = timezone.now() - timedelta(days=1)
    class_digest_rows = _build_class_digest_rows(classes, since=digest_since)
    User = get_user_model()
    teacher_accounts = (
        User.objects.filter(is_staff=True)
        .order_by("username", "id")
        .only("id", "username", "first_name", "last_name", "email", "is_active", "is_superuser")
    )
    recent_submissions = list(
        Submission.objects.select_related("student", "material__module__classroom")
        .all()[:20]
    )
    output_dir = _authoring_template_output_dir()
    template_download_rows: list[dict] = []
    if template_slug and _TEMPLATE_SLUG_RE.match(template_slug):
        for kind, suffix in _AUTHORING_TEMPLATE_SUFFIXES.items():
            path = _authoring_template_file_path(template_slug, kind)
            exists = bool(path and path.exists() and path.is_file())
            template_download_rows.append(
                {
                    "kind": kind,
                    "label": f"{template_slug}-{suffix}",
                    "exists": exists,
                    "url": f"/teach/authoring-template/download?slug={template_slug}&kind={kind}",
                }
            )

    return render(
        request,
        "teach_home.html",
        {
            "classes": classes,
            "class_digest_rows": class_digest_rows,
            "digest_since": digest_since,
            "recent_submissions": recent_submissions,
            "notice": notice,
            "error": error,
            "template_slug": template_slug,
            "template_title": template_title,
            "template_sessions": template_sessions or "12",
            "template_duration": template_duration or "75",
            "template_output_dir": str(output_dir),
            "template_download_rows": template_download_rows,
            "teacher_accounts": teacher_accounts,
            "teacher_username": teacher_username,
            "teacher_email": teacher_email,
            "teacher_first_name": teacher_first_name,
            "teacher_last_name": teacher_last_name,
            "teacher_invite_active": teacher_invite_active,
        },
    )


@staff_member_required
@require_POST
def teach_generate_authoring_templates(request):
    slug = (request.POST.get("template_slug") or "").strip().lower()
    title = (request.POST.get("template_title") or "").strip()
    sessions_raw = (request.POST.get("template_sessions") or "").strip()
    duration_raw = (request.POST.get("template_duration") or "").strip()

    form_values = {
        "template_slug": slug,
        "template_title": title,
        "template_sessions": sessions_raw,
        "template_duration": duration_raw,
    }
    return_to = "/teach"

    if not slug:
        return redirect(_with_notice(return_to, error="Course slug is required.", extra=form_values))
    if not _TEMPLATE_SLUG_RE.match(slug):
        return redirect(_with_notice(return_to, error="Course slug can use lowercase letters, numbers, underscores, and dashes.", extra=form_values))
    if not title:
        return redirect(_with_notice(return_to, error="Course title is required.", extra=form_values))

    sessions = _parse_positive_int(sessions_raw, min_value=1, max_value=60)
    if sessions is None:
        return redirect(_with_notice(return_to, error="Sessions must be a whole number between 1 and 60.", extra=form_values))

    duration = _parse_positive_int(duration_raw, min_value=15, max_value=240)
    if duration is None:
        return redirect(_with_notice(return_to, error="Session duration must be between 15 and 240 minutes.", extra=form_values))

    age_band = (getattr(settings, "CLASSHUB_AUTHORING_TEMPLATE_AGE_BAND_DEFAULT", "5th-7th") or "5th-7th").strip()
    output_dir = Path(getattr(settings, "CLASSHUB_AUTHORING_TEMPLATE_DIR", "/uploads/authoring_templates"))

    try:
        result = generate_authoring_templates(
            slug=slug,
            title=title,
            sessions=sessions,
            duration=duration,
            age_band=age_band,
            out_dir=output_dir,
            overwrite=True,
        )
    except (OSError, ValueError) as exc:
        return redirect(_with_notice(return_to, error=f"Template generation failed: {exc}", extra=form_values))

    _audit(
        request,
        action="teacher_templates.generate",
        target_type="AuthoringTemplates",
        target_id=slug,
        summary=f"Generated authoring templates for {slug}",
        metadata={
            "slug": slug,
            "title": title,
            "sessions": sessions,
            "duration": duration,
            "output_dir": str(output_dir),
            "files": [str(path) for path in result.output_paths],
        },
    )
    notice = f"Generated templates for {slug} in {output_dir}."
    return redirect(_with_notice(return_to, notice=notice, extra=form_values))


@staff_member_required
def teach_download_authoring_template(request):
    slug = (request.GET.get("slug") or "").strip().lower()
    kind = (request.GET.get("kind") or "").strip()

    if not slug or not _TEMPLATE_SLUG_RE.match(slug):
        return HttpResponse("Invalid template slug.", status=400)

    path = _authoring_template_file_path(slug, kind)
    if path is None:
        return HttpResponse("Invalid template kind.", status=400)

    output_dir = _authoring_template_output_dir().resolve()
    candidate = path.resolve()
    if not candidate.is_relative_to(output_dir):
        return HttpResponse("Invalid template path.", status=400)
    if not candidate.exists() or not candidate.is_file():
        return HttpResponse("Template file not found.", status=404)

    _audit(
        request,
        action="teacher_templates.download",
        target_type="AuthoringTemplates",
        target_id=f"{slug}:{kind}",
        summary=f"Downloaded authoring template {candidate.name}",
        metadata={"slug": slug, "kind": kind, "path": str(candidate)},
    )
    return FileResponse(candidate.open("rb"), as_attachment=True, filename=candidate.name)


@staff_member_required
def teach_lessons(request):
    classes = list(Class.objects.all().order_by("name", "id"))
    try:
        class_id = int((request.GET.get("class_id") or "0").strip())
    except Exception:
        class_id = 0
    selected_class = next((c for c in classes if c.id == class_id), None)
    notice = (request.GET.get("notice") or "").strip()
    error = (request.GET.get("error") or "").strip()

    target_classes = [selected_class] if selected_class else classes
    class_rows = []
    for classroom in target_classes:
        if not classroom:
            continue
        student_count = classroom.students.count()
        modules = list(classroom.modules.prefetch_related("materials").all())
        modules.sort(key=lambda m: (m.order_index, m.id))
        lesson_rows = _build_lesson_tracker_rows(request, classroom.id, modules, student_count)
        class_rows.append(
            {
                "classroom": classroom,
                "student_count": student_count,
                "lesson_rows": lesson_rows,
            }
        )

    return render(
        request,
        "teach_lessons.html",
        {
            "classes": classes,
            "selected_class_id": selected_class.id if selected_class else 0,
            "class_rows": class_rows,
            "notice": notice,
            "error": error,
        },
    )


@staff_member_required
@require_POST
def teach_set_lesson_release(request):
    try:
        class_id = int((request.POST.get("class_id") or "0").strip())
    except Exception:
        class_id = 0

    default_return = f"/teach/lessons?class_id={class_id}" if class_id else "/teach/lessons"
    return_to = _safe_teacher_return_path((request.POST.get("return_to") or "").strip(), default_return)

    classroom = Class.objects.filter(id=class_id).first()
    if not classroom:
        return redirect(_with_notice(return_to, error="Class not found."))

    course_slug = (request.POST.get("course_slug") or "").strip()
    lesson_slug = (request.POST.get("lesson_slug") or "").strip()
    if not course_slug or not lesson_slug:
        return redirect(_with_notice(return_to, error="Missing course or lesson slug."))

    action = (request.POST.get("action") or "").strip()
    try:
        LessonRelease.objects.only("id").first()
    except (OperationalError, ProgrammingError) as exc:
        if "hub_lessonrelease" in str(exc).lower():
            return redirect(_with_notice(return_to, error="Lesson release table is missing. Run `python manage.py migrate`."))
        raise

    release = LessonRelease.objects.filter(
        classroom_id=classroom.id,
        course_slug=course_slug,
        lesson_slug=lesson_slug,
    ).first()

    if action == "set_date":
        raw_date = (request.POST.get("available_on") or "").strip()
        parsed_date = parse_release_date(raw_date)
        if parsed_date is None:
            return redirect(_with_notice(return_to, error="Enter a valid date (YYYY-MM-DD)."))
        if release is None:
            release = LessonRelease(
                classroom=classroom,
                course_slug=course_slug,
                lesson_slug=lesson_slug,
            )
        release.available_on = parsed_date
        release.force_locked = False
        release.save()
        _audit(
            request,
            action="lesson_release.set_date",
            classroom=classroom,
            target_type="LessonRelease",
            target_id=f"{course_slug}/{lesson_slug}",
            summary=f"Set lesson release date {parsed_date.isoformat()}",
            metadata={"course_slug": course_slug, "lesson_slug": lesson_slug, "available_on": parsed_date.isoformat()},
        )
        return redirect(_with_notice(return_to, notice=f"Release date set to {parsed_date.isoformat()}."))

    if action == "toggle_lock":
        if release is None:
            release = LessonRelease.objects.create(
                classroom=classroom,
                course_slug=course_slug,
                lesson_slug=lesson_slug,
                force_locked=True,
            )
            _audit(
                request,
                action="lesson_release.lock",
                classroom=classroom,
                target_type="LessonRelease",
                target_id=f"{course_slug}/{lesson_slug}",
                summary="Locked lesson",
                metadata={"course_slug": course_slug, "lesson_slug": lesson_slug, "force_locked": True},
            )
            return redirect(_with_notice(return_to, notice="Lesson locked."))
        release.force_locked = not release.force_locked
        release.save(update_fields=["force_locked", "updated_at"])
        _audit(
            request,
            action="lesson_release.toggle_lock",
            classroom=classroom,
            target_type="LessonRelease",
            target_id=f"{course_slug}/{lesson_slug}",
            summary=f"Toggled lesson lock to {release.force_locked}",
            metadata={"course_slug": course_slug, "lesson_slug": lesson_slug, "force_locked": release.force_locked},
        )
        if release.force_locked:
            return redirect(_with_notice(return_to, notice="Lesson locked."))
        return redirect(_with_notice(return_to, notice="Lesson lock removed."))

    if action == "unlock_now":
        if release is None:
            release = LessonRelease(
                classroom=classroom,
                course_slug=course_slug,
                lesson_slug=lesson_slug,
            )
        release.available_on = None
        release.force_locked = False
        release.save()
        _audit(
            request,
            action="lesson_release.unlock_now",
            classroom=classroom,
            target_type="LessonRelease",
            target_id=f"{course_slug}/{lesson_slug}",
            summary="Opened lesson now",
            metadata={"course_slug": course_slug, "lesson_slug": lesson_slug},
        )
        return redirect(_with_notice(return_to, notice="Lesson opened now for this class."))

    if action == "set_helper_scope":
        helper_context_override = (request.POST.get("helper_context_override") or "").strip()[:200]
        helper_topics_override = _normalize_helper_topics_text(request.POST.get("helper_topics_override") or "")
        helper_allowed_topics_override = _normalize_helper_topics_text(
            request.POST.get("helper_allowed_topics_override") or ""
        )
        helper_reference_override = (request.POST.get("helper_reference_override") or "").strip()[:200]
        has_helper_override = bool(
            helper_context_override
            or helper_topics_override
            or helper_allowed_topics_override
            or helper_reference_override
        )

        if release is None:
            if not has_helper_override:
                return redirect(_with_notice(return_to, notice="Helper tuning is using lesson defaults."))
            release = LessonRelease(
                classroom=classroom,
                course_slug=course_slug,
                lesson_slug=lesson_slug,
            )

        release.helper_context_override = helper_context_override
        release.helper_topics_override = helper_topics_override
        release.helper_allowed_topics_override = helper_allowed_topics_override
        release.helper_reference_override = helper_reference_override

        if (
            not has_helper_override
            and release.available_on is None
            and not release.force_locked
            and release.id is not None
        ):
            release.delete()
        else:
            release.save()

        _audit(
            request,
            action="lesson_release.set_helper_scope",
            classroom=classroom,
            target_type="LessonRelease",
            target_id=f"{course_slug}/{lesson_slug}",
            summary="Updated lesson helper tuning",
            metadata={
                "course_slug": course_slug,
                "lesson_slug": lesson_slug,
                "helper_context_override": helper_context_override,
                "helper_topics_override": helper_topics_override,
                "helper_allowed_topics_override": helper_allowed_topics_override,
                "helper_reference_override": helper_reference_override,
            },
        )
        if has_helper_override:
            return redirect(_with_notice(return_to, notice="Helper tuning saved for this lesson."))
        return redirect(_with_notice(return_to, notice="Helper tuning reset to lesson defaults."))

    if action == "reset_default":
        LessonRelease.objects.filter(
            classroom_id=classroom.id,
            course_slug=course_slug,
            lesson_slug=lesson_slug,
        ).delete()
        _audit(
            request,
            action="lesson_release.reset_default",
            classroom=classroom,
            target_type="LessonRelease",
            target_id=f"{course_slug}/{lesson_slug}",
            summary="Reset lesson release override",
            metadata={"course_slug": course_slug, "lesson_slug": lesson_slug},
        )
        return redirect(_with_notice(return_to, notice="Lesson release reset to content default."))

    return redirect(_with_notice(return_to, error="Unknown release action."))


@staff_member_required
@require_POST
def teach_create_class(request):
    name = (request.POST.get("name") or "").strip()[:200]
    if not name:
        return redirect("/teach")

    join_code = gen_class_code()
    for _ in range(10):
        if not Class.objects.filter(join_code=join_code).exists():
            break
        join_code = gen_class_code()

    classroom = Class.objects.create(name=name, join_code=join_code)
    _audit(
        request,
        action="class.create",
        classroom=classroom,
        target_type="Class",
        target_id=str(classroom.id),
        summary=f"Created class {classroom.name}",
        metadata={"join_code": classroom.join_code},
    )
    return redirect("/teach")


@staff_member_required
@require_POST
def teach_create_teacher(request):
    if not request.user.is_superuser:
        return redirect(_with_notice("/teach", error="Only superusers can create teacher accounts."))

    username = (request.POST.get("username") or "").strip()
    email = (request.POST.get("email") or "").strip()
    password = (request.POST.get("password") or "").strip()
    first_name = (request.POST.get("first_name") or "").strip()[:150]
    last_name = (request.POST.get("last_name") or "").strip()[:150]
    include_password_in_email = (request.POST.get("email_include_password") or "").strip() == "1"

    form_values = {
        "teacher_username": username,
        "teacher_email": email,
        "teacher_first_name": first_name,
        "teacher_last_name": last_name,
    }

    if not username:
        return redirect(_with_notice("/teach", error="Teacher username is required.", extra=form_values))
    if not email:
        return redirect(_with_notice("/teach", error="Teacher email is required.", extra=form_values))
    if not password:
        return redirect(_with_notice("/teach", error="Starting password is required.", extra=form_values))
    try:
        validate_email(email)
    except Exception:
        return redirect(_with_notice("/teach", error="Enter a valid teacher email address.", extra=form_values))

    User = get_user_model()
    if User.objects.filter(username=username).exists():
        return redirect(_with_notice("/teach", error="That username already exists.", extra=form_values))

    user = User.objects.create_user(
        username=username,
        email=email,
        password=password,
        first_name=first_name,
        last_name=last_name,
    )
    user.is_staff = True
    user.is_superuser = False
    user.is_active = True
    user.save(update_fields=["is_staff", "is_superuser", "is_active"])

    token = _build_teacher_setup_token(user)
    setup_url = request.build_absolute_uri(f"/teach/2fa/setup?{urlencode({'token': token})}")
    email_error = ""
    try:
        _send_teacher_onboarding_email(
            request,
            user=user,
            setup_url=setup_url,
            starting_password=password if include_password_in_email else "",
        )
    except Exception as exc:
        email_error = str(exc)

    _audit(
        request,
        action="teacher_account.create",
        target_type="User",
        target_id=str(user.id),
        summary=f"Created teacher account {user.username}",
        metadata={
            "username": user.username,
            "email": user.email,
            "email_sent": not bool(email_error),
            "invite_includes_password": include_password_in_email,
            "setup_url_host": urlparse(setup_url).netloc,
        },
    )

    if email_error:
        notice = f"Teacher account '{user.username}' created."
        error = f"Invite email failed: {email_error}"
        return redirect(_with_notice("/teach", notice=notice, error=error))

    notice = f"Teacher account '{user.username}' created and invite email sent."
    return redirect(_with_notice("/teach", notice=notice))


def _resolve_teacher_setup_context(request):
    requested_next = (request.GET.get("next") or request.POST.get("next") or "").strip()
    safe_next = requested_next if requested_next.startswith("/teach") and not requested_next.startswith("//") else ""
    token = (request.GET.get("token") or request.POST.get("token") or "").strip()
    if token:
        user, err = _resolve_teacher_setup_user(token)
        if err:
            return None, token, err, safe_next
        if not request.user.is_authenticated or request.user.pk != user.pk:
            user.backend = "django.contrib.auth.backends.ModelBackend"
            auth_login(request, user)
        return user, token, "", safe_next

    current = getattr(request, "user", None)
    if current and current.is_authenticated and current.is_staff and current.is_active:
        return current, "", "", safe_next

    return None, "", "Sign in first, or open a valid setup link from your invite email.", safe_next


def teach_teacher_2fa_setup(request):
    user, token, setup_error, safe_next = _resolve_teacher_setup_context(request)
    if user is None:
        login_next = "/teach/2fa/setup"
        if safe_next:
            login_next = f"{login_next}?{urlencode({'next': safe_next})}"
        login_url = f"/admin/login/?{urlencode({'next': login_next})}"
        if token:
            return render(
                request,
                "teach_setup_otp.html",
                {
                    "error": setup_error,
                    "token": token,
                    "otp_ready": False,
                    "already_configured": False,
                    "setup_user": None,
                    "next_path": safe_next,
                },
                status=400,
            )
        return redirect(login_url)

    device_name = _teacher_2fa_device_name()
    device = TOTPDevice.objects.filter(user=user, name=device_name).first()
    if device is None:
        device = TOTPDevice.objects.create(user=user, name=device_name, confirmed=False)

    notice = ""
    error = setup_error
    if request.method == "POST":
        otp_token = re.sub(r"\s+", "", (request.POST.get("otp_token") or "").strip())
        if device.confirmed:
            notice = "2FA is already configured for this account."
        elif not otp_token.isdigit() or len(otp_token) != int(device.digits or 6):
            error = f"Enter the {int(device.digits or 6)}-digit code from your authenticator app."
        elif not device.verify_token(otp_token):
            error = "Invalid code. Check your authenticator app and try again."
        else:
            device.confirmed = True
            device.save(update_fields=["confirmed"])
            _audit(
                request,
                action="teacher_2fa.enroll",
                target_type="User",
                target_id=str(user.id),
                summary=f"Completed teacher 2FA enrollment for {user.username}",
                metadata={"device_name": device.name},
            )
            redirect_to = safe_next if safe_next.startswith("/teach") else "/teach"
            return redirect(_with_notice(redirect_to, notice="2FA setup complete."))

    already_configured = bool(device.confirmed)
    qr_svg = ""
    manual_secret = ""
    config_url = ""
    if not already_configured:
        config_url = getattr(device, "config_url", "")
        if config_url:
            qr_svg = _totp_qr_svg(config_url)
        manual_secret = _format_base32_for_display(_totp_secret_base32(device))

    return render(
        request,
        "teach_setup_otp.html",
        {
            "setup_user": user,
            "token": token,
            "notice": notice,
            "error": error,
            "otp_ready": bool(config_url),
            "already_configured": already_configured,
            "config_url": config_url,
            "manual_secret": manual_secret,
            "qr_svg": mark_safe(qr_svg) if qr_svg else "",
            "digits": int(device.digits or 6),
            "next_path": safe_next,
        },
    )


@staff_member_required
def teach_class_dashboard(request, class_id: int):
    classroom = Class.objects.filter(id=class_id).first()
    if not classroom:
        return HttpResponse("Not found", status=404)

    modules = list(classroom.modules.prefetch_related("materials").all())
    modules.sort(key=lambda m: (m.order_index, m.id))
    _normalize_order(modules)
    modules = list(classroom.modules.prefetch_related("materials").all())
    modules.sort(key=lambda m: (m.order_index, m.id))

    upload_material_ids = []
    for m in modules:
        for mat in m.materials.all():
            if mat.type == Material.TYPE_UPLOAD:
                upload_material_ids.append(mat.id)

    submission_counts = {}
    if upload_material_ids:
        qs = (
            Submission.objects.filter(material_id__in=upload_material_ids)
            .values("material_id", "student_id")
            .distinct()
        )
        for row in qs:
            submission_counts[row["material_id"]] = submission_counts.get(row["material_id"], 0) + 1

    student_count = classroom.students.count()
    students = list(classroom.students.all().order_by("created_at", "id"))
    lesson_rows = _build_lesson_tracker_rows(request, classroom.id, modules, student_count)
    submission_counts_by_student: dict[int, int] = {}
    if students:
        rows = (
            Submission.objects.filter(student__classroom=classroom)
            .values("student_id")
            .annotate(total=models.Count("id"))
        )
        for row in rows:
            submission_counts_by_student[int(row["student_id"])] = int(row["total"])
    notice = (request.GET.get("notice") or "").strip()
    error = (request.GET.get("error") or "").strip()

    response = render(
        request,
        "teach_class.html",
        {
            "classroom": classroom,
            "modules": modules,
            "student_count": student_count,
            "students": students,
            "submission_counts": submission_counts,
            "submission_counts_by_student": submission_counts_by_student,
            "lesson_rows": lesson_rows,
            "notice": notice,
            "error": error,
        },
    )
    response["Cache-Control"] = "private, no-store"
    return response


@staff_member_required
def teach_class_join_card(request, class_id: int):
    classroom = Class.objects.filter(id=class_id).first()
    if not classroom:
        return HttpResponse("Not found", status=404)

    query = urlencode({"class_code": classroom.join_code})
    return render(
        request,
        "teach_join_card.html",
        {
            "classroom": classroom,
            "join_url": request.build_absolute_uri("/"),
            "prefilled_join_url": request.build_absolute_uri(f"/?{query}"),
        },
    )


@staff_member_required
@require_POST
def teach_rename_student(request, class_id: int):
    classroom = Class.objects.filter(id=class_id).first()
    if not classroom:
        return HttpResponse("Not found", status=404)

    try:
        student_id = int((request.POST.get("student_id") or "0").strip())
    except Exception:
        student_id = 0
    new_name = (request.POST.get("display_name") or "").strip()[:80]
    if not student_id:
        return redirect(_with_notice(f"/teach/class/{classroom.id}", error="Invalid student selection."))
    if not new_name:
        return redirect(_with_notice(f"/teach/class/{classroom.id}", error="Student name cannot be empty."))

    student = StudentIdentity.objects.filter(id=student_id, classroom=classroom).first()
    if student is None:
        return redirect(_with_notice(f"/teach/class/{classroom.id}", error="Student not found in this class."))

    old_name = student.display_name
    if old_name == new_name:
        return redirect(_with_notice(f"/teach/class/{classroom.id}", notice="No change applied to student name."))

    student.display_name = new_name
    student.save(update_fields=["display_name"])
    _audit(
        request,
        action="student.rename",
        classroom=classroom,
        target_type="StudentIdentity",
        target_id=str(student.id),
        summary=f"Renamed student {old_name} -> {new_name}",
        metadata={"old_name": old_name, "new_name": new_name},
    )
    return redirect(_with_notice(f"/teach/class/{classroom.id}", notice=f"Renamed student to {new_name}."))


@staff_member_required
@require_POST
def teach_reset_roster(request, class_id: int):
    classroom = Class.objects.filter(id=class_id).first()
    if not classroom:
        return HttpResponse("Not found", status=404)

    rotate_code = (request.POST.get("rotate_code") or "1").strip() == "1"

    students_qs = StudentIdentity.objects.filter(classroom=classroom)
    student_count = students_qs.count()
    submission_count = Submission.objects.filter(student__classroom=classroom).count()

    students_qs.delete()

    updated_fields = []
    classroom.session_epoch = int(getattr(classroom, "session_epoch", 1) or 1) + 1
    updated_fields.append("session_epoch")
    if rotate_code:
        join_code = gen_class_code()
        for _ in range(10):
            if not Class.objects.filter(join_code=join_code).exclude(id=classroom.id).exists():
                break
            join_code = gen_class_code()
        classroom.join_code = join_code
        updated_fields.append("join_code")
    classroom.save(update_fields=updated_fields)

    _audit(
        request,
        action="class.reset_roster",
        classroom=classroom,
        target_type="Class",
        target_id=str(classroom.id),
        summary=f"Reset roster for {classroom.name}",
        metadata={
            "students_deleted": student_count,
            "submissions_deleted": submission_count,
            "session_epoch": classroom.session_epoch,
            "rotated_join_code": rotate_code,
        },
    )

    notice = f"Roster reset complete. Removed {student_count} students and {submission_count} submissions."
    if rotate_code:
        notice += " Join code rotated."
    return redirect(_with_notice(f"/teach/class/{classroom.id}", notice=notice))


@staff_member_required
@require_POST
def teach_toggle_lock(request, class_id: int):
    classroom = Class.objects.filter(id=class_id).first()
    if not classroom:
        return HttpResponse("Not found", status=404)
    classroom.is_locked = not classroom.is_locked
    classroom.save(update_fields=["is_locked"])
    _audit(
        request,
        action="class.toggle_lock",
        classroom=classroom,
        target_type="Class",
        target_id=str(classroom.id),
        summary=f"Toggled class lock to {classroom.is_locked}",
        metadata={"is_locked": classroom.is_locked},
    )
    return redirect(f"/teach/class/{classroom.id}")


@staff_member_required
@require_POST
def teach_lock_class(request, class_id: int):
    classroom = Class.objects.filter(id=class_id).first()
    if not classroom:
        return HttpResponse("Not found", status=404)

    if not classroom.is_locked:
        classroom.is_locked = True
        classroom.save(update_fields=["is_locked"])

    _audit(
        request,
        action="class.lock",
        classroom=classroom,
        target_type="Class",
        target_id=str(classroom.id),
        summary=f"Locked class {classroom.name}",
        metadata={"is_locked": classroom.is_locked},
    )
    return redirect(_with_notice("/teach", notice=f"Locked class {classroom.name}."))


@staff_member_required
def teach_export_class_submissions_today(request, class_id: int):
    classroom = Class.objects.filter(id=class_id).first()
    if not classroom:
        return HttpResponse("Not found", status=404)

    day_start, day_end = _local_day_window()
    rows = list(
        Submission.objects.filter(
            student__classroom=classroom,
            uploaded_at__gte=day_start,
            uploaded_at__lt=day_end,
        )
        .select_related("student", "material")
        .order_by("student__display_name", "material__title", "uploaded_at", "id")
    )

    tmp = tempfile.TemporaryFile(mode="w+b")

    file_count = 0
    used_paths: set[str] = set()
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for sub in rows:
            try:
                source_path = sub.file.path
            except Exception:
                continue
            student_name = safe_filename(sub.student.display_name)
            material_name = safe_filename(sub.material.title)
            original = safe_filename(sub.original_filename or Path(sub.file.name).name)
            stamp = timezone.localtime(sub.uploaded_at).strftime("%H%M%S")
            candidate = f"{student_name}/{material_name}/{stamp}_{original}"
            if candidate in used_paths:
                candidate = f"{student_name}/{material_name}/{stamp}_{sub.id}_{original}"
            used_paths.add(candidate)
            try:
                archive.write(source_path, arcname=candidate)
            except Exception:
                continue
            file_count += 1
        if file_count == 0:
            archive.writestr(
                "README.txt",
                (
                    "No submission files were available for this class today.\n"
                    "This can happen when there were no uploads or file sources were unavailable.\n"
                ),
            )

    _audit(
        request,
        action="class.export_submissions_today",
        classroom=classroom,
        target_type="Class",
        target_id=str(classroom.id),
        summary=f"Exported today's submissions for {classroom.name}",
        metadata={
            "day_start": day_start.isoformat(),
            "day_end": day_end.isoformat(),
            "file_count": file_count,
        },
    )

    day_label = timezone.localdate().strftime("%Y%m%d")
    filename = f"{safe_filename(classroom.name)}_submissions_{day_label}.zip"
    tmp.seek(0)
    return FileResponse(tmp, as_attachment=True, filename=filename)


@staff_member_required
@require_POST
def teach_rotate_code(request, class_id: int):
    classroom = Class.objects.filter(id=class_id).first()
    if not classroom:
        return HttpResponse("Not found", status=404)

    join_code = gen_class_code()
    for _ in range(10):
        if not Class.objects.filter(join_code=join_code).exists():
            break
        join_code = gen_class_code()

    classroom.join_code = join_code
    classroom.save(update_fields=["join_code"])
    _audit(
        request,
        action="class.rotate_code",
        classroom=classroom,
        target_type="Class",
        target_id=str(classroom.id),
        summary="Rotated class join code",
        metadata={"join_code": classroom.join_code},
    )
    return redirect(f"/teach/class/{classroom.id}")


@staff_member_required
@require_POST
def teach_add_module(request, class_id: int):
    classroom = Class.objects.filter(id=class_id).first()
    if not classroom:
        return HttpResponse("Not found", status=404)

    title = (request.POST.get("title") or "").strip()[:200]
    if not title:
        return redirect(f"/teach/class/{class_id}")

    max_idx = classroom.modules.aggregate(models.Max("order_index")).get("order_index__max")
    order_index = int(max_idx) + 1 if max_idx is not None else 0

    mod = Module.objects.create(classroom=classroom, title=title, order_index=order_index)
    _audit(
        request,
        action="module.add",
        classroom=classroom,
        target_type="Module",
        target_id=str(mod.id),
        summary=f"Added module {mod.title}",
        metadata={"order_index": order_index},
    )
    return redirect(f"/teach/module/{mod.id}")


@staff_member_required
@require_POST
def teach_move_module(request, class_id: int):
    classroom = Class.objects.filter(id=class_id).first()
    if not classroom:
        return HttpResponse("Not found", status=404)

    module_id = int(request.POST.get("module_id") or 0)
    direction = (request.POST.get("direction") or "").strip()

    modules = list(classroom.modules.all())
    modules.sort(key=lambda m: (m.order_index, m.id))

    idx = next((i for i, m in enumerate(modules) if m.id == module_id), None)
    if idx is None:
        return redirect(f"/teach/class/{class_id}")

    if direction == "up" and idx > 0:
        modules[idx - 1], modules[idx] = modules[idx], modules[idx - 1]
    elif direction == "down" and idx < len(modules) - 1:
        modules[idx + 1], modules[idx] = modules[idx], modules[idx + 1]

    for i, m in enumerate(modules):
        if m.order_index != i:
            m.order_index = i
            m.save(update_fields=["order_index"])
    _audit(
        request,
        action="module.reorder",
        classroom=classroom,
        target_type="Module",
        target_id=str(module_id),
        summary=f"Reordered module {module_id}",
        metadata={"direction": direction},
    )

    return redirect(f"/teach/class/{class_id}")


@staff_member_required
def teach_module(request, module_id: int):
    module = Module.objects.select_related("classroom").prefetch_related("materials").filter(id=module_id).first()
    if not module:
        return HttpResponse("Not found", status=404)

    mats = list(module.materials.all())
    mats.sort(key=lambda m: (m.order_index, m.id))
    _normalize_order(mats)
    mats = list(module.materials.all())

    return render(
        request,
        "teach_module.html",
        {
            "classroom": module.classroom,
            "module": module,
            "materials": mats,
        },
    )


@staff_member_required
@require_POST
def teach_add_material(request, module_id: int):
    module = Module.objects.select_related("classroom").filter(id=module_id).first()
    if not module:
        return HttpResponse("Not found", status=404)

    mtype = (request.POST.get("type") or Material.TYPE_LINK).strip()
    title = (request.POST.get("title") or "").strip()[:200]
    if not title:
        return redirect(f"/teach/module/{module_id}")

    max_idx = module.materials.aggregate(models.Max("order_index")).get("order_index__max")
    order_index = int(max_idx) + 1 if max_idx is not None else 0

    mat = Material.objects.create(module=module, title=title, type=mtype, order_index=order_index)

    if mtype == Material.TYPE_LINK:
        mat.url = (request.POST.get("url") or "").strip()
        mat.save(update_fields=["url"])
    elif mtype == Material.TYPE_TEXT:
        mat.body = (request.POST.get("body") or "").strip()
        mat.save(update_fields=["body"])
    elif mtype == Material.TYPE_UPLOAD:
        mat.accepted_extensions = (request.POST.get("accepted_extensions") or ".sb3").strip()
        try:
            mat.max_upload_mb = int(request.POST.get("max_upload_mb") or 50)
        except Exception:
            mat.max_upload_mb = 50
        mat.save(update_fields=["accepted_extensions", "max_upload_mb"])
    _audit(
        request,
        action="material.add",
        classroom=module.classroom,
        target_type="Material",
        target_id=str(mat.id),
        summary=f"Added material {mat.title}",
        metadata={"type": mtype, "module_id": module.id},
    )

    return redirect(f"/teach/module/{module_id}")


@staff_member_required
@require_POST
def teach_move_material(request, module_id: int):
    module = Module.objects.filter(id=module_id).first()
    if not module:
        return HttpResponse("Not found", status=404)

    material_id = int(request.POST.get("material_id") or 0)
    direction = (request.POST.get("direction") or "").strip()

    mats = list(module.materials.all())
    mats.sort(key=lambda m: (m.order_index, m.id))

    idx = next((i for i, m in enumerate(mats) if m.id == material_id), None)
    if idx is None:
        return redirect(f"/teach/module/{module_id}")

    if direction == "up" and idx > 0:
        mats[idx - 1], mats[idx] = mats[idx], mats[idx - 1]
    elif direction == "down" and idx < len(mats) - 1:
        mats[idx + 1], mats[idx] = mats[idx], mats[idx + 1]

    for i, m in enumerate(mats):
        if m.order_index != i:
            m.order_index = i
            m.save(update_fields=["order_index"])
    _audit(
        request,
        action="material.reorder",
        classroom=module.classroom,
        target_type="Material",
        target_id=str(material_id),
        summary=f"Reordered material {material_id}",
        metadata={"direction": direction, "module_id": module.id},
    )

    return redirect(f"/teach/module/{module_id}")


@staff_member_required
def teach_material_submissions(request, material_id: int):
    material = (
        Material.objects.select_related("module__classroom")
        .filter(id=material_id)
        .first()
    )
    if not material or material.type != Material.TYPE_UPLOAD:
        return HttpResponse("Not found", status=404)

    classroom = material.module.classroom
    students = list(classroom.students.all().order_by("created_at", "id"))

    all_subs = list(
        Submission.objects.filter(material=material)
        .select_related("student")
        .order_by("-uploaded_at", "-id")
    )

    latest_by_student = {}
    count_by_student = {}
    for s in all_subs:
        sid = s.student_id
        count_by_student[sid] = count_by_student.get(sid, 0) + 1
        if sid not in latest_by_student:
            latest_by_student[sid] = s

    show = (request.GET.get("show") or "all").strip()

    if request.GET.get("download") == "zip_latest":
        tmp = tempfile.TemporaryFile(mode="w+b")

        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for st in students:
                s = latest_by_student.get(st.id)
                if not s:
                    continue
                try:
                    src_path = s.file.path
                except Exception:
                    continue
                base_name = safe_filename(st.display_name)
                orig = safe_filename(s.original_filename or Path(s.file.name).name)
                arc = f"{base_name}/{orig}"
                try:
                    z.write(src_path, arcname=arc)
                except Exception:
                    continue

        download_name = f"{safe_filename(classroom.name)}_material_{material.id}_latest.zip"
        tmp.seek(0)
        return FileResponse(tmp, as_attachment=True, filename=download_name)

    rows = []
    missing = 0
    for st in students:
        latest = latest_by_student.get(st.id)
        c = count_by_student.get(st.id, 0)
        if not latest:
            missing += 1
        rows.append(
            {
                "student": st,
                "latest": latest,
                "count": c,
            }
        )

    if show == "missing":
        rows = [r for r in rows if r["latest"] is None]
    elif show == "submitted":
        rows = [r for r in rows if r["latest"] is not None]

    return render(
        request,
        "teach_material_submissions.html",
        {
            "classroom": classroom,
            "module": material.module,
            "material": material,
            "rows": rows,
            "missing": missing,
            "student_count": len(students),
            "show": show,
        },
    )


__all__ = [
    "teacher_logout",
    "teach_home",
    "teach_teacher_2fa_setup",
    "teach_generate_authoring_templates",
    "teach_download_authoring_template",
    "teach_create_teacher",
    "teach_lessons",
    "teach_set_lesson_release",
    "teach_create_class",
    "teach_class_dashboard",
    "teach_class_join_card",
    "teach_rename_student",
    "teach_reset_roster",
    "teach_toggle_lock",
    "teach_lock_class",
    "teach_export_class_submissions_today",
    "teach_rotate_code",
    "teach_add_module",
    "teach_move_module",
    "teach_videos",
    "teach_assets",
    "teach_module",
    "teach_add_material",
    "teach_move_material",
    "teach_material_submissions",
]
