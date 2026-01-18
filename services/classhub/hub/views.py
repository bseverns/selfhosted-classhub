import json
import re
import tempfile
import zipfile
from pathlib import Path
from django.http import FileResponse, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.middleware.csrf import get_token
from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.db import models

import yaml
import markdown as md
import bleach

from .forms import SubmissionUploadForm
from .models import Class, Module, Material, StudentIdentity, Submission, gen_class_code


# --- Repo-authored course content (markdown) ---------------------------------

_COURSES_DIR = Path(settings.CONTENT_ROOT) / "courses"


def _load_course_manifest(course_slug: str) -> dict:
    manifest_path = _COURSES_DIR / course_slug / "course.yaml"
    if not manifest_path.exists():
        return {}
    return yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}


def _load_lesson_markdown(course_slug: str, lesson_slug: str) -> tuple[dict, str]:
    """Return (front_matter, markdown_body)."""
    manifest = _load_course_manifest(course_slug)
    lessons = manifest.get("lessons") or []
    match = next((l for l in lessons if (l.get("slug") == lesson_slug)), None)
    if not match:
        return {}, ""

    rel = match.get("file")
    if not rel:
        return {}, ""
    lesson_path = (_COURSES_DIR / course_slug / rel).resolve()
    if not lesson_path.exists():
        return {}, ""

    raw = lesson_path.read_text(encoding="utf-8")
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) >= 3:
            fm = yaml.safe_load(parts[1]) or {}
            body = parts[2].lstrip("\n")
            return fm, body
    return {}, raw


def _render_markdown_to_safe_html(markdown_text: str) -> str:
    html = md.markdown(
        markdown_text,
        extensions=["fenced_code", "tables", "toc"],
        output_format="html5",
    )

    allowed_tags = set(bleach.sanitizer.ALLOWED_TAGS).union(
        {
            "p",
            "pre",
            "code",
            "h1",
            "h2",
            "h3",
            "h4",
            "hr",
            "br",
            "table",
            "thead",
            "tbody",
            "tr",
            "th",
            "td",
            "details",
            "summary",
        }
    )

    allowed_attrs = {
        **bleach.sanitizer.ALLOWED_ATTRIBUTES,
        "a": ["href", "title", "target", "rel"],
        "code": ["class"],
        "pre": ["class"],
    }

    cleaned = bleach.clean(html, tags=list(allowed_tags), attributes=allowed_attrs, strip=True)
    return cleaned


def healthz(request):
    return HttpResponse("ok", content_type="text/plain")


def index(request):
    """Landing page.

    - If student session exists, send them to /student
    - Otherwise, show join form

    Teachers/admins can use /admin for now.
    """
    if getattr(request, "student", None) is not None:
        return redirect("/student")
    get_token(request)
    return render(request, "student_join.html", {})


@require_POST
def join_class(request):
    """Join via class code + display name.

    Body (JSON): {"class_code": "ABCD1234", "display_name": "Ada"}

    Stores student identity in session cookie.
    """
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "bad_json"}, status=400)

    code = (payload.get("class_code") or "").strip().upper()
    name = (payload.get("display_name") or "").strip()[:80]

    if not code or not name:
        return JsonResponse({"error": "missing_fields"}, status=400)

    classroom = Class.objects.filter(join_code=code).first()
    if not classroom:
        return JsonResponse({"error": "invalid_code"}, status=404)
    if classroom.is_locked:
        return JsonResponse({"error": "class_locked"}, status=403)

    student = StudentIdentity.objects.create(classroom=classroom, display_name=name)
    student.last_seen_at = timezone.now()
    student.save(update_fields=["last_seen_at"])

    request.session["student_id"] = student.id
    request.session["class_id"] = classroom.id

    return JsonResponse({"ok": True})


