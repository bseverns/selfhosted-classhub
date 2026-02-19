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
- Set a strong `DJANGO_SECRET_KEY` (do not keep placeholder/default values)
- Keep admin 2FA enforcement enabled: `DJANGO_ADMIN_2FA_REQUIRED=1`
- For domain/TLS mode, set:
  - `DJANGO_SECURE_SSL_REDIRECT=1`
  - `DJANGO_SECURE_HSTS_SECONDS=31536000` (after initial validation)
- Confirm proxy body limits for your workload:
  - `CADDY_CLASSHUB_MAX_BODY` (uploads; default `650MB`)
  - `CADDY_HELPER_MAX_BODY` (helper API; default `1MB`)
- Configure LLM backend (default is Ollama; ensure it is running)
- Configure smoke-check credentials in `compose/.env` (for strict mode):
  - `SMOKE_BASE_URL`
  - `SMOKE_CLASS_CODE`
  - `SMOKE_TEACHER_USERNAME`
  - `SMOKE_TEACHER_PASSWORD`
- Optional: use fixture-backed golden smoke mode to avoid managing static smoke credentials:
  - `DEPLOY_SMOKE_MODE=golden bash scripts/deploy_with_smoke.sh`
- Run content preflight checks (blocks bad lesson video/copy sync):
  - `bash scripts/content_preflight.sh piper_scratch_12_session`
- Validate deploy secrets and routing env:
  - `bash scripts/validate_env_secrets.sh`
- Run migration gate:
  - `bash scripts/migration_gate.sh`
- Run deterministic production deploy + smoke:
  - `bash scripts/deploy_with_smoke.sh`
- Run one-command end-to-end diagnostic:
  - `bash scripts/system_doctor.sh`
- Manual production compose fallback (if needed):
  - `docker compose -f docker-compose.yml up -d --build`
- Create first superuser
- Create at least one staff teacher account (`is_staff=True`, non-superuser preferred for daily use), e.g.:
  - `docker compose exec classhub_web python manage.py create_teacher --username teacher1 --email teacher1@example.org --password CHANGE_ME`
- Verify health endpoints
- Verify teacher routes:
  - `/teach`
  - `/teach/lessons`

## Routing mode switch (local vs domain)
Use `.env` as the single selector (no ad-hoc file renames):

- Local/day-1 mode:
  - `CADDYFILE_TEMPLATE=Caddyfile.local`
  - `DOMAIN` can stay placeholder
- Domain/TLS mode:
  - `CADDYFILE_TEMPLATE=Caddyfile.domain`
  - set real `DOMAIN=...`
  - point DNS A/AAAA record to server

Then deploy/reload:

```bash
cd compose
docker compose -f docker-compose.yml up -d --build
```

If you need a manual fallback (older docs/scripts), use explicit copy commands:

```bash
cp compose/Caddyfile.local compose/Caddyfile
cp compose/Caddyfile.domain compose/Caddyfile
```

PowerShell equivalents:

```powershell
Copy-Item compose/Caddyfile.local compose/Caddyfile -Force
Copy-Item compose/Caddyfile.domain compose/Caddyfile -Force
```

## Verification commands (run in both modes)

Local mode expectations (`CADDYFILE_TEMPLATE=Caddyfile.local`):

```bash
cd compose
docker compose ps
curl -i http://localhost/healthz
curl -i http://localhost/helper/healthz
curl -I http://localhost/
```

Expected behavior: health endpoints return `200` on `http://localhost`; no TLS required.

Domain mode expectations (`CADDYFILE_TEMPLATE=Caddyfile.domain`):

```bash
cd compose
docker compose ps
curl -i https://$DOMAIN/healthz
curl -i https://$DOMAIN/helper/healthz
curl -I http://$DOMAIN/
curl -I https://$DOMAIN/
```

Expected behavior: HTTPS endpoints return `200`; HTTP redirects to HTTPS (`301`/`308`).

Service exposure defaults:
- Postgres/Redis are internal-only on Docker networking.
- Ollama (`11434`) and MinIO console (`9001`) bind to `127.0.0.1` on host.
