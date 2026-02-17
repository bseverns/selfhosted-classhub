"""Media streaming/download endpoint callables."""

import mimetypes
import re
from pathlib import Path

from django.db.utils import OperationalError, ProgrammingError
from django.http import FileResponse, HttpResponse, StreamingHttpResponse

from ..models import LessonAsset, LessonVideo
from ..services.content_links import safe_filename, video_mime_type


def _request_can_view_lesson_video(request) -> bool:
    if request.user.is_authenticated and request.user.is_staff:
        return True
    if getattr(request, "student", None) is not None:
        return True
    return False


def _request_can_view_lesson_asset(request) -> bool:
    # Mirrors video access: active classroom students + staff can open assets.
    if request.user.is_authenticated and request.user.is_staff:
        return True
    if getattr(request, "student", None) is not None:
        return True
    return False


def _stream_file_with_range(request, file_path: Path, content_type: str):
    # Supports HTTP byte-range requests for seekable video playback.
    file_size = file_path.stat().st_size
    range_header = request.headers.get("Range") or request.META.get("HTTP_RANGE", "")
    if not range_header:
        response = FileResponse(open(file_path, "rb"), content_type=content_type)
        response["Content-Length"] = str(file_size)
        response["Accept-Ranges"] = "bytes"
        return response

    m = re.match(r"bytes=(\d*)-(\d*)", range_header)
    if not m:
        response = HttpResponse(status=416)
        response["Content-Range"] = f"bytes */{file_size}"
        return response

    start_raw, end_raw = m.group(1), m.group(2)
    if not start_raw and not end_raw:
        response = HttpResponse(status=416)
        response["Content-Range"] = f"bytes */{file_size}"
        return response

    if start_raw:
        start = int(start_raw)
        end = int(end_raw) if end_raw else file_size - 1
    else:
        suffix_len = int(end_raw)
        if suffix_len <= 0:
            response = HttpResponse(status=416)
            response["Content-Range"] = f"bytes */{file_size}"
            return response
        start = max(file_size - suffix_len, 0)
        end = file_size - 1

    if start >= file_size or end < start:
        response = HttpResponse(status=416)
        response["Content-Range"] = f"bytes */{file_size}"
        return response

    end = min(end, file_size - 1)
    length = (end - start) + 1

    file_handle = open(file_path, "rb")

    def _iter_file(handle, offset: int, remaining: int, chunk_size: int = 64 * 1024):
        try:
            handle.seek(offset)
            left = remaining
            while left > 0:
                chunk = handle.read(min(chunk_size, left))
                if not chunk:
                    break
                left -= len(chunk)
                yield chunk
        finally:
            handle.close()

    response = StreamingHttpResponse(
        _iter_file(file_handle, start, length),
        status=206,
        content_type=content_type,
    )
    response["Content-Length"] = str(length)
    response["Content-Range"] = f"bytes {start}-{end}/{file_size}"
    response["Accept-Ranges"] = "bytes"
    return response


def lesson_video_stream(request, video_id: int):
    try:
        video = LessonVideo.objects.filter(id=video_id).first()
    except (OperationalError, ProgrammingError) as exc:
        if "hub_lessonvideo" in str(exc).lower():
            return HttpResponse("Not found", status=404)
        raise
    if not video or not video.video_file:
        return HttpResponse("Not found", status=404)

    is_staff_user = bool(request.user.is_authenticated and request.user.is_staff)
    if not video.is_active and not is_staff_user:
        return HttpResponse("Not found", status=404)

    if not _request_can_view_lesson_video(request):
        return HttpResponse("Forbidden", status=403)

    try:
        file_path = Path(video.video_file.path)
    except Exception:
        return HttpResponse("Not found", status=404)
    if not file_path.exists():
        return HttpResponse("Not found", status=404)

    content_type = video_mime_type(video.video_file.name)
    return _stream_file_with_range(request, file_path, content_type)


def lesson_asset_download(request, asset_id: int):
    try:
        asset = LessonAsset.objects.select_related("folder").filter(id=asset_id).first()
    except (OperationalError, ProgrammingError) as exc:
        if "hub_lessonasset" in str(exc).lower():
            return HttpResponse("Not found", status=404)
        raise
    if not asset or not asset.file:
        return HttpResponse("Not found", status=404)

    is_staff_user = bool(request.user.is_authenticated and request.user.is_staff)
    if not asset.is_active and not is_staff_user:
        return HttpResponse("Not found", status=404)

    if not _request_can_view_lesson_asset(request):
        return HttpResponse("Forbidden", status=403)

    try:
        file_path = Path(asset.file.path)
    except Exception:
        return HttpResponse("Not found", status=404)
    if not file_path.exists():
        return HttpResponse("Not found", status=404)

    filename = safe_filename((asset.original_filename or file_path.name or "asset").strip()[:255])
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return FileResponse(open(file_path, "rb"), as_attachment=False, filename=filename, content_type=content_type)


__all__ = [
    "lesson_video_stream",
    "lesson_asset_download",
]
