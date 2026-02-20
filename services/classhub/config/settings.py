"""Django settings for Class Hub.

This is intentionally minimal: a Day-1 scaffold.

Key idea:
- Teachers/admins use Django auth (admin site is enough for MVP).
- Students do NOT have accounts. They join a class with a code and get a session cookie.

Reading order for non-developers:
1) identity + host/domain settings
2) apps + middleware
3) database + cache
4) static/uploads
5) security flags for reverse proxy deployments
"""

from pathlib import Path
import os
import environ

BASE_DIR = Path(__file__).resolve().parent.parent

# Repo-authored curriculum content lives inside the Django build context so it
# ships with the container image.
#
# Layout:
#   services/classhub/content/courses/<course_slug>/course.yaml
#   services/classhub/content/courses/<course_slug>/lessons/*.md
env = environ.Env(
    DJANGO_DEBUG=(bool, False),
)

# Repo-authored content packs live under:
#   services/classhub/content/courses/<course_slug>/...
CONTENT_ROOT = BASE_DIR / "content"
CONTENT_COURSES_ROOT = CONTENT_ROOT / "courses"

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

# Use when serving via domain + HTTPS so Django accepts browser CSRF tokens
# coming from those origins.
CSRF_TRUSTED_ORIGINS = []
_origins = env("CSRF_TRUSTED_ORIGINS", default="")
if _origins:
    CSRF_TRUSTED_ORIGINS = [o.strip() for o in _origins.split(",") if o.strip()]

EMAIL_BACKEND = env(
    "DJANGO_EMAIL_BACKEND",
    default="django.core.mail.backends.console.EmailBackend",
).strip() or "django.core.mail.backends.console.EmailBackend"
EMAIL_HOST = env("DJANGO_EMAIL_HOST", default="").strip()
EMAIL_PORT = env.int("DJANGO_EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("DJANGO_EMAIL_HOST_USER", default="").strip()
EMAIL_HOST_PASSWORD = env("DJANGO_EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("DJANGO_EMAIL_USE_TLS", default=True)
EMAIL_USE_SSL = env.bool("DJANGO_EMAIL_USE_SSL", default=False)
EMAIL_TIMEOUT = env.int("DJANGO_EMAIL_TIMEOUT_SECONDS", default=10)
DEFAULT_FROM_EMAIL = env("DJANGO_DEFAULT_FROM_EMAIL", default="classhub@localhost").strip() or "classhub@localhost"
TEACHER_INVITE_FROM_EMAIL = (
    env("TEACHER_INVITE_FROM_EMAIL", default=DEFAULT_FROM_EMAIL).strip() or DEFAULT_FROM_EMAIL
)
TEACHER_2FA_INVITE_MAX_AGE_SECONDS = env.int("TEACHER_2FA_INVITE_MAX_AGE_SECONDS", default=72 * 3600)
TEACHER_2FA_DEVICE_NAME = (
    env("TEACHER_2FA_DEVICE_NAME", default="teacher-primary").strip() or "teacher-primary"
)

INSTALLED_APPS = [
    "config.apps.ClassHubAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_otp",
    "django_otp.plugins.otp_totp",
    "django_otp.plugins.otp_static",
    "hub.apps.HubConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "config.middleware.SecurityHeadersMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",
    "config.middleware.TeacherOTPRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # StudentSessionMiddleware relies on sessions.
    "hub.middleware.StudentSessionMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
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

REDIS_URL = os.getenv("REDIS_URL", "").strip()
if REDIS_URL:
    # Production/default path: shared cache in Redis.
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
        }
    }
else:
    # Fallback path: single-process in-memory cache (fine for local/demo).
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "classhub-default",
        }
    }

LANGUAGE_CODE = "en-us"
TIME_ZONE = env("DJANGO_TIME_ZONE", default="America/Chicago").strip() or "America/Chicago"
USE_I18N = True
USE_TZ = True

_DEFAULT_CSP_REPORT_ONLY_POLICY = (
    "default-src 'self'; "
    "base-uri 'self'; "
    "object-src 'none'; "
    "frame-ancestors 'self'; "
    "img-src 'self' data: https:; "
    "media-src 'self' https:; "
    "frame-src 'self' https://www.youtube.com https://www.youtube-nocookie.com; "
    "style-src 'self' 'unsafe-inline'; "
    "script-src 'self' 'unsafe-inline'; "
    "connect-src 'self' https:;"
)

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    # Default uploaded-file storage for submission and lesson media.
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Uploads (student submissions)
#
# We intentionally do NOT serve these as public /media files.
# Downloads go through a permission-checked Django view.
MEDIA_ROOT = Path(os.environ.get("CLASSHUB_UPLOAD_ROOT", "/uploads"))
MEDIA_URL = "/_uploads/"
# Teacher-generated authoring templates (from /teach landing page action).
CLASSHUB_AUTHORING_TEMPLATE_DIR = Path(
    os.environ.get("CLASSHUB_AUTHORING_TEMPLATE_DIR", "/uploads/authoring_templates")
)
CLASSHUB_AUTHORING_TEMPLATE_AGE_BAND_DEFAULT = os.environ.get(
    "CLASSHUB_AUTHORING_TEMPLATE_AGE_BAND_DEFAULT",
    "5th-7th",
).strip() or "5th-7th"

