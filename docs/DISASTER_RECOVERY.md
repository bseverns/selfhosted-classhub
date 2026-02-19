# Disaster Recovery (Start from Zero)

This is a quick checklist to rebuild the server from scratch after a total loss.

## 1) Provision a fresh server

- Ubuntu 24.04+ recommended.
- Install Docker + Docker Compose plugin.

## 2) Clone the repo

```bash
cd /srv
git clone git@github.com:bseverns/selfhosted-classhub.git lms
cd /srv/lms
```

## 3) Set environment variables

Copy the example and fill in secrets:

```bash
cp compose/.env.example compose/.env
```

Important settings to restore (from your password manager/backups):

Core:
- `DOMAIN` (if using TLS / Caddy domain config)
- `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`
- `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD`
- `DJANGO_SECRET_KEY`
- `DJANGO_ADMIN_2FA_REQUIRED`
- `DJANGO_ALLOWED_HOSTS` (include server IP or domain)
- `CSRF_TRUSTED_ORIGINS`

Helper:
- `HELPER_LLM_BACKEND` (`ollama` or `openai`; `mock` is CI/test-only)
- `HELPER_STRICTNESS`, `HELPER_SCOPE_MODE`
- `HELPER_REFERENCE_DIR`, `HELPER_REFERENCE_FILE`
- `HELPER_REFERENCE_MAP` (optional)
- `HELPER_TOPIC_FILTER_MODE`
- `HELPER_TEXT_LANGUAGE_KEYWORDS`
- `HELPER_MAX_CONCURRENCY`
- `HELPER_QUEUE_MAX_WAIT_SECONDS`
- `HELPER_QUEUE_POLL_SECONDS`
- `HELPER_QUEUE_SLOT_TTL_SECONDS`

Ollama:
- `OLLAMA_BASE_URL`
- `OLLAMA_MODEL`
- `OLLAMA_TIMEOUT_SECONDS`
- `OLLAMA_TEMPERATURE`
- `OLLAMA_TOP_P`

OpenAI (optional):
- `OPENAI_API_KEY`
- `OPENAI_MODEL`

## 4) Pick the right Caddyfile

- No domain yet: use `compose/Caddyfile.local` and HTTP.
- Domain available: use `compose/Caddyfile.domain` and TLS.

Copy to `compose/Caddyfile`:

```bash
cd compose
cp Caddyfile.local Caddyfile
```

## 5) Restore data (if you have backups)

If you have backups from:
- `scripts/backup_postgres.sh`
- `scripts/backup_minio.sh`
- `scripts/backup_uploads.sh`

Restore Postgres + uploads + MinIO before bringing up the stack.

## 6) Start services

```bash
cd /srv/lms/compose
docker compose up -d --build
```

## 7) Pull the Ollama model (if using local LLM)

```bash
cd /srv/lms/compose
docker compose exec ollama ollama pull llama3.2:1b
```

## 8) Quick smoke tests

```bash
curl http://localhost/healthz
curl http://localhost/helper/healthz
curl -i -X POST http://localhost/helper/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"What is 7 plus 5?"}'
```

## 9) Restore teacher/admin access

Create first admin:

```bash
cd /srv/lms/compose
docker compose exec classhub_web python manage.py createsuperuser
```

Provision admin OTP device:

```bash
cd /srv/lms/compose
docker compose exec classhub_web python manage.py bootstrap_admin_otp --username <admin_username> --with-static-backup
```

Create a staff teacher account:

```bash
cd /srv/lms/compose
docker compose exec classhub_web python manage.py create_teacher \
  --username teacher1 \
  --email teacher1@example.org \
  --password CHANGE_ME
```

Verify:
- `https://<domain>/teach`
- `https://<domain>/teach/lessons`
