"""Markdown/course parsing and sanitization helpers for Class Hub views."""

import copy
from functools import lru_cache
from pathlib import Path
import re
from urllib.parse import urlparse

import bleach
import markdown as md
import yaml
from django.conf import settings

_COURSES_DIR = Path(settings.CONTENT_ROOT) / "courses"
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


@lru_cache(maxsize=256)
def _load_manifest_cached(path_str: str, mtime_ns: int) -> dict:
    manifest_path = Path(path_str)
    return yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}


@lru_cache(maxsize=512)
def _load_lesson_cached(path_str: str, mtime_ns: int) -> tuple[dict, str]:
    lesson_path = Path(path_str)
    raw = lesson_path.read_text(encoding="utf-8")
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) >= 3:
            front_matter_text = parts[1]
            validate_front_matter(front_matter_text, lesson_path)
            try:
                fm = yaml.safe_load(front_matter_text) or {}
            except yaml.scanner.ScannerError as exc:
                raise ValueError(f"Invalid YAML in {lesson_path}: {exc}") from exc
            body = parts[2].lstrip("\n")
            return fm, body
    return {}, raw


def validate_front_matter(front_matter_text: str, source: Path) -> None:
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


def load_course_manifest(course_slug: str) -> dict:
    manifest_path = _COURSES_DIR / course_slug / "course.yaml"
    if not manifest_path.exists():
        return {}
    mtime_ns = manifest_path.stat().st_mtime_ns
    return copy.deepcopy(_load_manifest_cached(str(manifest_path), mtime_ns))


def load_lesson_markdown(course_slug: str, lesson_slug: str) -> tuple[dict, str, dict]:
    """Return (front_matter, markdown_body, lesson_meta)."""
    manifest = load_course_manifest(course_slug)
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

    mtime_ns = lesson_path.stat().st_mtime_ns
    fm, body = _load_lesson_cached(str(lesson_path), mtime_ns)
    return copy.deepcopy(fm), body, match


def is_teacher_section_heading(heading_text: str) -> bool:
    normalized = re.sub(r"\s+", " ", (heading_text or "").strip().lower())
    if not normalized:
        return False
    if normalized.startswith("teacher "):
        return True
    return any(normalized.startswith(prefix) for prefix in _TEACHER_SECTION_PREFIXES)


def split_lesson_markdown_for_audiences(markdown_text: str) -> tuple[str, str]:
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
            chunk_is_teacher = is_teacher_section_heading(heading.group(1))
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


def teacher_panel_markdown(front_matter: dict) -> str:
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


def render_markdown_to_safe_html(markdown_text: str) -> str:
    allow_images = bool(getattr(settings, "CLASSHUB_MARKDOWN_ALLOW_IMAGES", False))
    allowed_hosts = {
        str(host).strip().lower()
        for host in getattr(settings, "CLASSHUB_MARKDOWN_ALLOWED_IMAGE_HOSTS", [])
        if str(host).strip()
    }

    def _img_src_allowed(value: str) -> bool:
        candidate = (value or "").strip()
        if not candidate:
            return False
        parsed = urlparse(candidate)
        if parsed.scheme in {"http", "https"}:
            host = (parsed.hostname or "").lower()
            return host in allowed_hosts
        if parsed.scheme or parsed.netloc:
            return False
        # Relative path (same-origin once rendered).
        return True

    def _img_attr_allowed(_tag: str, name: str, value: str) -> bool:
        if name == "src":
            return _img_src_allowed(value)
        if name in {"alt", "title", "loading", "decoding"}:
            return True
        return False

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
    if allow_images:
        allowed_tags.add("img")

    allowed_attrs = {
        **bleach.sanitizer.ALLOWED_ATTRIBUTES,
        "a": ["href", "title", "target", "rel"],
        "code": ["class"],
        "pre": ["class"],
        "h1": ["id"],
        "h2": ["id"],
        "h3": ["id"],
        "h4": ["id"],
    }
    if allow_images:
        allowed_attrs["img"] = _img_attr_allowed

    cleaned = bleach.clean(html, tags=list(allowed_tags), attributes=allowed_attrs, strip=True)
    return cleaned


def load_teacher_material_html(course_slug: str, lesson_slug: str) -> str:
    try:
        front_matter, body_markdown, _ = load_lesson_markdown(course_slug, lesson_slug)
    except ValueError:
        return ""

    _, teacher_body = split_lesson_markdown_for_audiences(body_markdown)
    teacher_panel = teacher_panel_markdown(front_matter)
    teacher_markdown = "\n\n".join(part.strip() for part in [teacher_panel, teacher_body] if part.strip()).strip()
    if not teacher_markdown:
        return ""
    return render_markdown_to_safe_html(teacher_markdown)
