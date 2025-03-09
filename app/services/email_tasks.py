import logging

from app.config import config
from app.services.celery import Celery
from app.services.email_service import send_email

celery = Celery("email_tasks", broker=config.CELERY_BROKER_URL)

logger = logging.getLogger(__name__)


@celery.task(bind=True, max_retries=3)
def send_password_reset_email(self, email: str, reset_link: str):
    """Надсилає лист для скидання пароля."""
    subject = "Password Reset Request"
    message = f"""
    <html>
        <body>
            <p>Hello,</p>
            <p>You requested a password reset. Click the link below to reset your password:</p>
            <p><a href="{reset_link}" style="font-size: 16px; color: #007bff; text-decoration: none;">Reset Password</a></p>
            <p>If you did not request this, please ignore this email.</p>
        </body>
    </html>
    """
    try:
        send_email(email, subject, message, html=True)
        logger.info(f"Password reset email sent to {email}")
    except Exception as e:
        logger.error(f"Error sending password reset email to {email}: {e}")
        raise self.retry(exc=e, countdown=10)  # Повторна спроба через 10 сек