def student_home(request):
    if getattr(request, "student", None) is None or getattr(request, "classroom", None) is None:
        return redirect("/")

    # Update last seen (cheap pulse; later do this asynchronously)
    request.student.last_seen_at = timezone.now()
    request.student.save(update_fields=["last_seen_at"])

    classroom = request.classroom
    modules = classroom.modules.prefetch_related("materials").all()

    # Submission status for this student (shown next to upload materials)
    material_ids = []
    for m in modules:
        for mat in m.materials.all():
            material_ids.append(mat.id)

    submissions_by_material = {}
    if material_ids:
        qs = (
            Submission.objects.filter(student=request.student, material_id__in=material_ids)
            .only("id", "material_id", "uploaded_at")
            .order_by("material_id", "-uploaded_at", "-id")
        )
        for s in qs:
            if s.material_id not in submissions_by_material:
                submissions_by_material[s.material_id] = {"count": 0, "last": s.uploaded_at, "last_id": s.id}
            submissions_by_material[s.material_id]["count"] += 1

    return render(
        request,
        "student_class.html",
        {
            "student": request.student,
            "classroom": classroom,
            "modules": modules,
            "submissions_by_material": submissions_by_material,
        },
    )


def _parse_extensions(ext_csv: str) -> list[str]:
    parts = [p.strip().lower() for p in (ext_csv or "").split(",") if p.strip()]
    out = []
    for p in parts:
        if not p.startswith("."):
            p = "." + p
        if p not in out:
            out.append(p)
    return out


def material_upload(request, material_id: int):
    """Student upload page for a Material of type=upload."""
    if getattr(request, "student", None) is None or getattr(request, "classroom", None) is None:
        return redirect("/")

    material = (
        Material.objects.select_related("module__classroom")
        .filter(id=material_id)
        .first()
    )
    if not material or material.module.classroom_id != request.classroom.id:
        return HttpResponse("Not found", status=404)
    if material.type != Material.TYPE_UPLOAD:
        return HttpResponse("Not an upload material", status=404)

    allowed_exts = _parse_extensions(material.accepted_extensions) or [".sb3"]
    max_bytes = int(material.max_upload_mb) * 1024 * 1024

    error = ""

    if request.method == "POST":
        form = SubmissionUploadForm(request.POST, request.FILES)
        if form.is_valid():
            f = form.cleaned_data["file"]
            note = (form.cleaned_data.get("note") or "").strip()

            name = (getattr(f, "name", "") or "upload").strip()
            lower = name.lower()
            ext = "." + lower.rsplit(".", 1)[-1] if "." in lower else ""

            if ext not in allowed_exts:
                error = f"File type not allowed. Allowed: {', '.join(allowed_exts)}"
            elif getattr(f, "size", 0) and f.size > max_bytes:
                error = f"File too large. Max size: {material.max_upload_mb}MB"
            else:
                Submission.objects.create(
                    material=material,
                    student=request.student,
                    original_filename=name,
                    file=f,
                    note=note,
                )
                return redirect(f"/material/{material.id}/upload")
    else:
        form = SubmissionUploadForm()

    submissions = Submission.objects.filter(material=material, student=request.student).all()

    return render(
        request,
        "material_upload.html",
        {
            "student": request.student,
            "classroom": request.classroom,
            "material": material,
            "allowed_exts": allowed_exts,
            "form": form,
            "error": error,
            "submissions": submissions,
        },
    )


def submission_download(request, submission_id: int):
    """Download a submission.

    - Staff users can download any submission.
    - Students can only download their own submissions.

    We intentionally avoid serving uploads as public /media files.
    """
    s = (
        Submission.objects.select_related("student", "material__module__classroom")
        .filter(id=submission_id)
        .first()
    )
    if not s:
        return HttpResponse("Not found", status=404)

    if request.user.is_authenticated and request.user.is_staff:
        pass
    else:
        if getattr(request, "student", None) is None:
            return redirect("/")
        if s.student_id != request.student.id:
            return HttpResponse("Forbidden", status=403)

    filename = s.original_filename or Path(s.file.name).name
    return FileResponse(s.file.open("rb"), as_attachment=True, filename=filename)


