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
- `.env` validation (`scripts/validate_env_secrets.sh`) for strong secrets and routing sanity
- migration gate (`makemigrations --check --dry-run`) for both Django services
- compose launch using only `compose/docker-compose.yml` (no implicit override behavior)
- Caddy mount guardrail (`/etc/caddy/Caddyfile` must come from selected `compose/Caddyfile.*` template)
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

Note: Ollama is host-bound to `127.0.0.1:11434` in compose by default.

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

## CI coverage artifacts

GitHub Actions `test-suite` job now uploads:
- `coverage-classhub.xml`
- `coverage-helper.xml`

## Env/secret gate only

```bash
bash scripts/validate_env_secrets.sh
```

This checks `compose/.env` for placeholder/weak secrets and domain routing mismatches before deploy.

## Smoke checks only

```bash
bash scripts/smoke_check.sh --strict
```

## Caddy request body limits

Set in `compose/.env`:

```bash
CADDY_CLASSHUB_MAX_BODY=650MB
CADDY_HELPER_MAX_BODY=1MB
```

Use this to cap upload/request size at the proxy before requests reach Django.

## Compose health checks

`classhub_web` and `helper_web` now expose container-level health checks:
- `classhub_web`: `http://127.0.0.1:8000/healthz`
- `helper_web`: `http://127.0.0.1:8000/helper/healthz`

Caddy depends on these health checks before starting proxy routing.

## Teacher accounts

Canonical teacher account workflow:
- `docs/TEACHER_PORTAL.md`
- `docs/TEACHER_HANDOFF_CHECKLIST.md`
- `docs/TEACHER_HANDOFF_RECORD_TEMPLATE.md`

Command script:
- `scripts/examples/teacher_accounts.sh` (dry-run by default; use `RUN=1` to execute)

## Admin 2FA bootstrap

Admin routes use OTP 2FA by default (`DJANGO_ADMIN_2FA_REQUIRED=1`).

Provision a TOTP device for a superuser:

```bash
cd /srv/lms/compose
docker compose exec classhub_web python manage.py bootstrap_admin_otp --username <admin_username> --with-static-backup
```

Use `--rotate` to replace an existing device name.

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
- `scripts/backup_uploads.sh`

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
