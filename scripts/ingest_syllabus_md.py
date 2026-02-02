#!/usr/bin/env python3
"""
Parse a syllabus Markdown or DOCX file and scaffold a course.

Inputs:
  --sessions-md  Teacher-facing session plan (.md or .docx) (required)
  --overview-md  Public-facing syllabus (.md or .docx) (optional)

Output:
  services/classhub/content/courses/<slug>/course.yaml
  services/classhub/content/courses/<slug>/lessons/*.md
"""
from __future__ import annotations

import argparse
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


COURSES_ROOT = Path("services/classhub/content/courses")

SESSION_RE = re.compile(r"^#?\s*Session\s*(\d+)\s*:\s*(.+)$", re.I)
HEADING_RE = re.compile(r"^(#{2,6})\s+(.*)")
BULLET_RE = re.compile(r"^\s*[-*•]\s+(.*)")
NUMBERED_RE = re.compile(r"^\s*\d+[.)]\s+(.*)")
META_RE = re.compile(r"^\*{0,2}(.+?)\*{0,2}\s*:\s*(.+)$")

SECTION_NAMES = {
    "teacher prep",
    "materials",
    "agenda",
    "checkpoints",
    "common stuck points + fixes",
    "common stuck points",
    "stuck points",
    "extensions",
}


def _slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text or "session"


def _yaml_quote(value: str) -> str:
    escaped = value.replace('"', '\\"')
    return f"\"{escaped}\""


def _yaml_list(key: str, items: list[str], indent: int = 0) -> str:
    if not items:
        return ""
    pad = " " * indent
    out = f"{pad}{key}:\n"
    for item in items:
        out += f"{pad}  - {_yaml_quote(item)}\n"
    return out


def _extract_bullets(lines: list[str]) -> list[str]:
    items = []
    for line in lines:
        m = BULLET_RE.match(line) or NUMBERED_RE.match(line)
        if m:
            items.append(m.group(1).strip())
            continue
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and not stripped.startswith("**"):
            items.append(stripped)
    return items


def _read_docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as zf:
        xml_data = zf.read("word/document.xml")
    root = ET.fromstring(xml_data)
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs = []
    for para in root.findall(".//w:p", ns):
        texts = [node.text for node in para.findall(".//w:t", ns) if node.text]
        if texts:
            paragraphs.append("".join(texts))
    return "\n".join(paragraphs)


def _read_text(path: Path) -> str:
    if path.suffix.lower() == ".docx":
        return _read_docx_text(path)
    return path.read_text(encoding="utf-8")


def _collect_sections(lines: list[str]) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current = None
    for line in lines:
        heading = HEADING_RE.match(line)
        if heading:
            title = heading.group(2).strip().lower()
            current = title
            sections.setdefault(current, [])
            continue
        stripped = line.strip().rstrip(":").lower()
        if any(stripped.startswith(name) for name in SECTION_NAMES):
            current = next((name for name in SECTION_NAMES if stripped.startswith(name)), stripped)
            sections.setdefault(current, [])
            continue
        if current is not None:
            sections[current].append(line)
    return sections


def _find_section(sections: dict[str, list[str]], keyword: str) -> list[str]:
    for key, lines in sections.items():
        if keyword in key:
            return lines
    return []


def _parse_sessions(raw: str) -> list[dict]:
    lines = raw.splitlines()
    indices = []
    for idx, line in enumerate(lines):
        if SESSION_RE.match(line):
            indices.append(idx)
    sessions = []
    for i, start in enumerate(indices):
        end = indices[i + 1] if i + 1 < len(indices) else len(lines)
        header = lines[start]
        m = SESSION_RE.match(header)
        if not m:
            continue
        session_num = int(m.group(1))
        title = m.group(2).strip()
        body_lines = lines[start + 1 : end]
        sessions.append({
            "session": session_num,
            "title": title,
            "body_lines": body_lines,
        })
    return sessions


def _has_session_headers(raw: str) -> bool:
    return any(SESSION_RE.match(line) for line in raw.splitlines())