def student_logout(request):
    request.session.flush()
    return redirect("/")


def course_overview(request, course_slug: str):
    """Tiny course landing page.

    This does not require a student session; it simply renders the manifest so
    teachers can verify links.
    """
    manifest = _load_course_manifest(course_slug)
    if not manifest:
        return HttpResponse("Course not found", status=404)

    return render(
        request,
        "course_overview.html",
        {
            "course_slug": course_slug,
            "course": manifest,
            "lessons": manifest.get("lessons") or [],
        },
    )


def course_lesson(request, course_slug: str, lesson_slug: str):
    """Render a markdown lesson page from disk."""
    manifest = _load_course_manifest(course_slug)
    if not manifest:
        return HttpResponse("Course not found", status=404)

    fm, body_md = _load_lesson_markdown(course_slug, lesson_slug)
    if not body_md:
        return HttpResponse("Lesson not found", status=404)

    html = _render_markdown_to_safe_html(body_md)

    lessons = manifest.get("lessons") or []
    idx = next((i for i, l in enumerate(lessons) if l.get("slug") == lesson_slug), None)
    prev_l = lessons[idx - 1] if isinstance(idx, int) and idx > 0 else None
    next_l = lessons[idx + 1] if isinstance(idx, int) and idx + 1 < len(lessons) else None

    return render(
        request,
        "lesson_page.html",
        {
            "course_slug": course_slug,
            "course": manifest,
            "lesson_slug": lesson_slug,
            "front_matter": fm,
            "lesson_html": html,
            "prev": prev_l,
            "next": next_l,
        },
    )


# --- Teacher cockpit (staff-only UI) ----------------------------------------


def _normalize_order(qs, field: str = "order_index"):
    """Normalize order_index values to 0..N-1 in current QS order."""
    for i, obj in enumerate(qs):
        if getattr(obj, field) != i:
            setattr(obj, field, i)
            obj.save(update_fields=[field])


@staff_member_required
def teach_home(request):
    """Teacher landing page (outside /admin)."""
    classes = Class.objects.all().order_by("name", "id")
    return render(request, "teach_home.html", {"classes": classes})


@staff_member_required
@require_POST
def teach_create_class(request):
    name = (request.POST.get("name") or "").strip()[:200]
    if not name:
        return redirect("/teach")

    # join_code must be unique
    join_code = gen_class_code()
    for _ in range(10):
        if not Class.objects.filter(join_code=join_code).exists():
            break
        join_code = gen_class_code()

    Class.objects.create(name=name, join_code=join_code)
    return redirect("/teach")


@staff_member_required
def teach_class_dashboard(request, class_id: int):
    classroom = Class.objects.filter(id=class_id).first()
    if not classroom:
        return HttpResponse("Not found", status=404)

    modules = classroom.modules.prefetch_related("materials").all()
    # normalize module order occasionally (cheap, safe)
    _normalize_order(list(modules))
    modules = classroom.modules.prefetch_related("materials").all()

    # Count submissions per upload material (latest only, by student)
    upload_material_ids = []
    for m in modules:
        for mat in m.materials.all():
            if mat.type == Material.TYPE_UPLOAD:
                upload_material_ids.append(mat.id)

    submission_counts = {}
    if upload_material_ids:
        qs = (
            Submission.objects.filter(material_id__in=upload_material_ids)
            .values("material_id", "student_id")
            .distinct()
        )
        for row in qs:
            submission_counts[row["material_id"]] = submission_counts.get(row["material_id"], 0) + 1

    student_count = classroom.students.count()

    return render(
        request,
        "teach_class.html",
        {
            "classroom": classroom,
            "modules": modules,
            "student_count": student_count,
            "submission_counts": submission_counts,
        },
    )


