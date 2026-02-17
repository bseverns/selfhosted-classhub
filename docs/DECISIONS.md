# Decisions (living)

## 2026-02-17 — Add regression coverage for helper auth/admin hardening

**Why:**
- Helper auth/admin safeguards were added quickly and needed explicit tests to prevent future drift.
- Without tests, stale-session rejection and helper admin superuser gating could regress silently.

**Tradeoffs:**
- Slightly larger helper test suite.
- Uses lightweight mocking for DB-unavailable fallback behavior.

**Plan:**
- Add helper tests for stale student sessions (`_student_session_exists=False` => `401`).
- Add helper tests for classhub-table-unavailable fallback (`ProgrammingError` => fail-open function behavior).
- Add helper admin access tests (staff non-superuser denied; superuser allowed).

## 2026-02-17 — Restore classhub test baseline after security hardening

**Why:**
- `classhub` test suite was failing on two baseline issues unrelated to feature intent:
  - upload view lock-state path referenced `form` before assignment;
  - file-backed model tests require a configured default Django storage backend.
- A reliable test baseline is part of the repo's "boring infra" promise.

**Tradeoffs:**
- Slightly more explicit settings (`STORAGES["default"]`) in classhub config.
- No behavior change for production uploads; this aligns tests with real runtime expectations.

**Plan:**
- Initialize `SubmissionUploadForm` before lock-state branching in `material_upload`.
- Add `STORAGES["default"] = django.core.files.storage.FileSystemStorage` in classhub settings.
- Re-run classhub tests to confirm regression closure.

## 2026-02-17 — Fail fast when `DJANGO_SECRET_KEY` is missing in both services

**Why:**
- Silent fallback secrets are operationally dangerous: a stack can boot "fine" with an insecure key.
- Demo and production environments should fail loudly when identity/session signing secrets are missing.

**Tradeoffs:**
- Fresh setup now hard-fails until `.env` is populated correctly.
- Slightly less forgiving for quick local experiments.

**Plan:**
- Require `DJANGO_SECRET_KEY` in `services/classhub/config/settings.py` and `services/homework_helper/config/settings.py`.
- Keep `.env.example` as the teaching scaffold and call out required secret setup in README.

## 2026-02-17 — Harden helper actor validation and error labeling

**Why:**
- Helper auth should reject stale student sessions when shared DB tables are available.
- Incident response needs accurate backend error labels; generic parsing errors should not be tagged as Ollama outages.

**Tradeoffs:**
- Helper now performs one lightweight DB existence check for student sessions.
- On deployments without shared classhub schema access, helper gracefully falls back to session-only auth checks.

**Plan:**
- Validate `student_id` + `class_id` against `hub_studentidentity` when reachable.
- Keep permissive fallback when table/schema is unavailable.
- Restrict `ollama_error` responses to actual network/HTTP failures from Ollama paths.

## 2026-02-17 — Align helper admin surface with classhub superuser-only policy

**Why:**
- Class Hub already gates Django admin behind superuser checks.
- Helper service should mirror that boundary for consistency and least privilege.

**Tradeoffs:**
- Non-superuser staff can no longer access helper admin.

**Plan:**
- Apply a superuser-only `admin.site.has_permission` override in helper URLs.

## 2026-02-16 — Add teacher-managed lesson asset library (folders + files)

**Why:**
- Teachers need to add/update classroom reference files (GPIO maps, handouts, checklists) without shell/git edits.
- Non-programmer staff need the same assets visible in Django admin for backup operations and audits.

**Tradeoffs:**
- Lesson assets now live in the database/media store, while markdown lessons still live in git.
- Asset links use stable app routes (`/lesson-asset/<id>/download`) rather than direct storage paths.

**Plan:**
- Add `LessonAssetFolder` and `LessonAsset` models with publish/draft status.
- Add staff UI at `/teach/assets` for folder creation, uploads, and publish/hide/delete actions.
- Add protected asset route `/lesson-asset/<id>/download` and expose assets in Django admin.

