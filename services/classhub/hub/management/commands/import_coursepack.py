"""Import a repo-authored course pack into the DB as Modules + Materials.

Why this exists:
- Curriculum should be versioned in git (content/courses/...)
- The DB should only be an index + per-class ordering

Usage:
  python manage.py import_coursepack --course-slug piper_scratch_12_session --create-class

Or target an existing class:
  python manage.py import_coursepack --course-slug piper_scratch_12_session --class-code ABCD1234 --replace

Notes:
- This command creates one Module per lesson session.
- Each module gets a link material that points to the markdown renderer route:
    /course/<course_slug>/<lesson_slug>
"""

from __future__ import annotations

from pathlib import Path

import yaml
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from hub.models import Class, Module, Material


def _courses_dir() -> Path:
    return Path(getattr(settings, "CONTENT_ROOT", Path.cwd() / "content")) / "courses"


def _load_manifest(course_slug: str) -> dict:
    manifest_path = _courses_dir() / course_slug / "course.yaml"
    if not manifest_path.exists():
        raise CommandError(f"Course manifest not found: {manifest_path}")
    return yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}


def _read_front_matter(course_slug: str, rel_path: str) -> dict:
    lesson_path = (_courses_dir() / course_slug / rel_path).resolve()
    if not lesson_path.exists():
        return {}
    raw = lesson_path.read_text(encoding="utf-8")
    if not raw.startswith("---"):
        return {}
    parts = raw.split("---", 2)
    if len(parts) < 3:
        return {}
    return yaml.safe_load(parts[1]) or {}


def _normalize_submission_extensions(submission: dict, naming: str) -> list[str]:
    accepted = submission.get("accepted") or []
    if isinstance(accepted, str):
        accepted = [p.strip() for p in accepted.replace("|", ",").split(",") if p.strip()]

    exts = []
    for raw in accepted:
        ext = str(raw).strip().lower()
        if not ext:
            continue
        if not ext.startswith("."):
            ext = "." + ext
        if ext not in exts:
            exts.append(ext)

    if not exts and naming:
        maybe_ext = Path(naming).suffix.strip().lower()
        if maybe_ext.startswith("."):
            exts.append(maybe_ext)

    return exts


class Command(BaseCommand):
    help = "Import a repo-authored course pack into Modules + Materials."

    def add_arguments(self, parser):
        parser.add_argument("--course-slug", default="piper_scratch_12_session")

        group = parser.add_mutually_exclusive_group()
        group.add_argument("--class-code", default="")
        group.add_argument("--class-name", default="")

        parser.add_argument(
            "--create-class",
            action="store_true",
            help="Create a new Class if it does not exist (uses course title by default).",
        )
        parser.add_argument(
            "--replace",
            action="store_true",
            help="Delete existing modules/materials for the class before importing.",
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        course_slug = opts["course_slug"]
        manifest = _load_manifest(course_slug)

        lessons = manifest.get("lessons") or []
        if not lessons:
            raise CommandError("Manifest has no lessons.")

        # Resolve/construct Class
        classroom = None
        if opts.get("class_code"):
            classroom = Class.objects.filter(join_code=opts["class_code"].strip().upper()).first()
            if not classroom:
                raise CommandError("No class found for that code. Create one in /admin or use --create-class.")
        elif opts.get("class_name"):
            classroom = Class.objects.filter(name=opts["class_name"].strip()).first()
            if not classroom and not opts.get("create_class"):
                raise CommandError("No class found for that name. Use --create-class to create it.")
            if not classroom:
                classroom = Class.objects.create(name=opts["class_name"].strip())
        else:
            # Default: class name = course title
            default_name = (manifest.get("title") or course_slug).strip()
            classroom = Class.objects.filter(name=default_name).first()
            if not classroom and not opts.get("create_class"):
                raise CommandError(
                    "No class found for course title. Use --create-class, or specify --class-code / --class-name."
                )
            if not classroom:
                classroom = Class.objects.create(name=default_name)

        if opts.get("replace"):
            classroom.modules.all().delete()

        # Import
        created_modules = 0
        created_materials = 0

        for l in lessons:
            session = int(l.get("session") or 0)
            lesson_slug = (l.get("slug") or "").strip()
            title = (l.get("title") or lesson_slug).strip()
            rel_path = (l.get("file") or "").strip()

            if not lesson_slug or not rel_path:
                continue

            module_title = f"Session {session}: {title}" if session else title
            mod = Module.objects.create(classroom=classroom, title=module_title, order_index=session)
            created_modules += 1

            # Main lesson link
            Material.objects.create(
                module=mod,
                title="Open lesson",
                type=Material.TYPE_LINK,
                url=f"/course/{course_slug}/{lesson_slug}",
                order_index=0,
            )
            created_materials += 1

            # Quick-glance summary (text)
            fm = _read_front_matter(course_slug, rel_path)
            makes = (fm.get("makes") or "").strip()
            submission = fm.get("submission") or {}
            naming = (submission.get("naming") or "").strip()
            submission_type = str(submission.get("type") or "").strip().lower()
            exts = _normalize_submission_extensions(submission, naming)

            # If the lesson expects a file submission, add a built-in dropbox.
            # This lets students submit privately from the lesson itself.
            if submission_type == "file":
                Material.objects.create(
                    module=mod,
                    title="Homework dropbox",
                    type=Material.TYPE_UPLOAD,
                    accepted_extensions=",".join(exts or [".sb3"]),
                    max_upload_mb=50,
                    order_index=2,
                )
                created_materials += 1

            summary_lines = []
            if makes:
                summary_lines.append(f"Makes: {makes}")
            if naming:
                summary_lines.append(f"Submit: {naming}")
            elif exts:
                summary_lines.append(f"Submit: {', '.join(exts)}")

            if summary_lines:
                Material.objects.create(
                    module=mod,
                    title="Today at a glance",
                    type=Material.TYPE_TEXT,
                    body="\n".join(summary_lines),
                    order_index=1,
                )
                created_materials += 1

        self.stdout.write(self.style.SUCCESS(
            f"Imported course '{course_slug}' into class '{classroom.name}' ({classroom.join_code}). "
            f"Modules: {created_modules}, materials: {created_materials}."
        ))
