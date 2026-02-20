from urllib.parse import urlencode

from django.conf import settings
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse


class SecurityHeadersMiddleware:
    """Attach optional security headers configured via settings."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        csp_policy = (getattr(settings, "CSP_POLICY", "") or "").strip()
        if csp_policy and "Content-Security-Policy" not in response:
            response["Content-Security-Policy"] = csp_policy
        csp_report_only = (getattr(settings, "CSP_REPORT_ONLY_POLICY", "") or "").strip()
        if csp_report_only and "Content-Security-Policy-Report-Only" not in response:
            response["Content-Security-Policy-Report-Only"] = csp_report_only
        permissions_policy = (getattr(settings, "PERMISSIONS_POLICY", "") or "").strip()
        if permissions_policy and "Permissions-Policy" not in response:
            response["Permissions-Policy"] = permissions_policy
        referrer_policy = (
            getattr(settings, "SECURITY_REFERRER_POLICY", None)
            or getattr(settings, "SECURE_REFERRER_POLICY", "")
            or ""
        ).strip()
        if referrer_policy and "Referrer-Policy" not in response:
            response["Referrer-Policy"] = referrer_policy
        x_frame_options = (getattr(settings, "X_FRAME_OPTIONS", "") or "").strip()
        if x_frame_options and "X-Frame-Options" not in response:
            response["X-Frame-Options"] = x_frame_options
        return response


class TeacherOTPRequiredMiddleware:
    """Require OTP-verified staff sessions for /teach routes."""

    _EXEMPT_PREFIXES = (
        "/teach/2fa/setup",
        "/teach/logout",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not getattr(settings, "TEACHER_2FA_REQUIRED", True):
            return self.get_response(request)

        path = request.path or ""
        if not path.startswith("/teach"):
            return self.get_response(request)
        if any(path.startswith(prefix) for prefix in self._EXEMPT_PREFIXES):
            return self.get_response(request)

        user = getattr(request, "user", None)
        if not user or not user.is_authenticated or not user.is_staff:
            return self.get_response(request)

        is_verified_attr = getattr(user, "is_verified", None)
        is_verified = bool(is_verified_attr() if callable(is_verified_attr) else is_verified_attr)
        if is_verified:
            return self.get_response(request)

        next_path = request.get_full_path()
        params = urlencode({"next": next_path}) if next_path else ""
        destination = "/teach/2fa/setup"
        if params:
            destination = f"{destination}?{params}"
        return HttpResponseRedirect(destination)


class SiteModeMiddleware:
    """Gate high-impact routes when operator enables a degraded site mode."""

    _SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
    _JOIN_ONLY_ALLOWED_EXACT = {"/", "/join", "/student", "/logout", "/healthz"}
    _JOIN_ONLY_ALLOWED_PREFIXES = ("/course/", "/lesson-video/", "/lesson-asset/", "/static/")
    _MAINTENANCE_ALLOWED_EXACT = {"/healthz"}
    _MAINTENANCE_ALLOWED_PREFIXES = ("/admin/", "/teach", "/static/")

    def __init__(self, get_response):
        self.get_response = get_response

    @staticmethod
    def _site_mode() -> str:
        mode = (getattr(settings, "SITE_MODE", "normal") or "normal").strip().lower()
        return mode if mode else "normal"

    @staticmethod
    def _mode_message(mode: str) -> str:
        override = (getattr(settings, "SITE_MODE_MESSAGE", "") or "").strip()
        if override:
            return override
        if mode == "read-only":
            return "Class Hub is in read-only mode. Uploads and write actions are temporarily disabled."
        if mode == "join-only":
            return "Class Hub is in join-only mode. Class entry is available; teaching and upload actions are paused."
        if mode == "maintenance":
            return "Class Hub is in maintenance mode. Please try again shortly."
        return ""

    @staticmethod
    def _wants_json(request) -> bool:
        path = (request.path or "").strip()
        accept = (request.headers.get("Accept", "") or "").lower()
        content_type = (request.headers.get("Content-Type", "") or "").lower()
        return (
            path == "/join"
            or "application/json" in accept
            or "application/json" in content_type
            or (request.headers.get("X-Requested-With", "") or "").lower() == "xmlhttprequest"
        )

    @classmethod
    def _join_only_allows(cls, path: str) -> bool:
        if path in cls._JOIN_ONLY_ALLOWED_EXACT:
            return True
        return any(path.startswith(prefix) for prefix in cls._JOIN_ONLY_ALLOWED_PREFIXES)

    @classmethod
    def _maintenance_allows(cls, path: str) -> bool:
        if path in cls._MAINTENANCE_ALLOWED_EXACT:
            return True
        return any(path.startswith(prefix) for prefix in cls._MAINTENANCE_ALLOWED_PREFIXES)

    @classmethod
    def _read_only_blocks(cls, request) -> bool:
        path = (request.path or "").strip()
        method = (request.method or "GET").upper()
        if path.startswith("/admin/"):
            return False
        if path.startswith("/internal/events/"):
            return False
        if path.startswith("/teach/2fa/setup"):
            return False
        if path.startswith("/material/") and path.endswith("/upload"):
            return True
        if method not in cls._SAFE_METHODS and path != "/join":
            return True
        return False

    def _blocked_response(self, request, *, mode: str):
        message = self._mode_message(mode)
        if self._wants_json(request):
            response = JsonResponse(
                {
                    "error": "site_mode_restricted",
                    "site_mode": mode,
                    "message": message,
                },
                status=503,
            )
        else:
            response = HttpResponse(message, status=503, content_type="text/plain; charset=utf-8")
        response["Retry-After"] = "120"
        response["Cache-Control"] = "no-store"
        return response

    def __call__(self, request):
        mode = self._site_mode()
        if mode == "normal":
            return self.get_response(request)

        path = (request.path or "").strip()
        if mode == "read-only" and self._read_only_blocks(request):
            return self._blocked_response(request, mode=mode)
        if mode == "join-only" and not self._join_only_allows(path):
            return self._blocked_response(request, mode=mode)
        if mode == "maintenance" and not self._maintenance_allows(path):
            return self._blocked_response(request, mode=mode)
        return self.get_response(request)
