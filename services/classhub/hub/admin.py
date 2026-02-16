from django.contrib import admin
from django.utils.html import format_html

from .models import Class, Module, Material, StudentIdentity, Submission, LessonRelease, LessonVideo

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
    list_display = ("display_name", "classroom", "created_at", "last_seen_at")
    list_filter = ("classroom",)
    search_fields = ("display_name",)


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