## 2026-02-16 — Add plain-English structure comments in core Class Hub code files

**Why:**
- Non-programmer staff need to understand request flow and ownership boundaries quickly during demos and support.
- Variable names alone do not explain "where traffic goes" and "which route is for whom."

**Tradeoffs:**
- More comments means a small maintenance cost when routes or auth flow change.

**Plan:**
- Add high-level flow comments in:
  - `services/classhub/config/urls.py`
  - `services/classhub/hub/middleware.py`
  - `services/classhub/hub/views.py`
- Keep these as comment-only changes (no behavior changes).

## 2026-02-16 — Expand documentary comments in settings/models/release logic

**Why:**
- Team handoff requires context that explains operational intent (not just variable names).
- Office staff need a literal map of "what this switch/route/model does" during support.

**Tradeoffs:**
- Slightly larger source files and a small ongoing comment-maintenance burden.

**Plan:**
- Add plain-English comments in:
  - `services/classhub/config/settings.py`
  - `services/classhub/hub/models.py`
  - `services/classhub/hub/views.py` (release, upload, teacher actions)
- Keep these as comment-only/documentation changes.

## 2026-02-16 — Add explicit “Done for now” cues in student class views

**Why:**
- Students and non-technical staff need a clear visual definition of completion.
- “Upload exists” was visible but not explicit as a completion signal.

**Tradeoffs:**
- “Done for now” means at least one upload exists; it is not rubric-graded completion.

**Plan:**
- Add a small status legend in student class view.
- Show `Done for now` badge when a student has at least one submission for a dropbox.
- Mirror that cue on lesson dropbox and upload pages.

## 2026-02-16 — Add plain-language What/Where/Why guide for non-programmer staff

**Why:**
- Existing docs are strong for engineering/operations but harder for non-technical coworkers.
- Demo support and day-to-day handoff improve when one plain-language entry point exists.

**Tradeoffs:**
- Adds one more doc to keep current as routes and workflows evolve.
- Some overlap with teacher/runbook docs is intentional to reduce confusion.

**Plan:**
- Add `docs/WHAT_WHERE_WHY.md` with URL map, role map, quick checklist, and troubleshooting.
- Link this guide from `README.md` so it is easy to find.

## 2026-02-16 — Add explicit teacher logout route and simplify admin login UI

**Why:**
- Teachers needed an obvious way to end staff sessions from `/teach` screens.
- The admin login view should avoid extra sidebar/theme/filter controls that distract from sign-in.

**Tradeoffs:**
- `/teach/logout` always clears the full session and redirects to `/admin/login/`.
- Admin sidebar navigation filters are disabled globally for a simpler admin surface.

**Plan:**
- Add `GET /teach/logout` that logs out Django auth and flushes session state.
- Add `Log out` links to all teacher templates.
- Disable Django admin nav sidebar and hide login-page toggle/popout controls.

## 2026-02-16 — Same-device rejoin without return code using signed cookie hints

**Why:**
- Return-code-only rejoin is secure across devices, but too heavy for fixed classroom machines.
- Students often rejoin from the same browser after session expiry/logout.

**Tradeoffs:**
- Same-device rejoin now depends on browser cookie persistence.
- Shared machines can still reuse identity only when class code + display name match.

**Plan:**
- Store a signed, HTTP-only device hint cookie after successful join.
- If `return_code` is omitted, allow same-device rejoin when cookie maps to the same class + display name.
- Keep return code required for cross-device recovery.

## 2026-02-16 — Replace display-name auto-rejoin with explicit student return codes (amended)

**Why:**
- Reusing identity by display name enabled accidental or deliberate impersonation in class.
- We need a low-friction way to reclaim identity after cookie loss without relying on name collisions.

**Tradeoffs:**
- Students now need a short return code to reclaim an existing identity.
- Entering an invalid return code returns an explicit join error instead of silently creating/reusing records.

