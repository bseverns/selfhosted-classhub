# Security notes (MVP)

- Student accounts are pseudonymous (class-code + display name).
- Teacher/admin uses Django auth (password).
- Prefer staff (non-superuser) teacher accounts for daily use; keep superusers for ops.
- Keep `DJANGO_SECRET_KEY` secret.
- Use HTTPS in production.
- Ensure `DJANGO_DEBUG=0` in production and do not run the dev override file.
- Rate limit join + helper endpoints.
- Helper chat requires either a student classroom session or staff-authenticated teacher session.
- Same-device student rejoin uses a signed, HTTP-only cookie hint; cross-device recovery still uses return code.
- Local LLM inference keeps student queries on your infrastructure, but logs and
  prompt storage still require care.

## Student submissions (uploads)

- Uploads are stored on the server under `data/classhub_uploads/`.
- Uploads are **not** served as public `/media/*` URLs.
  - Students download only their own files via `/submission/<id>/download`.
  - Staff/admin can download any submission.
- Decide on a retention policy (e.g. delete uploads after N days) if you are working
  in higher-risk environments.

## Future
- Google SSO for teachers
- Audit logs for teacher/admin actions
- Separate DBs per service if needed
