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
- [Helper event ingestion boundary](#helper-event-ingestion-boundary)
- [Helper grounding for Piper hardware](#helper-grounding-for-piper-hardware)
- [Helper lesson citations](#helper-lesson-citations)
- [Production transport hardening](#production-transport-hardening)
- [Content parse caching](#content-parse-caching)
- [Admin access 2FA](#admin-access-2fa)
- [Teacher onboarding invites + 2FA](#teacher-onboarding-invites--2fa)
- [Teacher route 2FA enforcement](#teacher-route-2fa-enforcement)
- [Lesson asset delivery hardening](#lesson-asset-delivery-hardening)
- [Optional separate asset origin](#optional-separate-asset-origin)
- [Upload content validation](#upload-content-validation)
- [Deployment timezone by environment](#deployment-timezone-by-environment)
- [Migration execution at deploy time](#migration-execution-at-deploy-time)
- [Teacher daily digest + closeout workflow](#teacher-daily-digest--closeout-workflow)
- [Student portfolio export](#student-portfolio-export)
- [Automated retention maintenance](#automated-retention-maintenance)

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

## Teacher route 2FA enforcement

**Current decision:**
- `/teach/*` now requires OTP-verified staff sessions by default (`DJANGO_TEACHER_2FA_REQUIRED=1`).
- `/teach/2fa/setup` and `/teach/logout` stay exempt so enrollment/recovery remains reachable.
- Middleware redirects unverified staff to `/teach/2fa/setup?next=<requested_teach_path>`.

**Why this remains active:**
- Teacher routes can rotate join codes, manage rosters, and access submissions; password-only is insufficient.
- Keeps teacher onboarding usable while enforcing stronger session posture on operational pages.

## Lesson asset delivery hardening

**Current decision:**
- Lesson assets are served as attachments by default.
- Inline rendering is restricted to allow-listed media/PDF MIME types only.
- Asset responses include `X-Content-Type-Options: nosniff`; inline responses include CSP sandbox.

**Why this remains active:**
- Reduces stored-XSS risk from HTML/script-like teacher uploads served on the LMS origin.
- Preserves inline behavior for expected classroom media types.

## Optional separate asset origin

**Current decision:**
- Set `CLASSHUB_ASSET_BASE_URL` to rewrite lesson media URLs (`/lesson-asset/*`, `/lesson-video/*`) to a separate origin.
- Markdown-rendered lesson links and teacher asset/video copy links both use this rewrite when configured.
- Leave `CLASSHUB_ASSET_BASE_URL` empty for same-origin behavior.

**Why this remains active:**
- Gives operators an incremental path to isolate uploaded media origin without changing teacher authoring flow.
- Keeps local/day-1 deployments simple while enabling stricter production hosting topologies.

## Upload content validation

**Current decision:**
- Extension checks remain, but uploads now include lightweight content checks before storage.
- `.sb3` uploads must be valid zip archives and include `project.json`.
- Magic-byte checks reject obvious extension/content mismatches for common file types.

**Why this remains active:**
- Reduces support churn from corrupted/mislabeled files.
- Adds cheap safety checks without introducing heavyweight scanning dependencies.

## Deployment timezone by environment

**Current decision:**
- Both services read `DJANGO_TIME_ZONE` (default `America/Chicago`) instead of hardcoding UTC.
- Operators set local classroom timezone in `compose/.env` (for example `America/Chicago`).

**Why this remains active:**
- Release-date gating uses `timezone.localdate()`, so deployment timezone must match classroom expectations.
- Prevents off-by-one-day release behavior around local midnight.

## Migration execution at deploy time

**Current decision:**
- Deploy/doctor/golden scripts explicitly run `manage.py migrate --noinput` for both services.
- Container boot keeps a compatibility toggle (`RUN_MIGRATIONS_ON_START`, default `1`) during rollout.

**Why this remains active:**
- Explicit migration steps are safer for multi-instance deployment workflows.
- The boot toggle preserves Day-1 simplicity while operators migrate to deploy-step migrations.

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
- Optional separate asset host: use `compose/Caddyfile.domain.assets` + `ASSET_DOMAIN`.
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
- Shared limiter helpers fail open when cache backends error, and emit request-id-tagged warnings when available.
- Helper admin follows superuser-only access, matching classhub admin posture.

**Why this remains active:**
- Prevents policy drift between services.
- Reduces abuse risk while keeping classroom usage workable behind proxies.

## Observability and retention boundaries

**Current decision:**
- Teacher/staff mutations emit append-only `AuditEvent` records.
- Student join/rejoin/upload/helper-access metadata emits append-only `StudentEvent` records.
- Retention is operator-managed using prune commands.
- Student event prune supports optional CSV snapshot export before deletion (`prune_student_events --export-csv <path>`).
- File-backed upload models use delete/replacement cleanup signals to prevent orphan file accumulation.
- Orphan file scavenger is available for legacy cleanup (`scavenge_orphan_uploads`, report-first).

**Why this remains active:**
- Preserves incident traceability and accountability.
- Keeps privacy boundaries explicit by storing metadata rather than raw helper prompt/file content in event logs.
- Supports audit handoff and offline review before destructive retention actions.
- Keeps upload storage bounded and predictable after roster resets, asset/video deletes, and file replacements.

## Deployment guardrails

**Current decision:**
- Deploy path uses migration gate + smoke checks + deterministic compose invocation.
- Caddy mount source must match the expected compose config file.
- `scripts/system_doctor.sh` is the canonical one-command stack diagnostic.
- Golden-path smoke can auto-provision fixtures via `scripts/golden_path_smoke.sh`.
- Class Hub static assets are collected during image build; runtime migration-at-boot is toggleable (`RUN_MIGRATIONS_ON_START`) while deploy scripts run explicit migrations.
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

## Helper event ingestion boundary

**Current decision:**
- Homework Helper no longer writes directly to Class Hub tables.
- Helper emits metadata-only chat access events to `POST /internal/events/helper-chat-access` on Class Hub.
- Endpoint is authenticated with `CLASSHUB_INTERNAL_EVENTS_TOKEN` and appends `StudentEvent` rows server-side.

**Why this remains active:**
- Removes raw cross-service SQL writes and keeps ownership of `StudentEvent` writes inside Class Hub.
- Preserves append-only telemetry behavior while reducing coupling between services.

## Helper grounding for Piper hardware

**Current decision:**
- Piper course helper references include explicit hardware troubleshooting context (breadboard/jumper/shared-ground/input-path checks), not only Scratch workflow guidance.
- Per-lesson helper references include "Common stuck issues (symptom -> check -> retest)" snippets for deterministic coaching before open-ended hinting.
- Early StoryMode lessons include hardware phrases in `helper_allowed_topics` so strict topic filtering still permits Piper control/wiring questions.
- Helper chat uses a deterministic Piper hardware triage branch for wiring-style questions (clarify mission/step, one targeted check, retest request) before model generation.
- Helper widget includes context-aware quick-action prompts (Piper vs Scratch vs general) that one-tap send structured help requests.
- `scripts/eval_helper.py` supports lightweight rule-based scoring (including Piper hardware cases) so response regressions are easier to spot in CI/local checks.

**Why this remains active:**
- The Piper course includes both Scratch work and physical control wiring; helper grounding must reflect both to be useful in class.
- Narrow topic filtering without hardware terms can incorrectly block or under-serve valid lesson questions.

## Helper lesson citations

**Current decision:**
- Helper now retrieves short lesson excerpts from the signed lesson reference file and includes up to 3 citations in each `/helper/chat` response.
- Prompt policy tells the model to ground responses in those excerpts and cite bracket ids (for example `[L1]`) when relevant.
- Student helper widget renders returned citations under the answer so grounding is visible to the learner.

**Why this remains active:**
- Makes helper output more inspectable and less likely to drift away from lesson intent.
- Gives teachers/students quick traceability from advice back to lesson material.

## Production transport hardening

**Current decision:**
- Internal services remain private by default (Postgres/Redis internal network only; Ollama/MinIO host bindings are localhost-only).
- Caddy explicitly sets forwarded IP/proto headers before proxying to Django.
- Proxy-header trust is explicit opt-in (`REQUEST_SAFETY_TRUST_PROXY_HEADERS=0` by default).
- Caddy enforces request-body limits per upstream (`CADDY_CLASSHUB_MAX_BODY`, `CADDY_HELPER_MAX_BODY`).
- Class Hub emits a report-only CSP baseline by default in production; `DJANGO_CSP_REPORT_ONLY_POLICY` can override/tune it.
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

## Teacher lesson-level helper tuning

**Current decision:**
- Reuse `LessonRelease` as the per-class/per-lesson storage point for teacher helper-scope overrides.
- Teachers can set optional overrides for helper context, focus topics, allowed-topic gate, and reference key directly from each lesson row in `/teach/class/<id>`.
- Class Hub applies these overrides when issuing signed helper scope tokens for students in that class.

**Why this remains active:**
- Keeps helper tuning close to lesson release controls where teachers already manage pacing.
- Avoids introducing a second override model/table for the same class+lesson keyspace.

## Collapsed teacher course controls by default

**Current decision:**
- On the teacher class dashboard, `Roster`, `Lesson Tracker`, and `Module Editor` are collapsed by default using explicit section toggles.
- Content is shown only when the teacher opens a section.

**Why this remains active:**
- Reduces visual load in day-to-day teaching workflows while preserving full control paths.
- Makes the class dashboard easier to scan during live instruction.

## Progressive docs layering for non-developers

**Current decision:**
- Introduce a dedicated non-developer entry page: `docs/NON_DEVELOPER_GUIDE.md`.
- Keep `docs/START_HERE.md` short and role-based with minimal links per audience.
- Keep `docs/README.md` as a concise docs index (not a wall of policy text).
- Keep deep ops docs (`docs/RUNBOOK.md`, `docs/TROUBLESHOOTING.md`) in quick-action-first format with command blocks and symptom indexing.

**Why this remains active:**
- Most readers need task guidance, not full architecture context.
- Progressive disclosure lowers cognitive load for teachers and staff while preserving deep technical docs for operators/developers.

## Teacher daily digest + closeout workflow

**Current decision:**
- `/teach` includes a per-class "since yesterday" digest (new students, uploads, helper usage, first-upload gaps, latest submission timestamp).
- `/teach` includes collapsed closeout actions per class: lock class, export today's submissions zip, print join card.
- Closeout export is local-day scoped (deployment timezone aware), with audit events for lock/export actions.

**Why this remains active:**
- Gives teachers a fast day-over-day signal without opening each class.
- Standardizes end-of-class operations into one predictable flow.

## Student portfolio export

**Current decision:**
- Students can download a personal portfolio ZIP from `/student/portfolio-export`.
- The ZIP contains:
  - `index.html` (offline summary with timestamps, lesson/module labels, notes),
  - `files/...` entries for that student's own submissions only.
- Export filenames are sanitized and scoped to the current authenticated student session.

**Why this remains active:**
- Gives students a take-home artifact without requiring full accounts.
- Supports portability and parent/mentor sharing while preserving class privacy boundaries.

## Automated retention maintenance

**Current decision:**
- Use `scripts/retention_maintenance.sh` as the single scheduled task entrypoint for:
  - `prune_submissions`
  - `prune_student_events` (with optional CSV export-before-delete)
  - `scavenge_orphan_uploads` (report/delete/off modes)
- Optional webhook notifications report failures (and optional success) for unattended runs.
- Provide reference systemd units in `ops/systemd/` for daily execution.

**Why this remains active:**
- Moves retention from manual cleanup to reliable routine operations.
- Surfaces cleanup failures early and keeps uploads/event tables bounded over time.