def _parse_overview(raw: str) -> dict:
    info: dict[str, str] = {}
    title = ""
    for line in raw.splitlines():
        if line.startswith("# ") and not title:
            title = line[2:].strip()
        m = META_RE.match(line.strip())
        if m:
            key = m.group(1).strip().lower()
            value = m.group(2).strip()
            info[key] = value
    if title:
        info["title"] = title
    return info


def _derive_duration_and_sessions(meeting_time: str) -> tuple[int | None, int | None]:
    # Example: "1 hour/week for 12 weeks"
    meeting_time = meeting_time.lower()
    minutes = None
    sessions = None
    m = re.search(r"(\d+)\s*(hour|hours|hr|hrs)", meeting_time)
    if m:
        minutes = int(m.group(1)) * 60
    m = re.search(r"(\d+)\s*(minute|minutes|min|mins)", meeting_time)
    if m:
        minutes = int(m.group(1))
    m = re.search(r"for\s+(\d+)\s+weeks", meeting_time)
    if m:
        sessions = int(m.group(1))
    return minutes, sessions


def _build_lesson_front_matter(
    course_slug: str,
    session_num: int,
    title: str,
    duration: int,
    mission: str,
    needs: list[str],
    checkpoints: list[str],
    quick_fixes: list[str],
    extensions: list[str],
    teacher_prep: list[str],
) -> str:
    lesson_slug = f"s{session_num:02d}-{_slugify(title)}"
    out = "---\n"
    out += f"course: {course_slug}\n"
    out += f"session: {session_num}\n"
    out += f"slug: {lesson_slug}\n"
    out += f"title: {_yaml_quote(title)}\n"
    out += f"duration_minutes: {duration}\n"
    if mission:
        out += f"makes: {_yaml_quote(mission)}\n"
    out += _yaml_list("needs", needs)
    out += _yaml_list("done_looks_like", checkpoints)
    if quick_fixes:
        out += "help:\n"
        out += _yaml_list("quick_fixes", quick_fixes, indent=2)
    out += _yaml_list("extend", extensions)
    if teacher_prep:
        out += "teacher_panel:\n"
        out += _yaml_list("prep", teacher_prep, indent=2)
    out += "---\n"
    return out


def _render_course_yaml(
    slug: str,
    title: str,
    sessions: list[dict],
    duration: int,
    age_band: str,
    needs: list[str],
) -> str:
    lesson_entries = []
    for session in sessions:
        session_num = session["session"]
        lesson_title = session["title"]
        lesson_slug = f"s{session_num:02d}-{_slugify(lesson_title)}"
        filename = f"{session_num:02d}-{_slugify(lesson_title)}.md"
        lesson_entries.append(
            f"""  - session: {session_num}
    slug: {lesson_slug}
    title: {_yaml_quote(lesson_title)}
    file: lessons/{filename}"""
        )

    course_yaml = f"""slug: {slug}
title: {_yaml_quote(title)}
sessions: {len(sessions)}
default_duration_minutes: {duration}
age_band: {_yaml_quote(age_band)}
{_yaml_list("needs", needs).rstrip()}
helper_reference: {slug}
lessons:
{chr(10).join(lesson_entries)}
"""
    return course_yaml


