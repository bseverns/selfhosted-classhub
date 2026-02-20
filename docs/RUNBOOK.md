# Runbook

This is the operator playbook for running the stack safely in production.

If you are new, start with `docs/START_HERE.md` and `docs/DAY1_DEPLOY_CHECKLIST.md` first.

## Working directories

- Repo root (server): `/srv/lms/app`
- Compose folder: `/srv/lms/app/compose`

Use repo root unless a section explicitly says otherwise.

## 60-second quick command set

```bash
cd /srv/lms/app
bash scripts/system_doctor.sh

cd /srv/lms/app/compose
docker compose ps
docker compose logs --tail=200 classhub_web helper_web caddy
```

If `system_doctor` passes, the platform is usually in good shape.

## Standard operations

### Start / stop stack

```bash
cd /srv/lms/app/compose
# Start
docker compose up -d
# Stop
docker compose down
```

Verify:

```bash
docker compose ps
curl -fsS http://localhost/healthz
curl -fsS http://localhost/helper/healthz
```

### Guardrailed deploy (recommended)

```bash
cd /srv/lms/app
bash scripts/deploy_with_smoke.sh
```

What this deploy command enforces:

- environment and secret validation
- migration gate for both Django services
- runtime `manage.py migrate --noinput` for both Django services
- compose launch via `compose/docker-compose.yml` only
- Caddy template mount sanity checks
- smoke checks (`/healthz`, `/helper/healthz`, join, helper chat, teacher login)

Optional rollback hook:

```bash
cd /srv/lms/app
ROLLBACK_CMD='echo "replace with your rollback command"' bash scripts/deploy_with_smoke.sh
```

### Full stack self-check (doctor)

```bash
cd /srv/lms/app
bash scripts/system_doctor.sh
```

Useful variants:

```bash
# Strict smoke using existing SMOKE_* env values
bash scripts/system_doctor.sh --smoke-mode strict

# Fast baseline smoke
bash scripts/system_doctor.sh --smoke-mode basic

# Infra/content checks only
bash scripts/system_doctor.sh --smoke-mode off
```

### Smoke checks only

```bash
cd /srv/lms/app
bash scripts/smoke_check.sh --strict
```

Golden-path smoke (auto fixture bootstrap):

```bash
cd /srv/lms/app
bash scripts/golden_path_smoke.sh
```

## Health and logs

### Health checks

```bash
cd /srv/lms/app/compose
docker compose ps
curl -I http://localhost/healthz
curl -I http://localhost/helper/healthz
```

### Tail logs

```bash
cd /srv/lms/app/compose
docker compose logs -f --tail=200 classhub_web
docker compose logs -f --tail=200 helper_web
docker compose logs -f --tail=200 caddy
```

Helper logs include structured events like `success`, `queue_busy`, and `backend_transport_error` with `request_id`.

## Migration and content gates

### Migration gate only

```bash
cd /srv/lms/app
bash scripts/migration_gate.sh
```

`migration_gate.sh` checks that migration files are committed. It does not apply DB migrations.

### Apply runtime migrations

```bash
cd /srv/lms/app/compose
docker compose exec -T classhub_web python manage.py migrate --noinput
docker compose exec -T helper_web python manage.py migrate --noinput
```

If your deployment pipeline always runs the commands above, set `RUN_MIGRATIONS_ON_START=0` in `compose/.env` to avoid boot-time migration races.

### Content preflight

```bash
cd /srv/lms/app
bash scripts/content_preflight.sh piper_scratch_12_session
```

Strict global sequence checks:

```bash
cd /srv/lms/app
bash scripts/content_preflight.sh piper_scratch_12_session --strict-global
```

## Helper backend operations

### Ollama model setup

```bash
cd /srv/lms/app/compose
docker compose exec ollama ollama pull llama3.2:1b
curl http://localhost:11434/api/tags
```

Note: Ollama is host-bound at `127.0.0.1:11434` by default.

### Helper queue tuning (CPU-focused)

Set in `compose/.env`:

```dotenv
HELPER_MAX_CONCURRENCY=2
HELPER_QUEUE_MAX_WAIT_SECONDS=10
HELPER_QUEUE_POLL_SECONDS=0.2
HELPER_QUEUE_SLOT_TTL_SECONDS=120
```

## Security and edge limits

### Env/secret gate only

```bash
cd /srv/lms/app
bash scripts/validate_env_secrets.sh
```

### Caddy request size limits

Set in `compose/.env`:

```dotenv
CADDY_CLASSHUB_MAX_BODY=650MB
CADDY_HELPER_MAX_BODY=1MB
```

## Teacher/admin operations

### Teacher account workflow

- `docs/TEACHER_PORTAL.md`
- `docs/TEACHER_HANDOFF_CHECKLIST.md`
- `docs/TEACHER_HANDOFF_RECORD_TEMPLATE.md`

Helper script:

- `scripts/examples/teacher_accounts.sh` (dry-run by default; set `RUN=1` to execute)

