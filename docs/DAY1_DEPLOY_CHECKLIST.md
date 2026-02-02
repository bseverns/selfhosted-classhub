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
- Create superuser
- Verify health endpoints

## Domain later
If you do not have a domain yet:
- use `compose/Caddyfile.local` (HTTP on :80)

When a domain exists:
- set `DOMAIN=...` in `.env`
- point DNS A record to server
- copy `compose/Caddyfile.domain` → `compose/Caddyfile`
- Caddy will obtain TLS certificates automatically
