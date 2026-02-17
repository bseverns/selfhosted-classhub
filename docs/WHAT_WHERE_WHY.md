# Class Hub + Helper: What / Where / Why (Plain-Language Guide)

This guide is for non-programmer staff who need to run, demo, or support the LMS.
For the canonical role-based doc map and URL list, start at `docs/START_HERE.md`.

## What this system is

- `Class Hub` is the main LMS site.
- `Homework Helper` is the AI tutor inside the LMS.
- Students use class code + display name (no student passwords in MVP).
- Teachers use staff accounts and open the teacher portal at `/teach`.
- Admins use Django admin at `/admin/`.

## Where to go

Use canonical route list in `docs/START_HERE.md#canonical-url-map`.
Use role-based docs list in `docs/START_HERE.md#pick-your-role`.

## Why the system is split this way

- Helper is a separate service so LMS pages stay available if AI has issues.
- Caddy routes `/helper/*` to helper and everything else to class hub.
- Postgres stores core records, Redis handles limits/queues, MinIO stores files.
- This design keeps operations simpler and failure boundaries clearer.

## Day-of-class quick checklist

1. Confirm site opens at your domain.
2. Confirm teacher can sign in and open teacher portal.
3. Confirm students can join and reach class view.
4. Confirm helper responds inside lesson/class page.
5. Confirm teacher can see submissions queue.

Detailed operator run steps: `docs/RUNBOOK.md`

## If something is wrong

- Teacher cannot access `/teach`:
  - Usually account is not staff or user is not logged in.
  - Ask admin to verify teacher account with `create_teacher` command.
- Students cannot join class:
  - Check class code, class lock status, and that class exists.
- Helper not responding:
  - Check `/helper/healthz`.
  - Restart `helper_web` container if needed.
- Uploads failing:
  - Check teacher dropbox settings and allowed file extensions.

## What to read next

- Role-specific paths: `docs/START_HERE.md`
- Teacher workflow details: `docs/TEACHER_PORTAL.md`
- Operations depth: `docs/RUNBOOK.md`
