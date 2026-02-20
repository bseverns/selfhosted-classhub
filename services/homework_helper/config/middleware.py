from django.conf import settings
from django.http import JsonResponse


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


class SiteModeMiddleware:
    """Gate helper chat when the platform is intentionally degraded."""

    _ALWAYS_ALLOWED_PREFIXES = ("/helper/healthz", "/admin/", "/static/")

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
        if mode == "join-only":
            return "Homework Helper is paused while the site is in join-only mode."
        if mode == "maintenance":
            return "Homework Helper is temporarily unavailable during maintenance."
        return "Homework Helper is temporarily unavailable."

    @classmethod
    def _is_always_allowed(cls, path: str) -> bool:
        return any(path.startswith(prefix) for prefix in cls._ALWAYS_ALLOWED_PREFIXES)

    def __call__(self, request):
        mode = self._site_mode()
        if mode in {"normal", "read-only"}:
            return self.get_response(request)

        path = (request.path or "").strip()
        if self._is_always_allowed(path):
            return self.get_response(request)

        if mode in {"join-only", "maintenance"} and path.startswith("/helper/chat"):
            response = JsonResponse(
                {
                    "error": "site_mode_restricted",
                    "site_mode": mode,
                    "message": self._mode_message(mode),
                },
                status=503,
            )
            response["Retry-After"] = "120"
            response["Cache-Control"] = "no-store"
            return response
        return self.get_response(request)
