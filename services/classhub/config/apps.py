from django.contrib.admin.apps import AdminConfig


class ClassHubAdminConfig(AdminConfig):
    default_site = "config.admin.ClassHubAdminSite"
