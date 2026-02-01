#!/usr/bin/env python3
"""
Generate per-lesson helper reference files from course markdown.

Usage:
  python scripts/generate_lesson_references.py \
    --course services/classhub/content/courses/piper_scratch_12_session/course.yaml \
    --out services/homework_helper/tutor/reference

This writes one file per lesson: <out>/<lesson_slug>.md
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml


HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)")
LIST_RE = re.compile(r"^(\s*[-*]|\s*\d+[.)])\s+")
SAFE_KEY_RE = re.compile(r"^[a-z0-9_-]+$")

WANTED_SECTIONS = {
    "goal",
    "watch",
    "do",
    "submit",
    "help",
    "extend",
    "teacher panel",
}


def _parse_front_matter(raw: str) -> tuple[dict, str]:
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) >= 3:
            fm = yaml.safe_load(parts[1]) or {}
            body = parts[2].lstrip("\n")
            return fm, body
    return {}, raw


def _collect_sections(body: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current = None
    for line in body.splitlines():
        heading = HEADING_RE.match(line)
        if heading:
            title = heading.group(2).strip()
            key = title.lower()
            current = key
            sections.setdefault(current, [])
            continue
        if current is None:
            continue
        if LIST_RE.match(line):
            sections[current].append(LIST_RE.sub("", line).strip())
        elif line.strip().startswith("**") and ":" in line:
            sections[current].append(line.strip().strip("*"))
        elif line.strip().startswith("Stop point:"):
            sections[current].append(line.strip())
    return sections


def _select_section(sections: dict[str, list[str]], name: str, max_items: int = 6) -> list[str]:
    items: list[str] = []
    for key, values in sections.items():
        if key == name or key.startswith(name):
            items.extend(values)
    # De-dupe while preserving order.
    seen = set()
    uniq = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            uniq.append(item)
    return uniq[:max_items]


def _render_reference(
    lesson_slug: str,
    title: str,
    session: int | None,
    fm: dict,
    sections: dict[str, list[str]],
) -> str:
    lines: list[str] = []
    lines.append(f"# Reference: {lesson_slug}")
    lines.append("")
    lines.append("## Lesson summary")
    lines.append(f"- Title: {title}")
    if session is not None:
        lines.append(f"- Session: {session}")
    makes = fm.get("makes")
    needs = fm.get("needs")
    if makes:
        lines.append(f"- Makes: {makes}")
    if needs:
        lines.append(f"- Needs: {needs}")

    def add_section(label: str, key: str):
        items = _select_section(sections, key)
        if not items:
            return
        lines.append("")
        lines.append(f"## {label}")
        for item in items:
            lines.append(f"- {item}")

    add_section("Watch", "watch")
    add_section("Do", "do")
    add_section("Submit", "submit")
    add_section("Help", "help")
    add_section("Extend", "extend")
    add_section("Teacher notes", "teacher panel")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--course", required=True, help="Path to course.yaml")
    parser.add_argument("--out", required=True, help="Output directory for references")
    args = parser.parse_args()

    course_path = Path(args.course)
    out_dir = Path(args.out)
    manifest = yaml.safe_load(course_path.read_text(encoding="utf-8")) or {}
    course_dir = course_path.parent
    lessons = manifest.get("lessons") or []

    out_dir.mkdir(parents=True, exist_ok=True)

    for lesson in lessons:
        slug = lesson.get("slug")
        if not slug or not SAFE_KEY_RE.match(slug):
            raise ValueError(f"Invalid lesson slug: {slug}")
        rel = lesson.get("file")
        if not rel:
            continue
        lesson_path = course_dir / rel
        raw = lesson_path.read_text(encoding="utf-8")
        fm, body = _parse_front_matter(raw)
        sections = _collect_sections(body)
        title = lesson.get("title") or fm.get("title") or slug
        session = lesson.get("session")
        ref_text = _render_reference(slug, title, session, fm, sections)
        (out_dir / f"{slug}.md").write_text(ref_text, encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
