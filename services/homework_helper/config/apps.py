from django.contrib.admin.apps import AdminConfig


class HelperAdminConfig(AdminConfig):
    default_site = "config.admin.HelperAdminSite"
