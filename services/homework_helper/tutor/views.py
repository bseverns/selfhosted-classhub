import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
import uuid
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.core.signing import BadSignature, SignatureExpired
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST
from common.request_safety import (
    build_staff_or_student_actor_key,
    client_ip_from_request,
    fixed_window_allow,
)
from common.helper_scope import parse_scope_token

from django.db import connection, transaction
from django.db.utils import DatabaseError

from .policy import build_instructions
from .queueing import acquire_slot, release_slot
from .classhub_events import emit_helper_chat_access_event

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
PHONE_RE = re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")
SAFE_REF_KEY_RE = re.compile(r"^[a-z0-9_-]+$")
DEFAULT_TEXT_LANGUAGE_KEYWORDS = [
    "pascal",
    "python",
    "java",
    "javascript",
    "typescript",
    "c++",
    "c#",
    "csharp",
    "ruby",
    "php",
    "go",
    "golang",
    "rust",
    "swift",
    "kotlin",
]
logger = logging.getLogger(__name__)


def _redact(text: str) -> str:
    """Apply lightweight redaction before model invocation/logging."""
    value = str(text or "")
    value = EMAIL_RE.sub("[REDACTED_EMAIL]", value)
    value = PHONE_RE.sub("[REDACTED_PHONE]", value)
    return value


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except Exception:
        return default


def _request_id(request) -> str:
    header_value = (request.META.get("HTTP_X_REQUEST_ID", "") or "").strip()
    if header_value:
        return header_value[:80]
    return uuid.uuid4().hex


def _json_response(payload: dict, *, request_id: str, status: int = 200) -> JsonResponse:
    body = dict(payload or {})
    body.setdefault("request_id", request_id)
    resp = JsonResponse(body, status=status)
    resp["X-Request-ID"] = request_id
    return resp


def _log_chat_event(level: str, event: str, *, request_id: str, **fields):
    row = {"event": event, "request_id": request_id, **fields}
    line = json.dumps(row, sort_keys=True, default=str)
    if level == "warning":
        logger.warning(line)
    elif level == "error":
        logger.error(line)
    else:
        logger.info(line)


def _backend_circuit_key(backend: str) -> str:
    return f"helper:circuit_open:{backend}"


def _backend_failure_counter_key(backend: str) -> str:
    return f"helper:circuit_failures:{backend}"


def _backend_circuit_is_open(backend: str) -> bool:
    return bool(cache.get(_backend_circuit_key(backend)))


def _record_backend_failure(backend: str) -> None:
    threshold = max(_env_int("HELPER_CIRCUIT_BREAKER_FAILURES", 5), 1)
    ttl = max(_env_int("HELPER_CIRCUIT_BREAKER_TTL_SECONDS", 30), 1)
    key = _backend_failure_counter_key(backend)
    current = cache.get(key)
    if current is None:
        cache.set(key, 1, timeout=ttl)
        count = 1
    else:
        try:
            count = int(cache.incr(key))
        except Exception:
            count = int(current) + 1
            cache.set(key, count, timeout=ttl)
    if count >= threshold:
        cache.set(_backend_circuit_key(backend), 1, timeout=ttl)


def _reset_backend_failure_state(backend: str) -> None:
    cache.delete(_backend_failure_counter_key(backend))
    cache.delete(_backend_circuit_key(backend))


@lru_cache(maxsize=32)
def _table_exists(table_name: str) -> bool:
    """Best-effort table existence check without raising for missing tables."""
    try:
        with connection.cursor() as cursor:
            return table_name in set(connection.introspection.table_names(cursor))
    except DatabaseError:
        if connection.in_atomic_block:
            try:
                transaction.set_rollback(False)
            except Exception:
                pass
        return False


def _student_session_exists(student_id: int, class_id: int) -> bool:
    """Validate student session against shared Class Hub table when available."""
    if not _table_exists("hub_studentidentity"):
        if bool(getattr(settings, "HELPER_REQUIRE_CLASSHUB_TABLE", False)):
            return False
        return True
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM hub_studentidentity WHERE id = %s AND classroom_id = %s LIMIT 1",
                [student_id, class_id],
            )
            return cursor.fetchone() is not None
    except DatabaseError:
        # Postgres marks the transaction as aborted after SQL errors; clear the
        # rollback flag so this best-effort check doesn't poison the request.
        if connection.in_atomic_block:
            try:
                transaction.set_rollback(False)
            except Exception:
                pass
        # MVP default is fail-open for local/demo setups; production can force
        # fail-closed by enabling HELPER_REQUIRE_CLASSHUB_TABLE.
        if bool(getattr(settings, "HELPER_REQUIRE_CLASSHUB_TABLE", False)):
            return False
        return True


