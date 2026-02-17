# Runbook

This page is operational depth for operators.
For first-time orientation and canonical URL map, start at `docs/START_HERE.md`.

## Start / stop

```bash
cd /srv/lms/compose
docker compose up -d
# stop:
docker compose down
```

## Production deploy (guardrailed)

From repo root:

```bash
cd /srv/lms
bash scripts/deploy_with_smoke.sh
```

What it enforces:
- migration gate (`makemigrations --check --dry-run`) for both Django services
- compose launch using only `compose/docker-compose.yml` (no implicit override behavior)
- Caddy mount guardrail (`/etc/caddy/Caddyfile` must come from `compose/Caddyfile`)
- smoke checks (`/healthz`, `/helper/healthz`, student join, helper chat, teacher login)

Optional rollback hook:

```bash
ROLLBACK_CMD='echo "replace with your rollback command"' bash scripts/deploy_with_smoke.sh
```

## Local development

See `docs/DEVELOPMENT.md` (canonical local dev workflow).

## Local LLM (Ollama)

The helper defaults to Ollama. Ensure the model server is running and reachable
from the `helper_web` container.

Pull a model (Compose):

```bash
cd /srv/lms/compose
docker compose exec ollama ollama pull llama3.2:1b
```

Minimal check:

```bash
curl http://localhost:11434/api/tags
```

If Ollama runs on the Docker host instead of Compose, set `OLLAMA_BASE_URL`
to the host address that containers can reach.

## Helper queue tuning

For CPU-only deployments, cap concurrent model calls:

```
HELPER_MAX_CONCURRENCY=2
HELPER_QUEUE_MAX_WAIT_SECONDS=10
HELPER_QUEUE_POLL_SECONDS=0.2
HELPER_QUEUE_SLOT_TTL_SECONDS=120
```

## Logs

```bash
docker compose logs -f --tail=200 classhub_web
```

Helper telemetry logs:

```bash
docker compose logs -f --tail=200 helper_web
```

Look for structured helper events (`success`, `queue_busy`, `backend_transport_error`)
that include `request_id`, attempts, and timing.

## Migration gate only

```bash
bash scripts/migration_gate.sh
```

## Smoke checks only

```bash
bash scripts/smoke_check.sh --strict
```

## Teacher accounts

Canonical teacher account workflow:
- `docs/TEACHER_PORTAL.md`
- `docs/TEACHER_HANDOFF_CHECKLIST.md`
- `docs/TEACHER_HANDOFF_RECORD_TEMPLATE.md`

Command script:
- `scripts/examples/teacher_accounts.sh` (dry-run by default; use `RUN=1` to execute)

## Pre-deploy content checks

```bash
bash scripts/content_preflight.sh piper_scratch_12_session
```

Use strict global checks when you want full video sequence enforcement:

```bash
bash scripts/content_preflight.sh piper_scratch_12_session --strict-global
```

## Backups

- `scripts/backup_postgres.sh`
- `scripts/backup_minio.sh`

## Disaster recovery

See `docs/DISASTER_RECOVERY.md` for a start-from-zero checklist and settings.

## Restore drill (recommended)

- Restore Postgres dump into a temporary DB
- Confirm Django can migrate and start

## Submission retention

Dry run:

```bash
cd /srv/lms/compose
docker compose exec classhub_web python manage.py prune_submissions --older-than-days 90 --dry-run
```

Apply:

```bash
cd /srv/lms/compose
docker compose exec classhub_web python manage.py prune_submissions --older-than-days 90
```

Optional default via `.env`:

```
CLASSHUB_SUBMISSION_RETENTION_DAYS=90
```

## Student event retention

Dry run:

```bash
cd /srv/lms/compose
docker compose exec classhub_web python manage.py prune_student_events --older-than-days 180 --dry-run
```

Apply:

```bash
cd /srv/lms/compose
docker compose exec classhub_web python manage.py prune_student_events --older-than-days 180
```

Optional default via `.env`:

```
CLASSHUB_STUDENT_EVENT_RETENTION_DAYS=180
```

## Audit events

Staff actions in `/teach/*` are written to `AuditEvent` rows and visible in Django admin.
