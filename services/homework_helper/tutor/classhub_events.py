"""Best-effort forwarding of helper chat access events to Class Hub."""

from __future__ import annotations

import json
import logging
from functools import lru_cache
import urllib.error
import urllib.request

from django.conf import settings

logger = logging.getLogger(__name__)


def _events_url() -> str:
    return str(getattr(settings, "CLASSHUB_INTERNAL_EVENTS_URL", "") or "").strip()


def _events_token() -> str:
    return str(getattr(settings, "CLASSHUB_INTERNAL_EVENTS_TOKEN", "") or "").strip()


def _events_timeout_seconds() -> int:
    raw = int(getattr(settings, "CLASSHUB_INTERNAL_EVENTS_TIMEOUT_SECONDS", 3) or 0)
    return raw if raw > 0 else 3


@lru_cache(maxsize=4)
def _log_missing_config_once(url_present: bool, token_present: bool) -> None:
    logger.warning(
        "helper_chat_event_forward_disabled url_present=%s token_present=%s",
        "1" if url_present else "0",
        "1" if token_present else "0",
    )


def emit_helper_chat_access_event(
    *,
    classroom_id: int | None,
    student_id: int | None,
    ip_address: str,
    details: dict,
) -> None:
    """Best-effort event forwarding. Never raises."""
    if not classroom_id and not student_id:
        return

    url = _events_url()
    token = _events_token()
    if not url or not token:
        _log_missing_config_once(bool(url), bool(token))
        return

    payload = {
        "classroom_id": classroom_id or None,
        "student_id": student_id or None,
        "ip_address": ip_address or None,
        "details": details or {},
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-ClassHub-Internal-Token": token,
        },
    )

    request_id = str((details or {}).get("request_id") or "").strip() or "unknown"
    try:
        with urllib.request.urlopen(req, timeout=_events_timeout_seconds()) as resp:
            status = getattr(resp, "status", None) or resp.getcode()
            if not (200 <= int(status) < 300):
                logger.warning(
                    "helper_chat_event_forward_failed request_id=%s status=%s",
                    request_id,
                    status,
                )
    except urllib.error.HTTPError as exc:
        logger.warning(
            "helper_chat_event_forward_failed request_id=%s status=%s",
            request_id,
            exc.code,
        )
    except Exception as exc:
        logger.warning(
            "helper_chat_event_forward_failed request_id=%s error=%s",
            request_id,
            exc.__class__.__name__,
        )