**Plan (initial):**
- Add `StudentIdentity.return_code` (unique per class).
- First join creates a new identity and returns the code.
- Rejoin only reuses identity when `return_code` matches.

## 2026-02-16 — Helper endpoint now requires classroom/staff session and proxy-aware limits

**Why:**
- `/helper/chat` was publicly reachable and CSRF-exempt.
- IP-only throttling based on `REMOTE_ADDR` can collapse all users behind a proxy.

**Tradeoffs:**
- Anonymous users cannot use helper chat.
- Rate limit keys now include both actor/session and client IP, which is stricter but safer for shared infrastructure.

**Plan:**
- Require either student session (`student_id`, `class_id`) or staff auth.
- Keep CSRF protection enabled for helper POST requests.
- Read client IP from `X-Forwarded-For` with validation fallback to `REMOTE_ADDR`.
- Apply per-actor and per-IP limits.

## 2026-02-16 — Align helper runtime and routing with production compose

**Why:**
- Helper container runtime port and Caddy helper route handling were inconsistent with app URLs.
- Both Django services depend on Gunicorn in Docker CMD.

**Tradeoffs:**
- Dependency set is slightly larger (`gunicorn`, `openai` in helper; `gunicorn` in classhub).

**Plan:**
- Bind helper Gunicorn to port `8000` (matching compose reverse proxy target).
- Use Caddy `handle /helper/*` (no path stripping).
- Add required runtime dependencies to requirements files.

## 2026-02-16 — Rejoin by class code reuses existing student identity by display name (superseded)

**Why:**
- Students who log out and rejoin with the same name were creating duplicate identities.
- Duplicate identities fragment submission history and lesson progress visibility.

**Tradeoffs:**
- Name matching is class-scoped and case-insensitive.
- Students sharing the same display name in one class will map to one identity in MVP.

**Plan:**
- On `/join`, lookup existing `StudentIdentity` by `classroom + display_name__iexact`.
- Reuse that identity and refresh `last_seen_at` instead of creating a new row.
- Serialize join flow per class transaction to reduce same-name race duplicates.

## 2026-02-16 — Date-based lesson release with intro-only pre-access

**Why:**
- Teachers need calendar-based pacing without exposing full activities early.
- Students should see lesson context before unlock, but full exploration and submissions should wait for schedule.

**Tradeoffs:**
- Release behavior is driven by content metadata (`available_on`) and depends on accurate dates.
- Intro-only extraction uses heading boundaries (`##`) and may need editorial tuning for unusual lesson formats.

**Plan:**
- Add optional `available_on: YYYY-MM-DD` on lesson metadata.
- Before release, render intro-only lesson content for students and hide full lesson blocks.
- Block lesson-linked uploads until the release date.
- Show unlock date status on `/student` materials and lesson pages.
- Add per-class release overrides in teacher tools so staff can set date, lock/unlock, or reset defaults without editing markdown.

## 2026-02-16 — Restrict Django admin to superusers; hide admin links for non-admin teachers

**Why:**
- Teachers use `/teach` for day-to-day operations.
- `/admin` should be visible and accessible only to accounts with explicit admin authority.

**Tradeoffs:**
- Staff users who are not superusers can no longer access Django admin.
- Operational tasks needed by teachers must remain available in `/teach`.

**Plan:**
- Override admin site permission check to require `is_superuser`.
- Keep teacher portal staff-only.
- Render `/admin` links in teacher templates only when `request.user.is_superuser`.

## 2026-02-16 — Keep lesson pages learner-only; move teacher notes to teacher tools

**Why:**
- Learner lesson pages were rendering teacher-authored sections (prep, agenda, checkpoints).
- We need `/course/...` to be safe for student-only reading.

**Tradeoffs:**
- Teacher sections are hidden from learner pages by heading-based rules.
- Mis-labeled headings may land in the wrong audience bucket until normalized.

