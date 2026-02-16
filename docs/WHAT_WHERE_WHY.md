# Class Hub + Helper: What / Where / Why (Plain-Language Guide)

This guide is for non-programmer staff who need to run, demo, or support the LMS.

## What this system is

- `Class Hub` is the main LMS site.
- `Homework Helper` is the AI tutor inside the LMS.
- Students use class code + display name (no student passwords in MVP).
- Teachers use staff accounts and open the teacher portal at `/teach`.
- Admins use Django admin at `/admin/`.

## Where to go (URLs)

- Student join page: `/`
- Student class page: `/student`
- Teacher portal: `/teach`
- Teacher lesson tracker: `/teach/lessons`
- Teacher video manager: `/teach/videos`
- Admin login: `/admin/login/`
- Site health check: `/healthz`
- Helper health check: `/helper/healthz`

## Where things live (repo map)

- `compose/`: deployment config (Docker, Caddy, env)
- `services/classhub/`: main LMS app (students + teacher portal + admin)
- `services/homework_helper/`: AI helper app
- `services/classhub/content/courses/`: course content files (what students read)
- `docs/`: operational and policy docs
- `scripts/`: helper scripts for rebuilds and checks

## Why the system is split this way

- Helper is a separate service so LMS pages stay available if AI has issues.
- Caddy routes `/helper/*` to helper and everything else to class hub.
- Postgres stores core records, Redis handles limits/queues, MinIO stores files.
- This design keeps operations simpler and failure boundaries clearer.

## Day-of-class quick checklist (operator view)

1. Confirm site opens at your domain.
2. Confirm teacher can log in at `/admin/login/` and open `/teach`.
3. Confirm students can join from `/` using class code.
4. Confirm helper responds in a lesson page.
5. Confirm submission queue is visible in `/teach`.

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

## Who should use which docs next

- Teachers and office staff: `docs/TEACHER_PORTAL.md`
- Staffing changes: `docs/TEACHER_HANDOFF_CHECKLIST.md`
- Deployment and server operations: `docs/RUNBOOK.md`
- Technical architecture overview: `docs/ARCHITECTURE.md`

