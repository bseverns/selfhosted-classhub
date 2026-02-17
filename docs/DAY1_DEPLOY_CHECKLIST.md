# Day 1 deploy checklist (Ubuntu)

See `scripts/bootstrap_day1.sh` for an automated starter.

## Essentials
- Create non-root deploy user
- Enable firewall (SSH/80/443 only)
- Install Docker + Compose
- Set Docker log limits
- Create `/srv/classhub` directory spine
- Put backups off-server

## Run
- Copy `compose/.env.example` → `compose/.env`
- Configure LLM backend (default is Ollama; ensure it is running)
- Configure smoke-check credentials in `compose/.env`:
  - `SMOKE_BASE_URL`
  - `SMOKE_CLASS_CODE`
  - `SMOKE_TEACHER_USERNAME`
  - `SMOKE_TEACHER_PASSWORD`
- Run content preflight checks (blocks bad lesson video/copy sync):
  - `bash scripts/content_preflight.sh piper_scratch_12_session`
- Run migration gate:
  - `bash scripts/migration_gate.sh`
- Run deterministic production deploy + smoke:
  - `bash scripts/deploy_with_smoke.sh`
- Manual production compose fallback (if needed):
  - `docker compose -f docker-compose.yml up -d --build`
- Create first superuser
- Create at least one staff teacher account (`is_staff=True`, non-superuser preferred for daily use), e.g.:
  - `docker compose exec classhub_web python manage.py create_teacher --username teacher1 --email teacher1@example.org --password CHANGE_ME`
- Verify health endpoints
- Verify teacher routes:
  - `/teach`
  - `/teach/lessons`

## Domain later
If you do not have a domain yet:
- use `compose/Caddyfile.local` (HTTP on :80)

When a domain exists:
- set `DOMAIN=...` in `.env`
- point DNS A record to server
- copy `compose/Caddyfile.domain` → `compose/Caddyfile`
- Caddy will obtain TLS certificates automatically
