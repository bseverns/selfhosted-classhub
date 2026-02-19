# Troubleshooting Guide

This page is symptom-first. Start with what you see, then follow the shortest
path to isolate and resolve.

Use this method in sequence:
1. Reproduce once.
2. Capture one log window around the failure.
3. Classify failure type:
  - routing
  - auth/session
  - dependency/service
  - data/schema
4. Apply the smallest reversible fix first.

Fastest full-stack baseline check:

```bash
bash scripts/system_doctor.sh --smoke-mode basic
```

## Fast triage checklist

1. Confirm container health:
```bash
cd /srv/lms/app/compose
docker compose ps
```
2. Confirm app health endpoints:
```bash
curl -I http://localhost/healthz
curl -I http://localhost/helper/healthz
```
3. Tail logs for the failing service:
```bash
docker compose logs --tail=200 classhub_web
docker compose logs --tail=200 helper_web
docker compose logs --tail=200 caddy
```

Interpretation shortcut:
- health endpoint failure + healthy DB/Redis usually indicates app boot/import issue.
- only helper failing usually indicates model backend, helper config, or helper-specific DB access.
- only classhub failing usually indicates migrations, content parsing, or auth-related changes.

## Symptom: site does not load over HTTPS

Common causes:
- wrong Caddyfile template mounted
- wrong `DOMAIN`
- DNS or ACME certificate issuance failure

Checks:
```bash
cd /srv/lms/app/compose
docker inspect classhub_caddy --format '{{range .Mounts}}{{println .Source "->" .Destination}}{{end}}'
docker compose logs --tail=200 caddy
grep -E '^(CADDYFILE_TEMPLATE|DOMAIN)=' .env
```

What to look for:
- mount should point to intended template (`Caddyfile.domain` for production)
- caddy logs should reference your real domain (not placeholder domains)
- ACME errors like rejected identifiers indicate wrong domain value

## Symptom: helper or classhub container is unhealthy/restarting

Common causes:
- DB auth mismatch
- migration/import-time error
- route import failure

Checks:
```bash
cd /srv/lms/app/compose
docker compose ps -a
docker compose logs --tail=200 helper_web
docker compose logs --tail=200 classhub_web
```

What to look for:
- `password authentication failed` means env credentials mismatch
- `AttributeError` on URL/view symbol usually means partial deploy or stale code

## Symptom: helper tests fail with transaction-aborted DB errors

Common cause:
- helper best-effort classhub table access executed in test DB without classhub tables

Status:
- helper now has table-existence guards for:
  - `hub_studentidentity`
  - `hub_studentevent`

If this reappears:
1. Confirm helper image includes latest code:
```bash
cd /srv/lms/app/compose
docker compose up -d --build helper_web
```
2. Re-run:
```bash
docker compose exec -T helper_web python manage.py test tutor.tests.HelperChatAuthTests
docker compose exec -T helper_web python manage.py test tutor.tests
```

Interpretation notes:
- `helper_chat_student_event_write_failed` log lines are expected in environments
  where classhub event tables do not exist.
- the hard failure is not the warning log itself; the hard failure is any
  subsequent request/test raising `current transaction is aborted`.
- if transaction-aborted persists, inspect code paths that catch `DatabaseError`
  but do not fully reset transaction rollback state.

## Symptom: teacher invite email fails

Common causes:
- SMTP host typo
- DNS resolution failure in container
- tenant SMTP auth disabled (Office 365 default in many orgs)

Checks:
```bash
cd /srv/lms/app/compose
grep -nE '^(DJANGO_EMAIL_|TEACHER_INVITE_FROM_EMAIL)=' .env
docker compose exec -T classhub_web env | grep -E '^(DJANGO_EMAIL_|TEACHER_INVITE_FROM_EMAIL)'
docker compose exec -T classhub_web python - <<'PY'
import os, socket
host = os.getenv("DJANGO_EMAIL_HOST","")
print("HOST:", host)
print("DNS:", socket.gethostbyname(host))
PY
```

Office 365 notes:
- host should be `smtp.office365.com`
- typical port/TLS: `587` + `DJANGO_EMAIL_USE_TLS=1`
- tenant may require enabling SMTP AUTH per mailbox/tenant policy

## Symptom: helper returns policy redirect instead of model answer

Common cause:
- strict topic filter is active and prompt is out of scope

Check:
```bash
cd /srv/lms/app/compose
docker compose exec -T helper_web env | grep -E '^HELPER_TOPIC_FILTER_MODE='
```

Behavior:
- `HELPER_TOPIC_FILTER_MODE=strict` can intentionally short-circuit backend calls.
- for tests or less strict classroom operation, use `soft`.

## Symptom: admin login blocked by OTP requirement

Cause:
- admin 2FA enforced and no device enrolled for that account

Fix:
```bash
cd /srv/lms/app/compose
docker compose exec classhub_web python manage.py bootstrap_admin_otp --username <admin_username> --with-static-backup
```

If no superuser exists:
```bash
docker compose exec classhub_web python manage.py createsuperuser
```

## Symptom: class content disappeared after rebuild/reset

Cause:
- DB or volume reset removed class/module/material records

Recovery:
```bash
cd /srv/lms/app
scripts/rebuild_coursepack.sh --course-slug piper_scratch_12_session --create-class
```

Then verify in `/teach` and `/student`.

## Symptom: CI dependency security job fails (`pip-audit`)

Cause:
- pinned dependency below fixed advisory range

Fix pattern:
1. bump dependency in service requirements file
2. rebuild and run `manage.py check`/tests
3. re-run CI

Example:
- upgrading Django from `5.0.8` to a fixed `5.2.x` release resolves known CVEs.

Verification pattern after dependency bump:
```bash
cd /srv/lms/app/compose
docker compose up -d --build classhub_web helper_web
docker compose exec -T classhub_web python manage.py test hub.tests hub.tests_services
docker compose exec -T helper_web python manage.py test tutor.tests
```

## When to escalate

Escalate to full incident workflow when:
- health checks fail after restart + config verification
- migrations fail in production
- repeated auth failures with no config drift
- data integrity issues (missing submissions/classes without intended prune/reset)

Use:
- `docs/RUNBOOK.md`
- `docs/DISASTER_RECOVERY.md`

## Troubleshooting anti-patterns

Avoid these during incident response:

1. Rebuilding all services before collecting logs:
  - destroys first-failure evidence.
2. Applying multiple config changes at once:
  - makes root cause attribution impossible.
3. Ignoring warning logs without classification:
  - some warnings are benign, others predict failure on next request.
4. Skipping health endpoint checks:
  - increases time-to-isolate by mixing user-path and platform-path failures.
