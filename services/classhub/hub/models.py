"""Data model for the MVP.

Teachers/admins can manage these objects in Django admin.
Students never authenticate with email/password; they join a class by code.

Note: for Day-1, we keep the model tiny. As the platform grows, add:
- Organizations/schools (multi-tenancy)
- Rubrics/grading + teacher feedback
"""

import re
import secrets
from django.conf import settings
from django.db import models


def gen_class_code(length: int = 8) -> str:
    """Generate a human-friendly class code.

    Excludes ambiguous characters (0/O, 1/I).
    """
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def gen_student_return_code(length: int = 6) -> str:
    """Generate a short student return code.

    This is shown to students so they can reclaim their identity after cookie loss.
    """
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


class Class(models.Model):
    """A classroom roster with one join code.

    Non-technical framing:
    - Think of this as one class period/section.
    - `is_locked=True` temporarily blocks new student joins.
    """

    name = models.CharField(max_length=200)
    join_code = models.CharField(max_length=16, unique=True, default=gen_class_code)
    is_locked = models.BooleanField(default=False)

    def __str__(self) -> str:
        return f"{self.name} ({self.join_code})"


class Module(models.Model):
    """An ordered group of materials (usually one lesson/session)."""

    classroom = models.ForeignKey(Class, on_delete=models.CASCADE, related_name="modules")
    title = models.CharField(max_length=200)
    order_index = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order_index", "id"]

    def __str__(self) -> str:
        return f"{self.classroom.name}: {self.title}"


class Material(models.Model):
    """A single item shown to students inside a module.

    Types:
    - link: points to lesson/content URL
    - text: short instructions/reminders
    - upload: student dropbox for file submission
    """

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
    return_code = models.CharField(max_length=12, default=gen_student_return_code)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        # Return code only needs to be unique inside one class.
        constraints = [
            models.UniqueConstraint(
                fields=["classroom", "return_code"],
                name="uniq_student_return_code_per_class",
            ),
        ]
        # Speeds up joins/searches by class + display name/return code.
        indexes = [
            models.Index(fields=["classroom", "display_name"]),
            models.Index(fields=["classroom", "return_code"]),
        ]

    def __str__(self) -> str:
        return f"{self.display_name} @ {self.classroom.join_code}"


