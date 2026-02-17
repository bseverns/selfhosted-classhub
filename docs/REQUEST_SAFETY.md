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

## Shared env knobs

Set once in `compose/.env` (applies to both services):

- `REQUEST_SAFETY_TRUST_PROXY_HEADERS`
  - `1` (default): trust `X-Forwarded-For`
  - `0`: use only `REMOTE_ADDR`
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
