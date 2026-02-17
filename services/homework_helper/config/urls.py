from django.contrib import admin
from django.urls import path
from tutor import views


def _admin_superuser_only(request) -> bool:
    return bool(request.user.is_active and request.user.is_superuser)


admin.site.has_permission = _admin_superuser_only

urlpatterns = [
    path("admin/", admin.site.urls),
    path("helper/healthz", views.healthz),
    path("helper/chat", views.chat),
]
