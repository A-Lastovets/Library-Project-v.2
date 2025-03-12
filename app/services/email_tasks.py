import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload

from app.dependencies.database import get_db
from app.models.book import Book, BookStatus
from app.models.reservation import Reservation, ReservationStatus
from app.models.user import User
from app.services.celery import celery_app
from app.services.email_service import (
    send_email,
    send_reservation_cancellation_email,
    send_return_reminder_email,
)

logger = logging.getLogger(__name__)


def get_db_session() -> AsyncSession:
    """Отримує сесію БД для Celery-завдань."""
    return next(get_db())


@celery_app.task(bind=True, max_retries=3)
def send_password_reset_email(self, email: str, reset_link: str):
    """📩 Надсилає лист для скидання пароля."""
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
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Використовуємо create_task, якщо Celery вже працює в event loop
            loop.create_task(send_email(email, subject, message, html=True))
        else:
            # Якщо немає активного event loop, запускаємо новий
            asyncio.run(send_email(email, subject, message, html=True))

        logger.info(f"Password reset email sent to {email}")
    except Exception as e:
        logger.error(f"Error sending password reset email to {email}: {e}")
        raise self.retry(exc=e, countdown=10)  # Повторна спроба через 10 сек


@celery_app.task
def check_expired_reservations():
    """🛑 Перевіряє бронювання, які прострочені (минуло 5 днів), і скасовує їх."""
    db: AsyncSession = get_db_session()
    now = datetime.now()

    result = db.execute(
        select(Reservation)
        .options(
            joinedload(Reservation.book),
            joinedload(Reservation.user),
        )  # Завантажуємо пов'язані об'єкти
        .where(
            Reservation.expires_at < now,
            Reservation.status == ReservationStatus.PENDING,
        ),
    )

    expired_reservations = result.scalars().all()

    for reservation in expired_reservations:
        book: Book = reservation.book
        user: User = reservation.user

        reservation.status = ReservationStatus.CANCELLED
        book.status = BookStatus.AVAILABLE

        # Викликаємо відправку email без asyncio.run()
        asyncio.run(send_reservation_cancellation_email(user.email, book.title))

    db.commit()


@celery_app.task
def send_return_reminders():
    """📩 Надсилає нагадування про повернення книг за 3 дні до дедлайну."""
    db: AsyncSession = get_db_session()
    now = datetime.now()
    reminder_date = now + timedelta(days=3)

    result = db.execute(
        select(Reservation)
        .options(
            joinedload(Reservation.book),
            joinedload(Reservation.user),
        )  # Завантажуємо зв'язані об'єкти
        .where(
            Reservation.expires_at == reminder_date,
            Reservation.status == ReservationStatus.CONFIRMED,
        ),
    )
    reservations = result.scalars().all()

    for reservation in reservations:
        book: Book = reservation.book
        user: User = reservation.user

        asyncio.run(
            send_return_reminder_email(
                user.email,
                book.title,
                reservation.expires_at.strftime("%Y-%m-%d"),
            ),
        )

    db.commit()
