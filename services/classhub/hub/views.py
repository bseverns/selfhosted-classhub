import json
import ipaddress
import mimetypes
import re
import tempfile
import zipfile
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse
from django.http import FileResponse, HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.middleware.csrf import get_token
from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.db import models, transaction
from django.db.utils import OperationalError, ProgrammingError
from django.core.cache import cache
from django.core import signing
from django.core.signing import BadSignature, SignatureExpired

import yaml
import markdown as md
import bleach

from .forms import SubmissionUploadForm
from .models import (
    Class,
    LessonRelease,
    LessonVideo,
    Module,
    Material,
    StudentIdentity,
    Submission,
    gen_class_code,
    gen_student_return_code,
)


# --- Repo-authored course content (markdown) ---------------------------------

_COURSES_DIR = Path(settings.CONTENT_ROOT) / "courses"
_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtu.be", "youtube-nocookie.com", "www.youtube-nocookie.com"}
_COURSE_LESSON_PATH_RE = re.compile(r"^/course/(?P<course_slug>[-a-zA-Z0-9_]+)/(?P<lesson_slug>[-a-zA-Z0-9_]+)$")
_HEADING_LEVEL2_RE = re.compile(r"^##\s+(.+?)\s*$")
_LEGACY_TEACHER_DETAILS_RE = re.compile(r"(?is)<details>\s*<summary>.*?teacher.*?</summary>.*?</details>")
_TEACHER_SECTION_PREFIXES = (
    "teacher prep",
    "teacher panel",
    "teacher notes",
    "agenda",
    "materials",
    "checkpoints",
    "common stuck points",
    "extensions (fast finisher menu)",
    "notes + options",
)
_VIDEO_EXTENSIONS = {
    ".m3u8",
    ".mp4",
    ".m4v",
    ".mov",
    ".webm",
    ".ogg",
    ".ogv",
}


def _validate_front_matter(front_matter_text: str, source: Path) -> None:
    for lineno, line in enumerate(front_matter_text.splitlines(), start=1):
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#") or stripped.startswith("-"):
            continue
        if ":" not in line:
            continue
        _, _, value = line.partition(":")
        value = value.strip()
        if not value:
            continue
        if value[0] in ('"', "'", "|", ">", "[", "{"):
            continue
        if ":" in value:
            raise ValueError(
                f"{source.name}:{lineno} unquoted colon in front matter line: {line.strip()}"
            )


def _load_course_manifest(course_slug: str) -> dict:
    manifest_path = _COURSES_DIR / course_slug / "course.yaml"
    if not manifest_path.exists():
        return {}
    return yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}


def _load_lesson_markdown(course_slug: str, lesson_slug: str) -> tuple[dict, str, dict]:
    """Return (front_matter, markdown_body, lesson_meta)."""
    manifest = _load_course_manifest(course_slug)
    lessons = manifest.get("lessons") or []
    match = next((l for l in lessons if (l.get("slug") == lesson_slug)), None)
    if not match:
        return {}, "", {}

    rel = match.get("file")
    if not rel:
        return {}, "", match
    lesson_path = (_COURSES_DIR / course_slug / rel).resolve()
    if not lesson_path.exists():
        return {}, "", match

    raw = lesson_path.read_text(encoding="utf-8")
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) >= 3:
            front_matter_text = parts[1]
            _validate_front_matter(front_matter_text, lesson_path)
            try:
                fm = yaml.safe_load(front_matter_text) or {}
            except yaml.scanner.ScannerError as exc:
                raise ValueError(f"Invalid YAML in {lesson_path}: {exc}") from exc
            body = parts[2].lstrip("\n")
            return fm, body, match
    return {}, raw, match


def _is_teacher_section_heading(heading_text: str) -> bool:
    normalized = re.sub(r"\s+", " ", (heading_text or "").strip().lower())
    if not normalized:
        return False
    if normalized.startswith("teacher "):
        return True
    return any(normalized.startswith(prefix) for prefix in _TEACHER_SECTION_PREFIXES)


def _split_lesson_markdown_for_audiences(markdown_text: str) -> tuple[str, str]:
    """Return (learner_markdown, teacher_markdown)."""
    if not (markdown_text or "").strip():
        return "", ""

    legacy_teacher_blocks = _LEGACY_TEACHER_DETAILS_RE.findall(markdown_text)
    stripped_markdown = _LEGACY_TEACHER_DETAILS_RE.sub("", markdown_text)

    learner_chunks: list[str] = []
    teacher_chunks: list[str] = []
    chunk_lines: list[str] = []
    chunk_is_teacher = False

    def flush_chunk():
        if not chunk_lines:
            return
        text = "\n".join(chunk_lines).strip()
        chunk_lines.clear()
        if not text:
            return
        if chunk_is_teacher:
            teacher_chunks.append(text)
        else:
            learner_chunks.append(text)

    for line in stripped_markdown.splitlines():
        heading = _HEADING_LEVEL2_RE.match(line)
        if heading:
            flush_chunk()
            chunk_lines.append(line)
            chunk_is_teacher = _is_teacher_section_heading(heading.group(1))
            continue
        chunk_lines.append(line)
    flush_chunk()

    for block in legacy_teacher_blocks:
        block = (block or "").strip()
        if block:
            teacher_chunks.append(block)

    learner_markdown = "\n\n".join(c for c in learner_chunks if c).strip()
    teacher_markdown = "\n\n".join(c for c in teacher_chunks if c).strip()

    if learner_markdown:
        learner_markdown += "\n"
    if teacher_markdown:
        teacher_markdown += "\n"
    return learner_markdown, teacher_markdown


