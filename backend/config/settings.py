"""Django settings for KEMTA SUIVI.

Toute configuration sensible passe par l'environnement (12-factor).
Voir `.env.example` à la racine du dépôt.
"""

import os
from datetime import timedelta
from pathlib import Path

import environ
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BASE_DIR.parent

env = environ.Env()
environ.Env.read_env(os.path.join(ROOT_DIR, ".env"))  # optionnel

# ---------------------------------------------------------------------------
# Environnement
# ---------------------------------------------------------------------------
ENV = env.str("DJANGO_ENV", default="local").lower()
IS_TEST = ENV == "test"
IS_PRODUCTION = ENV == "production"
DEBUG = env.bool("DEBUG", default=ENV == "local")

SECRET_KEY = env.str("SECRET_KEY", default="")
if IS_PRODUCTION:
    if not SECRET_KEY:
        raise ImproperlyConfigured("SECRET_KEY est obligatoire en production.")
    if DEBUG:
        raise ImproperlyConfigured("DEBUG doit valoir False en production.")
else:
    # Clé de commodité pour le développement uniquement.
    SECRET_KEY = SECRET_KEY or "dev-only-insecure-key-do-not-use-in-production"

ALLOWED_HOSTS = env.list(
    "ALLOWED_HOSTS", default=["localhost", "127.0.0.1", "0.0.0.0", "testserver"]
)
ALLOWED_HOSTS += env.list("EXTRA_ALLOWED_HOSTS", default=[])
if ENV == "local":
    # Le proxy de prévisualisation Arena utilise des sous-domaines éphémères en développement.
    ALLOWED_HOSTS.append(".e2b.app")
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "apps.core",
    "apps.users",
    "apps.organizations",
    "apps.projects",
    "apps.evidences",
    "apps.sync",
    "apps.finance",
    "apps.notifications.apps.NotificationsConfig",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.gzip.GZipMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.RequestIDMiddleware",
    "apps.core.metrics.MetricsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"
AUTH_USER_MODEL = "users.User"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

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
            ],
        },
    }
]

# ---------------------------------------------------------------------------
# Base de données
# ---------------------------------------------------------------------------
USE_SQLITE = env.bool("USE_SQLITE", default=IS_TEST)
if USE_SQLITE:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": env.str("SQLITE_PATH", default=str(BASE_DIR / "db.sqlite3")),
        }
    }
else:
    DATABASES = {
        "default": env.db_url(
            "DATABASE_URL",
            default="postgres://kemta:kemta@db:5432/kemta",
        )
    }
    DATABASES["default"].setdefault("CONN_MAX_AGE", 60)

# ---------------------------------------------------------------------------
# Cache / Redis
# ---------------------------------------------------------------------------
REDIS_URL = env.str("REDIS_URL", default="redis://redis:6379/1")
DASHBOARD_CACHE_TTL_SECONDS = env.int("DASHBOARD_CACHE_TTL_SECONDS", default=30)
if IS_TEST or env.bool("USE_LOCAL_CACHE", default=False):
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "kemta-tests",
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
            "OPTIONS": {"socket_connect_timeout": 2, "socket_timeout": 2},
        }
    }

# ---------------------------------------------------------------------------
# REST framework & JWT
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.users.authentication.KemtaJWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "EXCEPTION_HANDLER": "apps.core.exceptions.kemta_exception_handler",
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.DefaultPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "otp_request": env.str("THROTTLE_OTP_REQUEST", default="20/hour"),
        "password_reset": env.str("THROTTLE_PASSWORD_RESET", default="20/hour"),
        "login": env.str("THROTTLE_LOGIN", default="10/min"),
        "sensitive": env.str("THROTTLE_SENSITIVE", default="60/hour"),
        # Protections par défaut de DRF (par IP pour les anonymes, par utilisateur sinon).
        "anon": env.str("THROTTLE_ANON", default="60/min"),
        "user": env.str("THROTTLE_USER", default="2000/hour"),
    },
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env.int("JWT_ACCESS_MINUTES", default=15)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env.int("JWT_REFRESH_DAYS", default=7)),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

