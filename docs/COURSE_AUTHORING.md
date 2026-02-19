# Course Authoring Guide

This project loads courses directly from disk. No backend changes are required.

## Course folder structure

```
services/classhub/content/courses/<course_slug>/
  course.yaml
  lessons/
    01-lesson-slug.md
    02-lesson-slug.md
    ...
```

## Create a new course (scaffold)

```bash
python3 scripts/new_course_scaffold.py \
  --slug robotics_intro \
  --title "Robotics: Sensors + Motion" \
  --sessions 8 \
  --duration 75 \
  --age-band "5th-7th"
```

This creates:
- `course.yaml` (manifest)
- lesson markdown stubs
- a helper reference file at `services/homework_helper/tutor/reference/<slug>.md`

## Create a course from a syllabus (Markdown or DOCX)

If you have a teacher-facing session plan file in `.md` or `.docx`, you can ingest it:

```bash
python3 scripts/ingest_syllabus_md.py \
  --sessions-md /path/to/teacher_plan.md \
  --overview-md /path/to/public_syllabus.md \
  --slug scratch_game_design \
  --title "Scratch Game Design + Cutscenes Lab"
```

Dry run (no files written):

```bash
python3 scripts/ingest_syllabus_md.py \
  --sessions-md /path/to/teacher_plan.docx \
  --overview-md /path/to/public_syllabus.docx \
  --slug scratch_game_design \
  --title "Scratch Game Design + Cutscenes Lab" \
  --dry-run
```

Notes:
- The script looks for headings like `# Session 01: Title` (or `Session 01: Title` in DOCX).
- It maps sections to lesson front matter:
  - **Mission** → `makes`
  - **Materials** → `needs`
  - **Checkpoints** → `done_looks_like`
  - **Common stuck points + fixes** → `help.quick_fixes`
  - **Extensions** → `extend`
  - **Teacher prep** → `teacher_panel.prep`
- Headings such as **Teacher prep**, **Agenda**, **Materials**, **Checkpoints**, and
  **Common stuck points + fixes** are treated as teacher-facing sections in the app.
  They are hidden on learner lesson pages and shown in teacher tools (`/teach/lessons`
  and class dashboard rows).
- DOCX works best if section titles are on their own line (e.g., “Materials”, “Agenda”).
- The script prints a warning if no `Session 01: Title` headers are found.

## Generate teacher templates (`.md` + `.docx`)

If teachers need a pre-formatted starter file, generate templates keyed by course slug:

```bash
python3 scripts/generate_authoring_templates.py \
  --slug scratch_game_design \
  --title "Scratch Game Design + Cutscenes Lab" \
  --sessions 12 \
  --duration 75 \
  --age-band "5th-7th"
```

Default output folder:

- `docs/examples/course_authoring/<slug>-teacher-plan-template.md`
- `docs/examples/course_authoring/<slug>-teacher-plan-template.docx`
- `docs/examples/course_authoring/<slug>-public-overview-template.md`
- `docs/examples/course_authoring/<slug>-public-overview-template.docx`

These files are formatted to match the ingest parser in `scripts/ingest_syllabus_md.py`
(`Session NN: Title`, `Mission`, `Teacher prep`, `Materials`, `Checkpoints`,
`Common stuck points + fixes`, `Extensions`).

Teacher UI option:
- Staff users can generate the same templates from `/teach` (Teacher Portal home)
  by filling in the same four fields: slug, title, sessions, duration.
- The same card shows direct download links for any generated files for that slug.

## Change the course title after scaffolding

1) Update the course manifest:
   - `services/classhub/content/courses/<course_slug>/course.yaml`
   - Change `title: "..."`.

2) (Optional) Update lesson titles:
   - `services/classhub/content/courses/<course_slug>/lessons/*.md`
   - Edit the `title:` field in the front matter (`---` block).

No backend changes are required; the app reads these files at runtime.

## Rename a course slug (manual steps)

If you need to change the course slug after creating content, follow this order:

1) Rename the course folder:
   - `services/classhub/content/courses/<old_slug>/` → `<new_slug>/`

