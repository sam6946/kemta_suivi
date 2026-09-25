"""Réglages dédiés aux tests : aucune infrastructure externe requise."""

from .settings import *  # noqa: F401,F403

ENV = "test"  # noqa: F811
DEBUG = False
DJANGO_ENV = "test"

SECRET_KEY = "test-only-insecure-key"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "kemta-pytest",
    }
}

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

SMS_PROVIDER = "console"

# Les tests exercent explicitement les outils de développement (boîte SMS/email) ;
# la production les désactive par défaut (voir `config/settings.py`).
ENABLE_DEV_OUTBOX = True

# Les mots de passe de test restent valides vis-à-vis des validateurs.
PASSWORD_MIN_LENGTH = 10

# Accélération des tests (les hashes sont volontairement rapides en test).
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
