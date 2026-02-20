"""URL/media helper functions shared by classhub views."""

import mimetypes
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from django.conf import settings

from .filenames import safe_filename

_YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
    "www.youtu.be",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
}
_COURSE_LESSON_PATH_RE = re.compile(
    r"^/course/(?P<course_slug>[-a-zA-Z0-9_]+)/(?P<lesson_slug>[-a-zA-Z0-9_]+)$"
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


def courses_dir() -> Path:
    return Path(settings.CONTENT_ROOT) / "courses"


def extract_youtube_id(url: str) -> str:
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
    elif (
        parsed.path.startswith("/embed/")
        or parsed.path.startswith("/shorts/")
        or parsed.path.startswith("/live/")
    ):
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) >= 2:
            video_id = parts[1]

    if re.fullmatch(r"[A-Za-z0-9_-]{6,20}", video_id or ""):
        return video_id
    return ""


def safe_external_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url.strip())
    if parsed.scheme.lower() not in {"http", "https"}:
        return ""
    return url.strip()


def asset_base_url() -> str:
    raw = str(getattr(settings, "CLASSHUB_ASSET_BASE_URL", "") or "").strip()
    return raw.rstrip("/")


def build_asset_url(url_or_path: str) -> str:
    raw = (url_or_path or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if parsed.scheme.lower() in {"http", "https"}:
        return raw

    path = raw if raw.startswith("/") else f"/{raw}"
    base = asset_base_url()
    if not base:
        return path
    return f"{base}{path}"


def is_probably_video_url(url: str) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    path = (parsed.path or "").lower()
    return any(path.endswith(ext) for ext in _VIDEO_EXTENSIONS)


def video_mime_type(url: str) -> str:
    guessed, _ = mimetypes.guess_type(url or "")
    return guessed or "video/mp4"


def parse_course_lesson_url(url: str) -> tuple[str, str] | None:
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


def normalize_lesson_videos(front_matter: dict) -> list[dict]:
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
        url = safe_external_url(str(video.get("url") or "").strip())
        youtube_id = str(video.get("youtube_id") or "").strip()
        if youtube_id and not re.fullmatch(r"[A-Za-z0-9_-]{6,20}", youtube_id):
            youtube_id = ""
        if not youtube_id and url:
            youtube_id = extract_youtube_id(url)
        if youtube_id and not url:
            url = f"https://www.youtube.com/watch?v={youtube_id}"
        embed_url = f"https://www.youtube.com/embed/{youtube_id}" if youtube_id else ""
        source_type = "youtube" if youtube_id else ("native" if is_probably_video_url(url) else "link")
        media_url = url if source_type == "native" else ""
        media_type = video_mime_type(url) if media_url else ""
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
