from django.conf import settings
from django_otp.admin import OTPAdminSite


class ClassHubAdminSite(OTPAdminSite):
    site_header = "createMPLS Course Admin"
    site_title = "createMPLS Course Admin"
    index_title = "createMPLS Course Admin"
    enable_nav_sidebar = False

    def has_permission(self, request) -> bool:
        user = getattr(request, "user", None)
        if not user or not user.is_active or not user.is_superuser:
            return False
        if not bool(getattr(settings, "ADMIN_2FA_REQUIRED", True)):
            return True
        is_verified = getattr(user, "is_verified", None)
        return bool(is_verified() if callable(is_verified) else False)