# ---------------------------------------------------------------------------
# Authentification : politique de mot de passe
# ---------------------------------------------------------------------------
PASSWORD_MIN_LENGTH = env.int("PASSWORD_MIN_LENGTH", default=10)
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": PASSWORD_MIN_LENGTH},
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

# ---------------------------------------------------------------------------
# Téléphone, OTP, verrouillage de compte
# ---------------------------------------------------------------------------
PHONE_ALLOWED_REGIONS = env.list("PHONE_ALLOWED_REGIONS", default=["CM"])
OTP_LENGTH = env.int("OTP_LENGTH", default=6)
OTP_TTL_SECONDS = env.int("OTP_TTL_SECONDS", default=300)
OTP_MAX_ATTEMPTS = env.int("OTP_MAX_ATTEMPTS", default=5)
OTP_RESEND_LIMIT_PER_PHONE = env.int("OTP_RESEND_LIMIT_PER_PHONE", default=3)
OTP_RESEND_LIMIT_PER_IP = env.int("OTP_RESEND_LIMIT_PER_IP", default=10)
OTP_RESEND_COOLDOWN_SECONDS = env.int("OTP_RESEND_COOLDOWN_SECONDS", default=60)

LOGIN_MAX_FAILED_ATTEMPTS = env.int("LOGIN_MAX_FAILED_ATTEMPTS", default=5)
LOGIN_LOCK_SECONDS = env.int("LOGIN_LOCK_SECONDS", default=900)

EMAIL_BACKEND_PROVIDER = env.str("EMAIL_BACKEND_PROVIDER", default="console")  # console | smtp
DEFAULT_FROM_EMAIL = env.str("DEFAULT_FROM_EMAIL", default="no-reply@kemta.cm")
EMAIL_HOST = env.str("EMAIL_HOST", default="")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env.str("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env.str("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)

SMS_PROVIDER = (
    env.str("SMS_PROVIDER", default="console").strip().lower()
)  # console | africastalking
SMS_API_KEY = env.str("SMS_API_KEY", default="")
SMS_USERNAME = env.str("SMS_USERNAME", default="")
SMS_API_URL = env.str(
    "SMS_API_URL", default="https://api.africastalking.com/version1/messaging/bulk"
).strip()
SMS_API_TIMEOUT_SECONDS = env.int("SMS_API_TIMEOUT_SECONDS", default=8)
SMS_SENDER_ID = env.str("SMS_SENDER_ID", default="KEMTA").strip()
if IS_PRODUCTION:
    if SMS_PROVIDER not in {"africastalking", "real"}:
        raise ImproperlyConfigured(
            "SMS_PROVIDER doit être configuré sur africastalking en production."
        )
    if not SMS_API_KEY or not SMS_USERNAME or not SMS_SENDER_ID:
        raise ImproperlyConfigured(
            "SMS_API_KEY, SMS_USERNAME et SMS_SENDER_ID sont obligatoires en production."
        )
    if not SMS_API_URL.startswith("https://"):
        raise ImproperlyConfigured("SMS_API_URL doit utiliser HTTPS en production.")

# ---------------------------------------------------------------------------
# Celery
# ---------------------------------------------------------------------------
CELERY_BROKER_URL = env.str("CELERY_BROKER_URL", default="redis://redis:6379/0")
CELERY_TASK_ALWAYS_EAGER = IS_TEST or env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TIMEZONE = "UTC"
CELERY_BEAT_SCHEDULE = {
    "purge-expired-otps": {
        "task": "apps.users.tasks.purge_expired_otps",
        "schedule": timedelta(hours=6),
    },
    "retry-business-event-outbox": {
        "task": "apps.notifications.tasks.retry_pending_business_events",
        "schedule": timedelta(minutes=2),
    },
    "retry-pending-media-scans": {
        "task": "apps.evidences.tasks.retry_pending_media_scans",
        "schedule": timedelta(minutes=5),
    },
    "emit-project-delay-events": {
        "task": "apps.notifications.tasks.emit_project_delay_events",
        "schedule": timedelta(hours=24),
    },
    "purge-old-celery-task-logs": {
        "task": "apps.notifications.tasks.purge_task_logs",
        "schedule": timedelta(days=1),
    },
}