@staff_member_required
@require_POST
def teach_toggle_lock(request, class_id: int):
    classroom = Class.objects.filter(id=class_id).first()
    if not classroom:
        return HttpResponse("Not found", status=404)
    classroom.is_locked = not classroom.is_locked
    classroom.save(update_fields=["is_locked"])
    return redirect(f"/teach/class/{classroom.id}")


@staff_member_required
@require_POST
def teach_rotate_code(request, class_id: int):
    classroom = Class.objects.filter(id=class_id).first()
    if not classroom:
        return HttpResponse("Not found", status=404)

    join_code = gen_class_code()
    for _ in range(10):
        if not Class.objects.filter(join_code=join_code).exists():
            break
        join_code = gen_class_code()

    classroom.join_code = join_code
    classroom.save(update_fields=["join_code"])
    return redirect(f"/teach/class/{classroom.id}")


@staff_member_required
@require_POST
def teach_add_module(request, class_id: int):
    classroom = Class.objects.filter(id=class_id).first()
    if not classroom:
        return HttpResponse("Not found", status=404)

    title = (request.POST.get("title") or "").strip()[:200]
    if not title:
        return redirect(f"/teach/class/{class_id}")

    max_idx = classroom.modules.aggregate(models.Max("order_index")).get("order_index__max")
    order_index = int(max_idx) + 1 if max_idx is not None else 0

    mod = Module.objects.create(classroom=classroom, title=title, order_index=order_index)
    return redirect(f"/teach/module/{mod.id}")


@staff_member_required
@require_POST
def teach_move_module(request, class_id: int):
    classroom = Class.objects.filter(id=class_id).first()
    if not classroom:
        return HttpResponse("Not found", status=404)

    module_id = int(request.POST.get("module_id") or 0)
    direction = (request.POST.get("direction") or "").strip()

    modules = list(classroom.modules.all())
    modules.sort(key=lambda m: (m.order_index, m.id))

    idx = next((i for i, m in enumerate(modules) if m.id == module_id), None)
    if idx is None:
        return redirect(f"/teach/class/{class_id}")

    if direction == "up" and idx > 0:
        modules[idx - 1], modules[idx] = modules[idx], modules[idx - 1]
    elif direction == "down" and idx < len(modules) - 1:
        modules[idx + 1], modules[idx] = modules[idx], modules[idx + 1]

    for i, m in enumerate(modules):
        if m.order_index != i:
            m.order_index = i
            m.save(update_fields=["order_index"])

    return redirect(f"/teach/class/{class_id}")


@staff_member_required
def teach_module(request, module_id: int):
    module = Module.objects.select_related("classroom").prefetch_related("materials").filter(id=module_id).first()
    if not module:
        return HttpResponse("Not found", status=404)

    mats = list(module.materials.all())
    mats.sort(key=lambda m: (m.order_index, m.id))
    _normalize_order(mats)
    mats = list(module.materials.all())

    return render(
        request,
        "teach_module.html",
        {
            "classroom": module.classroom,
            "module": module,
            "materials": mats,
        },
    )


@staff_member_required
@require_POST
def teach_add_material(request, module_id: int):
    module = Module.objects.select_related("classroom").filter(id=module_id).first()
    if not module:
        return HttpResponse("Not found", status=404)

    mtype = (request.POST.get("type") or Material.TYPE_LINK).strip()
    title = (request.POST.get("title") or "").strip()[:200]
    if not title:
        return redirect(f"/teach/module/{module_id}")

    max_idx = module.materials.aggregate(models.Max("order_index")).get("order_index__max")
    order_index = int(max_idx) + 1 if max_idx is not None else 0

    mat = Material.objects.create(module=module, title=title, type=mtype, order_index=order_index)

    if mtype == Material.TYPE_LINK:
        mat.url = (request.POST.get("url") or "").strip()
        mat.save(update_fields=["url"])
    elif mtype == Material.TYPE_TEXT:
        mat.body = (request.POST.get("body") or "").strip()
        mat.save(update_fields=["body"])
    elif mtype == Material.TYPE_UPLOAD:
        mat.accepted_extensions = (request.POST.get("accepted_extensions") or ".sb3").strip()
        try:
            mat.max_upload_mb = int(request.POST.get("max_upload_mb") or 50)
        except Exception:
            mat.max_upload_mb = 50
        mat.save(update_fields=["accepted_extensions", "max_upload_mb"])

    return redirect(f"/teach/module/{module_id}")


