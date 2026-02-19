from django.contrib import admin
from django.urls import path
from tutor import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("helper/healthz", views.healthz),
    path("helper/chat", views.chat),
]