**Plan:**
- Split lesson markdown into learner vs teacher sections at render time.
- Treat headings like `Teacher prep`, `Agenda`, `Materials`, `Checkpoints`, and `Common stuck points` as teacher-only.
- Keep teacher notes visible in `/teach/lessons` and `/teach/class/<id>` via expandable panels.

## 2026-02-16 — Fail-open lesson pages when `LessonVideo` table is missing

**Why:**
- `LessonVideo` code paths can execute before migration `hub.0002_lessonvideo` is applied.
- Student lesson pages should not hard-fail due to schema drift.

**Tradeoffs:**
- Stored lesson videos are temporarily hidden when the table is absent.
- This safety layer does not replace running migrations.

**Plan:**
- Catch missing-table DB errors in lesson video read paths.
- Return lesson pages without DB-backed videos instead of raising `500`.
- Show a clear migrate action in teacher video management.

## 2026-02-13 — Self-hosted lesson video library with teacher tagging + accordion playback

**Why:**
- Course front matter listed lesson videos, but non-YouTube sources were link-only.
- Teachers needed an in-product way to upload and tag videos to specific lessons.
- Student lesson pages needed a cleaner video UX (open one at a time, avoid multiple concurrent players).

**Tradeoffs:**
- Uploaded files are streamed through Django for access control, which is simpler but less efficient than direct object storage/CDN delivery at scale.
- Teacher tagging currently keys on `course_slug + lesson_slug` (global), not per-class overrides.

**Plan:**
- Add `LessonVideo` model with tagged metadata (`course_slug`, `lesson_slug`, title, outcome, URL or uploaded file, order).
- Add staff UI at `/teach/videos` for upload/link, ordering, and deletion.
- Add publish/draft controls so teachers can stage videos before student release.
- Add bulk file upload flow to reduce repetitive tagging work for multi-clip lessons.
- Add secure stream endpoint `/lesson-video/<id>/stream` with byte-range support for seekable playback.
- Render lesson videos as an accordion where clicking a heading opens that item and closes/pause-resets others.
- Keep YouTube embed support while adding inline playback for self-hosted/native video URLs.

## 2026-02-13 — Add `create_teacher` management command for staff account ops

**Why:**
- Shell one-liners for user creation are easy to mistype and hard to remember.
- Teacher onboarding and recovery should use a repeatable, documented command.

**Tradeoffs:**
- Adds a small command-maintenance surface in `hub.management.commands`.
- We still rely on Django password auth (SSO planned later).

**Plan:**
- Add `manage.py create_teacher` for create/update flows.
- Default to `is_staff=True`, non-superuser for least privilege.
- Support updates (`--update`) for password resets and account activation changes.

## 2026-02-13 — Teacher-first portal centered on lessons and submissions

**Why:**
- Teachers primarily need lesson flow and submission visibility, not full admin object editing.
- Existing `/teach` screens exposed module/material internals first, which made day-to-day teaching tasks slower.

**Tradeoffs:**
- Lesson tracking depends on detecting lesson links from module materials (`/course/<course>/<lesson>` pattern).
- If classes use custom link structures, they may not appear in the lesson tracker.

**Plan:**
- Add `/teach/lessons` as a lesson-level tracker grouped by class.
- Show per-lesson dropbox progress (`submitted / total`, missing count, latest upload timestamp).
- Add direct triage actions from lesson rows (`all`, `missing`, `download latest zip`) to reduce click depth.
- Add a primary row-level `Review missing now` shortcut that targets the highest-missing dropbox.
- Add recent submissions summary to `/teach` for quick triage.
- Keep module/material editing in place as a secondary workflow, not the primary teacher view.

## 2026-02-08 — Scripted course-pack rebuilds for test classes

**Why:**
- Curriculum edits require re-importing Modules + Materials.
- We want a single, repeatable command that targets a class code or creates a new class.

**Tradeoffs:**
- Assumes a Compose-based workflow and container name `classhub_web`.
- Adds a small maintenance surface (the wrapper script).