def _write_course(
    slug: str,
    title: str,
    sessions: list[dict],
    duration: int,
    age_band: str,
    needs: list[str],
) -> Path:
    course_dir = COURSES_ROOT / slug
    lessons_dir = course_dir / "lessons"
    course_dir.mkdir(parents=True, exist_ok=True)
    lessons_dir.mkdir(parents=True, exist_ok=True)

    for session in sessions:
        session_num = session["session"]
        lesson_title = session["title"]
        lesson_slug = f"s{session_num:02d}-{_slugify(lesson_title)}"
        filename = f"{session_num:02d}-{_slugify(lesson_title)}.md"

        body_lines = session["body_lines"]
        mission = ""
        for line in body_lines:
            m = re.search(r"(?:\*{0,2})Mission(?:\*{0,2})\s*:\s*(.+)", line, re.I)
            if m:
                mission = m.group(1).strip()
                break

        sections = _collect_sections(body_lines)
        needs_items = _extract_bullets(_find_section(sections, "materials"))
        checkpoints = _extract_bullets(_find_section(sections, "checkpoints"))
        quick_fixes = _extract_bullets(_find_section(sections, "common stuck points"))
        if not quick_fixes:
            quick_fixes = _extract_bullets(_find_section(sections, "stuck points"))
        extensions = _extract_bullets(_find_section(sections, "extensions"))
        teacher_prep = _extract_bullets(_find_section(sections, "teacher prep"))

        front_matter = _build_lesson_front_matter(
            slug,
            session_num,
            lesson_title,
            duration,
            mission,
            needs_items,
            checkpoints,
            quick_fixes,
            extensions,
            teacher_prep,
        )

        body = "\n".join(body_lines).strip() + "\n"
        (lessons_dir / filename).write_text(front_matter + body, encoding="utf-8")

    course_yaml = _render_course_yaml(slug, title, sessions, duration, age_band, needs)
    (course_dir / "course.yaml").write_text(course_yaml, encoding="utf-8")
    return course_dir


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sessions-md", required=True)
    parser.add_argument("--overview-md")
    parser.add_argument("--slug", required=True)
    parser.add_argument("--title")
    parser.add_argument("--sessions", type=int)
    parser.add_argument("--duration", type=int)
    parser.add_argument("--age-band", default="5th-7th")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    sessions_path = Path(args.sessions_md)
    sessions_raw = _read_text(sessions_path)
    if not _has_session_headers(sessions_raw):
        print("[warn] No session headers found. Expected lines like: 'Session 01: Title'.")
    sessions = _parse_sessions(sessions_raw)
    if not sessions:
        raise SystemExit("No sessions found. Expected headings like: Session 01: Title")

    overview_info = {}
    if args.overview_md:
        overview_raw = _read_text(Path(args.overview_md))
        overview_info = _parse_overview(overview_raw)

    title = args.title or overview_info.get("title")
    if not title:
        raise SystemExit("Missing course title. Provide --title or include a top-level # Title in overview.md")

    meeting_time = overview_info.get("meeting time", "")
    derived_duration, derived_sessions = _derive_duration_and_sessions(meeting_time)

    duration = args.duration or derived_duration or 75
    age_band = args.age_band or overview_info.get("grade level", "5th-7th")
    needs = []
    if "platform" in overview_info:
        needs.append(overview_info["platform"])

    course_dir = COURSES_ROOT / args.slug
    if course_dir.exists() and any(course_dir.iterdir()) and not args.force:
        raise SystemExit(f"Course folder already exists: {course_dir} (use --force to overwrite)")

    if args.dry_run:
        print("[dry-run] course.yaml:")
        print(_render_course_yaml(args.slug, title, sessions, duration, age_band, needs))
        for session in sessions:
            session_num = session["session"]
            lesson_title = session["title"]
            filename = f"{session_num:02d}-{_slugify(lesson_title)}.md"
            body_lines = session["body_lines"]
            mission = ""
            for line in body_lines:
                m = re.search(r"(?:\*{0,2})Mission(?:\*{0,2})\s*:\s*(.+)", line, re.I)
                if m:
                    mission = m.group(1).strip()
                    break
            sections = _collect_sections(body_lines)
            needs_items = _extract_bullets(_find_section(sections, "materials"))
            checkpoints = _extract_bullets(_find_section(sections, "checkpoints"))
            quick_fixes = _extract_bullets(_find_section(sections, "common stuck points"))
            if not quick_fixes:
                quick_fixes = _extract_bullets(_find_section(sections, "stuck points"))
            extensions = _extract_bullets(_find_section(sections, "extensions"))
            teacher_prep = _extract_bullets(_find_section(sections, "teacher prep"))
            front_matter = _build_lesson_front_matter(
                args.slug,
                session_num,
                lesson_title,
                duration,
                mission,
                needs_items,
                checkpoints,
                quick_fixes,
                extensions,
                teacher_prep,
            )
            print(f"[dry-run] lessons/{filename}:")
            print(front_matter + "\n".join(body_lines).strip())
        return 0

    _write_course(args.slug, title, sessions, duration, age_band, needs)
    print(f"Created course at {course_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
