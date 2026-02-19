# Security notes (MVP)

- Student accounts are pseudonymous (class-code + display name).
- Teacher/admin uses Django auth (password).
- Django admin requires OTP-based 2FA for superusers by default (`DJANGO_ADMIN_2FA_REQUIRED=1`).
- Prefer staff (non-superuser) teacher accounts for daily use; keep superusers for ops.
- Keep `DJANGO_SECRET_KEY` secret.
- In production (`DJANGO_DEBUG=0`), use a strong non-default `DJANGO_SECRET_KEY` (32+ chars).
- Use HTTPS in production.
- Ensure `DJANGO_DEBUG=0` in production and do not run the dev override file.
- For domain/TLS deployments, enable secure redirects and HSTS via:
  - `DJANGO_SECURE_SSL_REDIRECT=1`
  - `DJANGO_SECURE_HSTS_SECONDS` (recommended `>=31536000` once verified)
  - `DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS=1` only if all subdomains are HTTPS-ready
- Rate limit join + helper endpoints.
- Helper chat requires either a student classroom session or staff-authenticated teacher session.
- Same-device student rejoin uses a signed, HTTP-only cookie hint; cross-device recovery still uses return code.
- Local LLM inference keeps student queries on your infrastructure, but logs and
  prompt storage still require care.
- Postgres/Redis remain internal to Docker networking; Ollama/MinIO host ports are localhost-bound.
- Proxy request-body limits are enforced in Caddy (`CADDY_CLASSHUB_MAX_BODY`, `CADDY_HELPER_MAX_BODY`).
- Run `bash scripts/validate_env_secrets.sh` before production deploys.
- Optional malware scanning is available for student uploads:
  - `CLASSHUB_UPLOAD_SCAN_ENABLED=1`
  - `CLASSHUB_UPLOAD_SCAN_COMMAND` (for example `clamscan --no-summary --stdout`)
  - `CLASSHUB_UPLOAD_SCAN_FAIL_CLOSED=1` to block uploads on scanner errors/timeouts.
- Markdown image rendering stays disabled by default; if enabled, explicitly restrict remote hosts via `CLASSHUB_MARKDOWN_ALLOWED_IMAGE_HOSTS`.
- Bootstrap an admin OTP device before locking down production:
  - `docker compose exec classhub_web python manage.py bootstrap_admin_otp --username <admin_username> --with-static-backup`
- Teacher/staff mutations in `/teach/*` now emit immutable `AuditEvent` rows for
  incident review and operational accountability.
- Student-facing activity telemetry now emits append-only `StudentEvent` rows for:
  - class join / rejoin mode
  - submission upload metadata
  - helper chat access metadata

`StudentEvent` privacy boundary:
- Metadata only (IDs, mode, status/timing/request IDs).
- No raw helper prompt text and no file contents are stored in `StudentEvent.details`.

## Student submissions (uploads)

- Uploads are stored on the server under `data/classhub_uploads/`.
- Uploads are **not** served as public `/media/*` URLs.
  - Students download only their own files via `/submission/<id>/download`.
  - Staff/admin can download any submission.
- Decide on a retention policy (e.g. delete uploads after N days) if you are working
  in higher-risk environments.
  - Use `python manage.py prune_submissions --older-than-days <N>` to enforce retention.
- Event log retention is also operator-defined:
  - `python manage.py prune_student_events --older-than-days <N>`

## Future
- Google SSO for teachers
- Separate DBs per service if needed
