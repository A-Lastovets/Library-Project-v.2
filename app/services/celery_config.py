from celery import Celery
from celery.schedules import crontab

from app.config import config

celery_app = Celery("tasks")

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
    beat_schedule={
        "check_all_reservations": {
            "task": "app.services.email_tasks.check_and_cleanup_reservations",
            "schedule": crontab(minute=0, hour=0),
        },
        "send-return-reminders": {
            "task": "app.services.email_tasks.check_and_send_return_reminders",
            "schedule": crontab(minute=0, hour="*/2"),
        },
        "check-wishlist-availability-every-5-minutes": {
            "task": "app.services.email_tasks.check_wishlist_availability",
            "schedule": crontab(minute="*/60"),
        },
    },
)
celery_app.autodiscover_tasks(["app.services.email_tasks"])
