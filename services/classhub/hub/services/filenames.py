"""Filename sanitation helpers for download/export paths."""

from __future__ import annotations

import re


def safe_filename(value: str) -> str:
    """Return a conservative filesystem/header-safe filename."""
    name = (value or "file").strip()
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    name = name.strip("._")
    return name or "file"