class StudentEvent(models.Model):
    """Append-only student activity stream for operational visibility.

    Privacy boundary:
    - Keep this event log metadata-only (IDs, modes, status, timing).
    - Do not store raw helper prompts or submission file contents.
    """

    EVENT_CLASS_JOIN = "class_join"
    EVENT_REJOIN_DEVICE_HINT = "session_rejoin_device_hint"
    EVENT_REJOIN_RETURN_CODE = "session_rejoin_return_code"
    EVENT_SUBMISSION_UPLOAD = "submission_upload"
    EVENT_HELPER_CHAT_ACCESS = "helper_chat_access"

    EVENT_TYPE_CHOICES = [
        (EVENT_CLASS_JOIN, "Class join"),
        (EVENT_REJOIN_DEVICE_HINT, "Session rejoin (device hint)"),
        (EVENT_REJOIN_RETURN_CODE, "Session rejoin (return code)"),
        (EVENT_SUBMISSION_UPLOAD, "Submission upload"),
        (EVENT_HELPER_CHAT_ACCESS, "Helper chat access"),
    ]

    classroom = models.ForeignKey(
        Class,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="student_events",
    )
    student = models.ForeignKey(
        "StudentIdentity",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events",
    )
    event_type = models.CharField(max_length=48, choices=EVENT_TYPE_CHOICES)
    source = models.CharField(max_length=40, default="classhub")
    details = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["event_type", "created_at"]),
            models.Index(fields=["classroom", "created_at"]),
            models.Index(fields=["student", "created_at"]),
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError("StudentEvent is append-only and cannot be updated.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("StudentEvent is append-only and cannot be deleted.")

    def __str__(self) -> str:
        return f"{self.created_at.isoformat()} {self.event_type}"


def _safe_path_part(raw: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_-]+", "-", (raw or "").strip().lower())
    value = value.strip("-")
    return value or "unknown"


def _lesson_video_upload_to(instance: "LessonVideo", filename: str) -> str:
    course = _safe_path_part(instance.course_slug)
    lesson = _safe_path_part(instance.lesson_slug)
    return f"lesson_videos/{course}/{lesson}/{filename}"


def _normalize_asset_folder_path(raw: str) -> str:
    parts = []
    for segment in str(raw or "").replace("\\", "/").split("/"):
        segment = segment.strip()
        if not segment:
            continue
        parts.append(_safe_path_part(segment))
    return "/".join(parts) or "general"


def _safe_asset_filename(raw: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", (raw or "").strip())
    value = value.strip("._")
    return value or "asset"


class LessonAssetFolder(models.Model):
    """Teacher-managed folder namespace for reference assets."""

    path = models.CharField(max_length=200, unique=True, default="general")
    display_name = models.CharField(max_length=120, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["path", "id"]

    def save(self, *args, **kwargs):
        self.path = _normalize_asset_folder_path(self.path)
        if not self.display_name:
            self.display_name = self.path
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.path


def _lesson_asset_upload_to(instance: "LessonAsset", filename: str) -> str:
    folder_path = _normalize_asset_folder_path(getattr(instance.folder, "path", "general"))
    return f"lesson_assets/{folder_path}/{_safe_asset_filename(filename)}"


class LessonVideo(models.Model):
    """Teacher-managed video asset tagged to one course lesson."""

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


class LessonRelease(models.Model):
    """Per-class release overrides for lesson availability.

    Priority:
    - `force_locked=True` always locks
    - else `available_on` can schedule open date
    - else lesson uses markdown/content defaults
    """

    classroom = models.ForeignKey(Class, on_delete=models.CASCADE, related_name="lesson_releases")
    course_slug = models.SlugField(max_length=120)
    lesson_slug = models.SlugField(max_length=120)
    # If set, students are locked until this date in the classroom.
    available_on = models.DateField(blank=True, null=True)
    # Hard lock regardless of date (until toggled off by teacher/admin).
    force_locked = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["classroom", "course_slug", "lesson_slug"],
                name="uniq_lesson_release_per_class_lesson",
            ),
        ]
        indexes = [
            models.Index(fields=["classroom", "course_slug", "lesson_slug"]),
        ]

    def __str__(self) -> str:
        return f"{self.classroom.join_code}:{self.course_slug}/{self.lesson_slug}"


class LessonAsset(models.Model):
    """Teacher-managed reference file that can be linked inside lesson markdown."""

    folder = models.ForeignKey(LessonAssetFolder, on_delete=models.PROTECT, related_name="assets")
    course_slug = models.SlugField(max_length=120, blank=True, default="")
    lesson_slug = models.SlugField(max_length=120, blank=True, default="")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    original_filename = models.CharField(max_length=255, blank=True, default="")
    file = models.FileField(upload_to=_lesson_asset_upload_to)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "id"]
        indexes = [
            models.Index(fields=["folder", "is_active"], name="hub_lessona_folder__764626_idx"),
            models.Index(
                fields=["course_slug", "lesson_slug", "is_active"],
                name="hub_lessona_course__7a0ed8_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.folder.path}: {self.title}"


class AuditEvent(models.Model):
    """Immutable staff-action record for operations and incident review."""

    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="hub_audit_events",
    )
    classroom = models.ForeignKey(
        Class,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    action = models.CharField(max_length=80)
    target_type = models.CharField(max_length=80, blank=True, default="")
    target_id = models.CharField(max_length=64, blank=True, default="")
    summary = models.CharField(max_length=255, blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["created_at"]),
            models.Index(fields=["action", "created_at"]),
            models.Index(fields=["classroom", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.created_at.isoformat()} {self.action} {self.target_type}:{self.target_id}"