**Plan:**
- Add `scripts/rebuild_coursepack.sh` to wrap `import_coursepack`.
- Document the script in `docs/DEVELOPMENT.md`.

## 2026-02-04 — Lesson-linked homework dropbox from front matter

**Why:**
- Students needed a predictable place to submit work directly from each lesson.
- Submission rules already exist in lesson front matter (`submission.type`, `accepted`, `naming`).
- Teachers should not have to manually create upload materials per lesson.

**Tradeoffs:**
- Dropbox availability now depends on importing course packs into class modules.
- Non-file submissions (`submission.type: text`) still rely on teacher workflow outside file uploads.

**Plan:**
- During `import_coursepack`, auto-create a `Homework dropbox` material for any lesson with `submission.type: file`.
- Use front matter extension rules to configure allowed upload types.
- Surface the dropbox on lesson pages when a student is signed in, with latest upload status.

## 2026-01-30 — Local dev override for hot reload

**Why:**
- Avoid rebuilds for every template/markdown/Python change.
- Faster local iteration while keeping production images stable.

**Tradeoffs:**
- Uses Django `runserver` + `DJANGO_DEBUG=1` (not production-safe).
- Static handling differs from production (`collectstatic` not required in dev).

**Plan:**
- Keep `compose/docker-compose.override.yml` for local dev only.
- Use production build (`--build`) when deploying or testing prod-like behavior.

## 2026-01-30 — Local LLM via Ollama (OpenAI optional)

**Why:**
- Keep student prompts and responses on our infrastructure.
- Predictable cost for a single-course launch.
- Allow prompt + RAG iteration without third-party dependencies.

**Tradeoffs:**
- We own model quality, safety, and availability.
- Hardware constraints (GPU/CPU) can affect latency.

**Plan:**
- Default `HELPER_LLM_BACKEND=ollama`.
- Keep an optional OpenAI backend for future fallback.
- Add a strictness switch (`HELPER_STRICTNESS`) to adjust answer policy.
- Default to a small model on CPU-only servers; adjust as hardware allows.
- Add a Redis-backed concurrency queue to avoid overload on small servers.

## 2026-02-01 — Per-lesson reference files for helper expertise

**Why:**
- Small models respond better to short, lesson-specific context.
- Avoids a single giant reference file that dilutes signal.
- Lets expertise shift as students move through lessons.

**Tradeoffs:**
- More files to manage.
- Requires a generator to keep references aligned with lesson content.

**Plan:**
- Generate `reference/<lesson_slug>.md` files from course markdown.
- Set `helper_reference: <lesson_slug>` per lesson in `course.yaml`.
- Allow safe slug-based reference lookup in the helper.

## 2026-02-01 — Scratch-only guardrails for helper responses

**Why:**
- Avoid irrelevant text-language answers (e.g., Pascal) for Scratch lessons.
- Keep responses aligned with blocks-based instruction.

**Tradeoffs:**
- Overly strict keyword filtering may redirect some legitimate questions.

**Plan:**
- Add Scratch-only guardrails in the prompt policy.
- Add a lightweight redirect filter in the helper for text-language keywords.
- Lower randomness for the Ollama backend.
- Allow an explicit per-lesson allowed-topics list and redirect off-topic queries.
- Default to strict scope + strict allowed-topics for Scratch-only course delivery.

## 2026-01-16 — Student access is class-code + display name

**Why:**
- Minimum friction for classrooms.
- Minimal PII collection.
- Fewer account recovery issues at MVP stage.

**Tradeoffs:**
- If a student clears cookies, they “lose” identity unless we add a return-code.

**Plan:**
- MVP uses session cookie only.
- Add optional “return code” later.

## 2026-01-16 — Homework Helper is a separate service

**Why:**
- Reliability: helper failures do not block class materials.
- Safety: independent rate limits and logs.
- Clarity: prompt policy lives in one place.
