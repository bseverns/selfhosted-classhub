"""Signed helper scope metadata shared between Class Hub and Homework Helper."""

from __future__ import annotations

from django.core import signing


SCOPE_TOKEN_SALT = "classhub.helper.scope.v1"
SCOPE_TOKEN_VERSION = 1


def _normalize_text(value) -> str:
    return str(value or "").strip()


def _normalize_list(value) -> list[str]:
    if isinstance(value, str):
        parts = [part.strip() for part in value.split("|")]
        return [part for part in parts if part]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def issue_scope_token(
    *,
    context: str = "",
    topics=None,
    allowed_topics=None,
    reference: str = "",
) -> str:
    payload = {
        "v": SCOPE_TOKEN_VERSION,
        "context": _normalize_text(context),
        "topics": _normalize_list(topics),
        "allowed_topics": _normalize_list(allowed_topics),
        "reference": _normalize_text(reference),
    }
    return signing.dumps(payload, salt=SCOPE_TOKEN_SALT)


def parse_scope_token(token: str, *, max_age_seconds: int) -> dict:
    payload = signing.loads(token, salt=SCOPE_TOKEN_SALT, max_age=max_age_seconds)
    if not isinstance(payload, dict):
        raise ValueError("invalid_scope_payload")
    version = int(payload.get("v") or 0)
    if version != SCOPE_TOKEN_VERSION:
        raise ValueError("unsupported_scope_version")
    return {
        "context": _normalize_text(payload.get("context")),
        "topics": _normalize_list(payload.get("topics")),
        "allowed_topics": _normalize_list(payload.get("allowed_topics")),
        "reference": _normalize_text(payload.get("reference")),
    }


__all__ = [
    "issue_scope_token",
    "parse_scope_token",
    "SCOPE_TOKEN_SALT",
    "SCOPE_TOKEN_VERSION",
]
