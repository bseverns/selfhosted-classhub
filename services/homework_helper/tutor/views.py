import json
import ipaddress
import os
import re
import urllib.error
import urllib.request
from functools import lru_cache
from pathlib import Path

from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from django.db import connection
from django.db.utils import OperationalError, ProgrammingError

from .policy import build_instructions
from .queueing import acquire_slot, release_slot

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


def _redact(text: str) -> str:
    """Very light redaction.

    Goal: reduce accidental PII in prompts.
    Not a complete privacy solution.
    """
    text = EMAIL_RE.sub("[REDACTED_EMAIL]", text)
    text = PHONE_RE.sub("[REDACTED_PHONE]", text)
    return text


def _rate_limit(key: str, limit: int, window_seconds: int) -> bool:
    """Return True if allowed; False if blocked."""
    current = cache.get(key)
    if current is None:
        cache.set(key, 1, timeout=window_seconds)
        return True
    if int(current) >= limit:
        return False
    try:
        cache.incr(key)
    except Exception:
        cache.set(key, int(current) + 1, timeout=window_seconds)
    return True


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
    return "unknown"


def _student_session_exists(student_id: int, class_id: int) -> bool:
    """Validate student session against shared Class Hub table when available."""
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM hub_studentidentity WHERE id = %s AND classroom_id = %s LIMIT 1",
                [student_id, class_id],
            )
            return cursor.fetchone() is not None
    except (OperationalError, ProgrammingError):
        # If the Class Hub table is not reachable in this helper deployment,
        # rely on session presence as the MVP boundary.
        return True


def _actor_key(request) -> str:
    user = getattr(request, "user", None)
    if user and user.is_authenticated and user.is_staff:
        return f"staff:{user.id}"

    student_id = request.session.get("student_id")
    class_id = request.session.get("class_id")
    if not (student_id and class_id):
        return ""

    if not _student_session_exists(student_id, class_id):
        return ""

    return f"student:{class_id}:{student_id}"


def _ollama_chat(base_url: str, model: str, instructions: str, message: str) -> tuple[str, str]:
    url = base_url.rstrip("/") + "/api/chat"
    temperature = float(os.getenv("OLLAMA_TEMPERATURE", "0.2"))
    top_p = float(os.getenv("OLLAMA_TOP_P", "0.9"))
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": instructions},
            {"role": "user", "content": message},
        ],
        "stream": False,
        "options": {
            "temperature": temperature,
            "top_p": top_p,
        },
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
    response = client.responses.create(
        model=model,
        instructions=instructions,
        input=message,
    )
    return (getattr(response, "output_text", "") or ""), model


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


def _normalize_allowed_topics(value) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        return [v.strip() for v in value.split("|") if v.strip()]
    return []


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
    actor = _actor_key(request)
    if not actor:
        return JsonResponse({"error": "unauthorized"}, status=401)

    client_ip = _client_ip(request)
    actor_limit = int(os.getenv("HELPER_RATE_LIMIT_PER_MINUTE", "30"))
    ip_limit = int(os.getenv("HELPER_RATE_LIMIT_PER_IP_PER_MINUTE", "90"))
    if not _rate_limit(f"rl:actor:{actor}:m", limit=actor_limit, window_seconds=60):
        return JsonResponse({"error": "rate_limited"}, status=429)
    if not _rate_limit(f"rl:ip:{client_ip}:m", limit=ip_limit, window_seconds=60):
        return JsonResponse({"error": "rate_limited"}, status=429)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "bad_json"}, status=400)

    context_value = payload.get("context")
    topics_value = payload.get("topics")
    allowed_topics_value = payload.get("allowed_topics")
    reference_key = payload.get("reference")
    message = (payload.get("message") or "").strip()
    if not message:
        return JsonResponse({"error": "missing_message"}, status=400)

    # Bound size + redact obvious PII patterns
    message = _redact(message)[:8000]

    backend = (os.getenv("HELPER_LLM_BACKEND", "ollama") or "ollama").lower()
    strictness = (os.getenv("HELPER_STRICTNESS", "light") or "light").lower()
    scope_mode = (os.getenv("HELPER_SCOPE_MODE", "soft") or "soft").lower()
    topics: list[str] = []
    if isinstance(topics_value, str):
        topics = [t.strip() for t in topics_value.split("|") if t.strip()]
    elif isinstance(topics_value, list):
        topics = [str(t).strip() for t in topics_value if str(t).strip()]
    allowed_topics = _normalize_allowed_topics(allowed_topics_value)
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
        return JsonResponse({
            "text": (
                "We’re using Scratch blocks in this class, not text programming languages. "
                "Tell me which Scratch block or part of your project you’re stuck on, "
                "and I’ll help you with the Scratch version."
            ),
            "model": "",
            "backend": backend,
            "strictness": strictness,
        })
    if allowed_topics:
        filter_mode = (os.getenv("HELPER_TOPIC_FILTER_MODE", "soft") or "soft").lower()
        if filter_mode == "strict" and not _allowed_topic_overlap(message, allowed_topics):
            return JsonResponse({
                "text": (
                    "Let’s keep this focused on today’s lesson topics: "
                    + ", ".join(allowed_topics)
                    + ". Which part of that do you need help with?"
                ),
                "model": "",
                "backend": backend,
                "strictness": strictness,
            })
    instructions = build_instructions(
        strictness,
        context=context_value or "",
        topics=topics,
        scope_mode=scope_mode,
        allowed_topics=allowed_topics,
        reference_text=reference_text,
    )

    max_concurrency = int(os.getenv("HELPER_MAX_CONCURRENCY", "2"))
    max_wait = float(os.getenv("HELPER_QUEUE_MAX_WAIT_SECONDS", "10"))
    poll = float(os.getenv("HELPER_QUEUE_POLL_SECONDS", "0.2"))
    ttl = int(os.getenv("HELPER_QUEUE_SLOT_TTL_SECONDS", "120"))
    slot_key, token = acquire_slot(max_concurrency, max_wait, poll, ttl)
    if not slot_key:
        return JsonResponse({"error": "busy"}, status=503)

    try:
        if backend == "ollama":
            model = os.getenv("OLLAMA_MODEL", "llama3.2:1b")
            base_url = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
            text, model_used = _ollama_chat(base_url, model, instructions, message)
        elif backend == "openai":
            model = os.getenv("OPENAI_MODEL", "gpt-5.2")
            text, model_used = _openai_chat(model, instructions, message)
        else:
            return JsonResponse({"error": "unknown_backend"}, status=500)
    except RuntimeError as exc:
        if str(exc) == "openai_not_installed":
            return JsonResponse({"error": "openai_not_installed"}, status=500)
        return JsonResponse({"error": "backend_error"}, status=502)
    except (urllib.error.URLError, urllib.error.HTTPError):
        if backend == "ollama":
            return JsonResponse({"error": "ollama_error"}, status=502)
        return JsonResponse({"error": "backend_error"}, status=502)
    except ValueError:
        return JsonResponse({"error": "backend_error"}, status=502)
    except Exception:
        return JsonResponse({"error": "backend_error"}, status=502)
    finally:
        release_slot(slot_key, token)

    return JsonResponse({
        "text": text or "",
        "model": model_used,
        "backend": backend,
        "strictness": strictness,
    })