def _teacher_panel_markdown(front_matter: dict) -> str:
    panel = front_matter.get("teacher_panel") or {}
    if not isinstance(panel, dict):
        return ""

    lines = ["## Teacher panel"]
    purpose = str(panel.get("purpose") or "").strip()
    if purpose:
        lines.extend(["", f"**Purpose:** {purpose}"])

    snags = panel.get("snags") or []
    if isinstance(snags, str):
        snags = [snags]
    snags = [str(s).strip() for s in snags if str(s).strip()]
    if snags:
        lines.extend(["", "**Common snags:**"])
        lines.extend([f"- {item}" for item in snags])

    assessment = panel.get("assessment") or []
    if isinstance(assessment, str):
        assessment = [assessment]
    assessment = [str(a).strip() for a in assessment if str(a).strip()]
    if assessment:
        lines.extend(["", "**What to look for:**"])
        lines.extend([f"- {item}" for item in assessment])

    if len(lines) == 1:
        return ""
    return "\n".join(lines).strip() + "\n"


def _load_teacher_material_html(course_slug: str, lesson_slug: str) -> str:
    try:
        front_matter, body_markdown, _ = _load_lesson_markdown(course_slug, lesson_slug)
    except ValueError:
        return ""

    _, teacher_body = _split_lesson_markdown_for_audiences(body_markdown)
    teacher_panel = _teacher_panel_markdown(front_matter)
    teacher_markdown = "\n\n".join(part.strip() for part in [teacher_panel, teacher_body] if part.strip()).strip()
    if not teacher_markdown:
        return ""
    return _render_markdown_to_safe_html(teacher_markdown)


def _render_markdown_to_safe_html(markdown_text: str) -> str:
    html = md.markdown(
        markdown_text,
        extensions=["fenced_code", "tables", "toc"],
        output_format="html5",
    )

    allowed_tags = set(bleach.sanitizer.ALLOWED_TAGS).union(
        {
            "p",
            "pre",
            "code",
            "h1",
            "h2",
            "h3",
            "h4",
            "hr",
            "br",
            "table",
            "thead",
            "tbody",
            "tr",
            "th",
            "td",
            "details",
            "summary",
        }
    )

    allowed_attrs = {
        **bleach.sanitizer.ALLOWED_ATTRIBUTES,
        "a": ["href", "title", "target", "rel"],
        "code": ["class"],
        "pre": ["class"],
    }

    cleaned = bleach.clean(html, tags=list(allowed_tags), attributes=allowed_attrs, strip=True)
    return cleaned


def _extract_youtube_id(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower()
    if ":" in host:
        host = host.split(":", 1)[0]
    if host not in _YOUTUBE_HOSTS:
        return ""

    video_id = ""
    if host.endswith("youtu.be"):
        video_id = parsed.path.lstrip("/").split("/", 1)[0]
    elif parsed.path == "/watch":
        video_id = parse_qs(parsed.query).get("v", [""])[0]
    elif parsed.path.startswith("/embed/") or parsed.path.startswith("/shorts/") or parsed.path.startswith("/live/"):
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) >= 2:
            video_id = parts[1]

    if re.fullmatch(r"[A-Za-z0-9_-]{6,20}", video_id or ""):
        return video_id
    return ""


def _safe_external_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url.strip())
    if parsed.scheme.lower() not in {"http", "https"}:
        return ""
    return url.strip()


def _is_probably_video_url(url: str) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    path = (parsed.path or "").lower()
    return any(path.endswith(ext) for ext in _VIDEO_EXTENSIONS)


def _video_mime_type(url: str) -> str:
    guessed, _ = mimetypes.guess_type(url or "")
    return guessed or "video/mp4"


def _title_from_video_filename(filename: str) -> str:
    stem = Path(filename or "").stem
    stem = re.sub(r"[_-]+", " ", stem)
    stem = re.sub(r"\s+", " ", stem).strip()
    return (stem[:200] or "Untitled video")


def _next_lesson_video_order(course_slug: str, lesson_slug: str) -> int:
    try:
        max_idx = (
            LessonVideo.objects.filter(course_slug=course_slug, lesson_slug=lesson_slug)
            .aggregate(models.Max("order_index"))
            .get("order_index__max")
        )
    except (OperationalError, ProgrammingError) as exc:
        # Fail open when schema is behind code deploys; callers can still continue.
        if "hub_lessonvideo" in str(exc).lower():
            return 0
        raise
    return int(max_idx) + 1 if max_idx is not None else 0


def _parse_course_lesson_url(url: str) -> tuple[str, str] | None:
    """Return (course_slug, lesson_slug) when url matches /course/<course>/<lesson>."""
    if not url:
        return None
    raw = (url or "").strip()
    if not raw:
        return None
    parsed = urlparse(raw)
    path = parsed.path if (parsed.scheme or parsed.netloc) else raw
    path = (path or "").rstrip("/") or "/"
    match = _COURSE_LESSON_PATH_RE.fullmatch(path)
    if not match:
        return None
    return (match.group("course_slug"), match.group("lesson_slug"))


