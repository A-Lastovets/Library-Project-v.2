from celery.schedules import crontab

from app.services.celery import celery_app

# Налаштування періодичних завдань у Celery Beat
celery_app.conf.update(
    timezone="UTC",
    beat_schedule={
        "cancel_expired_reservations": {
            "task": "app.services.email_tasks.check_and_cancel_expired_reservations",
            "schedule": crontab(hour=0, minute=0),  # Виконувати щодня опівночі
        },
        "send_due_date_reminders": {
            "task": "app.services.email_tasks.check_and_send_return_reminders",
            "schedule": crontab(hour=8, minute=0),  # Виконувати щодня о 8:00 ранку
        },
    },
)
