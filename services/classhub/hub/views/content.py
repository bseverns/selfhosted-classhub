"""Course/markdown rendering endpoint callables."""

from django.db.utils import OperationalError, ProgrammingError
from django.http import HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import render
from django.template.loader import render_to_string
from common.helper_scope import issue_scope_token

from ..models import LessonVideo, Material, Module, Submission
from ..services.content_links import (
    courses_dir,
    extract_youtube_id,
    is_probably_video_url,
    normalize_lesson_videos,
    video_mime_type,
)
from ..services.markdown_content import (
    load_course_manifest,
    load_lesson_markdown,
    render_markdown_to_safe_html,
    split_lesson_markdown_for_audiences,
)
from ..services.release_state import lesson_release_state
from ..services.upload_policy import front_matter_submission


def course_overview(request, course_slug: str):
    """Tiny course landing page."""
    manifest = load_course_manifest(course_slug)
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
            media_type = video_mime_type(row.video_file.name)
            source_type = "native"
            embed_url = ""
        else:
            youtube_id = extract_youtube_id(url)
            if youtube_id:
                source_type = "youtube"
                embed_url = f"https://www.youtube.com/embed/{youtube_id}"
                media_url = ""
                media_type = ""
            elif is_probably_video_url(url):
                source_type = "native"
                embed_url = ""
                media_url = url
                media_type = video_mime_type(url)
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


def course_lesson(request, course_slug: str, lesson_slug: str):
    """Render a markdown lesson page from disk."""
    manifest = load_course_manifest(course_slug)
    if not manifest:
        return HttpResponse("Course not found", status=404)

    try:
        fm, body_md, lesson_meta = load_lesson_markdown(course_slug, lesson_slug)
    except ValueError as exc:
        return HttpResponse(f"Invalid lesson metadata: {exc}", status=500)
    if not body_md:
        return HttpResponse("Lesson not found", status=404)

    learner_body_md, _teacher_body_md = split_lesson_markdown_for_audiences(body_md)
    classroom_id = getattr(getattr(request, "classroom", None), "id", 0) or 0
    release_state = lesson_release_state(
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
    html = render_markdown_to_safe_html(learner_body_md)
    lesson_videos = normalize_lesson_videos(fm)
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
    lesson_submission = front_matter_submission(fm)
    lesson_upload_material = None
    lesson_upload_status = {}

    if (
        not lesson_locked
        and lesson_submission.get("type") == "file"
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
    helper_scope_token = issue_scope_token(
        context=helper_context,
        topics=helper_topics,
        allowed_topics=helper_allowed_topics,
        reference=helper_reference,
    )
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
                "helper_scope_token": helper_scope_token,
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


def iter_course_lesson_options() -> list[dict]:
    """Enumerate lesson options from course manifests for teacher tooling."""
    options: list[dict] = []
    root = courses_dir()
    if not root.exists():
        return options

    for manifest_path in sorted(root.glob("*/course.yaml")):
        course_slug = manifest_path.parent.name
        manifest = load_course_manifest(course_slug)
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


__all__ = [
    "course_overview",
    "course_lesson",
    "iter_course_lesson_options",
]
