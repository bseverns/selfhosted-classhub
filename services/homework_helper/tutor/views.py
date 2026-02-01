import json
import os
import re
import urllib.error
import urllib.request
from functools import lru_cache
from pathlib import Path

from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .policy import build_instructions
from .queueing import acquire_slot, release_slot

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
PHONE_RE = re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")
SAFE_REF_KEY_RE = re.compile(r"^[a-z0-9_-]+$")


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


def _ollama_chat(base_url: str, model: str, instructions: str, message: str) -> tuple[str, str]:
    url = base_url.rstrip("/") + "/api/chat"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": instructions},
            {"role": "user", "content": message},
        ],
        "stream": False,
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


@csrf_exempt
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
    who = request.META.get("REMOTE_ADDR", "unknown")

    # Rate limit: 20 req/min per IP (MVP). Replace with user-id when auth exists here.
    if not _rate_limit(f"rl:{who}:m", limit=20, window_seconds=60):
        return JsonResponse({"error": "rate_limited"}, status=429)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "bad_json"}, status=400)

    context_value = payload.get("context")
    topics_value = payload.get("topics")
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
    reference_dir = os.getenv("HELPER_REFERENCE_DIR", "/app/tutor/reference").strip()
    reference_map_raw = os.getenv("HELPER_REFERENCE_MAP", "").strip()
    reference_file = os.getenv("HELPER_REFERENCE_FILE", "").strip()
    resolved = _resolve_reference_file(reference_key, reference_dir, reference_map_raw)
    if resolved:
        reference_file = resolved
    reference_text = _load_reference_text(reference_file)
    instructions = build_instructions(
        strictness,
        context=context_value or "",
        topics=topics,
        scope_mode=scope_mode,
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
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError):
        return JsonResponse({"error": "ollama_error"}, status=502)
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
