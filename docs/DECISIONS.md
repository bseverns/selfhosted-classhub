# Decisions (living)

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