def _normalize_lesson_videos(front_matter: dict) -> list[dict]:
    if not isinstance(front_matter, dict):
        return []

    videos = front_matter.get("videos") or []
    normalized = []
    for i, video in enumerate(videos, start=1):
        if not isinstance(video, dict):
            continue
        vid = str(video.get("id") or "").strip()
        title = str(video.get("title") or vid or f"Video {i}").strip()
        minutes = video.get("minutes")
        outcome = str(video.get("outcome") or "").strip()
        url = _safe_external_url(str(video.get("url") or "").strip())
        youtube_id = str(video.get("youtube_id") or "").strip()
        if youtube_id and not re.fullmatch(r"[A-Za-z0-9_-]{6,20}", youtube_id):
            youtube_id = ""
        if not youtube_id and url:
            youtube_id = _extract_youtube_id(url)
        if youtube_id and not url:
            url = f"https://www.youtube.com/watch?v={youtube_id}"
        embed_url = f"https://www.youtube.com/embed/{youtube_id}" if youtube_id else ""
        source_type = "youtube" if youtube_id else ("native" if _is_probably_video_url(url) else "link")
        media_url = url if source_type == "native" else ""
        media_type = _video_mime_type(url) if media_url else ""
        normalized.append(
            {
                "id": vid,
                "title": title,
                "minutes": minutes,
                "outcome": outcome,
                "url": url,
                "embed_url": embed_url,
                "source_type": source_type,
                "media_url": media_url,
                "media_type": media_type,
            }
        )
    return normalized


def healthz(request):
    return HttpResponse("ok", content_type="text/plain")


def index(request):
    """Landing page.

    - If student session exists, send them to /student
    - Otherwise, show join form

    Teachers/admins can use /admin for now.
    """
    if getattr(request, "student", None) is not None:
        return redirect("/student")
    get_token(request)
    return render(request, "student_join.html", {})


def _rate_limit(key: str, limit: int, window_seconds: int) -> bool:
    """Return True when request is within limit, False when blocked."""
    if limit <= 0:
        return True
    current = cache.get(key)
    if current is None:
        cache.set(key, 1, timeout=window_seconds)
        return True
    if int(current) >= limit:
        return False
    try:
        cache.incr(key)
    except Exception:
        cache.set(key, int(current) + 1, timeout=window_seconds)
    return True


def _client_ip(request) -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        for part in forwarded.split(","):
            candidate = part.strip()
            if not candidate:
                continue
            try:
                ipaddress.ip_address(candidate)
                return candidate
            except ValueError:
                continue

    remote = (request.META.get("REMOTE_ADDR", "") or "").strip()
    if remote:
        try:
            ipaddress.ip_address(remote)
            return remote
        except ValueError:
            pass
    return "unknown"


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

    client_ip = _client_ip(request)
    join_limit = int(getattr(settings, "JOIN_RATE_LIMIT_PER_MINUTE", 20))
    if not _rate_limit(f"join:ip:{client_ip}:m", limit=join_limit, window_seconds=60):
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
        # Serialize joins per class so return-code assignment and lookup stay deterministic.
        Class.objects.select_for_update().filter(id=classroom.id).first()

        student = None
        rejoined = False
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
        else:
            student = _load_device_hint_student(request, classroom, name)
            if student is not None:
                rejoined = True

        if student is None:
            student = _create_student_identity(classroom, name)

        student.last_seen_at = timezone.now()
        student.save(update_fields=["last_seen_at"])

    request.session["student_id"] = student.id
    request.session["class_id"] = classroom.id

    response = JsonResponse({"ok": True, "return_code": student.return_code, "rejoined": rejoined})
    _apply_device_hint_cookie(response, classroom, student)
    return response


