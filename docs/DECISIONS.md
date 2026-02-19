# Decisions (active)

This file tracks current live decisions and constraints.
Historical implementation logs and superseded decisions are archived by month in `docs/decisions/archive/`.

## Active Decisions Snapshot

- [Auth model: student access](#auth-model-student-access)
- [Service boundary: Homework Helper separate service](#service-boundary-homework-helper-separate-service)
- [Routing mode: local vs domain Caddy configs](#routing-mode-local-vs-domain-caddy-configs)
- [Documentation as first-class product surface](#documentation-as-first-class-product-surface)
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
- [Teacher onboarding invites + 2FA](#teacher-onboarding-invites--2fa)

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

## Teacher onboarding invites + 2FA

**Current decision:**
- Superusers can create teacher staff accounts from `/teach` and trigger invite emails.
- Invite email carries a signed, expiring link to `/teach/2fa/setup`.
- `/teach/2fa/setup` provisions and confirms teacher TOTP devices via QR + manual secret fallback.
- SMTP remains environment-configured; local default is console backend for safe non-production testing.

**Why this remains active:**
- Removes CLI-only OTP provisioning friction during teacher onboarding.
- Keeps enrollment self-service while preserving short-lived, signed invite boundaries.

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

## Documentation as first-class product surface

**Current decision:**
- Documentation is treated as a core deliverable, not a trailing artifact.
- Role-based entrypoint remains `docs/START_HERE.md`.
- Documentation contract and standards are centralized in `docs/README.md`.
- Guided, hands-on learning tracks are maintained in `docs/LEARNING_PATHS.md`.
- Symptom-first operational triage is maintained in `docs/TROUBLESHOOTING.md`.
- Documentation pedagogy and maintainer writing standards are maintained in `docs/TEACHING_PLAYBOOK.md`.

**Why this remains active:**
- This repository is both an operational system and a teaching object.
- Maintainers need repeatable onboarding and incident handling, not tribal knowledge.
- Shipping docs in lockstep with code reduces deployment and handoff risk.

## Secret handling: env-only secret sources

**Current decision:**
- Secrets are injected via environment (`compose/.env` or deployment environment), never committed to git.
- `DJANGO_SECRET_KEY` is required in both services.
- `.env.example` stays non-sensitive and documents required knobs.

**Why this remains active:**
- Prevents insecure fallback secret boot behavior.
- Supports basic secret hygiene for self-hosted operations.
- Keeps rotation/update workflow operationally simple.

## Request safety and helper access posture

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
- `scripts/system_doctor.sh` is the canonical one-command stack diagnostic.
- Golden-path smoke can auto-provision fixtures via `scripts/golden_path_smoke.sh`.
- Class Hub static assets are collected during image build; runtime boot path is migrations + gunicorn only.
- Smoke checks default to `http://localhost` when `CADDYFILE_TEMPLATE=Caddyfile.local`, regardless of placeholder `SMOKE_BASE_URL` values in env examples.
- CI doctor smoke uses `HELPER_LLM_BACKEND=mock` to keep `/helper/chat` deterministic without runtime model pull dependencies.
- Golden smoke issues a server-side staff session key for `/teach` checks so admin-login form changes (OTP/superuser prompts) do not create false negatives.
- Regression coverage is required for helper auth/admin hardening and backend retry/circuit behavior.

**Why this remains active:**
- Prevents avoidable outages from config drift.
- Catches regressions before users encounter them.
- Reduces operator setup friction for smoke checks that previously depended on static credentials.
- Reduces startup-time healthcheck failures from long runtime `collectstatic` work.
- Prevents CI from accidentally probing external placeholder domains while validating local compose stacks.
- Prevents CI flakes when local model servers are reachable but model weights are not yet loaded.
- Keeps strict smoke focused on route authorization outcomes instead of brittle intermediate login form internals.

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
- Homework Helper verifies `scope_token` server-side and ignores tamperable client scope fields.
- Student helper requests require a valid scope token.
- Staff can be forced to require scope tokens by setting `HELPER_REQUIRE_SCOPE_TOKEN_FOR_STAFF=1`.

**Why this remains active:**
- Prevents students from broadening helper scope by editing browser requests.
- Preserves lesson-scoped helper behavior without coupling helper directly to classhub content mounts.

## Production transport hardening

**Current decision:**
- Internal services remain private by default (Postgres/Redis internal network only; Ollama/MinIO host bindings are localhost-only).
- Caddy explicitly sets forwarded IP/proto headers before proxying to Django.
- Proxy-header trust is explicit opt-in (`REQUEST_SAFETY_TRUST_PROXY_HEADERS=0` by default).
- Caddy enforces request-body limits per upstream (`CADDY_CLASSHUB_MAX_BODY`, `CADDY_HELPER_MAX_BODY`).
- Both Django services can emit CSP in report-only mode via `DJANGO_CSP_REPORT_ONLY_POLICY`.
- Both Django services reject weak/default secret keys when `DJANGO_DEBUG=0`.
- Deploy flow includes automated `.env` validation via `scripts/validate_env_secrets.sh`.
- Security headers and HTTPS controls are enabled in production through explicit env knobs (`DJANGO_SECURE_*`).
- UI templates use local/system font stacks only (no Google Fonts network calls).
- CI now guards against non-localhost published ports for internal services (`scripts/check_compose_port_exposure.py`).
- CI now includes secret scanning and Python dependency vulnerability scanning (`.github/workflows/security.yml`).

**Why this remains active:**
- Reduces accidental public exposure of internal services.
- Improves trust in proxy-aware rate limiting and secure-cookie behavior.
- Drops oversized requests at the edge before they reach Django workers.
- Prevents unsafe production boots with placeholder secrets.
- Removes third-party font calls from student/teacher/admin page loads.
- Makes CSP rollout incremental without breaking inline-heavy templates.
- Prevents accidental internal service exposure regressions during future compose edits.
- Keeps proxy trust assumptions explicit and reviewable in deploy configuration.

## Content parse caching

**Current decision:**
- Course manifests and lesson markdown parsing are cached in-process using `(path, mtime)` keys.
- Cache entries invalidate automatically when file modification times change.
- Returned manifest/front-matter payloads are deep-copied on read to prevent accidental mutation leaks.

**Why this remains active:**
- Reduces repeated disk + YAML/markdown parsing overhead on hot lesson/class pages.
- Keeps behavior deterministic for live content edits without requiring manual cache flushes.
