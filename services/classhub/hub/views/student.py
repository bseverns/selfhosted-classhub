"""Student/session/upload endpoint callables."""

import json
import logging
from pathlib import Path

from django.conf import settings
from django.core import signing
from django.core.signing import BadSignature, SignatureExpired
from django.db import transaction
from django.http import FileResponse, HttpResponse, JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.http import require_POST
from common.helper_scope import issue_scope_token

from ..forms import SubmissionUploadForm
from ..models import (
    Class,
    Material,
    Module,
    StudentEvent,
    StudentIdentity,
    Submission,
    gen_student_return_code,
)
from ..services.content_links import parse_course_lesson_url
from ..services.markdown_content import load_lesson_markdown
from ..services.release_state import lesson_release_override_map, lesson_release_state
from ..services.upload_scan import scan_uploaded_file
from ..services.upload_policy import parse_extensions
from common.request_safety import client_ip_from_request, fixed_window_allow

logger = logging.getLogger(__name__)


def _emit_student_event(
    *,
    event_type: str,
    classroom: Class | None,
    student: StudentIdentity | None,
    source: str,
    details: dict,
    ip_address: str = "",
) -> None:
    try:
        StudentEvent.objects.create(
            classroom=classroom,
            student=student,
            event_type=event_type,
            source=source,
            details=details or {},
            ip_address=(ip_address or None),
        )
    except Exception:
        logger.exception("student_event_write_failed type=%s", event_type)


def healthz(request):
    # Used by Caddy/ops checks to confirm the app process is alive.
    return HttpResponse("ok", content_type="text/plain")


def index(request):
    """Landing page.

    - If student session exists, send them to /student
    - Otherwise, show join form

    Teachers/admins sign in at /admin/login/ and then use /teach.
    """
    if getattr(request, "student", None) is not None:
        return redirect("/student")
    get_token(request)
    return render(request, "student_join.html", {})


def _create_student_identity(classroom: Class, display_name: str) -> StudentIdentity:
    for _ in range(20):
        code = gen_student_return_code().upper()
        if StudentIdentity.objects.filter(classroom=classroom, return_code=code).exists():
            continue
        return StudentIdentity.objects.create(
            classroom=classroom,
            display_name=display_name,
            return_code=code,
        )
    raise RuntimeError("could_not_allocate_unique_student_return_code")


def _device_hint_cookie_max_age_seconds() -> int:
    days = int(getattr(settings, "DEVICE_REJOIN_MAX_AGE_DAYS", 30))
    return max(days, 1) * 24 * 60 * 60


def _load_device_hint_student(request, classroom: Class, display_name: str) -> StudentIdentity | None:
    cookie_name = getattr(settings, "DEVICE_REJOIN_COOKIE_NAME", "classhub_student_hint")
    raw = request.COOKIES.get(cookie_name)
    if not raw:
        return None
    try:
        payload = signing.loads(
            raw,
            salt="classhub.student-device-hint",
            max_age=_device_hint_cookie_max_age_seconds(),
        )
    except (BadSignature, SignatureExpired):
        return None

    try:
        class_id = int(payload.get("class_id") or 0)
        student_id = int(payload.get("student_id") or 0)
    except Exception:
        return None
    if class_id != classroom.id or student_id <= 0:
        return None

    student = (
        StudentIdentity.objects.filter(id=student_id, classroom=classroom)
        .order_by("id")
        .first()
    )
    if student is None:
        return None
    if student.display_name.strip().casefold() != display_name.strip().casefold():
        return None
    return student


def _apply_device_hint_cookie(response: JsonResponse, classroom: Class, student: StudentIdentity) -> None:
    payload = {"class_id": classroom.id, "student_id": student.id}
    signed = signing.dumps(payload, salt="classhub.student-device-hint")
    response.set_cookie(
        getattr(settings, "DEVICE_REJOIN_COOKIE_NAME", "classhub_student_hint"),
        signed,
        max_age=_device_hint_cookie_max_age_seconds(),
        httponly=True,
        samesite="Lax",
        secure=not settings.DEBUG,
    )


