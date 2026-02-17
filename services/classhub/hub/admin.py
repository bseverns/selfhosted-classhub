from django.contrib import admin
from django.utils.html import format_html

from .models import (
    AuditEvent,
    Class,
    LessonAsset,
    LessonAssetFolder,
    LessonRelease,
    LessonVideo,
    Material,
    Module,
    StudentEvent,
    StudentIdentity,
    Submission,
)

@admin.register(Class)
class ClassAdmin(admin.ModelAdmin):
    list_display = ("name", "join_code", "is_locked")
    search_fields = ("name", "join_code")
    list_filter = ("is_locked",)

@admin.register(Module)
class ModuleAdmin(admin.ModelAdmin):
    list_display = ("title", "classroom", "order_index")
    list_filter = ("classroom",)

@admin.register(Material)
class MaterialAdmin(admin.ModelAdmin):
    list_display = ("title", "module", "type", "order_index")
    list_filter = ("type", "module__classroom")

@admin.register(StudentIdentity)
class StudentIdentityAdmin(admin.ModelAdmin):
    list_display = ("display_name", "return_code", "classroom", "created_at", "last_seen_at")
    list_filter = ("classroom",)
    search_fields = ("display_name", "return_code")


@admin.register(StudentEvent)
class StudentEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "event_type", "classroom", "student", "source", "ip_address")
    list_filter = ("event_type", "classroom", "student", ("created_at", admin.DateFieldListFilter))
    search_fields = ("source", "ip_address", "student__display_name", "classroom__name", "classroom__join_code")
    readonly_fields = ("created_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ("id", "uploaded_at", "student", "material", "original_filename", "download_link")
    list_filter = ("material__module__classroom", "material")
    search_fields = ("original_filename", "student__display_name")
    readonly_fields = ("uploaded_at",)

    def download_link(self, obj: Submission):
        return format_html('<a href="/submission/{}/download">Download</a>', obj.id)

    download_link.short_description = "Download"


@admin.register(LessonVideo)
class LessonVideoAdmin(admin.ModelAdmin):
    list_display = ("title", "course_slug", "lesson_slug", "order_index", "is_active", "updated_at")
    list_filter = ("course_slug", "lesson_slug", "is_active")
    search_fields = ("title", "course_slug", "lesson_slug", "source_url")


@admin.register(LessonRelease)
class LessonReleaseAdmin(admin.ModelAdmin):
    list_display = ("classroom", "course_slug", "lesson_slug", "available_on", "force_locked", "updated_at")
    list_filter = ("classroom", "course_slug", "force_locked")
    search_fields = ("classroom__name", "classroom__join_code", "course_slug", "lesson_slug")


@admin.register(LessonAssetFolder)
class LessonAssetFolderAdmin(admin.ModelAdmin):
    list_display = ("path", "display_name", "created_at", "updated_at")
    search_fields = ("path", "display_name")
    ordering = ("path", "id")


@admin.register(LessonAsset)
class LessonAssetAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "folder",
        "course_slug",
        "lesson_slug",
        "is_active",
        "updated_at",
        "download_link",
    )
    list_filter = ("is_active", "folder", "course_slug", "lesson_slug")
    search_fields = ("title", "description", "original_filename", "folder__path", "course_slug", "lesson_slug")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("folder",)

    def download_link(self, obj: LessonAsset):
        return format_html('<a href="/lesson-asset/{}/download" target="_blank" rel="noopener">Download</a>', obj.id)

    download_link.short_description = "Download"


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "actor_user", "classroom", "target_type", "target_id", "ip_address")
    list_filter = ("action", "classroom", "actor_user")
    search_fields = ("action", "summary", "target_type", "target_id", "ip_address", "actor_user__username")
    readonly_fields = ("created_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
