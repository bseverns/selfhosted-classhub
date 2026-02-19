"""Django settings for Homework Helper.

This is a separate service so:
- rate limiting is clean
- prompt policy lives in one place
- outages do not break class materials

The helper is routed under /helper/* by Caddy.
"""

from pathlib import Path
import environ
import os

BASE_DIR = Path(__file__).resolve().parent.parent
env = environ.Env(
    DJANGO_DEBUG=(bool, False),
)

DEBUG = env.bool("DJANGO_DEBUG", default=False)
SECRET_KEY = env("DJANGO_SECRET_KEY", default="").strip()
if not SECRET_KEY:
    raise RuntimeError("DJANGO_SECRET_KEY is required")


def _secret_key_looks_unsafe(secret: str) -> bool:
    normalized = secret.strip().lower()
    blocked = {
        "dev-secret",
        "changeme",
        "change_me",
        "replace_me",
        "replace_me_strong",
        "secret",
        "password",
        "django-insecure",
    }
    if normalized in blocked or normalized.startswith("django-insecure"):
        return True
    if len(secret.strip()) < 32:
        return True
    return False


if not DEBUG and _secret_key_looks_unsafe(SECRET_KEY):
    raise RuntimeError("DJANGO_SECRET_KEY must be a strong non-default value when DJANGO_DEBUG=0")

ALLOWED_HOSTS = [h.strip() for h in env("DJANGO_ALLOWED_HOSTS", default="localhost,127.0.0.1").split(",") if h.strip()]

CSRF_TRUSTED_ORIGINS = []
_origins = env("CSRF_TRUSTED_ORIGINS", default="")
if _origins:
    CSRF_TRUSTED_ORIGINS = [o.strip() for o in _origins.split(",") if o.strip()]

INSTALLED_APPS = [
    "config.apps.HelperAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_otp",
    "django_otp.plugins.otp_totp",
    "django_otp.plugins.otp_static",
    "tutor",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "config.middleware.SecurityHeadersMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": env.db(default=f"sqlite:///{BASE_DIR/'db.sqlite3'}")
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Cache: use Redis in Compose, fallback to local memory for lightweight local checks.
REDIS_URL = os.getenv("REDIS_URL", "").strip()
if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "helper-default",
        }
    }

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG

if not DEBUG:
    SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=False)
    SECURE_HSTS_SECONDS = env.int("DJANGO_SECURE_HSTS_SECONDS", default=3600)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", default=False)
    SECURE_HSTS_PRELOAD = env.bool("DJANGO_SECURE_HSTS_PRELOAD", default=False)
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"
    SECURE_REFERRER_POLICY = (
        env("DJANGO_SECURE_REFERRER_POLICY", default="strict-origin-when-cross-origin").strip()
        or "strict-origin-when-cross-origin"
    )

# Shared request-safety controls for proxy-aware client IP extraction.
# Safe-by-default: only trust forwarded headers when explicitly enabled.
REQUEST_SAFETY_TRUST_PROXY_HEADERS = env.bool("REQUEST_SAFETY_TRUST_PROXY_HEADERS", default=False)
REQUEST_SAFETY_XFF_INDEX = env.int("REQUEST_SAFETY_XFF_INDEX", default=0)
ADMIN_2FA_REQUIRED = env.bool("DJANGO_ADMIN_2FA_REQUIRED", default=True)
HELPER_REQUIRE_CLASSHUB_TABLE = env.bool("HELPER_REQUIRE_CLASSHUB_TABLE", default=False)
HELPER_REQUIRE_SCOPE_TOKEN_FOR_STAFF = env.bool("HELPER_REQUIRE_SCOPE_TOKEN_FOR_STAFF", default=False)
CSP_REPORT_ONLY_POLICY = env("DJANGO_CSP_REPORT_ONLY_POLICY", default="").strip()
