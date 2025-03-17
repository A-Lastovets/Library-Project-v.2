import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy.future import select
from sqlalchemy.orm import joinedload

from app.dependencies.database import SessionLocal
from app.models.book import BookStatus
from app.models.reservation import Reservation, ReservationStatus
from app.schemas.schemas import BookResponse
from app.services.celery import celery_app
from app.services.email_service import send_email

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3)
def send_password_reset_email(self, email: str, reset_link: str):
    """Надсилає лист для скидання пароля."""
    subject = "🔑 Запит на скидання пароля"

    body = f"""
    <html>
        <body>
            <h2 style="color: #4CAF50;">🔑 Скидання пароля</h2>
            <p>Вітаємо!</p>
            <p>Ви надіслали запит на скидання пароля. Натисніть на посилання нижче, щоб встановити новий пароль:</p>
            <p>
                <a href="{reset_link}" style="font-size: 16px; color: #007bff; text-decoration: none;">
                    🔗 Скинути пароль
                </a>
            </p>
            <p>Якщо ви не надсилали цей запит, просто проігноруйте цей лист.</p>
            <br>
            <p>З найкращими побажаннями, <br>Ваша бібліотека</p>
        </body>
    </html>
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Використовуємо create_task, якщо Celery вже працює в event loop
            loop.create_task(send_email(email, subject, body, html=True))
        else:
            # Якщо немає активного event loop, запускаємо новий
            asyncio.run(send_email(email, subject, body, html=True))

        logger.info(f"Password reset email sent to {email}")
    except Exception as e:
        logger.error(f"Error sending password reset email to {email}: {e}")
        raise self.retry(exc=e, countdown=10)  # Повторна спроба через 10 сек


@celery_app.task
def send_reservation_email(email: str, book: dict, expires_at: str):
    """Лист після бронювання книги користувачем"""
    subject = "Ваше бронювання прийнято!"

    body = f"""
    <html>
        <body>
            <h2 style="color: #4CAF50;">Ми отримали ваше бронювання!</h2>
            <p>Дякуємо за користування нашою бібліотекою. Ваше бронювання книги прийнято і наразі очікує на підтвердження адміністратором.</p>
            <hr>
            <h3>{book["title"]}</h3>
            <p><strong>Автор:</strong> {book["author"]}</p>
            <p><strong>Жанр:</strong> {book["category"]}</p>
            <p><strong>Мова:</strong> {book["language"]}</p>
            <p><strong>Рік видання:</strong> {book["year"]}</p>
            <p><strong>Опис:</strong> {book["description"]}</p>
            <hr>
            <p><strong>Бронювання дійсне до:</strong> {expires_at}</p>
            <p>Будь ласка, очікуйте на підтвердження адміністратором.
            Як тільки бронювання буде підтверджене, ви отримаєте додатковий лист із деталями.</p>
            <br>
            <p>Гарного дня!<br>Ваша бібліотека</p>
        </body>
    </html>
    """

    loop = asyncio.get_event_loop()
    loop.create_task(send_email(email, subject, body, html=True))


@celery_app.task
def send_reservation_confirmation_email(email: str, book: dict, expires_at: str):
    """📩 Лист після бронювання книги користувачем"""
    subject = "Ваше бронювання книги підтверджено!"

    body = f"""
    <html>
        <body>
            <h2 style="color: #4CAF50;">Ваше бронювання підтверджено!</h2>
            <p>Дякуємо, що скористалися нашою бібліотекою. Ви успішно забронювали книгу:</p>
            <hr>
            <h3>{book["title"]}</h3>
            <p><strong>Автор:</strong> {book["author"]}</p>
            <p><strong>Жанр:</strong> {book["category"]}</p>
            <p><strong>Мова:</strong> {book["language"]}</p>
            <p><strong>Рік видання:</strong> {book["year"]}</p>
            <p><strong>Опис:</strong> {book["description"]}</p>
            <hr>
            <p><strong>Бронювання дійсне до:</strong> {expires_at}</p>
            <p>Будь ласка, заберіть книгу до цієї дати. Якщо ви не встигнете, бронювання буде автоматично скасовано.</p>
            <br>
            <p>Гарного читання!<br>Ваша бібліотека</p>
        </body>
    </html>
    """

    loop = asyncio.get_event_loop()
    loop.create_task(send_email(email, subject, body, html=True))


@celery_app.task
def send_reservation_cancelled_email(email: str, book_title: str):
    """📩 Лист після скасування бронювання"""
    subject = "Бронювання скасовано"
    body = f"Ваше бронювання книги '{book_title}' було скасовано."

    loop = asyncio.get_event_loop()
    loop.create_task(send_email(email, subject, body))


@celery_app.task
def send_book_checked_out_email(email: str, book_title: str, due_date: str):
    """📩 Лист після отримання книги (нагадування про 14 днів)"""
    subject = "Ви отримали книгу"
    body = f"Ви забрали книгу '{book_title}'. Термін повернення — {due_date}. Не забудьте повернути її вчасно!"

    loop = asyncio.get_event_loop()
    loop.create_task(send_email(email, subject, body))


@celery_app.task
def send_thank_you_email(user_email: str, book: dict):
    """📩 Лист після повернення книги"""
    subject = "📚 Дякуємо за повернення книги!"

    body = f"""
    <html>
        <body>
            <h2 style="color: #4CAF50;">📖 Дякуємо за повернення книги!</h2>
            <p>Ваша книга успішно повернена до бібліотеки. Ми цінуємо вашу відповідальність і сподіваємося, що ви отримали задоволення від читання.</p>
            <hr>
            <h3>📚 {book["title"]}</h3>
            <p><strong>Автор:</strong> {book["author"]}</p>
            <p><strong>Жанр:</strong> {book["category"]}</p>
            <p><strong>Мова:</strong> {book["language"]}</p>
            <p><strong>Рік видання:</strong> {book["year"]}</p>
            <p><strong>Опис:</strong> {book["description"]}</p>
            <hr>
            <p>✨ Ми завжди раді бачити вас у нашій бібліотеці!</p>
            <p>📖 Не забудьте заглянути до нас за новими книжками.</p>
            <br>
            <p>📚 З повагою,<br><strong>Ваша бібліотека</strong></p>
        </body>
    </html>
    """

    loop = asyncio.get_event_loop()
    loop.create_task(send_email(user_email, subject, body, html=True))


@celery_app.task
def send_reservation_cancellation_email(user_email: str, book_title: str):
    """📩 Лист після автоматичного скасування бронювання"""
    subject = "Бронювання автоматично скасовано"
    body = f"Ваше бронювання книги '{book_title}' було автоматично скасовано, оскільки ви не забрали її вчасно."

    loop = asyncio.get_event_loop()
    loop.create_task(send_email(user_email, subject, body))


@celery_app.task
def send_return_reminder_email(user_email: str, book_title: str, due_date: str):
    """📩 Лист-нагадування за 3 дні до повернення книги"""
    subject = "Нагадування про повернення книги"
    body = f"Нагадуємо, що термін повернення книги '{book_title}' закінчується {due_date}. Будь ласка, поверніть її вчасно!"

    loop = asyncio.get_event_loop()
    loop.create_task(send_email(user_email, subject, body))


@celery_app.task
def check_and_cancel_expired_reservations():
    """📌 Перевіряє прострочені бронювання (не забрали за 5 днів) та скасовує їх."""

    async def task():
        async with SessionLocal() as db:
            now = datetime.now()

            result = await db.execute(
                select(Reservation)
                .options(joinedload(Reservation.book), joinedload(Reservation.user))
                .where(
                    Reservation.expires_at < now,
                    Reservation.status == ReservationStatus.CONFIRMED,
                ),
            )
            expired_reservations = result.scalars().all()

            for reservation in expired_reservations:
                book = reservation.book
                user = reservation.user

                reservation.status = ReservationStatus.CANCELLED
                book.status = BookStatus.AVAILABLE

                # Надсилаємо e-mail
                send_reservation_cancellation_email.delay(user.email, book.title)

            await db.commit()

    loop = asyncio.get_event_loop()
    loop.create_task(task())


@celery_app.task
def check_and_send_return_reminders():
    """📌 Надсилає нагадування за 3 дні до закінчення терміну користування книгою."""

    async def task():
        async with SessionLocal() as db:
            now = datetime.now()
            reminder_date = now + timedelta(days=3)

            result = await db.execute(
                select(Reservation)
                .options(joinedload(Reservation.book), joinedload(Reservation.user))
                .where(
                    Reservation.expires_at == reminder_date,
                    Reservation.status == ReservationStatus.CONFIRMED,
                ),
            )
            reservations = result.scalars().all()

            for reservation in reservations:
                book = reservation.book
                user = reservation.user

                send_return_reminder_email.delay(
                    user.email,
                    book.title,
                    reservation.expires_at.strftime("%Y-%m-%d"),
                )

            await db.commit()

    loop = asyncio.get_event_loop()
    loop.create_task(task())
