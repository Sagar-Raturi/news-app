"""Django settings. Everything environment-specific comes from env vars."""

import os
import sys
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


# "development" (default), "staging" or "production". Staging and production
# are "deployed": DEBUG is off unless asked for, and missing secrets stop startup.
DJANGO_ENV = os.environ.get("DJANGO_ENV", "development")
if DJANGO_ENV not in {"development", "staging", "production"}:
    raise ImproperlyConfigured(f"DJANGO_ENV must be development, staging or production, not {DJANGO_ENV!r}.")
DEPLOYED = DJANGO_ENV != "development"

DEV_SECRET_KEY = "dev-only-insecure-secret-key-change-me"
DEBUG = env_bool("DJANGO_DEBUG", not DEPLOYED)
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", DEV_SECRET_KEY)
ALLOWED_HOSTS = env_list(
    "DJANGO_ALLOWED_HOSTS", "" if DEPLOYED else "localhost,127.0.0.1,0.0.0.0,[::1],testserver"
)

# Canonical public origin used in sitemaps, structured data and OG tags.
SITE_BASE_URL = os.environ.get("SITE_BASE_URL", "http://localhost:8000").rstrip("/")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", SITE_BASE_URL)

if DEPLOYED:
    problems = []
    if DEBUG:
        problems.append("DJANGO_DEBUG must be off")
    if SECRET_KEY == DEV_SECRET_KEY or len(SECRET_KEY) < 50:
        problems.append("DJANGO_SECRET_KEY must be set to 50+ random characters")
    if not ALLOWED_HOSTS:
        problems.append("DJANGO_ALLOWED_HOSTS must list the site's domains")
    if not SITE_BASE_URL.startswith("https://"):
        problems.append("SITE_BASE_URL must be the https:// address of the site")
    if DJANGO_ENV == "production" and os.environ.get("NEWSDESK_WRITER") == "fake":
        # Fake agents write placeholder text that must never reach readers.
        problems.append("NEWSDESK_WRITER=fake is for development and staging only")
    if problems:
        raise ImproperlyConfigured(f"{DJANGO_ENV} settings: " + "; ".join(problems) + ".")

INSTALLED_APPS = [
    "core",
    "news",
    "newsdesk",
    "wagtail.contrib.forms",
    "wagtail.contrib.redirects",
    "wagtail.contrib.settings",
    "wagtail.contrib.sitemaps",
    "wagtail.contrib.table_block",
    "wagtail.embeds",
    "wagtail.sites",
    "wagtail.users",
    "wagtail.snippets",
    "wagtail.documents",
    "wagtail.images",
    "wagtail.search",
    "wagtail.admin",
    "wagtail",
    "modelcluster",
    "taggit",
    "axes",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "core.apps.LedgerStaticFilesConfig",
    "django.contrib.sitemaps",
]

MIDDLEWARE = [
    # First, so uptime checks skip host validation and the HTTPS redirect.
    "core.middleware.HealthCheckMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "wagtail.contrib.redirects.middleware.RedirectMiddleware",
    "core.middleware.HtmxVaryMiddleware",
    # Last, as django-axes requires: locks out repeated failed logins.
    "axes.middleware.AxesMiddleware",
]

AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]

# Login rate limiting (django-axes): 5 failures for one username from one
# address lock that pair out for an hour. The address is the one Caddy reports
# in X-Real-IP (Cloudflare's CF-Connecting-IP when proxied); without a proxy
# it is REMOTE_ADDR.
AXES_FAILURE_LIMIT = int(os.environ.get("AXES_FAILURE_LIMIT", "5"))
AXES_COOLOFF_TIME = 1  # hours
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]
AXES_RESET_ON_SUCCESS = True
AXES_CLIENT_IP_CALLABLE = "core.middleware.client_ip"
AXES_ENABLED = env_bool("AXES_ENABLED", "test" not in sys.argv)

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
                "wagtail.contrib.settings.context_processors.settings",
                "core.context_processors.site_navigation",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": dj_database_url.config(
        default="postgres://newsapp:newsapp@localhost:5432/newsapp",
        conn_max_age=60,
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-gb"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(os.environ.get("DJANGO_MEDIA_ROOT", BASE_DIR / "media"))

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}