@staff_member_required
@require_POST
def teach_move_material(request, module_id: int):
    module = Module.objects.filter(id=module_id).first()
    if not module:
        return HttpResponse("Not found", status=404)

    material_id = int(request.POST.get("material_id") or 0)
    direction = (request.POST.get("direction") or "").strip()

    mats = list(module.materials.all())
    mats.sort(key=lambda m: (m.order_index, m.id))

    idx = next((i for i, m in enumerate(mats) if m.id == material_id), None)
    if idx is None:
        return redirect(f"/teach/module/{module_id}")

    if direction == "up" and idx > 0:
        mats[idx - 1], mats[idx] = mats[idx], mats[idx - 1]
    elif direction == "down" and idx < len(mats) - 1:
        mats[idx + 1], mats[idx] = mats[idx], mats[idx + 1]

    for i, m in enumerate(mats):
        if m.order_index != i:
            m.order_index = i
            m.save(update_fields=["order_index"])

    return redirect(f"/teach/module/{module_id}")


def _safe_filename(s: str) -> str:
    s = (s or "file").strip()
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", s)
    s = s.strip("._")
    return s or "file"


@staff_member_required
def teach_material_submissions(request, material_id: int):
    material = (
        Material.objects.select_related("module__classroom")
        .filter(id=material_id)
        .first()
    )
    if not material or material.type != Material.TYPE_UPLOAD:
        return HttpResponse("Not found", status=404)

    classroom = material.module.classroom
    students = list(classroom.students.all().order_by("created_at", "id"))

    all_subs = list(
        Submission.objects.filter(material=material)
        .select_related("student")
        .order_by("-uploaded_at", "-id")
    )

    latest_by_student = {}
    count_by_student = {}
    for s in all_subs:
        sid = s.student_id
        count_by_student[sid] = count_by_student.get(sid, 0) + 1
        if sid not in latest_by_student:
            latest_by_student[sid] = s

    show = (request.GET.get("show") or "all").strip()

    if request.GET.get("download") == "zip_latest":
        # Build a zip of latest submissions for each student.
        tmp = tempfile.NamedTemporaryFile(prefix="classhub_latest_", suffix=".zip", delete=False)
        tmp_path = tmp.name
        tmp.close()

        with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for st in students:
                s = latest_by_student.get(st.id)
                if not s:
                    continue
                try:
                    src_path = s.file.path
                except Exception:
                    continue
                base_name = _safe_filename(st.display_name)
                orig = _safe_filename(s.original_filename or Path(s.file.name).name)
                arc = f"{base_name}/{orig}"
                try:
                    z.write(src_path, arcname=arc)
                except Exception:
                    continue

        download_name = f"{_safe_filename(classroom.name)}_material_{material.id}_latest.zip"
        return FileResponse(open(tmp_path, "rb"), as_attachment=True, filename=download_name)

    rows = []
    missing = 0
    for st in students:
        latest = latest_by_student.get(st.id)
        c = count_by_student.get(st.id, 0)
        if not latest:
            missing += 1
        rows.append(
            {
                "student": st,
                "latest": latest,
                "count": c,
            }
        )

    if show == "missing":
        rows = [r for r in rows if r["latest"] is None]
    elif show == "submitted":
        rows = [r for r in rows if r["latest"] is not None]

    return render(
        request,
        "teach_material_submissions.html",
        {
            "classroom": classroom,
            "module": material.module,
            "material": material,
            "rows": rows,
            "missing": missing,
            "student_count": len(students),
            "show": show,
        },
    )