def _actor_key(request) -> str:
    key = build_staff_or_student_actor_key(request)
    if not key:
        return ""
    if key.startswith("student:"):
        student_id = request.session.get("student_id")
        class_id = request.session.get("class_id")
        if not (student_id and class_id):
            return ""
        if not _student_session_exists(student_id, class_id):
            return ""
    return key


def _load_scope_from_token(scope_token: str, *, max_age_seconds: int) -> dict:
    return parse_scope_token(scope_token, max_age_seconds=max_age_seconds)


def _ollama_chat(base_url: str, model: str, instructions: str, message: str) -> tuple[str, str]:
    url = base_url.rstrip("/") + "/api/chat"
    temperature = float(os.getenv("OLLAMA_TEMPERATURE", "0.2"))
    top_p = float(os.getenv("OLLAMA_TOP_P", "0.9"))
    num_predict = _env_int("OLLAMA_NUM_PREDICT", 0)
    options = {
        "temperature": temperature,
        "top_p": top_p,
    }
    if num_predict > 0:
        options["num_predict"] = num_predict
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": instructions},
            {"role": "user", "content": message},
        ],
        "stream": False,
        "options": options,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})

    timeout = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "30"))
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
    parsed = json.loads(body)

    text = ""
    if isinstance(parsed, dict):
        msg = parsed.get("message") or {}
        text = msg.get("content") or parsed.get("response") or ""
    return text, parsed.get("model", model) if isinstance(parsed, dict) else model


def _openai_chat(model: str, instructions: str, message: str) -> tuple[str, str]:
    try:
        from openai import OpenAI
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("openai_not_installed") from exc

    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    create_kwargs = {
        "model": model,
        "instructions": instructions,
        "input": message,
    }
    max_output_tokens = _env_int("OPENAI_MAX_OUTPUT_TOKENS", 0)
    if max_output_tokens > 0:
        create_kwargs["max_output_tokens"] = max_output_tokens
    response = client.responses.create(**create_kwargs)
    return (getattr(response, "output_text", "") or ""), model


def _mock_chat() -> tuple[str, str]:
    text = (os.getenv("HELPER_MOCK_RESPONSE_TEXT", "") or "").strip()
    if not text:
        text = "Let's solve this step by step. What did you try already?"
    return text, "mock-tutor-v1"


def _truncate_response_text(text: str) -> tuple[str, bool]:
    max_chars = _env_int("HELPER_RESPONSE_MAX_CHARS", 2200)
    if max_chars < 200:
        max_chars = 200
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars].rstrip(), True


def _is_retryable_backend_error(exc: Exception) -> bool:
    if isinstance(exc, RuntimeError) and str(exc) in {"openai_not_installed", "unknown_backend"}:
        return False
    if isinstance(exc, (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError)):
        return True
    return exc.__class__.__name__ in {
        "APIConnectionError",
        "APITimeoutError",
        "RateLimitError",
        "InternalServerError",
    }


def _invoke_backend(backend: str, instructions: str, message: str) -> tuple[str, str]:
    if backend == "ollama":
        model = os.getenv("OLLAMA_MODEL", "llama3.2:1b")
        base_url = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
        return _ollama_chat(base_url, model, instructions, message)
    if backend == "openai":
        model = os.getenv("OPENAI_MODEL", "gpt-5.2")
        return _openai_chat(model, instructions, message)
    if backend == "mock":
        return _mock_chat()
    raise RuntimeError("unknown_backend")


def _call_backend_with_retries(backend: str, instructions: str, message: str) -> tuple[str, str, int]:
    max_attempts = max(_env_int("HELPER_BACKEND_MAX_ATTEMPTS", 2), 1)
    base_backoff = max(_env_float("HELPER_BACKOFF_SECONDS", 0.4), 0.0)

    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            text, model_used = _invoke_backend(backend, instructions, message)
            return text, model_used, attempt
        except Exception as exc:
            last_exc = exc
            if attempt >= max_attempts or not _is_retryable_backend_error(exc):
                raise
            sleep_seconds = base_backoff * (2 ** (attempt - 1))
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)

    raise last_exc or RuntimeError("backend_error")