# ---------------------------------------------------------------------------
# Internationalisation
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "fr"
TIME_ZONE = env.str("TIME_ZONE", default="Africa/Douala")
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Fichiers
# ---------------------------------------------------------------------------
MEDIA_STORAGE = env.str("MEDIA_STORAGE", default="local")  # local | s3
MEDIA_URL = env.str("MEDIA_URL", default="/media/")
MEDIA_ROOT = env.str("MEDIA_ROOT", default=str(ROOT_DIR / "var" / "media"))
STATIC_URL = "static/"
STATIC_ROOT = env.str("STATIC_ROOT", default=str(ROOT_DIR / "var" / "static"))

MAX_UPLOAD_SIZE_MB = env.int("MAX_UPLOAD_SIZE_MB", default=10)
MAX_MEDIA_USER_QUOTA_MB = env.int("MAX_MEDIA_USER_QUOTA_MB", default=512)
MAX_MEDIA_PROJECT_QUOTA_MB = env.int("MAX_MEDIA_PROJECT_QUOTA_MB", default=5120)
SIGNED_MEDIA_TOKEN_TTL_SECONDS = env.int("SIGNED_MEDIA_TOKEN_TTL_SECONDS", default=300)
ANTIVIRUS_REQUIRED = env.bool("ANTIVIRUS_REQUIRED", default=IS_PRODUCTION)
CLAMAV_HOST = env.str("CLAMAV_HOST", default="")
CLAMAV_PORT = env.int("CLAMAV_PORT", default=3310)
CLAMAV_TIMEOUT_SECONDS = env.int("CLAMAV_TIMEOUT_SECONDS", default=5)
if IS_PRODUCTION and not ANTIVIRUS_REQUIRED:
    raise ImproperlyConfigured("ANTIVIRUS_REQUIRED doit être True en production.")
if IS_PRODUCTION and not CLAMAV_HOST:
    raise ImproperlyConfigured("CLAMAV_HOST doit désigner le moteur antivirus en production.")

# Preuves terrain (MVP-007 / MVP-008)
# Le contrôle de périmètre refuse (422) une photo prise manifestement hors chantier ; il peut
# être assoupli en exploitation si les relevés GPS de terrain sont imprécis.
EVIDENCE_GEOFENCE_ENFORCE = env.bool("EVIDENCE_GEOFENCE_ENFORCE", default=True)
# En production, les médias sont servis par Nginx après contrôle d'accès (X-Accel-Redirect).
MEDIA_X_ACCEL_REDIRECT = env.bool("MEDIA_X_ACCEL_REDIRECT", default=False)

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])
CORS_ALLOW_CREDENTIALS = True

# ---------------------------------------------------------------------------
# Sécurité
# ---------------------------------------------------------------------------
if IS_PRODUCTION:
    SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
    SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=31536000)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"
else:
    SECURE_SSL_REDIRECT = False

# ---------------------------------------------------------------------------
# Logs structurés
# ---------------------------------------------------------------------------
LOG_LEVEL = env.str("LOG_LEVEL", default="INFO" if not DEBUG else "DEBUG")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {"()": "apps.core.logging_utils.JsonFormatter"},
        "plain": {"format": "%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s"},
    },
    "filters": {
        "request_id": {"()": "apps.core.logging_utils.RequestIDFilter"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json" if IS_PRODUCTION else "plain",
            "filters": ["request_id"],
        },
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "kemta": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
        "django.security": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

# Outils de développement (boîte de réception SMS/email) : jamais en production.
ENABLE_DEV_OUTBOX = env.bool("ENABLE_DEV_OUTBOX", default=DEBUG and not IS_PRODUCTION)

APP_VERSION = env.str("APP_VERSION", default="0.1.0")
DEFAULT_SIGNUP_ROLE = env.str("DEFAULT_SIGNUP_ROLE", default="PROJECT_OWNER")