@require_POST
def join_class(request):
    """Join via class code + display name.

    Body (JSON): {"class_code": "ABCD1234", "display_name": "Ada", "return_code": "ABC234"}

    Stores student identity in session cookie.
    If return_code is omitted, we may rejoin via signed same-device cookie hint.
    """
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "bad_json"}, status=400)

    client_ip = client_ip_from_request(
        request,
        trust_proxy_headers=getattr(settings, "REQUEST_SAFETY_TRUST_PROXY_HEADERS", True),
        xff_index=getattr(settings, "REQUEST_SAFETY_XFF_INDEX", 0),
    )
    join_limit = int(getattr(settings, "JOIN_RATE_LIMIT_PER_MINUTE", 20))
    if not fixed_window_allow(f"join:ip:{client_ip}:m", limit=join_limit, window_seconds=60):
        return JsonResponse({"error": "rate_limited"}, status=429)

    code = (payload.get("class_code") or "").strip().upper()
    name = (payload.get("display_name") or "").strip()[:80]
    return_code = (payload.get("return_code") or "").strip().upper()

    if not code or not name:
        return JsonResponse({"error": "missing_fields"}, status=400)

    classroom = Class.objects.filter(join_code=code).first()
    if not classroom:
        return JsonResponse({"error": "invalid_code"}, status=404)
    if classroom.is_locked:
        return JsonResponse({"error": "class_locked"}, status=403)

    with transaction.atomic():
        Class.objects.select_for_update().filter(id=classroom.id).first()

        student = None
        rejoined = False
        join_mode = "new"
        if return_code:
            student = (
                StudentIdentity.objects.filter(classroom=classroom, return_code=return_code)
                .order_by("id")
                .first()
            )
            if student is None:
                return JsonResponse({"error": "invalid_return_code"}, status=400)
            if student.display_name.strip().casefold() != name.strip().casefold():
                return JsonResponse({"error": "invalid_return_code"}, status=400)
            rejoined = True
            join_mode = "return_code"
        else:
            student = _load_device_hint_student(request, classroom, name)
            if student is not None:
                rejoined = True
                join_mode = "device_hint"

        if student is None:
            student = _create_student_identity(classroom, name)

        student.last_seen_at = timezone.now()
        student.save(update_fields=["last_seen_at"])

    request.session["student_id"] = student.id
    request.session["class_id"] = classroom.id
    request.session["class_epoch"] = int(getattr(classroom, "session_epoch", 1) or 1)

    response = JsonResponse({"ok": True, "return_code": student.return_code, "rejoined": rejoined})
    _apply_device_hint_cookie(response, classroom, student)
    if join_mode == "return_code":
        event_type = StudentEvent.EVENT_REJOIN_RETURN_CODE
    elif join_mode == "device_hint":
        event_type = StudentEvent.EVENT_REJOIN_DEVICE_HINT
    else:
        event_type = StudentEvent.EVENT_CLASS_JOIN
    _emit_student_event(
        event_type=event_type,
        classroom=classroom,
        student=student,
        source="classhub.join_class",
        details={
            "class_code": classroom.join_code,
            "display_name": student.display_name,
        },
        ip_address=client_ip,
    )
    return response


