"""Optional upload malware scanning integration."""

from __future__ import annotations

import logging
import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings


logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    status: str
    message: str = ""


def _command_parts() -> list[str]:
    raw = str(getattr(settings, "CLASSHUB_UPLOAD_SCAN_COMMAND", "") or "").strip()
    if not raw:
        return []
    try:
        return shlex.split(raw)
    except ValueError:
        return []


def _write_temp_file(uploaded_file) -> Path:
    suffix = Path(getattr(uploaded_file, "name", "upload.bin")).suffix or ".bin"
    with tempfile.NamedTemporaryFile(prefix="classhub_scan_", suffix=suffix, delete=False) as tmp:
        for chunk in uploaded_file.chunks():
            tmp.write(chunk)
        return Path(tmp.name)


def scan_uploaded_file(uploaded_file) -> ScanResult:
    if not bool(getattr(settings, "CLASSHUB_UPLOAD_SCAN_ENABLED", False)):
        return ScanResult(status="disabled")

    command = _command_parts()
    if not command:
        return ScanResult(status="error", message="scan_command_missing")

    temp_path = None
    original_pos = None
    try:
        if hasattr(uploaded_file, "tell"):
            try:
                original_pos = uploaded_file.tell()
            except Exception:
                original_pos = None
        temp_path = _write_temp_file(uploaded_file)
        run_cmd = [*command, str(temp_path)]
        completed = subprocess.run(
            run_cmd,
            capture_output=True,
            text=True,
            timeout=int(getattr(settings, "CLASSHUB_UPLOAD_SCAN_TIMEOUT_SECONDS", 20)),
            check=False,
        )
        if completed.returncode == 0:
            return ScanResult(status="clean")
        if completed.returncode == 1:
            message = (completed.stdout or completed.stderr or "").strip()[:400]
            return ScanResult(status="infected", message=message or "scanner_detected_threat")
        message = (completed.stderr or completed.stdout or "").strip()[:400]
        logger.warning("upload_scan_error returncode=%s output=%s", completed.returncode, message)
        return ScanResult(status="error", message=message or "scanner_error")
    except subprocess.TimeoutExpired:
        logger.warning("upload_scan_timeout")
        return ScanResult(status="error", message="scanner_timeout")
    except Exception:
        logger.exception("upload_scan_exception")
        return ScanResult(status="error", message="scanner_exception")
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass
        if hasattr(uploaded_file, "seek"):
            try:
                uploaded_file.seek(0 if original_pos is None else original_pos)
            except Exception:
                pass
