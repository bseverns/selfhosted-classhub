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
- Run content preflight checks (blocks bad lesson video/copy sync):
  - `bash scripts/content_preflight.sh piper_scratch_12_session`
- Run production compose only (ignore dev override):
  - `docker compose -f docker-compose.yml up -d --build`
  - or remove/rename `docker-compose.override.yml` first
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