# Media (uploaded images) on S3-compatible object storage when a bucket is
# set (DigitalOcean Spaces, AWS S3), so the server can be rebuilt without
# losing anything. Otherwise files stay on disk (MEDIA_ROOT), served by Caddy.
AWS_STORAGE_BUCKET_NAME = os.environ.get("AWS_STORAGE_BUCKET_NAME", "")
if AWS_STORAGE_BUCKET_NAME:
    STORAGES["default"] = {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": AWS_STORAGE_BUCKET_NAME,
            "endpoint_url": os.environ.get("AWS_S3_ENDPOINT_URL") or None,
            "region_name": os.environ.get("AWS_S3_REGION_NAME") or None,
            "access_key": os.environ.get("AWS_ACCESS_KEY_ID", ""),
            "secret_key": os.environ.get("AWS_SECRET_ACCESS_KEY", ""),
            "custom_domain": os.environ.get("MEDIA_CDN_DOMAIN") or None,
            "default_acl": os.environ.get("AWS_DEFAULT_ACL") or None,
            "location": "media",
            "file_overwrite": False,
            "querystring_auth": False,
            # File names never change content (renditions get new names).
            "object_parameters": {"CacheControl": "public, max-age=31536000, immutable"},
        },
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Wagtail
WAGTAIL_SITE_NAME = "Manthan Reviews"
WAGTAILADMIN_BASE_URL = os.environ.get("WAGTAILADMIN_BASE_URL", "http://localhost:8000")
WAGTAILSEARCH_BACKENDS = {"default": {"BACKEND": "wagtail.search.backends.database"}}
WAGTAILDOCS_EXTENSIONS = ["csv", "docx", "key", "odt", "pdf", "pptx", "rtf", "txt", "xlsx", "zip"]
WAGTAIL_I18N_ENABLED = False
WAGTAIL_WORKFLOW_ENABLED = True
WAGTAIL_MODERATION_ENABLED = True
TAGGIT_CASE_INSENSITIVE = True

# Cache: Redis when DJANGO_CACHE_URL is set (deployed), memory otherwise.
DJANGO_CACHE_URL = os.environ.get("DJANGO_CACHE_URL", "")
if DJANGO_CACHE_URL:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": DJANGO_CACHE_URL}}

CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", CELERY_BROKER_URL)
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", False)
CELERY_TIMEZONE = TIME_ZONE
# Agent runs are long; take one task at a time so a busy worker doesn't hoard
# queued runs. A run that hits the soft limit fails with a "Retry" button.
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_SOFT_TIME_LIMIT = int(os.environ.get("CELERY_TASK_SOFT_TIME_LIMIT", "1800"))
CELERY_TASK_TIME_LIMIT = CELERY_TASK_SOFT_TIME_LIMIT + 120
CELERY_RESULT_EXPIRES = 60 * 60 * 24

# Newsdesk AI agents. The Anthropic SDK reads ANTHROPIC_API_KEY from the
# environment. NEWSDESK_WRITER=fake writes canned drafts without calling the
# API (demos, tests).
NEWSDESK_WRITER = os.environ.get("NEWSDESK_WRITER", "anthropic")
NEWSDESK_MAX_TOKENS = int(os.environ.get("NEWSDESK_MAX_TOKENS", "16000"))
# Live activity feed over Redis pub/sub (off in tests unless a test turns it on).
NEWSDESK_LIVE_EVENTS = env_bool("NEWSDESK_LIVE_EVENTS", "test" not in sys.argv)
# Fake agents pause this many seconds between streamed chunks so demos look live.
NEWSDESK_FAKE_DELAY = float(os.environ.get("NEWSDESK_FAKE_DELAY", "0"))

# Emails go to the console in dev (workflow notifications); deployed sites set
# DJANGO_EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend and the
# SMTP details of their provider (Amazon SES, Postmark).
EMAIL_BACKEND = os.environ.get(
    "DJANGO_EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend"
)
EMAIL_HOST = os.environ.get("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_TIMEOUT = 10
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "newsroom@example.com")
SERVER_EMAIL = os.environ.get("SERVER_EMAIL", DEFAULT_FROM_EMAIL)
# Who gets error emails (comma-separated addresses); Sentry is the main channel.
ADMINS = [(address, address) for address in env_list("DJANGO_ADMINS")]

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {
        "handlers": ["console"],
        "level": "WARNING" if "test" in sys.argv else os.environ.get("DJANGO_LOG_LEVEL", "INFO"),
    },
}

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = env_bool("DJANGO_SECURE_COOKIES", True)
    CSRF_COOKIE_SECURE = env_bool("DJANGO_SECURE_COOKIES", True)

if DEPLOYED:
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SSL_REDIRECT", True)
    # Start short on staging; a year in production (browsers then refuse plain
    # HTTP for this long, so only raise it once HTTPS works everywhere).
    SECURE_HSTS_SECONDS = int(
        os.environ.get("DJANGO_HSTS_SECONDS", "31536000" if DJANGO_ENV == "production" else "3600")
    )
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("DJANGO_HSTS_INCLUDE_SUBDOMAINS", False)
    SECURE_HSTS_PRELOAD = env_bool("DJANGO_HSTS_PRELOAD", False)
    SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
    SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"

# Error tracking: Sentry for the web app and the Celery worker.
SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
if SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=DJANGO_ENV,
        release=os.environ.get("APP_VERSION") or None,
        traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0")),
        send_default_pii=False,
    )