def _resolve_reference_file(reference_key: str | None, reference_dir: str, reference_map_raw: str) -> str:
    if not reference_key:
        return ""
    # Prefer explicit allowlist map when provided.
    if reference_map_raw:
        try:
            reference_map = json.loads(reference_map_raw)
            rel = reference_map.get(reference_key)
            if rel:
                return str(Path(reference_dir) / rel)
        except Exception:
            pass
    # Safe fallback: allow direct lookup by slug in reference_dir.
    if SAFE_REF_KEY_RE.match(reference_key):
        candidate = Path(reference_dir) / f"{reference_key}.md"
        if candidate.exists():
            return str(candidate)
    return ""


def _is_scratch_context(context_value: str, topics: list[str], reference_text: str) -> bool:
    if "scratch" in (context_value or "").lower():
        return True
    if any("scratch" in t.lower() for t in topics):
        return True
    if "scratch" in (reference_text or "").lower():
        return True
    return False


def _parse_csv_list(raw: str) -> list[str]:
    return [part.strip().lower() for part in (raw or "").split(",") if part.strip()]


def _contains_text_language(message: str, keywords: list[str]) -> bool:
    lowered = message.lower()
    return any(keyword in lowered for keyword in keywords)


def _tokenize(text: str) -> set[str]:
    parts = re.split(r"[^a-z0-9]+", text.lower())
    return {p for p in parts if len(p) >= 4}


def _allowed_topic_overlap(message: str, allowed_topics: list[str]) -> bool:
    if not allowed_topics:
        return True
    msg_tokens = _tokenize(message)
    if not msg_tokens:
        return False
    topic_tokens: set[str] = set()
    for topic in allowed_topics:
        topic_tokens |= _tokenize(topic)
    return bool(msg_tokens & topic_tokens)


@lru_cache(maxsize=4)
def _load_reference_text(path_str: str) -> str:
    if not path_str:
        return ""
    path = Path(path_str)
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return ""
    # Keep it compact for the system prompt.
    lines = [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]
    return " ".join(lines)


@require_GET
def healthz(request):
    backend = (os.getenv("HELPER_LLM_BACKEND", "ollama") or "ollama").lower()
    return JsonResponse({"ok": True, "backend": backend})


