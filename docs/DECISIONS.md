# Decisions (active)

This file tracks current live decisions and constraints.
Historical implementation logs and superseded decisions are archived by month in `docs/decisions/archive/`.

## Active Decisions Snapshot

- [Auth model: student access](#auth-model-student-access)
- [Service boundary: Homework Helper separate service](#service-boundary-homework-helper-separate-service)
- [Routing mode: local vs domain Caddy configs](#routing-mode-local-vs-domain-caddy-configs)
- [Secret handling: env-only secret sources](#secret-handling-env-only-secret-sources)
- [Request safety and helper access posture](#request-safety-and-helper-access-posture)
- [Observability and retention boundaries](#observability-and-retention-boundaries)
- [Deployment guardrails](#deployment-guardrails)
- [Teacher authoring templates](#teacher-authoring-templates)
- [Teacher UI comfort mode](#teacher-ui-comfort-mode)
- [Helper scope signing](#helper-scope-signing)
- [Production transport hardening](#production-transport-hardening)
- [Content parse caching](#content-parse-caching)
- [Admin access 2FA](#admin-access-2fa)

## Archive Index

- `docs/decisions/archive/2026-02.md`
- `docs/decisions/archive/2026-01.md`

## Auth model: student access

**Current decision:**
- Students join with class code + display name.
- Same-device rejoin can use a signed HTTP-only device hint cookie.
- Cross-device rejoin uses student return code.
- Teachers/admins authenticate with Django auth credentials.

**Why this remains active:**
- Keeps student friction low while limiting impersonation risk.
- Maintains minimal student PII collection in MVP.

## Admin access 2FA

**Current decision:**
- Django admin uses OTP-verified superuser sessions by default in both services.
- `DJANGO_ADMIN_2FA_REQUIRED=1` is the expected production posture.
- OTP enrollment is provisioned operationally via `bootstrap_admin_otp` command.

**Why this remains active:**
- Reduces risk from password reuse/phishing against admin accounts.
- Preserves clear separation: teacher workflow in `/teach`, hardened ops workflow in `/admin`.

## Service boundary: Homework Helper separate service

**Current decision:**
- Homework Helper remains a separate Django service.
- Routing is under `/helper/*` through Caddy.
- Helper policy, limits, and failure handling are isolated from Class Hub page delivery.

**Why this remains active:**
- Protects classroom materials from helper outages.
- Preserves independent scaling and policy controls as helper traffic grows.

## Routing mode: local vs domain Caddy configs

**Current decision:**
- Unknown/no domain: use `compose/Caddyfile.local`.
- Known domain: use `compose/Caddyfile.domain` with Caddy-managed TLS.
- Template selection is explicit via `CADDYFILE_TEMPLATE` in `compose/.env`.

**Why this remains active:**
- Keeps local setup simple while preserving production-safe HTTPS behavior.
- Reduces configuration drift during deployment.

## Secret handling: env-only secret sources

**Current decision:**
- Secrets are injected via environment (`compose/.env` or deployment environment), never committed to git.
- `.env.example` stays non-sensitive and documents required knobs.

**Why this remains active:**
- Supports basic secret hygiene for self-hosted operations.
- Keeps rotation/update workflow operationally simple.

## Request safety and helper access posture

**Current decision:**
- Shared request-safety helpers are canonical for client IP parsing and burst/token limiting.
- Helper chat requires either valid student classroom session context or authenticated staff context.
## Secret handling: required env secrets

**Current decision:**
- `DJANGO_SECRET_KEY` is required in both services.
- Secrets come from environment (`compose/.env` or deployment environment), never from committed defaults.
- `.env.example` remains non-sensitive and documents required knobs.

**Why this remains active:**
- Prevents insecure fallback secret boot behavior.
- Supports basic secret hygiene for self-hosted operations.

## Helper access and rate limiting posture

**Current decision:**
- Helper chat requires either authenticated staff context or valid student classroom session context.
- Student session validation checks classhub identity rows when table access is available, and fails open when classhub tables are unavailable.
- Shared request-safety helpers are canonical for proxy-aware client IP parsing and cache-backed limiter behavior.
- Helper admin follows superuser-only access, matching classhub admin posture.

**Why this remains active:**
- Prevents policy drift between services.
- Reduces abuse risk while keeping classroom usage workable behind proxies.

## Observability and retention boundaries

**Current decision:**
- Teacher/staff mutations emit append-only `AuditEvent` records.
- Student join/rejoin/upload/helper-access metadata emits append-only `StudentEvent` records.
- Retention is operator-managed using prune commands.

**Why this remains active:**
- Preserves incident traceability and accountability.
- Keeps privacy boundaries explicit by storing metadata rather than raw helper prompt/file content in event logs.

## Deployment guardrails

**Current decision:**
- Deploy path uses migration gate + smoke checks + deterministic compose invocation.
- Caddy mount source must match the expected compose config file.
- Regression coverage is required for helper auth/admin hardening and backend retry/circuit behavior.

**Why this remains active:**
- Prevents avoidable outages from config drift.
- Catches regressions before users encounter them.

## Teacher authoring templates

**Current decision:**
- Provide a script (`scripts/generate_authoring_templates.py`) that outputs both `.md` and `.docx` teacher templates keyed by course slug.
- Keep template sections aligned with `scripts/ingest_syllabus_md.py` parsing rules so teachers can fill in and import without manual reformatting.
- Expose the generator in the teacher landing page (`/teach`) with four required fields: slug, title, sessions, and duration.
- Provide staff-only direct download links for generated files from the same `/teach` card.
- Store UI-generated files under `CLASSHUB_AUTHORING_TEMPLATE_DIR` (default `/uploads/authoring_templates`) to avoid write dependencies on source mounts.

**Why this remains active:**
- Teachers can author in familiar formats (Markdown or Word) while preserving deterministic ingestion.
- Reduces onboarding friction and avoids repeated format mistakes in session-plan documents.

## Teacher UI comfort mode

**Current decision:**
- Teacher pages opt into a dedicated readability mode via `body.teacher-comfort`.
- Comfort mode increases card/table/form spacing, reduces motion emphasis, and removes decorative orb overlays.
- Student-facing pages keep existing visual behavior.

**Why this remains active:**
- Reduces visual fatigue during long grading/planning sessions.
- Improves scanability of dense teacher workflows without a full redesign.

## Helper scope signing

**Current decision:**
- Class Hub now signs helper scope metadata (context/topics/allowed-topics/reference) and sends it as `scope_token`.
- Homework Helper verifies `scope_token` server-side and ignores tamperable client scope fields when a token is present.
- Student helper requests require a valid scope token; staff requests can still use legacy/manual scope payloads for operational debugging.

**Why this remains active:**
- Prevents students from broadening helper scope by editing browser requests.
- Preserves lesson-scoped helper behavior without coupling helper directly to classhub content mounts.

## Production transport hardening

**Current decision:**
- Internal services remain private by default (Postgres/Redis internal network only; Ollama/MinIO host bindings are localhost-only).
- Caddy explicitly sets forwarded IP/proto headers before proxying to Django.
- Caddy enforces request-body limits per upstream (`CADDY_CLASSHUB_MAX_BODY`, `CADDY_HELPER_MAX_BODY`).
- Both Django services reject weak/default secret keys when `DJANGO_DEBUG=0`.
- Deploy flow includes automated `.env` validation via `scripts/validate_env_secrets.sh`.
- Security headers and HTTPS controls are enabled in production through explicit env knobs (`DJANGO_SECURE_*`).
- UI templates use local/system font stacks only (no Google Fonts network calls).

**Why this remains active:**
- Reduces accidental public exposure of internal services.
- Improves trust in proxy-aware rate limiting and secure-cookie behavior.
- Drops oversized requests at the edge before they reach Django workers.
- Prevents unsafe production boots with placeholder secrets.
- Removes third-party font calls from student/teacher/admin page loads.

## Content parse caching

**Current decision:**
- Course manifests and lesson markdown parsing are cached in-process using `(path, mtime)` keys.
- Cache entries invalidate automatically when file modification times change.
- Returned manifest/front-matter payloads are deep-copied on read to prevent accidental mutation leaks.

**Why this remains active:**
- Reduces repeated disk + YAML/markdown parsing overhead on hot lesson/class pages.
- Keeps behavior deterministic for live content edits without requiring manual cache flushes.
