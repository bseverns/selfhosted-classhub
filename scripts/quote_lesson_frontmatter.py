#!/usr/bin/env python3
"""Utility to quote lesson front matter values that include colons."""

from __future__ import annotations

from pathlib import Path


TARGET = Path("services/classhub/content/courses")


def _quote_line(line: str) -> str:
    if ":" not in line or line.lstrip().startswith("-"):
        return line
    prefix, sep, suffix = line.partition(":")
    if not sep:
        return line
    value = suffix.strip()
    if (
        not value
        or value[0] in ('"', "'", "|", ">", "[", "{")
        or ":" not in value
    ):
        return line

    leading_spaces = suffix[: len(suffix) - len(suffix.lstrip())]
    escaped = value.replace('"', '\\"')
    return f"{prefix}:{leading_spaces}\"{escaped}\""


def _quote_frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return text
    lines = text.splitlines()
    if len(lines) < 3:
        return text

    end_idx = 0
    for i, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            end_idx = i
            break
    if not end_idx:
        return text

    before = lines[: end_idx + 1]
    fm_lines = lines[1:end_idx]
    after = lines[end_idx:]

    quoted = [_quote_line(line) for line in fm_lines]
    return "\n".join([before[0]] + quoted + after)


def main() -> int:
    modified = []
    for course_dir in TARGET.glob("*/"):
        lessons_dir = course_dir / "lessons"
        if not lessons_dir.is_dir():
            continue
        for lesson in sorted(lessons_dir.glob("*.md")):
            text = lesson.read_text(encoding="utf-8")
            new_text = _quote_frontmatter(text)
            if new_text != text:
                lesson.write_text(new_text, encoding="utf-8")
                modified.append(lesson)

    if modified:
        print("Updated front matter for:")
        cwd = Path.cwd()
        for p in modified:
            print(f"  - {Path(p).resolve().relative_to(cwd)}")
    else:
        print("No changes required.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
