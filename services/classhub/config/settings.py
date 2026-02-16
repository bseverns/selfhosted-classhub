"""Django settings for Class Hub.

This is intentionally minimal: a Day-1 scaffold.

Key idea:
- Teachers/admins use Django auth (admin site is enough for MVP).
- Students do NOT have accounts. They join a class with a code and get a session cookie.
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
CONTENT_ROOT = BASE_DIR / "content"
env = environ.Env(
    DJANGO_DEBUG=(bool, False),
)

# Repo-authored content packs live under:
#   services/classhub/content/courses/<course_slug>/...
CONTENT_ROOT = BASE_DIR / "content"
CONTENT_COURSES_ROOT = CONTENT_ROOT / "courses"

DEBUG = env.bool("DJANGO_DEBUG", default=False)
SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-only-change-me")
ALLOWED_HOSTS = [h.strip() for h in env("DJANGO_ALLOWED_HOSTS", default="localhost,127.0.0.1").split(",") if h.strip()]

CSRF_TRUSTED_ORIGINS = []
_origins = env("CSRF_TRUSTED_ORIGINS", default="")
if _origins:
    CSRF_TRUSTED_ORIGINS = [o.strip() for o in _origins.split(",") if o.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "hub",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
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
            "LOCATION": "classhub-default",
        }
    }

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Uploads (student submissions)
#
# We intentionally do NOT serve these as public /media files.
# Downloads go through a permission-checked Django view.
MEDIA_ROOT = Path(os.environ.get("CLASSHUB_UPLOAD_ROOT", "/uploads"))
MEDIA_URL = "/_uploads/"

# Conservative defaults; raise if you expect large assets.
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024  # 5MB (larger files stream to disk)
# Request cap (MB) applies to teacher video uploads too.
UPLOAD_REQUEST_MAX_MB = env.int("CLASSHUB_UPLOAD_MAX_MB", default=600)
DATA_UPLOAD_MAX_MEMORY_SIZE = UPLOAD_REQUEST_MAX_MB * 1024 * 1024
JOIN_RATE_LIMIT_PER_MINUTE = env.int("CLASSHUB_JOIN_RATE_LIMIT_PER_MINUTE", default=20)
DEVICE_REJOIN_COOKIE_NAME = env("CLASSHUB_DEVICE_REJOIN_COOKIE_NAME", default="classhub_student_hint")
DEVICE_REJOIN_MAX_AGE_DAYS = env.int("CLASSHUB_DEVICE_REJOIN_MAX_AGE_DAYS", default=30)

# When behind Caddy, Django should respect forwarded proto for secure cookies.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
