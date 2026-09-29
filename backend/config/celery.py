import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("kemta")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# Les tâches périodiques sont déclarées dans `config.settings.CELERY_BEAT_SCHEDULE`.
