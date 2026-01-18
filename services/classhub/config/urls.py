from django.contrib import admin
from django.urls import path
from hub import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz", views.healthz),

    # Student flow
    path("", views.index),
    path("join", views.join_class),
    path("student", views.student_home),
    path("logout", views.student_logout),

    # Upload dropbox
    path("material/<int:material_id>/upload", views.material_upload),
    path("submission/<int:submission_id>/download", views.submission_download),

    # Repo-authored course content (markdown)
    path("course/<slug:course_slug>", views.course_overview),
    path("course/<slug:course_slug>/<slug:lesson_slug>", views.course_lesson),

    # Teacher cockpit (staff-only)
    path("teach", views.teach_home),
    path("teach/create-class", views.teach_create_class),
    path("teach/class/<int:class_id>", views.teach_class_dashboard),
    path("teach/class/<int:class_id>/toggle-lock", views.teach_toggle_lock),
    path("teach/class/<int:class_id>/rotate-code", views.teach_rotate_code),
    path("teach/class/<int:class_id>/add-module", views.teach_add_module),
    path("teach/class/<int:class_id>/move-module", views.teach_move_module),
    path("teach/module/<int:module_id>", views.teach_module),
    path("teach/module/<int:module_id>/add-material", views.teach_add_material),
    path("teach/module/<int:module_id>/move-material", views.teach_move_material),
    path("teach/material/<int:material_id>/submissions", views.teach_material_submissions),
]

