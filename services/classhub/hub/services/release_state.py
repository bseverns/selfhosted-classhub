"""Lesson release-state helpers extracted from views for isolated testing."""

from datetime import date

from django.db.utils import OperationalError, ProgrammingError
from django.utils import timezone

from ..models import LessonRelease


def parse_release_date(raw) -> date | None:
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


def lesson_available_on(front_matter: dict, lesson_meta: dict) -> date | None:
    if isinstance(front_matter, dict):
        for key in ("available_on", "release_date", "opens_on"):
            parsed = parse_release_date(front_matter.get(key))
            if parsed is not None:
                return parsed
    if isinstance(lesson_meta, dict):
        for key in ("available_on", "release_date", "opens_on"):
            parsed = parse_release_date(lesson_meta.get(key))
            if parsed is not None:
                return parsed
    return None


def request_can_bypass_lesson_release(request) -> bool:
    return bool(request.user.is_authenticated and request.user.is_staff)


def lesson_release_override_map(classroom_id: int) -> dict[tuple[str, str], LessonRelease]:
    if not classroom_id:
        return {}
    try:
        rows = LessonRelease.objects.filter(classroom_id=classroom_id).all()
    except (OperationalError, ProgrammingError) as exc:
        if "hub_lessonrelease" in str(exc).lower():
            return {}
        raise
    return {(row.course_slug, row.lesson_slug): row for row in rows}


def lesson_release_state(
    request,
    front_matter: dict,
    lesson_meta: dict,
    classroom_id: int = 0,
    course_slug: str = "",
    lesson_slug: str = "",
    override_map: dict[tuple[str, str], LessonRelease] | None = None,
    respect_staff_bypass: bool = True,
) -> dict:
    base_available_on = lesson_available_on(front_matter, lesson_meta)
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

    if respect_staff_bypass and request_can_bypass_lesson_release(request):
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