@require_POST
def chat(request):
    """POST /helper/chat

    Input JSON:
      {"message": "..."}

    Output JSON:
      {"text": "...", "model": "..."}

    Day-1 note:
    - This endpoint is not yet tied to class materials (RAG planned).
    - Caddy routes /helper/* to this service.
    """
    started_at = time.monotonic()
    request_id = _request_id(request)
    actor = _actor_key(request)
    actor_type = actor.split(":", 1)[0] if actor else "anonymous"
    client_ip = client_ip_from_request(
        request,
        trust_proxy_headers=getattr(settings, "REQUEST_SAFETY_TRUST_PROXY_HEADERS", False),
        xff_index=getattr(settings, "REQUEST_SAFETY_XFF_INDEX", 0),
    )

    if not actor:
        _log_chat_event("warning", "unauthorized", request_id=request_id, actor_type=actor_type, ip=client_ip)
        return _json_response({"error": "unauthorized"}, status=401, request_id=request_id)

    # Append-only event in classhub table (metadata-only; never raw prompt text).
    try:
        classroom_id = int(request.session.get("class_id") or 0)
    except Exception:
        classroom_id = 0
    try:
        student_id = int(request.session.get("student_id") or 0)
    except Exception:
        student_id = 0
    emit_helper_chat_access_event(
        classroom_id=classroom_id,
        student_id=student_id,
        ip_address=client_ip,
        details={"request_id": request_id, "actor_type": actor_type},
    )

    actor_limit = _env_int("HELPER_RATE_LIMIT_PER_MINUTE", 30)
    ip_limit = _env_int("HELPER_RATE_LIMIT_PER_IP_PER_MINUTE", 90)
    if not fixed_window_allow(
        f"rl:actor:{actor}:m",
        limit=actor_limit,
        window_seconds=60,
        cache_backend=cache,
    ):
        _log_chat_event("warning", "rate_limited_actor", request_id=request_id, actor_type=actor_type, ip=client_ip)
        return _json_response({"error": "rate_limited"}, status=429, request_id=request_id)
    if not fixed_window_allow(
        f"rl:ip:{client_ip}:m",
        limit=ip_limit,
        window_seconds=60,
        cache_backend=cache,
    ):
        _log_chat_event("warning", "rate_limited_ip", request_id=request_id, actor_type=actor_type, ip=client_ip)
        return _json_response({"error": "rate_limited"}, status=429, request_id=request_id)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        _log_chat_event("warning", "bad_json", request_id=request_id, actor_type=actor_type, ip=client_ip)
        return _json_response({"error": "bad_json"}, status=400, request_id=request_id)

    scope_token = str(payload.get("scope_token") or "").strip()
    context_value = ""
    topics: list[str] = []
    allowed_topics: list[str] = []
    reference_key = ""
    scope_verified = False

    if scope_token:
        try:
            scope = _load_scope_from_token(
                scope_token,
                max_age_seconds=max(_env_int("HELPER_SCOPE_TOKEN_MAX_AGE_SECONDS", 7200), 60),
            )
            context_value = scope.get("context", "")
            topics = scope.get("topics", [])
            allowed_topics = scope.get("allowed_topics", [])
            reference_key = scope.get("reference", "")
            scope_verified = True
        except SignatureExpired:
            _log_chat_event("warning", "scope_token_expired", request_id=request_id, actor_type=actor_type, ip=client_ip)
            return _json_response({"error": "invalid_scope_token"}, status=400, request_id=request_id)
        except (BadSignature, ValueError):
            _log_chat_event("warning", "scope_token_invalid", request_id=request_id, actor_type=actor_type, ip=client_ip)
            return _json_response({"error": "invalid_scope_token"}, status=400, request_id=request_id)
    else:
        # Students must send signed scope metadata.
        # Staff can optionally be forced to require signed scope metadata too.
        require_scope_for_staff = bool(getattr(settings, "HELPER_REQUIRE_SCOPE_TOKEN_FOR_STAFF", False))
        if actor_type == "student" or (actor_type == "staff" and require_scope_for_staff):
            _log_chat_event("warning", "scope_token_missing", request_id=request_id, actor_type=actor_type, ip=client_ip)
            return _json_response({"error": "missing_scope_token"}, status=400, request_id=request_id)
        # Do not trust unsigned, client-supplied scope fields.
        if any(payload.get(k) for k in ("context", "topics", "allowed_topics", "reference")):
            _log_chat_event(
                "info",
                "unsigned_scope_fields_ignored",
                request_id=request_id,
                actor_type=actor_type,
                ip=client_ip,
            )

    message = (payload.get("message") or "").strip()
    if not message:
        return _json_response({"error": "missing_message"}, status=400, request_id=request_id)

    # Bound size + redact obvious PII patterns
    message = _redact(message)[:8000]

    backend = (os.getenv("HELPER_LLM_BACKEND", "ollama") or "ollama").lower()
    strictness = (os.getenv("HELPER_STRICTNESS", "light") or "light").lower()
    scope_mode = (os.getenv("HELPER_SCOPE_MODE", "soft") or "soft").lower()
    reference_dir = os.getenv("HELPER_REFERENCE_DIR", "/app/tutor/reference").strip()
    reference_map_raw = os.getenv("HELPER_REFERENCE_MAP", "").strip()
    reference_file = os.getenv("HELPER_REFERENCE_FILE", "").strip()
    resolved = _resolve_reference_file(reference_key, reference_dir, reference_map_raw)
    if resolved:
        reference_file = resolved
    reference_text = _load_reference_text(reference_file)
    env_keywords = _parse_csv_list(os.getenv("HELPER_TEXT_LANGUAGE_KEYWORDS", ""))
    lang_keywords = env_keywords or DEFAULT_TEXT_LANGUAGE_KEYWORDS
    if _contains_text_language(message, lang_keywords) and _is_scratch_context(context_value or "", topics, reference_text):
        _log_chat_event("info", "policy_redirect_text_language", request_id=request_id, actor_type=actor_type, backend=backend)
        return _json_response(
            {
                "text": (
                    "We’re using Scratch blocks in this class, not text programming languages. "
                    "Tell me which Scratch block or part of your project you’re stuck on, "
                    "and I’ll help you with the Scratch version."
                ),
                "model": "",
                "backend": backend,
                "strictness": strictness,
                "attempts": 0,
                "scope_verified": scope_verified,
            },
            request_id=request_id,
        )
    if allowed_topics:
        filter_mode = (os.getenv("HELPER_TOPIC_FILTER_MODE", "soft") or "soft").lower()
        if filter_mode == "strict" and not _allowed_topic_overlap(message, allowed_topics):
            _log_chat_event("info", "policy_redirect_allowed_topics", request_id=request_id, actor_type=actor_type, backend=backend)
            return _json_response(
                {
                    "text": (
                        "Let’s keep this focused on today’s lesson topics: "
                        + ", ".join(allowed_topics)
                        + ". Which part of that do you need help with?"
                    ),
                    "model": "",
                    "backend": backend,
                    "strictness": strictness,
                    "attempts": 0,
                    "scope_verified": scope_verified,
                },
                request_id=request_id,
            )
    instructions = build_instructions(
        strictness,
        context=context_value or "",
        topics=topics,
        scope_mode=scope_mode,
        allowed_topics=allowed_topics,
        reference_text=reference_text,
    )

    if _backend_circuit_is_open(backend):
        _log_chat_event("warning", "backend_circuit_open", request_id=request_id, backend=backend)
        return _json_response({"error": "backend_unavailable"}, status=503, request_id=request_id)

    max_concurrency = _env_int("HELPER_MAX_CONCURRENCY", 2)
    max_wait = _env_float("HELPER_QUEUE_MAX_WAIT_SECONDS", 10.0)
    poll = _env_float("HELPER_QUEUE_POLL_SECONDS", 0.2)
    ttl = _env_int("HELPER_QUEUE_SLOT_TTL_SECONDS", 120)
    queue_started_at = time.monotonic()
    slot_key, token = acquire_slot(max_concurrency, max_wait, poll, ttl)
    queue_wait_ms = int((time.monotonic() - queue_started_at) * 1000)
    if not slot_key:
        _log_chat_event(
            "warning",
            "queue_busy",
            request_id=request_id,
            actor_type=actor_type,
            backend=backend,
            queue_wait_ms=queue_wait_ms,
        )
        return _json_response({"error": "busy"}, status=503, request_id=request_id)

    attempts_used = 0
    model_used = ""
    try:
        text, model_used, attempts_used = _call_backend_with_retries(backend, instructions, message)
    except RuntimeError as exc:
        _record_backend_failure(backend)
        if str(exc) == "openai_not_installed":
            _log_chat_event("error", "openai_not_installed", request_id=request_id, backend=backend)
            return _json_response({"error": "openai_not_installed"}, status=500, request_id=request_id)
        if str(exc) == "unknown_backend":
            _log_chat_event("error", "unknown_backend", request_id=request_id, backend=backend)
            return _json_response({"error": "unknown_backend"}, status=500, request_id=request_id)
        _log_chat_event(
            "error",
            "backend_runtime_error",
            request_id=request_id,
            backend=backend,
            error_type=exc.__class__.__name__,
        )
        return _json_response({"error": "backend_error"}, status=502, request_id=request_id)
    except (urllib.error.URLError, urllib.error.HTTPError):
        _record_backend_failure(backend)
        _log_chat_event("error", "backend_transport_error", request_id=request_id, backend=backend)
        if backend == "ollama":
            return _json_response({"error": "ollama_error"}, status=502, request_id=request_id)
        return _json_response({"error": "backend_error"}, status=502, request_id=request_id)
    except ValueError:
        _record_backend_failure(backend)
        _log_chat_event("error", "backend_parse_error", request_id=request_id, backend=backend)
        return _json_response({"error": "backend_error"}, status=502, request_id=request_id)
    except Exception:
        _record_backend_failure(backend)
        _log_chat_event("error", "backend_error", request_id=request_id, backend=backend)
        return _json_response({"error": "backend_error"}, status=502, request_id=request_id)
    finally:
        release_slot(slot_key, token)

    safe_text, truncated = _truncate_response_text(text or "")

    _reset_backend_failure_state(backend)
    total_ms = int((time.monotonic() - started_at) * 1000)
    _log_chat_event(
        "info",
        "success",
        request_id=request_id,
        actor_type=actor_type,
        backend=backend,
        attempts=attempts_used,
        queue_wait_ms=queue_wait_ms,
        response_chars=len(safe_text),
        truncated=truncated,
        total_ms=total_ms,
    )
    return _json_response(
        {
            "text": safe_text,
            "model": model_used,
            "backend": backend,
            "strictness": strictness,
            "attempts": attempts_used,
            "queue_wait_ms": queue_wait_ms,
            "total_ms": total_ms,
            "truncated": truncated,
            "scope_verified": scope_verified,
        },
        request_id=request_id,
    )
