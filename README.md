# Self‑Hosted Class Hub + Homework Helper (Django)

A lightweight, self-hosted learning portal inspired by the needs that surfaced around TailorEDU-style workflows — but built to be **reliable, inspectable, and owned by your org**.

This repo is intentionally *Day‑1 shippable*: it boots on a single Ubuntu server using Docker Compose and gives you:

- **Class Hub** (Django): class-code student access, teacher portal at `/teach`, Django admin for deep ops, class materials pages.
- **Homework Helper** (Django): separate service behind `/helper/*` with a configurable LLM backend (Ollama by default).
- Helper widget now lives in both the class summary and each lesson page so students can ask for hints in context.
- **Postgres + Redis + MinIO + Caddy**: boring infrastructure you can trust.

Also included:

- **Homework dropbox** for lesson file submissions (extension rules come from lesson front matter, tied to the student session cookie)
- **Lesson video manager** with publish/draft status and bulk upload for teacher workflows

> Philosophy: keep the system legible. Logs you can read. Deploys you can repeat. Features that don’t hide in someone else’s cloud.

## Quick start (local / no domain yet)

1) Copy env template:

```bash
cp compose/.env.example compose/.env
# Set Ollama/OpenAI settings as needed (helper defaults to Ollama)
```

2) Run the stack:

```bash
cd compose
docker compose up -d --build
```

3) Check health:

- Class Hub: `http://localhost/healthz`
- Helper: `http://localhost/helper/healthz`

4) Create a first admin account:

```bash
cd compose
docker compose exec classhub_web python manage.py createsuperuser
```

5) Visit:

- Teacher portal: `http://localhost/teach`
- Lesson tracker: `http://localhost/teach/lessons`
- Lesson videos manager: `http://localhost/teach/videos`
- Admin: `http://localhost/admin/`
- Student join page: `http://localhost/`

## Teacher accounts

For daily teaching, prefer staff (non-superuser) accounts.

1. Create a staff teacher account from the running container:

```bash
cd compose
docker compose exec classhub_web python manage.py create_teacher \
  --username teacher1 \
  --email teacher1@example.org \
  --password CHANGE_ME
```

2. Change password later if needed:

```bash
cd compose
docker compose exec classhub_web python manage.py create_teacher \
  --username teacher1 \
  --password NEW_PASSWORD \
  --update
```

3. Verify access:
- Staff teachers can use `/teach` and `/teach/lessons`.
- Superusers can also use `/admin`.

See `docs/TEACHER_PORTAL.md` for full teacher account and portal workflow details.
Command cookbook script: `scripts/examples/teacher_accounts.sh` (dry-run by default).
Personnel changes (onboard/offboard/update teacher details): `docs/TEACHER_PORTAL.md#changing-personnel-new-or-different-teachers`.
Handoff runbook: `docs/TEACHER_HANDOFF_CHECKLIST.md`.

## Local development (hot reload)

For fast edits without rebuilding images, use the dev override file:

- `compose/docker-compose.override.yml` (bind-mounts source + uses `runserver`)

Start with:

```bash
cd compose
docker compose up -d
```

See `docs/DEVELOPMENT.md` for details (content-only mounts, rebuild rules, and DEBUG behavior).

## Homework Helper LLM backend

By default, the helper is configured to use a local Ollama server. See:

- `docs/OPENAI_HELPER.md` (LLM backend configuration and strictness switch)
- `docs/HELPER_POLICY.md` (tutor stance + strictness notes)
- `docs/HELPER_EVALS.md` (prompt set + eval script)
- `docs/DISASTER_RECOVERY.md` (start-from-zero rebuild checklist)
- `scripts/new_course_scaffold.py` (create a new course skeleton)
- `docs/COURSE_AUTHORING.md` (how to create and edit courses)
- `scripts/ingest_syllabus_md.py` (parse a syllabus .md into a course)
- `scripts/validate_lesson_video_order.py` (check foundational video sequence)
- `scripts/content_preflight.sh` (pre-deploy content validation gate)

## Production (with a domain)

See:
- `docs/DAY1_DEPLOY_CHECKLIST.md`
- `docs/BOOTSTRAP_SERVER.md`

Note: Production should **not** load the dev override file. Use
`docker compose -f docker-compose.yml up -d --build` or remove the override.

## What’s next

- Add content authoring UI (beyond admin)
- Add RAG over class materials (pgvector) and citations in helper
- Add optional “return code” for students who clear cookies
- Add Google SSO for teachers (student access can remain class-code)

## Repo-authored course packs (markdown)

This repo can ship curriculum **inside the codebase** (versioned in git) and render it
as student-facing pages.

Layout:

```
services/classhub/content/
  courses/
    <course_slug>/
      course.yaml
      lessons/*.md
      video-scripts/*.md
      checklists/*.md
```

Import a course pack into a Class as Modules + Materials:

```bash
cd compose
docker compose exec classhub_web python manage.py import_coursepack --course-slug piper_scratch_12_session --create-class --replace
```

Students will see one module per session with an **Open lesson** link.
If a lesson has `submission.type: file`, import also creates a **Homework dropbox** material.

## Repository map

- `compose/` – Docker Compose + Caddy routing
- `services/classhub/` – Django class portal
- `services/homework_helper/` – Django helper service (OpenAI)
- `docs/` – architecture, decisions, ops, and policy
- `scripts/` – server bootstrap + backup helpers
