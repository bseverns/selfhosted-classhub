"""Top-level URL map for the Class Hub Django service.

Plain-language map:
- `/` + `/join` + `/student` are the learner flow.
- `/teach/...` is the teacher/staff workspace.
- `/admin/...` is the Django admin surface (superusers only here).
- `/helper/...` is intentionally NOT in this file; Caddy routes it to the
  separate Homework Helper service.
"""

from django.contrib import admin
from django.urls import path
from hub import views

urlpatterns = [
    # Admin surface (operations/configuration). Kept separate from daily teaching UI.
    path("admin/", admin.site.urls),

    # Health endpoint for reverse proxy and uptime checks.
    path("healthz", views.healthz),

    # Student flow (class-code login and classroom page).
    path("", views.index),
    path("join", views.join_class),
    path("student", views.student_home),
    path("logout", views.student_logout),

    # Student upload + shared download/stream routes.
    path("material/<int:material_id>/upload", views.material_upload),
    path("submission/<int:submission_id>/download", views.submission_download),
    path("lesson-video/<int:video_id>/stream", views.lesson_video_stream),
    path("lesson-asset/<int:asset_id>/download", views.lesson_asset_download),

    # Repo-authored course content pages (markdown rendered to HTML).
    path("course/<slug:course_slug>", views.course_overview),
    path("course/<slug:course_slug>/<slug:lesson_slug>", views.course_lesson),

    # Teacher cockpit (staff-only, outside Django admin).
    path("teach", views.teach_home),
    path("teach/generate-authoring-templates", views.teach_generate_authoring_templates),
    path("teach/authoring-template/download", views.teach_download_authoring_template),
    path("teach/logout", views.teacher_logout),
    path("teach/lessons", views.teach_lessons),
    path("teach/lessons/release", views.teach_set_lesson_release),
    path("teach/assets", views.teach_assets),
    path("teach/create-class", views.teach_create_class),
    path("teach/class/<int:class_id>", views.teach_class_dashboard),
    path("teach/class/<int:class_id>/join-card", views.teach_class_join_card),
    path("teach/class/<int:class_id>/rename-student", views.teach_rename_student),
    path("teach/class/<int:class_id>/reset-roster", views.teach_reset_roster),
    path("teach/class/<int:class_id>/toggle-lock", views.teach_toggle_lock),
    path("teach/class/<int:class_id>/rotate-code", views.teach_rotate_code),
    path("teach/class/<int:class_id>/add-module", views.teach_add_module),
    path("teach/class/<int:class_id>/move-module", views.teach_move_module),
    path("teach/videos", views.teach_videos),
    path("teach/module/<int:module_id>", views.teach_module),
    path("teach/module/<int:module_id>/add-material", views.teach_add_material),
    path("teach/module/<int:module_id>/move-material", views.teach_move_material),
    path("teach/material/<int:material_id>/submissions", views.teach_material_submissions),
]
