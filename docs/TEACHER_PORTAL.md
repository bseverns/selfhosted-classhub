# Teacher Portal + Accounts

This guide covers:
- creating teacher accounts
- accessing the teacher portal
- common day-to-day workflows

## Access model

- Student access: class code + display name.
- Teacher portal: staff-only (`is_staff=True`) Django users.
- Django admin: usually superusers (`is_superuser=True`).

Use superusers for setup and operations. Use staff (non-superuser) for daily teaching.

## Create teacher accounts

Prerequisite: stack is running.

```bash
cd compose
docker compose up -d
```

Create first admin (if needed):

```bash
cd compose
docker compose exec classhub_web python manage.py createsuperuser
```

Create a staff teacher account:

```bash
cd compose
docker compose exec classhub_web python manage.py create_teacher \
  --username teacher1 \
  --email teacher1@example.org \
  --password CHANGE_ME
```

Reset a teacher password:

```bash
cd compose
docker compose exec classhub_web python manage.py create_teacher \
  --username teacher1 \
  --password NEW_PASSWORD \
  --update
```

Disable teacher access without deleting account:

```bash
cd compose
docker compose exec classhub_web python manage.py create_teacher \
  --username teacher1 \
  --inactive \
  --update
```

Useful flags:
- `--update`: required when modifying an existing teacher.
- `--clear-email`: clear existing email on update.
- `--superuser` / `--no-superuser`: elevate or remove admin-level access.
- `--active` / `--inactive`: explicitly control account state.

## Example script

A runnable command cookbook is provided at:

- `scripts/examples/teacher_accounts.sh`

By default it prints commands only (dry-run). Execute for real:

```bash
RUN=1 bash scripts/examples/teacher_accounts.sh
```

Use production compose mode:

```bash
COMPOSE_MODE=prod RUN=1 bash scripts/examples/teacher_accounts.sh
```

Customize values when running the example script:

```bash
USERNAME=teacher2 \
EMAIL=teacher2@example.org \
PASSWORD=TEMP_PASSWORD \
NEW_PASSWORD=FINAL_PASSWORD \
RUN=1 \
bash scripts/examples/teacher_accounts.sh
```

## Changing personnel (new or different teachers)

Current behavior: any staff user can access any class in `/teach`. We do not
yet have per-class teacher assignment/ownership.

When a new person joins:

1. Create a new staff account.
2. Ask them to sign in and verify `/teach` + `/teach/lessons`.
3. Keep old account active briefly during transition, then disable it.

Commands:

```bash
# 1) onboard new teacher
docker compose exec classhub_web python manage.py create_teacher \
  --username teacher2 \
  --email teacher2@example.org \
  --password TEMP_PASSWORD

# 2) rotate their password after first login or handoff
docker compose exec classhub_web python manage.py create_teacher \
  --username teacher2 \
  --password FINAL_PASSWORD \
  --update

# 3) offboard previous teacher account
docker compose exec classhub_web python manage.py create_teacher \
  --username teacher1 \
  --inactive \
  --update
```

If contact info changes (same person, new email):

```bash
docker compose exec classhub_web python manage.py create_teacher \
  --username teacher2 \
  --email teacher2@newschool.org \
  --update
```

If login username should change, create a new account with the new username and
disable the old account after handoff.

Operational checklist: `docs/TEACHER_HANDOFF_CHECKLIST.md`.

## Teacher portal routes

- `/teach`:
  - class list
  - create class
  - recent submissions queue
- `/teach/lessons`:
  - lesson tracker grouped by class
  - per-dropbox quick actions: `All`, `Missing`, `ZIP latest`
  - row shortcut: `Review missing now`
  - row shortcut: `Manage videos`
- `/teach/videos`:
  - select course + lesson
  - upload video file or add video URL
  - bulk-upload multiple files in one action
  - order videos for lesson playback
  - publish/unpublish videos (draft visibility)
  - remove lesson-tagged videos
- `/teach/class/<id>`:
  - lesson tracker for one class
  - module/material editor
- `/teach/material/<id>/submissions`:
  - submitted vs missing filters
  - bulk download latest submissions as ZIP

## Common workflow

1. Sign in at `/admin/login/` with a staff or superuser account.
2. Open `/teach`.
3. Open `Lessons` for the target class.
4. Use `Manage videos` on a lesson row to add/update that lesson's video list.
5. Use `Review missing now` to jump to students who still owe uploads.
6. Use `ZIP latest` for batch review/download.

## Lesson video workflow

Use `/teach/videos` to tag media directly to `course_slug + lesson_slug`.

1. Pick a course and lesson from the selectors.
2. Add a title (+ optional minutes/outcome).
3. Choose one source:
   - `Video URL` (self-hosted MP4/HLS or YouTube URL), or
   - `Upload video file` (stored as a private lesson asset).
4. Save, then use `↑` / `↓` to set playback order.
5. Use `Publish` / `Unpublish` to control whether students can see each video.
6. Use `Bulk upload files` when adding many lesson clips at once (titles auto-generate from filenames).

Large file note:
- Upload request size is controlled by `CLASSHUB_UPLOAD_MAX_MB` (default `600`) in compose env.
- After changing `.env`, restart `classhub_web` to apply.

Lesson behavior:
- Student lesson page video panels are collapsed by default.
- Clicking a video heading opens that panel.
- Opening a different heading closes the previous panel.
- Uploaded files stream via `/lesson-video/<id>/stream` with permission checks.
- Draft videos are hidden from students until published.

## Troubleshooting

- Redirect to `/admin/login/` when opening `/teach`:
  - account is not authenticated, or
  - account does not have `is_staff=True`.
- Teacher can open `/teach` but should not have admin access:
  - ensure `is_superuser=False`.
- No lesson rows in tracker:
  - class modules may not include lesson links in `/course/<course>/<lesson>` format.