# Conservative defaults; raise if you expect large assets.
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024  # 5MB (larger files stream to disk)
# Request cap (MB) applies to teacher video uploads too.
UPLOAD_REQUEST_MAX_MB = env.int("CLASSHUB_UPLOAD_MAX_MB", default=600)
DATA_UPLOAD_MAX_MEMORY_SIZE = UPLOAD_REQUEST_MAX_MB * 1024 * 1024
# Join endpoint throttling (protects classroom join flow from brute-force/abuse).
JOIN_RATE_LIMIT_PER_MINUTE = env.int("CLASSHUB_JOIN_RATE_LIMIT_PER_MINUTE", default=20)
# Cookie used for same-device student rejoin hints.
DEVICE_REJOIN_COOKIE_NAME = env("CLASSHUB_DEVICE_REJOIN_COOKIE_NAME", default="classhub_student_hint")
DEVICE_REJOIN_MAX_AGE_DAYS = env.int("CLASSHUB_DEVICE_REJOIN_MAX_AGE_DAYS", default=30)
# Optional upload malware scanning (command-based, e.g., clamscan).
CLASSHUB_UPLOAD_SCAN_ENABLED = env.bool("CLASSHUB_UPLOAD_SCAN_ENABLED", default=False)
CLASSHUB_UPLOAD_SCAN_COMMAND = env(
    "CLASSHUB_UPLOAD_SCAN_COMMAND",
    default="clamscan --no-summary --stdout",
).strip()
CLASSHUB_UPLOAD_SCAN_TIMEOUT_SECONDS = env.int("CLASSHUB_UPLOAD_SCAN_TIMEOUT_SECONDS", default=20)
# If true, block uploads when scanner errors/timeouts occur.
CLASSHUB_UPLOAD_SCAN_FAIL_CLOSED = env.bool("CLASSHUB_UPLOAD_SCAN_FAIL_CLOSED", default=False)
# Optional markdown image support with explicit host allowlist.
CLASSHUB_MARKDOWN_ALLOW_IMAGES = env.bool("CLASSHUB_MARKDOWN_ALLOW_IMAGES", default=False)
_image_hosts_raw = env("CLASSHUB_MARKDOWN_ALLOWED_IMAGE_HOSTS", default="")
CLASSHUB_MARKDOWN_ALLOWED_IMAGE_HOSTS = [
    h.strip().lower() for h in _image_hosts_raw.split(",") if h.strip()
]
# Optional absolute origin used when rendering lesson asset/video links.
# Example: https://assets.creatempls.org
CLASSHUB_ASSET_BASE_URL = env("CLASSHUB_ASSET_BASE_URL", default="").strip().rstrip("/")
# Shared request-safety controls for proxy-aware client IP extraction.
# Safe-by-default: only trust forwarded headers when explicitly enabled.
REQUEST_SAFETY_TRUST_PROXY_HEADERS = env.bool("REQUEST_SAFETY_TRUST_PROXY_HEADERS", default=False)
REQUEST_SAFETY_XFF_INDEX = env.int("REQUEST_SAFETY_XFF_INDEX", default=0)
ADMIN_2FA_REQUIRED = env.bool("DJANGO_ADMIN_2FA_REQUIRED", default=True)
TEACHER_2FA_REQUIRED = env.bool("DJANGO_TEACHER_2FA_REQUIRED", default=True)
CSP_REPORT_ONLY_POLICY = env(
    "DJANGO_CSP_REPORT_ONLY_POLICY",
    default=("" if DEBUG else _DEFAULT_CSP_REPORT_ONLY_POLICY),
).strip()

# When behind Caddy, Django should respect forwarded proto for secure cookies.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# In production (DEBUG=False), session + CSRF cookies should only travel over HTTPS.
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_DOMAIN = env("DJANGO_SESSION_COOKIE_DOMAIN", default="").strip() or None
CSRF_COOKIE_DOMAIN = env("DJANGO_CSRF_COOKIE_DOMAIN", default="").strip() or None

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
