# Decisions (living)

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