def student_home(request):
    if getattr(request, "student", None) is None or getattr(request, "classroom", None) is None:
        return redirect("/")

    request.student.last_seen_at = timezone.now()
    request.student.save(update_fields=["last_seen_at"])

    classroom = request.classroom
    modules = classroom.modules.prefetch_related("materials").all()
    lesson_release_cache: dict[tuple[str, str], dict] = {}
    module_lesson_cache: dict[int, tuple[str, str] | None] = {}
    release_override_map = lesson_release_override_map(classroom.id)

    def _get_module_lesson(module: Module) -> tuple[str, str] | None:
        if module.id in module_lesson_cache:
            return module_lesson_cache[module.id]
        mats = list(module.materials.all())
        mats.sort(key=lambda m: (m.order_index, m.id))
        for mat in mats:
            if mat.type != Material.TYPE_LINK:
                continue
            parsed = parse_course_lesson_url(mat.url)
            if parsed:
                module_lesson_cache[module.id] = parsed
                return parsed
        module_lesson_cache[module.id] = None
        return None

    def _get_release_state(course_slug: str, lesson_slug: str) -> dict:
        key = (course_slug, lesson_slug)
        if key in lesson_release_cache:
            return lesson_release_cache[key]
        try:
            front_matter, _body, lesson_meta = load_lesson_markdown(course_slug, lesson_slug)
        except ValueError:
            front_matter = {}
            lesson_meta = {}
        state = lesson_release_state(
            request,
            front_matter,
            lesson_meta,
            classroom_id=classroom.id,
            course_slug=course_slug,
            lesson_slug=lesson_slug,
            override_map=release_override_map,
        )
        lesson_release_cache[key] = state
        return state

    material_ids = []
    material_access = {}
    for m in modules:
        module_lesson = _get_module_lesson(m)
        for mat in m.materials.all():
            material_ids.append(mat.id)
            access = {"is_locked": False, "available_on": None, "is_lesson_link": False, "is_lesson_upload": False}

            if mat.type == Material.TYPE_LINK:
                parsed = parse_course_lesson_url(mat.url)
                if parsed:
                    state = _get_release_state(*parsed)
                    access["is_lesson_link"] = True
                    access["is_locked"] = bool(state.get("is_locked"))
                    access["available_on"] = state.get("available_on")
            elif mat.type == Material.TYPE_UPLOAD and module_lesson:
                state = _get_release_state(*module_lesson)
                access["is_lesson_upload"] = True
                access["is_locked"] = bool(state.get("is_locked"))
                access["available_on"] = state.get("available_on")

            material_access[mat.id] = access

    submissions_by_material = {}
    if material_ids:
        qs = (
            Submission.objects.filter(student=request.student, material_id__in=material_ids)
            .only("id", "material_id", "uploaded_at")
            .order_by("material_id", "-uploaded_at", "-id")
        )
        for s in qs:
            if s.material_id not in submissions_by_material:
                submissions_by_material[s.material_id] = {"count": 0, "last": s.uploaded_at, "last_id": s.id}
            submissions_by_material[s.material_id]["count"] += 1

    helper_widget = render_to_string(
        "includes/helper_widget.html",
        {
            "helper_title": "Class helper",
            "helper_description": "This is a Day-1 wire-up. It will become smarter once it can cite your class materials.",
            "helper_context": f"Classroom summary: {classroom.name}",
            "helper_topics": "Classroom overview",
            "helper_reference": "",
            "helper_allowed_topics": "",
            "helper_scope_token": issue_scope_token(
                context=f"Classroom summary: {classroom.name}",
                topics=["Classroom overview"],
                allowed_topics=[],
                reference="",
            ),
        },
    )
    get_token(request)

    return render(
        request,
        "student_class.html",
        {
            "student": request.student,
            "classroom": classroom,
            "modules": modules,
            "submissions_by_material": submissions_by_material,
            "material_access": material_access,
            "helper_widget": helper_widget,
        },
    )


