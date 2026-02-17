# Class Hub Service Notebook (`services/classhub`)

This is the **classroom core**.
If the helper gets weird, Class Hub should still feel steady and boring in the best way.

## What this service owns

- Student entry flow: class code + display name (`/`).
- Student class experience (`/student`).
- Teacher workspace (`/teach*`).
- Admin panel configuration (`/admin`).
- Curriculum persistence (classes, modules, materials).

If you're asking "where should this code live?", default answer is:
- **Class flow + content model** → here.
- **LLM tutoring + chat policy** → `services/homework_helper`.

## Mental model (fast)

- `hub/models.py` = schema for classes/modules/materials and student session data.
- `hub/forms.py` = join/admin-facing forms.
- `hub/middleware.py` = student session loading + request context glue.
- `config/urls.py` = route map for the service.
- `templates/` = plain Django templates; intentionally minimal and readable.

## Local developer loop

From repo root:

```bash
DJANGO_SECRET_KEY=dev-secret python services/classhub/manage.py check
DJANGO_SECRET_KEY=dev-secret python services/classhub/manage.py test
```

If you’re running the full stack, use compose for realistic routing/storage behavior:

```bash
cd compose
docker compose up -d --build
```

## Non-negotiable product intent

- Student auth in MVP is intentionally lightweight: class code + display name.
- Teacher/admin auth rides Django auth and should remain explicit + auditable.
- Reliability beats cleverness. If a trick makes incident response harder, don't ship it.

## Before you open a PR touching this service

- Confirm URL behavior for `/`, `/student`, `/teach`, and `/admin/login/`.
- Confirm no new PII fields were introduced without a docs decision.
- Update `docs/DECISIONS.md` when you make architecture or policy choices.
- Prefer boring migrations and explicit admin config over magic.

That’s the vibe: make it clear, make it durable, and keep future-you out of pager hell.
