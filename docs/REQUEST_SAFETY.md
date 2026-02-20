# Request Safety (Shared)

Shared package: `services/common/request_safety/`

Use this package in both Django services for:
- proxy-aware client IP parsing
- cache-backed rate limit helpers
- optional actor key builders (staff/student session identity)

## Canonical usage

Python import:

```python
from common.request_safety import (
    build_staff_or_student_actor_key,
    client_ip_from_request,
    fixed_window_allow,
)
```

Typical request flow:
1. Build actor key (if needed): `build_staff_or_student_actor_key(request)`
2. Parse IP safely: `client_ip_from_request(request, trust_proxy_headers=..., xff_index=...)`
3. Enforce burst limit: `fixed_window_allow(key, limit=..., window_seconds=60, cache_backend=cache)`

Optional advanced limiter:
- `token_bucket_allow(...)` for smoother refill behavior.
- Both limiter helpers are fail-open on cache backend errors (requests continue).
- Pass `request_id=...` when available so cache warnings can be traced in logs.

## Shared env knobs

Set once in `compose/.env` (applies to both services):

- `REQUEST_SAFETY_TRUST_PROXY_HEADERS`
  - `0` (default): use only `REMOTE_ADDR`
  - `1`: trust `X-Forwarded-For`
- `REQUEST_SAFETY_XFF_INDEX`
  - default `0` (left-most IP in `X-Forwarded-For`)
  - use another index if your proxy chain requires it

## Service-specific limit knobs

Class Hub:
- `CLASSHUB_JOIN_RATE_LIMIT_PER_MINUTE`

Homework Helper:
- `HELPER_RATE_LIMIT_PER_MINUTE`
- `HELPER_RATE_LIMIT_PER_IP_PER_MINUTE`

Keep service limits separate, but keep parsing + limiter mechanics centralized
in `common.request_safety`.

## Proxy note

Keep `REQUEST_SAFETY_TRUST_PROXY_HEADERS=0` unless your immediate upstream proxy
is trusted and overwrites `X-Forwarded-*` headers.

The compose Caddy configs set `X-Forwarded-For`, `X-Real-IP`, and
`X-Forwarded-Proto` from the immediate connection values before proxying to
Django. When Caddy is your first hop, set `REQUEST_SAFETY_TRUST_PROXY_HEADERS=1`
for deterministic rate-limit IP parsing.