def material_upload(request, material_id: int):
    """Student upload page for a Material of type=upload."""
    if getattr(request, "student", None) is None or getattr(request, "classroom", None) is None:
        return redirect("/")

    material = (
        Material.objects.select_related("module__classroom")
        .filter(id=material_id)
        .first()
    )
    if not material or material.module.classroom_id != request.classroom.id:
        return HttpResponse("Not found", status=404)
    if material.type != Material.TYPE_UPLOAD:
        return HttpResponse("Not an upload material", status=404)

    release_state = {"is_locked": False, "available_on": None}
    module_mats = list(material.module.materials.all())
    module_mats.sort(key=lambda m: (m.order_index, m.id))
    for candidate in module_mats:
        if candidate.type != Material.TYPE_LINK:
            continue
        parsed = parse_course_lesson_url(candidate.url)
        if not parsed:
            continue
        try:
            front_matter, _body, lesson_meta = load_lesson_markdown(parsed[0], parsed[1])
        except ValueError:
            front_matter = {}
            lesson_meta = {}
        release_state = lesson_release_state(
            request,
            front_matter,
            lesson_meta,
            classroom_id=material.module.classroom_id,
            course_slug=parsed[0],
            lesson_slug=parsed[1],
        )
        break

    allowed_exts = parse_extensions(material.accepted_extensions) or [".sb3"]
    max_bytes = int(material.max_upload_mb) * 1024 * 1024

    error = ""
    response_status = 200

    if release_state.get("is_locked"):
        available_on = release_state.get("available_on")
        if available_on:
            error = f"Submissions for this lesson open on {available_on.isoformat()}."
        else:
            error = "Submissions for this lesson are not open yet."
        if request.method == "POST":
            response_status = 403
    elif request.method == "POST":
        form = SubmissionUploadForm(request.POST, request.FILES)
        if form.is_valid():
            f = form.cleaned_data["file"]
            note = (form.cleaned_data.get("note") or "").strip()

            name = (getattr(f, "name", "") or "upload").strip()
            lower = name.lower()
            ext = "." + lower.rsplit(".", 1)[-1] if "." in lower else ""

            if ext not in allowed_exts:
                error = f"File type not allowed. Allowed: {', '.join(allowed_exts)}"
            elif getattr(f, "size", 0) and f.size > max_bytes:
                error = f"File too large. Max size: {material.max_upload_mb}MB"
            else:
                scan_result = scan_uploaded_file(f)
                fail_closed = bool(getattr(settings, "CLASSHUB_UPLOAD_SCAN_FAIL_CLOSED", False))
                if scan_result.status == "infected":
                    logger.warning(
                        "upload_blocked_malware material_id=%s student_id=%s message=%s",
                        material.id,
                        request.student.id,
                        scan_result.message,
                    )
                    error = "Upload blocked by malware scan. Ask your teacher for help."
                    response_status = 400
                elif scan_result.status == "error" and fail_closed:
                    logger.warning(
                        "upload_blocked_scan_error material_id=%s student_id=%s message=%s",
                        material.id,
                        request.student.id,
                        scan_result.message,
                    )
                    error = "Upload scanner unavailable right now. Please try again shortly."
                    response_status = 503
                else:
                    submission = Submission.objects.create(
                        material=material,
                        student=request.student,
                        original_filename=name,
                        file=f,
                        note=note,
                    )
                    _emit_student_event(
                        event_type=StudentEvent.EVENT_SUBMISSION_UPLOAD,
                        classroom=request.classroom,
                        student=request.student,
                        source="classhub.material_upload",
                        details={
                            "material_id": material.id,
                            "submission_id": submission.id,
                            "original_filename": name[:255],
                            "size_bytes": int(getattr(f, "size", 0) or 0),
                            "scan_status": scan_result.status,
                        },
                        ip_address=client_ip_from_request(
                            request,
                            trust_proxy_headers=getattr(settings, "REQUEST_SAFETY_TRUST_PROXY_HEADERS", True),
                            xff_index=getattr(settings, "REQUEST_SAFETY_XFF_INDEX", 0),
                        ),
                    )
                    return redirect(f"/material/{material.id}/upload")
    else:
        form = SubmissionUploadForm()

    submissions = Submission.objects.filter(material=material, student=request.student).all()

    return render(
        request,
        "material_upload.html",
        {
            "student": request.student,
            "classroom": request.classroom,
            "material": material,
            "allowed_exts": allowed_exts,
            "form": form,
            "error": error,
            "submissions": submissions,
            "upload_locked": bool(release_state.get("is_locked")),
            "upload_available_on": release_state.get("available_on"),
        },
        status=response_status,
    )


def submission_download(request, submission_id: int):
    """Download a submission.

    - Staff users can download any submission.
    - Students can only download their own submissions.
    """
    s = (
        Submission.objects.select_related("student", "material__module__classroom")
        .filter(id=submission_id)
        .first()
    )
    if not s:
        return HttpResponse("Not found", status=404)

    if request.user.is_authenticated and request.user.is_staff:
        pass
    else:
        if getattr(request, "student", None) is None:
            return redirect("/")
        if s.student_id != request.student.id:
            return HttpResponse("Forbidden", status=403)

    filename = s.original_filename or Path(s.file.name).name
    return FileResponse(s.file.open("rb"), as_attachment=True, filename=filename)


def student_logout(request):
    request.session.flush()
    return redirect("/")


__all__ = [
    "healthz",
    "index",
    "join_class",
    "student_home",
    "material_upload",
    "submission_download",
    "student_logout",
]
