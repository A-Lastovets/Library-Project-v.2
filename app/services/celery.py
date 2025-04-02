from celery import Celery

from app.config import config

celery_app = Celery("tasks")

# Конфігурація Celery
celery_app.conf.update(
    broker_url=config.CELERY_BROKER_URL,
    result_backend=(
        config.CELERY_RESULT_BACKEND
        if hasattr(config, "CELERY_RESULT_BACKEND")
        else None
    ),
    task_routes={"app.tasks.*": {"queue": "default"}},
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
)

celery_app.autodiscover_tasks(["app.services"])

import app.services.celery_beat
