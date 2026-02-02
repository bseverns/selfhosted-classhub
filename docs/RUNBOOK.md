# Runbook

## Start / stop

```bash
cd /srv/lms/compose
docker compose up -d
# stop:
docker compose down
```

## Local development

Docker Compose automatically loads `compose/docker-compose.override.yml` if present.
That file bind-mounts the source and uses Django's dev server for hot reload.

```bash
cd compose
docker compose up -d
```

Remove or rename the override file for production-style runs.

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
