#!/usr/bin/env python3
"""
Generate pre-formatted teacher authoring templates in Markdown and DOCX.

Usage:
  python3 scripts/generate_authoring_templates.py \
    --slug scratch_game_design \
    --title "Scratch Game Design + Cutscenes Lab" \
    --sessions 12 \
    --duration 75 \
    --age-band "5th-7th"
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


DEFAULT_OUT_DIR = Path("docs/examples/course_authoring")
CLASSHUB_SERVICE_DIR = Path(__file__).resolve().parents[1] / "services" / "classhub"
if str(CLASSHUB_SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(CLASSHUB_SERVICE_DIR))

from hub.services.authoring_templates import generate_authoring_templates, slug_to_title  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", required=True)
    parser.add_argument("--title")
    parser.add_argument("--sessions", type=int, default=12)
    parser.add_argument("--duration", type=int, default=75)
    parser.add_argument("--age-band", default="5th-7th")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    slug = args.slug.strip()
    title = (args.title or slug_to_title(slug)).strip()

    try:
        result = generate_authoring_templates(
            slug=slug,
            title=title,
            sessions=args.sessions,
            duration=args.duration,
            age_band=args.age_band,
            out_dir=Path(args.out_dir),
            overwrite=args.overwrite,
        )
    except ValueError as exc:
        raise SystemExit(str(exc))

    for path in result.output_paths:
        print(f"Created: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
