"""Data model for the MVP.

Teachers/admins can manage these objects in Django admin.
Students never authenticate with email/password; they join a class by code.

Note: for Day-1, we keep the model tiny. As the platform grows, add:
- Organizations/schools (multi-tenancy)
- Rubrics/grading + teacher feedback
- Audit logs
"""

import re
import secrets
from django.db import models


def gen_class_code(length: int = 8) -> str:
    """Generate a human-friendly class code.

    Excludes ambiguous characters (0/O, 1/I).
    """
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


class Class(models.Model):
    name = models.CharField(max_length=200)
    join_code = models.CharField(max_length=16, unique=True, default=gen_class_code)
    is_locked = models.BooleanField(default=False)

    def __str__(self) -> str:
        return f"{self.name} ({self.join_code})"


class Module(models.Model):
    classroom = models.ForeignKey(Class, on_delete=models.CASCADE, related_name="modules")
    title = models.CharField(max_length=200)
    order_index = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order_index", "id"]

    def __str__(self) -> str:
        return f"{self.classroom.name}: {self.title}"


class Material(models.Model):
    TYPE_LINK = "link"
    TYPE_TEXT = "text"
    TYPE_UPLOAD = "upload"
    TYPE_CHOICES = [
        (TYPE_LINK, "Link"),
        (TYPE_TEXT, "Text"),
        (TYPE_UPLOAD, "Upload"),
    ]

    module = models.ForeignKey(Module, on_delete=models.CASCADE, related_name="materials")
    title = models.CharField(max_length=200)
    type = models.CharField(max_length=16, choices=TYPE_CHOICES, default=TYPE_LINK)

    # For link material
    url = models.URLField(blank=True, default="")

    # For text material
    body = models.TextField(blank=True, default="")

    # For upload material
    # Comma-separated list of extensions (including the leading dot), e.g. ".sb3,.png"
    accepted_extensions = models.CharField(max_length=200, blank=True, default="")
    max_upload_mb = models.PositiveIntegerField(default=50)

    order_index = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order_index", "id"]

    def __str__(self) -> str:
        return self.title


def _submission_upload_to(instance: "Submission", filename: str) -> str:
    """Upload path for student submissions.

    We keep paths boring and segregated by class + material.
    """
    classroom_id = instance.material.module.classroom_id
    material_id = instance.material_id
    student_id = instance.student_id
    return f"submissions/class_{classroom_id}/material_{material_id}/student_{student_id}/{filename}"


class Submission(models.Model):
    """A student file upload tied to a specific Material.

    Students do not have accounts; we tie this to StudentIdentity (stored in session).
    """

    material = models.ForeignKey(Material, on_delete=models.CASCADE, related_name="submissions")
    student = models.ForeignKey("StudentIdentity", on_delete=models.CASCADE, related_name="submissions")
    original_filename = models.CharField(max_length=255, blank=True, default="")
    file = models.FileField(upload_to=_submission_upload_to)
    note = models.TextField(blank=True, default="")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at", "-id"]

    def __str__(self) -> str:
        return f"Submission {self.id} ({self.student.display_name} → {self.material.title})"


class StudentIdentity(models.Model):
    """A pseudonymous identity stored per-class.

    Created when a student joins via class code.
    The id is stored in the session cookie.
    """

    classroom = models.ForeignKey(Class, on_delete=models.CASCADE, related_name="students")
    display_name = models.CharField(max_length=80)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.display_name} @ {self.classroom.join_code}"


def _safe_path_part(raw: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_-]+", "-", (raw or "").strip().lower())
    value = value.strip("-")
    return value or "unknown"


def _lesson_video_upload_to(instance: "LessonVideo", filename: str) -> str:
    course = _safe_path_part(instance.course_slug)
    lesson = _safe_path_part(instance.lesson_slug)
    return f"lesson_videos/{course}/{lesson}/{filename}"


class LessonVideo(models.Model):
    course_slug = models.SlugField(max_length=120)
    lesson_slug = models.SlugField(max_length=120)
    title = models.CharField(max_length=200)
    minutes = models.PositiveIntegerField(null=True, blank=True)
    outcome = models.CharField(max_length=300, blank=True, default="")
    source_url = models.URLField(blank=True, default="")
    video_file = models.FileField(upload_to=_lesson_video_upload_to, blank=True, null=True)
    order_index = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order_index", "id"]
        indexes = [
            models.Index(fields=["course_slug", "lesson_slug", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.course_slug}/{self.lesson_slug}: {self.title}"