### Admin OTP bootstrap

```bash
cd /srv/lms/app/compose
docker compose exec classhub_web python manage.py bootstrap_admin_otp --username <admin_username> --with-static-backup
```

Use `--rotate` to replace an existing device name.

## Backups and recovery hooks

Backup scripts:

- `scripts/backup_postgres.sh`
- `scripts/backup_minio.sh`
- `scripts/backup_uploads.sh`

Disaster recovery guide:

- `docs/DISASTER_RECOVERY.md`

Recommended restore drill:

1. Restore Postgres dump into a temporary DB.
2. Confirm both Django services migrate and boot.
3. Run `bash scripts/system_doctor.sh --smoke-mode basic`.

## Release artifact packaging

Create a shareable source zip without local machine clutter (`.venv`, `.git`, macOS metadata, caches):

```bash
cd /srv/lms/app
bash scripts/make_release_zip.sh
```

Optional output path:

```bash
bash scripts/make_release_zip.sh /srv/lms/releases/classhub_release.zip
```

Release packaging policy and verification details:

- `docs/RELEASING.md`

## Retention operations

### Submission retention

Dry run:

```bash
cd /srv/lms/app/compose
docker compose exec classhub_web python manage.py prune_submissions --older-than-days 90 --dry-run
```

Apply:

```bash
cd /srv/lms/app/compose
docker compose exec classhub_web python manage.py prune_submissions --older-than-days 90
```

Optional default (`compose/.env`):

```dotenv
CLASSHUB_SUBMISSION_RETENTION_DAYS=90
```

### Student event retention

Dry run:

```bash
cd /srv/lms/app/compose
docker compose exec classhub_web python manage.py prune_student_events --older-than-days 180 --dry-run
```

Dry run with CSV export snapshot:

```bash
cd /srv/lms/app/compose
docker compose exec classhub_web python manage.py prune_student_events --older-than-days 180 --dry-run --export-csv /tmp/student_events_older_than_180d.csv
```

Apply:

```bash
cd /srv/lms/app/compose
docker compose exec classhub_web python manage.py prune_student_events --older-than-days 180
```

Apply with export-before-delete snapshot:

```bash
cd /srv/lms/app/compose
docker compose exec classhub_web python manage.py prune_student_events --older-than-days 180 --export-csv /srv/lms/backups/student_events_before_prune_$(date +%Y%m%d).csv
```

Optional default (`compose/.env`):

```dotenv
CLASSHUB_STUDENT_EVENT_RETENTION_DAYS=180
```

### Orphan upload scavenger (legacy cleanup)

Report orphaned upload files (files on disk with no matching DB row):

```bash
cd /srv/lms/app/compose
docker compose exec classhub_web python manage.py scavenge_orphan_uploads
```

Delete orphans (use after reviewing report output):

```bash
cd /srv/lms/app/compose
docker compose exec classhub_web python manage.py scavenge_orphan_uploads --delete
```

### Legacy temp ZIP cleanup (one-time)

Older builds could leave export zips in `/tmp`.

Inspect:

```bash
ls -lh /tmp/classhub_closeout_*.zip /tmp/classhub_latest_*.zip 2>/dev/null || true
```

Delete:

```bash
rm -f /tmp/classhub_closeout_*.zip /tmp/classhub_latest_*.zip
```

## Helper event ingest check

Helper chat telemetry now forwards through an authenticated internal Class Hub endpoint.

Required env:

- `CLASSHUB_INTERNAL_EVENTS_URL`
- `CLASSHUB_INTERNAL_EVENTS_TOKEN`

Quick validation:

```bash
cd /srv/lms/app
bash scripts/validate_env_secrets.sh
bash scripts/system_doctor.sh --smoke-mode golden
```

### Automate retention + orphan cleanup

Run once manually:

```bash
cd /srv/lms/app
bash scripts/retention_maintenance.sh --compose-mode prod
```

Optional webhook alerts (for unattended runs):

```bash
export RETENTION_ALERT_WEBHOOK_URL="https://hooks.example.org/classhub"
bash scripts/retention_maintenance.sh --compose-mode prod --alert-on-success
```

Systemd timer (recommended):

```bash
sudo cp /srv/lms/app/ops/systemd/classhub-retention.service /etc/systemd/system/
sudo cp /srv/lms/app/ops/systemd/classhub-retention.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now classhub-retention.timer
sudo systemctl status classhub-retention.timer
```

Before enabling, edit `/etc/systemd/system/classhub-retention.service` if your app path or runtime user differs from `/srv/lms/app`.

Review last run:

```bash
systemctl list-timers | grep classhub-retention
journalctl -u classhub-retention.service -n 200 --no-pager
```

## Escalate when

Move to incident workflow (`docs/TROUBLESHOOTING.md`, then `docs/DISASTER_RECOVERY.md`) when any of these are true:

- health checks still fail after config verification
- migrations fail in production
- repeated auth failures without expected config drift
- data integrity issues (missing classes/submissions without intended prune/reset)
