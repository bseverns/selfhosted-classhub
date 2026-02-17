"""Best-effort audit logging helpers for staff actions."""

from __future__ import annotations

import ipaddress
import logging
from typing import Any

from ..models import AuditEvent, Class

logger = logging.getLogger(__name__)


def _client_ip(request) -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        for part in forwarded.split(","):
            candidate = part.strip()
            if not candidate:
                continue
            try:
                ipaddress.ip_address(candidate)
                return candidate
            except ValueError:
                continue

    remote = (request.META.get("REMOTE_ADDR", "") or "").strip()
    if remote:
        try:
            ipaddress.ip_address(remote)
            return remote
        except ValueError:
            pass
    return ""


def log_audit_event(
    request,
    *,
    action: str,
    target_type: str = "",
    target_id: str = "",
    summary: str = "",
    classroom: Class | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Record a staff action without impacting request success path."""
    try:
        AuditEvent.objects.create(
            actor_user=request.user if (request.user.is_authenticated and request.user.is_staff) else None,
            action=(action or "").strip()[:80] or "unknown",
            target_type=(target_type or "").strip()[:80],
            target_id=(target_id or "").strip()[:64],
            summary=(summary or "").strip()[:255],
            classroom=classroom,
            metadata=metadata or {},
            ip_address=_client_ip(request) or None,
        )
    except Exception:
        logger.exception("audit_event_write_failed action=%s", action)
