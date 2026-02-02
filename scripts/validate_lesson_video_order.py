#!/usr/bin/env python3
"""
Validate first-introduced video order and Watch copy sync across lessons.

Default checks:
- V01 is introduced in the first video-bearing session.
- `videos:` front matter IDs match `## Watch` section heading IDs per lesson.

Optional strict mode checks whether V01, V02, ... are introduced in
non-decreasing order by session number across the full course.

Auto-fix mode can reorder/rebuild Watch headings to match front matter IDs.

Usage:
  python3 scripts/validate_lesson_video_order.py \
    --lessons-dir services/classhub/content/courses/piper_scratch_12_session/lessons
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path


SESSION_RE = re.compile(r"^session:\s*(\d+)\s*$", re.M)
VIDEO_ID_RE = re.compile(r"^\s*-\s*id:\s*(V\d+)\s*$", re.M)
WATCH_VIDEO_RE = re.compile(r"^###\s+(V\d+)\b", re.M)
H2_RE = re.compile(r"^##\s+")
WATCH_HEADER_RE = re.compile(r"^\s*###\s+(V\d+)\b")


def _video_num(video_id: str) -> int:
    return int(video_id[1:])


def _split_doc(text: str) -> tuple[str, str, str]:
    """Return (front_block, front_matter, body)."""
    if not text.startswith("---"):
        return "", "", text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return "", "", text
    front_block = "---" + parts[1] + "---"
    return front_block, parts[1], parts[2]


def _sync_watch_section(body: str, lesson_videos: list[str]) -> tuple[str, bool]:
    lines = body.splitlines(keepends=True)
    watch_idx = next((i for i, line in enumerate(lines) if line.strip().lower() == "## watch"), None)
    if watch_idx is None:
        if not lesson_videos:
            return body, False
        tail = "" if body.endswith("\n") else "\n"
        tail += "\n## Watch\n\n"
        for vid in lesson_videos:
            tail += f"### {vid}\n\n"
        return body + tail, True

    end_idx = len(lines)
    for i in range(watch_idx + 1, len(lines)):
        if H2_RE.match(lines[i].strip()):
            end_idx = i
            break

    section = lines[watch_idx + 1 : end_idx]
    pre_lines: list[str] = []
    blocks: dict[str, list[str]] = {}
    block_order: list[str] = []
    current_vid = ""
    saw_block = False

    for line in section:
        m = WATCH_HEADER_RE.match(line)
        if m:
            current_vid = m.group(1)
            if current_vid not in blocks:
                blocks[current_vid] = []
                block_order.append(current_vid)
            blocks[current_vid].append(line)
            saw_block = True
            continue
        if not saw_block:
            pre_lines.append(line)
        elif current_vid:
            blocks[current_vid].append(line)

    rebuilt: list[str] = list(pre_lines)
    for vid in lesson_videos:
        block = blocks.get(vid)
        if block:
            rebuilt.extend(block)
        else:
            rebuilt.append(f"### {vid}\n")
            rebuilt.append("\n")

    # Keep unmatched blocks at the end so no authored details are lost.
    for vid in block_order:
        if vid not in lesson_videos:
            rebuilt.extend(blocks[vid])

    if section == rebuilt:
        return body, False

    new_lines = lines[: watch_idx + 1] + rebuilt + lines[end_idx:]
    return "".join(new_lines), True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lessons-dir", required=True)
    parser.add_argument("--strict-global", action="store_true")
    parser.add_argument("--fix-watch-sync", action="store_true")
    args = parser.parse_args()

    lessons_dir = Path(args.lessons_dir)
    if not lessons_dir.exists():
        raise SystemExit(f"Lessons directory not found: {lessons_dir}")

    first_seen: dict[str, tuple[int, str]] = {}
    lesson_order_errors: list[str] = []
    lesson_copy_errors: list[str] = []
    fixed_files: list[str] = []

    for path in sorted(lessons_dir.glob("*.md")):
        raw = path.read_text(encoding="utf-8")
        front_block, fm, body = _split_doc(raw)
        if not fm:
            continue
        m = SESSION_RE.search(fm)
        if not m:
            continue
        session = int(m.group(1))
        lesson_videos = VIDEO_ID_RE.findall(fm)

        if args.fix_watch_sync:
            new_body, changed = _sync_watch_section(body, lesson_videos)
            if changed:
                fixed_files.append(path.name)
                body = new_body
                new_raw = (front_block + body) if front_block else body
                path.write_text(new_raw, encoding="utf-8")

        watch_videos = WATCH_VIDEO_RE.findall(body)
        if lesson_videos != watch_videos:
            lesson_copy_errors.append(
                f"{path.name} front-matter videos ({', '.join(lesson_videos) or 'none'}) "
                f"do not match Watch section ({', '.join(watch_videos) or 'none'})"
            )

        nums = [_video_num(v) for v in lesson_videos]
        if nums != sorted(nums):
            lesson_order_errors.append(f"{path.name} has non-ascending videos: {', '.join(lesson_videos)}")
        for vid in lesson_videos:
            if vid not in first_seen or session < first_seen[vid][0]:
                first_seen[vid] = (session, path.name)

    if fixed_files:
        print("Auto-fixed Watch section video order/sync in:")
        for name in fixed_files:
            print(f"  - {name}")

    if not first_seen:
        print("No videos found in lesson front matter.")
        return 0

    intro_order = sorted(first_seen.items(), key=lambda kv: (kv[1][0], _video_num(kv[0])))
    print("First-introduced video order:")
    for vid, (session, filename) in intro_order:
        print(f"  {vid} -> session {session} ({filename})")

    errors: list[str] = []

    if "V01" not in first_seen:
        errors.append("V01 is missing from all lessons.")
    else:
        earliest_session = min(session for session, _ in first_seen.values())
        if first_seen["V01"][0] != earliest_session:
            errors.append(
                f"V01 first appears in session {first_seen['V01'][0]}, "
                f"but earliest video appears in session {earliest_session}."
            )

    errors.extend(lesson_copy_errors)

    if args.strict_global:
        errors.extend(lesson_order_errors)
        by_video_num = sorted(first_seen.items(), key=lambda kv: _video_num(kv[0]))
        prev_session = -1
        prev_vid = ""
        for vid, (session, filename) in by_video_num:
            if session < prev_session:
                errors.append(
                    f"{vid} first appears in session {session} ({filename}) "
                    f"before {prev_vid} which first appears in session {prev_session}"
                )
            prev_session = max(prev_session, session)
            prev_vid = vid

    if errors:
        print("\n[FAIL] Video order checks failed:")
        for err in errors:
            print(f"  - {err}")
        return 1

    if args.strict_global:
        print("\n[OK] Strict global video order checks passed.")
    else:
        print("\n[OK] Foundational and per-lesson video order checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