2) Update `course.yaml`:
   - Change `slug: <new_slug>`

3) Update lesson front matter:
   - In every lesson file, change `course: <new_slug>`

4) Update helper references (optional):
   - If you use `helper_reference: <old_slug>`, update to `<new_slug>`
   - Ensure a matching reference file exists:
     - `services/homework_helper/tutor/reference/<new_slug>.md`

5) Validate:
   - Visit `/course/<new_slug>/<lesson_slug>` and confirm the page renders.

## Lesson front matter template (recommended fields)

```yaml
---
course: <course slug>
session: 1
slug: s01-<lesson-slug>
title: <Lesson Title>
available_on: YYYY-MM-DD  # optional: intro-only until this date
duration_minutes: 75
makes: <short outcome>
needs:
  - <materials or tools>
privacy:
  - <privacy guardrails>
videos: []
submission:
  type: file
  accepted:
    - .<ext>
  naming: <example>
done_looks_like:
  - <objective check>
help:
  quick_fixes:
    - <common fix>
extend:
  - <optional stretch>
teacher_panel:
  purpose: <goal>
  snags:
    - <common pitfalls>
  assessment:
    - <what to look for>
---
```

Release scheduling:
- Set `available_on` in lesson front matter to keep lessons in intro-only mode until that date.
- You can also set `available_on` on each lesson entry in `course.yaml`.
- Until the date, students can open the lesson intro but cannot access full lesson sections or submit uploads.
- Staff users still see full lesson content.
- Teachers can override release dates per class from `/teach/lessons` or `/teach/class/<id>`:
  - set a date,
  - toggle hard lock,
  - open now,
  - reset back to content defaults.

To render videos on lesson pages, add `url` (or `youtube_id`) in each `videos`
entry:

```yaml
videos:
  - id: V01
    title: "Boot + desktop tour"
    minutes: 4
    outcome: "Reach desktop and identify key icons."
    url: "https://www.youtube.com/watch?v=VIDEO_ID"
```

`youtube_id` and `url` are both supported; when either resolves to YouTube, the
lesson page will embed the video and also show an external link.

## Homework dropbox behavior

When you run `import_coursepack`, each lesson with:

```yaml
submission:
  type: file
```

gets a `Homework dropbox` material automatically. Accepted file extensions are
taken from `submission.accepted` (or inferred from `submission.naming` if needed).
Students can open the dropbox from the lesson page and from `/student`.

## Helper configuration (optional)

- Per-course reference: set `helper_reference` in `course.yaml`.
- Per-lesson reference: set `helper_reference` in the lesson entry in `course.yaml`.
- Per-lesson allowed topics: add `helper_allowed_topics` in lesson front matter.

Auto-generate allowed topics:

```bash
python3 scripts/add_helper_allowed_topics.py \
  --lessons-dir services/classhub/content/courses/<course_slug>/lessons \
  --write
```

## Validate video introduction order

To ensure foundational videos are introduced in sequence (`V01`, `V02`, ...):

```bash
python3 scripts/validate_lesson_video_order.py \
  --lessons-dir services/classhub/content/courses/<course_slug>/lessons
```

This reports where each video first appears and fails if a higher-numbered
video is introduced before a lower-numbered one.

Default behavior checks:
- `V01` appears in the first video-bearing session.
- `videos:` in front matter matches the `## Watch` headings in each lesson.

Strict full-course check:

```bash
python3 scripts/validate_lesson_video_order.py \
  --lessons-dir services/classhub/content/courses/<course_slug>/lessons \
  --strict-global
```

Strict mode also checks:
- Video IDs are ascending inside each lesson.
- Lower-numbered videos are introduced before higher-numbered videos.

Auto-fix Watch heading order/sync to match front matter:

```bash
python3 scripts/validate_lesson_video_order.py \
  --lessons-dir services/classhub/content/courses/<course_slug>/lessons \
  --fix-watch-sync
```

## Pre-deploy content gate

Run content checks before deployment:

```bash
bash scripts/content_preflight.sh <course_slug>
```

Strict global mode:

```bash
bash scripts/content_preflight.sh <course_slug> --strict-global
```