def student_home(request):
    if getattr(request, "student", None) is None or getattr(request, "classroom", None) is None:
        return redirect("/")

    # Update last seen (cheap pulse; later do this asynchronously)
    request.student.last_seen_at = timezone.now()
    request.student.save(update_fields=["last_seen_at"])

    classroom = request.classroom
    modules = classroom.modules.prefetch_related("materials").all()
    lesson_release_cache: dict[tuple[str, str], dict] = {}
    module_lesson_cache: dict[int, tuple[str, str] | None] = {}
    release_override_map = _lesson_release_override_map(classroom.id)

    def _get_module_lesson(module: Module) -> tuple[str, str] | None:
        if module.id in module_lesson_cache:
            return module_lesson_cache[module.id]
        mats = list(module.materials.all())
        mats.sort(key=lambda m: (m.order_index, m.id))
        for mat in mats:
            if mat.type != Material.TYPE_LINK:
                continue
            parsed = _parse_course_lesson_url(mat.url)
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
            front_matter, _body, lesson_meta = _load_lesson_markdown(course_slug, lesson_slug)
        except ValueError:
            front_matter = {}
            lesson_meta = {}
        state = _lesson_release_state(
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

    # Submission status for this student (shown next to upload materials)
    material_ids = []
    material_access = {}
    for m in modules:
        module_lesson = _get_module_lesson(m)
        for mat in m.materials.all():
            material_ids.append(mat.id)
            access = {"is_locked": False, "available_on": None, "is_lesson_link": False, "is_lesson_upload": False}

            if mat.type == Material.TYPE_LINK:
                parsed = _parse_course_lesson_url(mat.url)
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


def _parse_extensions(ext_csv: str) -> list[str]:
    parts = [p.strip().lower() for p in (ext_csv or "").split(",") if p.strip()]
    out = []
    for p in parts:
        if not p.startswith("."):
            p = "." + p
        if p not in out:
            out.append(p)
    return out


def _front_matter_submission(front_matter: dict) -> dict:
    """Normalize lesson front-matter submission settings."""
    if not isinstance(front_matter, dict):
        return {"type": "", "accepted_exts": [], "naming": ""}

    submission = front_matter.get("submission") or {}
    if not isinstance(submission, dict):
        return {"type": "", "accepted_exts": [], "naming": ""}

    sub_type = str(submission.get("type") or "").strip().lower()
    naming = str(submission.get("naming") or "").strip()
    accepted = submission.get("accepted") or []
    if isinstance(accepted, str):
        accepted = [p.strip() for p in accepted.replace("|", ",").split(",") if p.strip()]

    accepted_exts = []
    for raw in accepted:
        ext = str(raw).strip().lower()
        if not ext:
            continue
        if not ext.startswith("."):
            ext = "." + ext
        if ext not in accepted_exts:
            accepted_exts.append(ext)

    return {"type": sub_type, "accepted_exts": accepted_exts, "naming": naming}


def _parse_release_date(raw) -> date | None:
    if raw is None:
        return None
    if isinstance(raw, date):
        return raw
    text = str(raw).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _lesson_available_on(front_matter: dict, lesson_meta: dict) -> date | None:
    if isinstance(front_matter, dict):
        for key in ("available_on", "release_date", "opens_on"):
            parsed = _parse_release_date(front_matter.get(key))
            if parsed is not None:
                return parsed
    if isinstance(lesson_meta, dict):
        for key in ("available_on", "release_date", "opens_on"):
            parsed = _parse_release_date(lesson_meta.get(key))
            if parsed is not None:
                return parsed
    return None


def _request_can_bypass_lesson_release(request) -> bool:
    return bool(request.user.is_authenticated and request.user.is_staff)


def _lesson_release_override_map(classroom_id: int) -> dict[tuple[str, str], LessonRelease]:
    if not classroom_id:
        return {}
    try:
        rows = LessonRelease.objects.filter(classroom_id=classroom_id).all()
    except (OperationalError, ProgrammingError) as exc:
        if "hub_lessonrelease" in str(exc).lower():
            return {}
        raise
    return {(row.course_slug, row.lesson_slug): row for row in rows}


def _lesson_release_state(
    request,
    front_matter: dict,
    lesson_meta: dict,
    classroom_id: int = 0,
    course_slug: str = "",
    lesson_slug: str = "",
    override_map: dict[tuple[str, str], LessonRelease] | None = None,
    respect_staff_bypass: bool = True,
) -> dict:
    base_available_on = _lesson_available_on(front_matter, lesson_meta)
    effective_available_on = base_available_on
    mode = "default"

    override = None
    if classroom_id and course_slug and lesson_slug:
        key = (course_slug, lesson_slug)
        if override_map is not None:
            override = override_map.get(key)
        else:
            try:
                override = LessonRelease.objects.filter(
                    classroom_id=classroom_id,
                    course_slug=course_slug,
                    lesson_slug=lesson_slug,
                ).first()
            except (OperationalError, ProgrammingError) as exc:
                if "hub_lessonrelease" in str(exc).lower():
                    override = None
                else:
                    raise

    if override:
        if override.force_locked:
            mode = "forced_locked"
            if override.available_on is not None:
                effective_available_on = override.available_on
            is_locked = True
        elif override.available_on is not None:
            mode = "scheduled_override"
            effective_available_on = override.available_on
            is_locked = timezone.localdate() < effective_available_on
        else:
            mode = "forced_open"
            effective_available_on = None
            is_locked = False
    else:
        is_locked = bool(effective_available_on and timezone.localdate() < effective_available_on)

    if respect_staff_bypass and _request_can_bypass_lesson_release(request):
        is_locked = False

    return {
        "available_on": effective_available_on,
        "is_locked": is_locked,
        "base_available_on": base_available_on,
        "has_override": bool(override),
        "override_available_on": override.available_on if override else None,
        "override_force_locked": bool(override.force_locked) if override else False,
        "mode": mode,
    }


def _safe_teacher_return_path(raw: str, fallback: str) -> str:
    parsed = urlparse((raw or "").strip())
    if parsed.scheme or parsed.netloc:
        return fallback
    if not parsed.path.startswith("/teach"):
        return fallback
    return (raw or "").strip() or fallback


def _with_notice(path: str, notice: str = "", error: str = "") -> str:
    params = {}
    if notice:
        params["notice"] = notice
    if error:
        params["error"] = error
    if not params:
        return path
    sep = "&" if "?" in path else "?"
    return f"{path}{sep}{urlencode(params)}"


def _intro_only_markdown(learner_markdown: str) -> str:
    lines = learner_markdown.splitlines()
    collected: list[str] = []
    for line in lines:
        if line.startswith("## "):
            break
        collected.append(line)
    intro = "\n".join(collected).strip()
    if intro:
        return intro + "\n"
    return "### Intro\nYour teacher will open the full lesson on the scheduled date.\n"


def _find_lesson_upload_material(classroom_id: int, course_slug: str, lesson_slug: str):
    """Find the upload material linked to a lesson for a specific class."""
    lesson_url = f"/course/{course_slug}/{lesson_slug}"
    module_ids = (
        Module.objects.filter(
            classroom_id=classroom_id,
            materials__type=Material.TYPE_LINK,
            materials__url=lesson_url,
        )
        .order_by("order_index", "id")
        .values_list("id", flat=True)
    )
    if not module_ids:
        return None

    return (
        Material.objects.filter(module_id__in=module_ids, type=Material.TYPE_UPLOAD)
        .order_by("module__order_index", "order_index", "id")
        .first()
    )


def _build_lesson_topics(front_matter: dict) -> list[str]:
    if not isinstance(front_matter, dict):
        return []

    topics = []
    makes = front_matter.get("makes")
    if makes:
        topics.append(f"Makes: {makes}")

    needs = front_matter.get("needs") or []
    if needs:
        joined = ", ".join(str(item).strip() for item in needs if item)
        if joined:
            topics.append(f"Needs: {joined}")

    videos = front_matter.get("videos") or []
    if videos:
        labels = []
        for video in videos:
            if isinstance(video, dict):
                label = video.get("id") or video.get("title")
                if label:
                    labels.append(label)
        if labels:
            topics.append("Videos: " + ", ".join(labels))

    session = front_matter.get("session")
    if session:
        topics.append(f"Session: {session}")

    helper_notes = front_matter.get("helper_notes") or []
    if helper_notes:
        notes = ", ".join(str(item).strip() for item in helper_notes if item)
        if notes:
            topics.append("Notes: " + notes)

    return topics


def _build_allowed_topics(front_matter: dict) -> list[str]:
    if not isinstance(front_matter, dict):
        return []
    allowed = front_matter.get("helper_allowed_topics") or front_matter.get("allowed_topics") or []
    if isinstance(allowed, str):
        parts = [p.strip() for p in allowed.split("|") if p.strip()]
        return parts
    if isinstance(allowed, list):
        return [str(p).strip() for p in allowed if str(p).strip()]
    return []


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
        parsed = _parse_course_lesson_url(candidate.url)
        if not parsed:
            continue
        try:
            front_matter, _body, lesson_meta = _load_lesson_markdown(parsed[0], parsed[1])
        except ValueError:
            front_matter = {}
            lesson_meta = {}
        release_state = _lesson_release_state(
            request,
            front_matter,
            lesson_meta,
            classroom_id=material.module.classroom_id,
            course_slug=parsed[0],
            lesson_slug=parsed[1],
        )
        break

    allowed_exts = _parse_extensions(material.accepted_extensions) or [".sb3"]
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
                Submission.objects.create(
                    material=material,
                    student=request.student,
                    original_filename=name,
                    file=f,
                    note=note,
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

    We intentionally avoid serving uploads as public /media files.
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


def course_overview(request, course_slug: str):
    """Tiny course landing page.

    This does not require a student session; it simply renders the manifest so
    teachers can verify links.
    """
    manifest = _load_course_manifest(course_slug)
    if not manifest:
        return HttpResponse("Course not found", status=404)

    return render(
        request,
        "course_overview.html",
        {
            "course_slug": course_slug,
            "course": manifest,
            "lessons": manifest.get("lessons") or [],
        },
    )


def course_lesson(request, course_slug: str, lesson_slug: str):
    """Render a markdown lesson page from disk."""
    manifest = _load_course_manifest(course_slug)
    if not manifest:
        return HttpResponse("Course not found", status=404)

    try:
        fm, body_md, lesson_meta = _load_lesson_markdown(course_slug, lesson_slug)
    except ValueError as exc:
        return HttpResponse(f"Invalid lesson metadata: {exc}", status=500)
    if not body_md:
        return HttpResponse("Lesson not found", status=404)

    learner_body_md, _teacher_body_md = _split_lesson_markdown_for_audiences(body_md)
    classroom_id = getattr(getattr(request, "classroom", None), "id", 0) or 0
    release_state = _lesson_release_state(
        request,
        fm,
        lesson_meta,
        classroom_id=classroom_id,
        course_slug=course_slug,
        lesson_slug=lesson_slug,
    )
    lesson_locked = bool(release_state.get("is_locked"))
    lesson_available_on = release_state.get("available_on")

    if lesson_locked:
        learner_body_md = _intro_only_markdown(learner_body_md)

    if not learner_body_md.strip():
        learner_body_md = "### Learner activity\nAsk your teacher for today's activity steps.\n"
    html = _render_markdown_to_safe_html(learner_body_md)
    lesson_videos = _normalize_lesson_videos(fm)
    lesson_videos.extend(_normalize_stored_lesson_videos(course_slug, lesson_slug))
    if lesson_locked:
        lesson_videos = []

    lessons = manifest.get("lessons") or []
    idx = next((i for i, l in enumerate(lessons) if l.get("slug") == lesson_slug), None)
    prev_l = lessons[idx - 1] if isinstance(idx, int) and idx > 0 else None
    next_l = lessons[idx + 1] if isinstance(idx, int) and idx + 1 < len(lessons) else None

    helper_context = fm.get("title") or lesson_slug
    helper_topics = _build_lesson_topics(fm)
    helper_allowed_topics = _build_allowed_topics(fm)
    lesson_submission = _front_matter_submission(fm)
    lesson_upload_material = None
    lesson_upload_status = {}

    if (
        not lesson_locked
        and
        lesson_submission.get("type") == "file"
        and getattr(request, "student", None) is not None
        and getattr(request, "classroom", None) is not None
    ):
        lesson_upload_material = _find_lesson_upload_material(request.classroom.id, course_slug, lesson_slug)
        if lesson_upload_material is not None:
            student_submissions = Submission.objects.filter(
                material=lesson_upload_material,
                student=request.student,
            )
            latest = student_submissions.only("id", "uploaded_at").first()
            if latest is not None:
                lesson_upload_status = {
                    "count": student_submissions.count(),
                    "last_uploaded_at": latest.uploaded_at,
                    "last_id": latest.id,
                }

    helper_reference = lesson_meta.get("helper_reference") or manifest.get("helper_reference") or ""
    helper_widget = ""
    can_use_helper = bool(
        getattr(request, "student", None) is not None
        or (request.user.is_authenticated and request.user.is_staff)
    )
    if not lesson_locked and can_use_helper:
        get_token(request)
        helper_widget = render_to_string(
            "includes/helper_widget.html",
            {
                "helper_title": "Lesson helper",
                "helper_description": "Need a hint for this lesson? Ask the helper to guide you without handing out answers.",
                "helper_context": helper_context,
                "helper_topics": " | ".join(helper_topics),
                "helper_reference": helper_reference,
                "helper_allowed_topics": " | ".join(helper_allowed_topics),
            },
        )

    return render(
        request,
        "lesson_page.html",
        {
            "course_slug": course_slug,
            "course": manifest,
            "lesson_slug": lesson_slug,
            "front_matter": fm,
            "lesson_html": html,
            "lesson_videos": lesson_videos,
            "prev": prev_l,
            "next": next_l,
            "helper_widget": helper_widget,
            "student": getattr(request, "student", None),
            "classroom": getattr(request, "classroom", None),
            "lesson_submission": lesson_submission,
            "lesson_upload_material": lesson_upload_material,
            "lesson_upload_status": lesson_upload_status,
            "lesson_locked": lesson_locked,
            "lesson_available_on": lesson_available_on,
        },
    )


def _iter_course_lesson_options() -> list[dict]:
    options: list[dict] = []
    if not _COURSES_DIR.exists():
        return options

    for manifest_path in sorted(_COURSES_DIR.glob("*/course.yaml")):
        course_slug = manifest_path.parent.name
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        course_title = str(manifest.get("title") or course_slug).strip()
        lessons = manifest.get("lessons") or []
        for lesson in lessons:
            lesson_slug = str(lesson.get("slug") or "").strip()
            if not lesson_slug:
                continue
            lesson_title = str(lesson.get("title") or lesson_slug).strip()
            session = lesson.get("session")
            options.append(
                {
                    "course_slug": course_slug,
                    "course_title": course_title,
                    "lesson_slug": lesson_slug,
                    "lesson_title": lesson_title,
                    "session": session,
                }
            )
    return options


def _normalize_stored_lesson_videos(course_slug: str, lesson_slug: str) -> list[dict]:
    try:
        rows = list(
            LessonVideo.objects.filter(course_slug=course_slug, lesson_slug=lesson_slug, is_active=True)
            .order_by("order_index", "id")
        )
    except (OperationalError, ProgrammingError) as exc:
        if "hub_lessonvideo" in str(exc).lower():
            return []
        raise
    normalized = []
    for row in rows:
        url = (row.source_url or "").strip()
        if row.video_file:
            media_url = f"/lesson-video/{row.id}/stream"
            media_type = _video_mime_type(row.video_file.name)
            source_type = "native"
            embed_url = ""
        else:
            youtube_id = _extract_youtube_id(url)
            if youtube_id:
                source_type = "youtube"
                embed_url = f"https://www.youtube.com/embed/{youtube_id}"
                media_url = ""
                media_type = ""
            elif _is_probably_video_url(url):
                source_type = "native"
                embed_url = ""
                media_url = url
                media_type = _video_mime_type(url)
            else:
                source_type = "link"
                embed_url = ""
                media_url = ""
                media_type = ""

        normalized.append(
            {
                "id": f"asset-{row.id}",
                "title": row.title,
                "minutes": row.minutes,
                "outcome": row.outcome,
                "url": url or media_url,
                "embed_url": embed_url,
                "source_type": source_type,
                "media_url": media_url,
                "media_type": media_type,
            }
        )
    return normalized


# --- Teacher cockpit (staff-only UI) ----------------------------------------


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


def _build_lesson_tracker_rows(request, classroom_id: int, modules: list[Module], student_count: int) -> list[dict]:
    rows: list[dict] = []
    upload_material_ids = []
    module_materials_map: dict[int, list[Material]] = {}
    teacher_material_html_by_lesson: dict[tuple[str, str], str] = {}
    lesson_title_by_lesson: dict[tuple[str, str], str] = {}
    lesson_release_by_lesson: dict[tuple[str, str], dict] = {}
    release_override_map = _lesson_release_override_map(classroom_id)

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
            # Prioritize the queue with the largest missing count.
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
            parsed = _parse_course_lesson_url(mat.url)
            if not parsed:
                continue
            lesson_key = parsed
            if lesson_key in seen_lessons:
                continue
            seen_lessons.add(lesson_key)
            course_slug, lesson_slug = parsed

            if lesson_key not in teacher_material_html_by_lesson:
                teacher_material_html_by_lesson[lesson_key] = _load_teacher_material_html(course_slug, lesson_slug)
                try:
                    front_matter, _body_markdown, lesson_meta = _load_lesson_markdown(course_slug, lesson_slug)
                except ValueError:
                    front_matter = {}
                    lesson_meta = {}
                lesson_title_by_lesson[lesson_key] = (
                    str(front_matter.get("title") or "").strip() or mat.title
                )
                lesson_release_by_lesson[lesson_key] = _lesson_release_state(
                    request,
                    front_matter,
                    lesson_meta,
                    classroom_id=classroom_id,
                    course_slug=course_slug,
                    lesson_slug=lesson_slug,
                    override_map=release_override_map,
                    respect_staff_bypass=False,
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
                }
            )

    return rows


def _request_can_view_lesson_video(request) -> bool:
    if request.user.is_authenticated and request.user.is_staff:
        return True
    if getattr(request, "student", None) is not None:
        return True
    return False


def _stream_file_with_range(request, file_path: Path, content_type: str):
    file_size = file_path.stat().st_size
    range_header = request.headers.get("Range") or request.META.get("HTTP_RANGE", "")
    if not range_header:
        response = FileResponse(open(file_path, "rb"), content_type=content_type)
        response["Content-Length"] = str(file_size)
        response["Accept-Ranges"] = "bytes"
        return response

    m = re.match(r"bytes=(\d*)-(\d*)", range_header)
    if not m:
        response = HttpResponse(status=416)
        response["Content-Range"] = f"bytes */{file_size}"
        return response

    start_raw, end_raw = m.group(1), m.group(2)
    if not start_raw and not end_raw:
        response = HttpResponse(status=416)
        response["Content-Range"] = f"bytes */{file_size}"
        return response

    if start_raw:
        start = int(start_raw)
        end = int(end_raw) if end_raw else file_size - 1
    else:
        suffix_len = int(end_raw)
        if suffix_len <= 0:
            response = HttpResponse(status=416)
            response["Content-Range"] = f"bytes */{file_size}"
            return response
        start = max(file_size - suffix_len, 0)
        end = file_size - 1

    if start >= file_size or end < start:
        response = HttpResponse(status=416)
        response["Content-Range"] = f"bytes */{file_size}"
        return response

    end = min(end, file_size - 1)
    length = (end - start) + 1

    file_handle = open(file_path, "rb")

    def _iter_file(handle, offset: int, remaining: int, chunk_size: int = 64 * 1024):
        try:
            handle.seek(offset)
            left = remaining
            while left > 0:
                chunk = handle.read(min(chunk_size, left))
                if not chunk:
                    break
                left -= len(chunk)
                yield chunk
        finally:
            handle.close()

    response = StreamingHttpResponse(
        _iter_file(file_handle, start, length),
        status=206,
        content_type=content_type,
    )
    response["Content-Length"] = str(length)
    response["Content-Range"] = f"bytes {start}-{end}/{file_size}"
    response["Accept-Ranges"] = "bytes"
    return response


def lesson_video_stream(request, video_id: int):
    try:
        video = LessonVideo.objects.filter(id=video_id).first()
    except (OperationalError, ProgrammingError) as exc:
        if "hub_lessonvideo" in str(exc).lower():
            return HttpResponse("Not found", status=404)
        raise
    if not video or not video.video_file:
        return HttpResponse("Not found", status=404)

    is_staff_user = bool(request.user.is_authenticated and request.user.is_staff)
    if not video.is_active and not is_staff_user:
        return HttpResponse("Not found", status=404)

    if not _request_can_view_lesson_video(request):
        return HttpResponse("Forbidden", status=403)

    try:
        file_path = Path(video.video_file.path)
    except Exception:
        return HttpResponse("Not found", status=404)
    if not file_path.exists():
        return HttpResponse("Not found", status=404)

    content_type = _video_mime_type(video.video_file.name)
    return _stream_file_with_range(request, file_path, content_type)


def _lesson_video_redirect_params(course_slug: str, lesson_slug: str, class_id: int = 0, notice: str = "") -> str:
    query = {"course_slug": course_slug, "lesson_slug": lesson_slug}
    if class_id:
        query["class_id"] = str(class_id)
    if notice:
        query["notice"] = notice
    return urlencode(query)


@staff_member_required
def teach_videos(request):
    try:
        class_id = int((request.GET.get("class_id") or request.POST.get("class_id") or "0").strip())
    except Exception:
        class_id = 0

    all_options = _iter_course_lesson_options()
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
        # Early check so missing migration is shown as a clear action item.
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
                    LessonVideo.objects.create(
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
                    LessonVideo.objects.create(
                        course_slug=selected_course_slug,
                        lesson_slug=selected_lesson_slug,
                        title=file_title,
                        source_url="",
                        video_file=file_obj,
                        order_index=next_order,
                        is_active=is_active,
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
                item.delete()
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
                notice = "Video order updated."

        if not error:
            query = _lesson_video_redirect_params(selected_course_slug, selected_lesson_slug, class_id, notice)
            return redirect(f"/teach/videos?{query}")

    lesson_video_rows = list(
        LessonVideo.objects.filter(course_slug=selected_course_slug, lesson_slug=selected_lesson_slug)
        .order_by("order_index", "id")
    ) if selected_course_slug and selected_lesson_slug else []
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
def teach_home(request):
    """Teacher landing page (outside /admin)."""
    classes = Class.objects.all().order_by("name", "id")
    recent_submissions = list(
        Submission.objects.select_related("student", "material__module__classroom")
        .all()[:20]
    )
    return render(
        request,
        "teach_home.html",
        {
            "classes": classes,
            "recent_submissions": recent_submissions,
        },
    )


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
        parsed_date = _parse_release_date(raw_date)
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
        return redirect(_with_notice(return_to, notice=f"Release date set to {parsed_date.isoformat()}."))

    if action == "toggle_lock":
        if release is None:
            release = LessonRelease.objects.create(
                classroom=classroom,
                course_slug=course_slug,
                lesson_slug=lesson_slug,
                force_locked=True,
            )
            return redirect(_with_notice(return_to, notice="Lesson locked."))
        release.force_locked = not release.force_locked
        release.save(update_fields=["force_locked", "updated_at"])
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
        return redirect(_with_notice(return_to, notice="Lesson opened now for this class."))

    if action == "reset_default":
        LessonRelease.objects.filter(
            classroom_id=classroom.id,
            course_slug=course_slug,
            lesson_slug=lesson_slug,
        ).delete()
        return redirect(_with_notice(return_to, notice="Lesson release reset to content default."))

    return redirect(_with_notice(return_to, error="Unknown release action."))


@staff_member_required
@require_POST
def teach_create_class(request):
    name = (request.POST.get("name") or "").strip()[:200]
    if not name:
        return redirect("/teach")

    # join_code must be unique
    join_code = gen_class_code()
    for _ in range(10):
        if not Class.objects.filter(join_code=join_code).exists():
            break
        join_code = gen_class_code()

    Class.objects.create(name=name, join_code=join_code)
    return redirect("/teach")


@staff_member_required
def teach_class_dashboard(request, class_id: int):
    classroom = Class.objects.filter(id=class_id).first()
    if not classroom:
        return HttpResponse("Not found", status=404)

    modules = list(classroom.modules.prefetch_related("materials").all())
    modules.sort(key=lambda m: (m.order_index, m.id))
    # normalize module order occasionally (cheap, safe)
    _normalize_order(modules)
    modules = list(classroom.modules.prefetch_related("materials").all())
    modules.sort(key=lambda m: (m.order_index, m.id))

    # Count submissions per upload material (latest only, by student)
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
    lesson_rows = _build_lesson_tracker_rows(request, classroom.id, modules, student_count)
    notice = (request.GET.get("notice") or "").strip()
    error = (request.GET.get("error") or "").strip()

    return render(
        request,
        "teach_class.html",
        {
            "classroom": classroom,
            "modules": modules,
            "student_count": student_count,
            "submission_counts": submission_counts,
            "lesson_rows": lesson_rows,
            "notice": notice,
            "error": error,
        },
    )


@staff_member_required
@require_POST
def teach_toggle_lock(request, class_id: int):
    classroom = Class.objects.filter(id=class_id).first()
    if not classroom:
        return HttpResponse("Not found", status=404)
    classroom.is_locked = not classroom.is_locked
    classroom.save(update_fields=["is_locked"])
    return redirect(f"/teach/class/{classroom.id}")


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

    return redirect(f"/teach/module/{module_id}")


def _safe_filename(s: str) -> str:
    s = (s or "file").strip()
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", s)
    s = s.strip("._")
    return s or "file"


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
        # Build a zip of latest submissions for each student.
        tmp = tempfile.NamedTemporaryFile(prefix="classhub_latest_", suffix=".zip", delete=False)
        tmp_path = tmp.name
        tmp.close()

        with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for st in students:
                s = latest_by_student.get(st.id)
                if not s:
                    continue
                try:
                    src_path = s.file.path
                except Exception:
                    continue
                base_name = _safe_filename(st.display_name)
                orig = _safe_filename(s.original_filename or Path(s.file.name).name)
                arc = f"{base_name}/{orig}"
                try:
                    z.write(src_path, arcname=arc)
                except Exception:
                    continue

        download_name = f"{_safe_filename(classroom.name)}_material_{material.id}_latest.zip"
        return FileResponse(open(tmp_path, "rb"), as_attachment=True, filename=download_name)

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
