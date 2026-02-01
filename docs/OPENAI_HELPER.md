# Homework Helper (LLM backend)

The helper service is a Django app that exposes:

- `GET /helper/healthz`
- `POST /helper/chat`

By default, the helper is wired to a local LLM server (Ollama).
OpenAI is supported as an **optional** backend, but is not required.

## Backend selection

Set the backend in `compose/.env`:

```bash
HELPER_LLM_BACKEND=ollama   # or "openai"
HELPER_STRICTNESS=light     # or "strict"
HELPER_SCOPE_MODE=soft      # or "strict"
HELPER_REFERENCE_FILE=/app/tutor/reference/piper_scratch.md
HELPER_REFERENCE_DIR=/app/tutor/reference
HELPER_REFERENCE_MAP={"piper_scratch":"piper_scratch.md"}
HELPER_MAX_CONCURRENCY=2
HELPER_QUEUE_MAX_WAIT_SECONDS=10
HELPER_QUEUE_POLL_SECONDS=0.2
HELPER_QUEUE_SLOT_TTL_SECONDS=120
```

### Ollama (local)

Required env:

```
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_MODEL=llama3.2:1b
OLLAMA_TIMEOUT_SECONDS=30
```

Ollama is included in `compose/docker-compose.yml` and persists models at
`data/ollama/`. Pull a model with:

```bash
cd compose
docker compose exec ollama ollama pull llama3.2:1b
```

On CPU-only servers with limited RAM, keep the model small (1B–2B range).
Larger models may be too slow or may not fit in memory.

If you run Ollama outside of Compose, set `OLLAMA_BASE_URL` to the host address
that containers can reach.

### OpenAI (optional)

If you want to re-enable OpenAI later:

```
HELPER_LLM_BACKEND=openai
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-5.2
```

You will also need to add the `openai` dependency back to
`services/homework_helper/requirements.txt`.

## Tutor stance and strictness

We support two modes:

- `HELPER_STRICTNESS=light` (default): may give direct answers, but must explain
  reasoning and include a check-for-understanding question.
- `HELPER_STRICTNESS=strict`: no final answers for graded work; respond with
  hints, steps, and questions.

The strictness switch is intentionally simple so teachers can “throw the switch”
without code changes.

## Lesson context metadata

Lesson pages now pass contextual data down to the helper widget so the backend
knows which lesson (and which topics) the student is working on:

- `data-helper-context`: lesson title/slug (or classroom summary) stored as `context`.
- `data-helper-topics`: a short summary derived from the lesson front matter (makes,
  needs, videos, session) stored as `topics`.

The helper service appends those values to the system instructions before calling
the LLM, giving you transparent, lesson-aware responses. Customize the include
or the lesson front matter to adjust how much metadata flows through.

## Course reference facts

You can reinforce subject expertise by providing a reference file with concrete
facts and workflows for the course. The helper will include this text in the
system instructions:

```
HELPER_REFERENCE_FILE=/app/tutor/reference/piper_scratch.md
```

The example `piper_scratch.md` lives in the helper image and can be edited to
match your curriculum.

### Multiple reference files (per course or lesson)

Use a reference key in `course.yaml` or `lesson` entries:

```
helper_reference: piper_scratch
```

Then configure a map in `.env` so the helper can resolve the key to a file:

```
HELPER_REFERENCE_DIR=/app/tutor/reference
HELPER_REFERENCE_MAP={"piper_scratch":"piper_scratch.md"}
```

This keeps file access safe and lets you swap references per lesson or course.

### Per-lesson references generated from content

For lesson-specific expertise, generate one reference file per lesson slug.
The helper will load `reference_dir/<lesson_slug>.md` when a lesson sets
`helper_reference: <lesson_slug>` in `course.yaml`.

Generate references from the course markdown:

```bash
python scripts/generate_lesson_references.py \
  --course services/classhub/content/courses/piper_scratch_12_session/course.yaml \
  --out services/homework_helper/tutor/reference
```

## Scope mode

Use `HELPER_SCOPE_MODE` to control how strictly the helper stays within the lesson:

- `soft` (default): prefer lesson scope, gently redirect off-topic requests
- `strict`: refuse unrelated questions and ask students to rephrase

## Queue / concurrency limits

On CPU-only servers, limit concurrent model calls to avoid overload.
The helper uses a small Redis-backed slot queue:

- `HELPER_MAX_CONCURRENCY`: maximum simultaneous LLM calls (default: 2)
- `HELPER_QUEUE_MAX_WAIT_SECONDS`: how long to wait for a slot (default: 10)
- `HELPER_QUEUE_POLL_SECONDS`: polling interval (default: 0.2)
- `HELPER_QUEUE_SLOT_TTL_SECONDS`: auto-release safety timeout (default: 120)

Canonical policy notes live in:

- `services/homework_helper/tutor/fixtures/policy_prompts.md`
- `docs/HELPER_POLICY.md`

## RAG (planned)

Phase 2 will retrieve relevant snippets from class materials and include citations.

## Evals (recommended)

- `services/homework_helper/tutor/fixtures/eval_prompts.jsonl`
- `docs/HELPER_EVALS.md`
