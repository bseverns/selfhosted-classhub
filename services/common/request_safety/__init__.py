"""Shared request safety helpers for Class Hub + Homework Helper.

Canonical usage:
- `client_ip_from_request(...)` for proxy-aware IP extraction.
- `fixed_window_allow(...)` for cache-backed burst limiting.
- `token_bucket_allow(...)` when smoother refill behavior is needed.
- `build_staff_or_student_actor_key(...)` for optional per-actor limits.

Canonical env knobs (documented in docs/REQUEST_SAFETY.md):
- `REQUEST_SAFETY_TRUST_PROXY_HEADERS` (default: false)
- `REQUEST_SAFETY_XFF_INDEX` (default: 0; client-most IP in X-Forwarded-For)

Service-specific limit knobs remain local to each service:
- Class Hub: `CLASSHUB_JOIN_RATE_LIMIT_PER_MINUTE`
- Helper: `HELPER_RATE_LIMIT_PER_MINUTE`, `HELPER_RATE_LIMIT_PER_IP_PER_MINUTE`
"""

from __future__ import annotations

import logging
import ipaddress
import time
from typing import Mapping

from django.core.cache import cache as default_cache

logger = logging.getLogger(__name__)


def _log_cache_warning(
    *,
    op: str,
    key: str,
    request_id: str,
    exc: Exception,
) -> None:
    rid = (request_id or "").strip() or "unknown"
    logger.warning(
        "request_safety_cache_warning request_id=%s op=%s key=%s error=%s",
        rid,
        op,
        key,
        exc.__class__.__name__,
    )


def _cache_get(store, key: str, *, request_id: str):
    try:
        return store.get(key), True
    except Exception as exc:
        _log_cache_warning(op="get", key=key, request_id=request_id, exc=exc)
        return None, False


def _cache_set(store, key: str, value, *, timeout: int, request_id: str) -> bool:
    try:
        store.set(key, value, timeout=timeout)
        return True
    except Exception as exc:
        _log_cache_warning(op="set", key=key, request_id=request_id, exc=exc)
        return False


def _cache_incr(store, key: str, *, request_id: str):
    try:
        return store.incr(key), True
    except Exception as exc:
        _log_cache_warning(op="incr", key=key, request_id=request_id, exc=exc)
        return None, False


def parse_client_ip(
    meta: Mapping[str, str],
    *,
    trust_proxy_headers: bool = False,
    xff_index: int = 0,
    xff_header: str = "HTTP_X_FORWARDED_FOR",
) -> str:
    if trust_proxy_headers:
        forwarded = (meta.get(xff_header) or "").strip()
        if forwarded:
            valid_ips: list[str] = []
            for part in forwarded.split(","):
                candidate = part.strip()
                if not candidate:
                    continue
                try:
                    ipaddress.ip_address(candidate)
                    valid_ips.append(candidate)
                except ValueError:
                    continue
            if valid_ips:
                idx = xff_index
                if idx < 0:
                    idx = len(valid_ips) + idx
                if idx < 0:
                    idx = 0
                if idx >= len(valid_ips):
                    idx = len(valid_ips) - 1
                return valid_ips[idx]

    remote = (meta.get("REMOTE_ADDR") or "").strip()
    if remote:
        try:
            ipaddress.ip_address(remote)
            return remote
        except ValueError:
            pass
    return "unknown"


def client_ip_from_request(
    request,
    *,
    trust_proxy_headers: bool = False,
    xff_index: int = 0,
    xff_header: str = "HTTP_X_FORWARDED_FOR",
) -> str:
    meta = getattr(request, "META", {}) or {}
    return parse_client_ip(
        meta,
        trust_proxy_headers=trust_proxy_headers,
        xff_index=xff_index,
        xff_header=xff_header,
    )


def fixed_window_allow(
    key: str,
    *,
    limit: int,
    window_seconds: int,
    cache_backend=None,
    request_id: str = "",
) -> bool:
    if limit <= 0:
        return True
    store = cache_backend or default_cache
    window = max(int(window_seconds), 1)

    current, ok = _cache_get(store, key, request_id=request_id)
    if not ok:
        # Fail-open: request handling must continue when cache backend is down.
        return True
    if current is None:
        _cache_set(store, key, 1, timeout=window, request_id=request_id)
        return True
    if int(current) >= limit:
        return False
    _, incr_ok = _cache_incr(store, key, request_id=request_id)
    if not incr_ok:
        try:
            next_value = int(current) + 1
        except Exception:
            next_value = 1
        _cache_set(store, key, next_value, timeout=window, request_id=request_id)
    return True


def token_bucket_allow(
    key: str,
    *,
    capacity: int,
    refill_per_second: float,
    cost: float = 1.0,
    cache_backend=None,
    request_id: str = "",
) -> bool:
    if capacity <= 0 or refill_per_second <= 0 or cost <= 0:
        return False

    store = cache_backend or default_cache
    now = time.monotonic()
    ttl = max(int((capacity / refill_per_second) * 4), 1)

    state, ok = _cache_get(store, key, request_id=request_id)
    if not ok:
        # Fail-open: allow requests when limiter state cannot be read.
        return True
    state = state or {"tokens": float(capacity), "last": now}
    tokens = float(state.get("tokens", capacity))
    last = float(state.get("last", now))

    elapsed = max(now - last, 0.0)
    tokens = min(float(capacity), tokens + (elapsed * float(refill_per_second)))

    allowed = tokens >= float(cost)
    if allowed:
        tokens -= float(cost)

    _cache_set(store, key, {"tokens": tokens, "last": now}, timeout=ttl, request_id=request_id)
    return allowed


def build_staff_actor_key(request, *, prefix: str = "staff") -> str:
    user = getattr(request, "user", None)
    if not user:
        return ""
    if not getattr(user, "is_authenticated", False):
        return ""
    if not getattr(user, "is_staff", False):
        return ""
    user_id = getattr(user, "id", None)
    if not user_id:
        return ""
    return f"{prefix}:{user_id}"


def build_student_actor_key(
    request,
    *,
    class_id_key: str = "class_id",
    student_id_key: str = "student_id",
    prefix: str = "student",
) -> str:
    session = getattr(request, "session", None)
    if session is None:
        return ""
    student_id = session.get(student_id_key)
    class_id = session.get(class_id_key)
    if student_id and class_id:
        return f"{prefix}:{class_id}:{student_id}"
    return ""


def build_staff_or_student_actor_key(
    request,
    *,
    staff_prefix: str = "staff",
    student_prefix: str = "student",
    class_id_key: str = "class_id",
    student_id_key: str = "student_id",
) -> str:
    key = build_staff_actor_key(request, prefix=staff_prefix)
    if key:
        return key
    return build_student_actor_key(
        request,
        class_id_key=class_id_key,
        student_id_key=student_id_key,
        prefix=student_prefix,
    )


__all__ = [
    "build_staff_actor_key",
    "build_staff_or_student_actor_key",
    "build_student_actor_key",
    "client_ip_from_request",
    "fixed_window_allow",
    "parse_client_ip",
    "token_bucket_allow",
]
