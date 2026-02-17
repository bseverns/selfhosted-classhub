# Self-Hosted Class Hub + Homework Helper (Django)

A lightweight, self-hosted LMS focused on reliable classroom operations.

Mission:
- reliable (boring infra)
- inspectable (logs, checks, audit trails)
- privacy-forward (minimal student identity model)
- fast to ship (MVP-first architecture)

## Architecture at a glance

- `Class Hub` (Django): student join/session flow, class views, `/teach`, `/admin`.
- `Homework Helper` (Django): separate AI tutor service under `/helper/*`.
- `Caddy`: reverse proxy and TLS termination.
- `Postgres`: primary data store.
- `Redis`: cache/rate-limit/queue state.
- `MinIO`: object storage for uploads/assets.

Detailed architecture: `docs/ARCHITECTURE.md`

## Quickstart (local)

1. Configure environment:

```bash
cp compose/.env.example compose/.env
```

2. Set routing template in `compose/.env`:

```env
CADDYFILE_TEMPLATE=Caddyfile.local
```

3. Build and run:

```bash
cd compose
docker compose up -d --build
```

4. Create initial admin:

```bash
docker compose exec classhub_web python manage.py createsuperuser
```

5. Verify health:

- `http://localhost/healthz`
- `http://localhost/helper/healthz`

## Docs entrypoint

Start with `docs/START_HERE.md` for role-specific paths:
- Operator
- Teacher/staff
- Developer
