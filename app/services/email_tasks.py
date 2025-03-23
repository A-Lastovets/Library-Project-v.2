import asyncio
import logging
from datetime import datetime, timedelta
from typing import List

from asgiref.sync import async_to_sync
from sqlalchemy.engine import Result
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload

from app.dependencies.database import SessionLocal
from app.models.book import BookStatus
from app.models.reservation import Reservation, ReservationStatus
from app.models.user import User
from app.services.celery_config import celery_app
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
    subject = "✅ Ваше бронювання прийнято!"

    body = f"""
    <html>
        <body>
            <h2 style="color: #4CAF50;">Ми отримали ваше бронювання!</h2>
            <p>Дякуємо за користування нашою бібліотекою. Ваше бронювання книги прийнято і наразі очікує на підтвердження адміністратором.</p>
            <hr>
            <h3>📚 {book["title"]}</h3>
            <p><strong>✍️ Автор:</strong> {book["author"]}</p>
            <p><strong>📖 Жанр:</strong> {book["category"]}</p>
            <p><strong>🌍 Мова:</strong> {book["language"]}</p>
            <p><strong>📅 Рік видання:</strong> {book["year"]}</p>
            <p><strong>📝 Опис:</strong> {book["description"]}</p>
            <hr>
            <p>Будь ласка, очікуйте на підтвердження адміністратором.
            Як тільки бронювання буде підтверджене, ви отримаєте додатковий лист із деталями.</p>
            <br>
            <p>📚 Гарного дня!<br>Ваша бібліотека</p>
        </body>
    </html>
    """

    loop = asyncio.get_event_loop()
    loop.create_task(send_email(email, subject, body, html=True))


@celery_app.task
def send_reservation_confirmation_email(email: str, book: dict, expires_at: str):
    """📩 Лист після бронювання книги користувачем"""
    subject = "✅ Ваше бронювання книги підтверджено!"

    body = f"""
    <html>
        <body>
            <h2 style="color: #4CAF50;">Ваше бронювання підтверджено!</h2>
            <p>Дякуємо, що скористалися нашою бібліотекою. Ви успішно забронювали книгу:</p>
            <hr>
            <h3>📚 {book["title"]}</h3>
            <p><strong>✍️ Автор:</strong> {book["author"]}</p>
            <p><strong>📖 Жанр:</strong> {book["category"]}</p>
            <p><strong>🌍 Мова:</strong> {book["language"]}</p>
            <p><strong>📅 Рік видання:</strong> {book["year"]}</p>
            <p><strong>📝 Опис:</strong> {book["description"]}</p>
            <hr>
            <p><strong>⏳ Бронювання дійсне до:</strong> {expires_at}</p>
            <p>Будь ласка, заберіть книгу до цієї дати. Якщо ви не встигнете, бронювання буде автоматично скасовано.</p>
            <br>
            <p>📚 Гарного читання!<br>Ваша бібліотека</p>
        </body>
    </html>
    """

    loop = asyncio.get_event_loop()
    loop.create_task(send_email(email, subject, body, html=True))


@celery_app.task
def send_reservation_cancelled_email(email: str, book_title: str):
    """📩 Лист після скасування бронювання"""
    subject = "⛔ Ваше бронювання скасовано"

    body = f"""
    <html>
        <body>
            <h2 style="color: #D32F2F;">⛔ Ваше бронювання було скасовано</h2>
            <p>Шановний читачу,</p>
            <p>Ми хочемо повідомити, що бронювання наступної книги було скасовано:</p>
            <hr>
            <h3>📖 {book_title}</h3>
            <p>🔹 <strong>Статус бронювання:</strong> Скасовано</p>
            <hr>
            <p>Можливі причини скасування:</p>
            <ul>
                <li>⏳ Ви вирішили самостійно відмінити бронювання.</li>
                <li>📅 Адміністратор скасував бронювання з інших причин.</li>
            </ul>
            <p>Якщо ви все ще бажаєте отримати цю книгу, ви можете зробити нове бронювання через наш каталог.</p>
            <br>
            <p>📚 Якщо у вас є запитання – звертайтеся до бібліотекарів.</p>
            <br>
            <p>📖 З повагою,<br><strong>Ваша бібліотека</strong></p>
        </body>
    </html>
    """

    loop = asyncio.get_event_loop()
    loop.create_task(send_email(email, subject, body, html=True))


@celery_app.task
def send_book_checked_out_email(email: str, book_title: str, due_date: str):
    """📩 Лист після отримання книги (нагадування про 14 днів)"""
    subject = "📖 Ви отримали книгу – не забудьте повернути вчасно!"

    body = f"""
    <html>
        <body>
            <h2 style="color: #4CAF50;">📖 Ви отримали книгу!</h2>
            <p>Шановний читачу,</p>
            <p>Ви забрали книгу з бібліотеки, і тепер вона у вашому розпорядженні. Будь ласка, ознайомтеся з важливою інформацією:</p>
            <hr>
            <h3>📚 {book_title}</h3>
            <p>📅 <strong>Термін повернення:</strong> {due_date}</p>
            <hr>
            <p>Будь ласка, поверніть книгу до зазначеного терміну, щоб інші читачі також могли нею скористатися.</p>
            <p>Якщо вам потрібно більше часу, зверніться до бібліотекаря для продовження терміну користування.</p>
            <br>
            <p>📚 Бажаємо вам приємного читання!</p>
            <br>
            <p>📖 З повагою,<br><strong>Ваша бібліотека</strong></p>
        </body>
    </html>
    """

    loop = asyncio.get_event_loop()
    loop.create_task(send_email(email, subject, body, html=True))


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
    subject = "⛔ Ваше бронювання скасовано"

    body = f"""
    <html>
        <body>
            <h2 style="color: #D32F2F;">⛔ Ваше бронювання було автоматично скасовано</h2>
            <p>Шановний читачу,</p>
            <p>Ми змушені повідомити, що ваше бронювання книги було скасовано, оскільки ви не забрали її вчасно.</p>
            <hr>
            <h3>📖 {book_title}</h3>
            <p>⏳ <strong>Термін бронювання закінчився</strong></p>
            <hr>
            <p>Якщо ви все ще зацікавлені в цій книзі, ви можете забронювати її знову через наш каталог.</p>
            <p>Будь ласка, звертайтеся до бібліотекарів, якщо у вас виникли запитання.</p>
            <br>
            <p>📚 З повагою,<br><strong>Ваша бібліотека</strong></p>
        </body>
    </html>
    """

    loop = asyncio.get_event_loop()
    loop.create_task(send_email(user_email, subject, body, html=True))


@celery_app.task
def send_return_reminder_email(user_email: str, book_title: str, due_date: str):
    """📩 Лист-нагадування за 3 дні до повернення книги"""
    subject = "📅 Нагадування про повернення книги"

    body = f"""
    <html>
        <body>
            <h2 style="color: #FFA500;">📅 Наближається термін повернення книги!</h2>
            <p>Шановний читачу,</p>
            <p>Нагадуємо, що термін повернення вашої книги спливає зовсім скоро.</p>
            <hr>
            <h3>📖 {book_title}</h3>
            <p>⏳ <strong>Термін повернення:</strong> {due_date}</p>
            <hr>
            <p>Будь ласка, поверніть книгу вчасно, щоб уникнути прострочення.</p>
            <p>Якщо вам потрібен додатковий час, зверніться до бібліотеки для продовження терміну.</p>
            <br>
            <p>📚 З повагою,<br><strong>Ваша бібліотека</strong></p>
        </body>
    </html>
    """

    loop = asyncio.get_event_loop()
    loop.create_task(send_email(user_email, subject, body, html=True))


@celery_app.task
def send_welcome_email(user_email: str, user_name: str):
    """📩 Лист після реєстрації користувача"""
    subject = "🎉 Вітаємо у нашій бібліотеці!"

    body = f"""
    <html>
        <body>
            <h2 style="color: #4CAF50;">📚 Ласкаво просимо до бібліотеки!</h2>
            <p>Шановний(а) {user_name},</p>
            <p>Ми раді вітати вас у нашій бібліотеці! Тут ви знайдете широкий вибір книг на будь-який смак.</p>
            <hr>
            <h3>📖 Що доступно в нашій бібліотеці?</h3>
            <ul>
                <li>📚 Художня та наукова література</li>
                <li>📘 Класичні та сучасні твори</li>
                <li>🔍 Рідкісні книги та архівні матеріали</li>
                <li>📅 Можливість бронювання книг онлайн</li>
            </ul>
            <hr>
            <p>✨ Ми впевнені, що серед наших книг ви знайдете щось цікаве для себе!</p>
            <p>🌟 Почніть свою подорож у світ знань прямо зараз – заходьте на сайт та обирайте книги!</p>
            <br>
            <p>📚 З повагою,<br><strong>Команда вашої бібліотеки</strong></p>
        </body>
    </html>
    """

    loop = asyncio.get_event_loop()
    loop.create_task(send_email(user_email, subject, body, html=True))


@celery_app.task
def send_user_blocked_email(email: str, first_name: str):
    subject = "🚫 Ваш акаунт заблоковано"
    body = f"""
    <html>
        <body>
            <h2 style="color: #D32F2F;">🚫 Акаунт тимчасово заблоковано</h2>
            <p>Шановний {first_name},</p>
            <p>Ваш акаунт був тимчасово заблокований через одну з наступних причин:</p>
            <ul>
                <li>📚 Ви маєте кілька книг з простроченим терміном повернення.</li>
                <li>🔒 Підозріла активність з вашого акаунта.</li>
            </ul>
            <hr>
            <p>Щоб відновити доступ, будь ласка, поверніть прострочені книги або зверніться до адміністратора бібліотеки.</p>
            <p>Якщо у вас виникли питання, ми будемо раді допомогти.</p>
            <br>
            <p>📚 З повагою,<br><strong>Ваша бібліотека</strong></p>
        </body>
    </html>
    """

    loop = asyncio.get_event_loop()
    loop.create_task(send_email(email, subject, body, html=True))


@celery_app.task
def send_user_unblocked_email(user_email: str, first_name: str):
    """📩 Лист після розблокування користувача бібліотекарем"""
    subject = "🔓 Ваш акаунт розблоковано!"

    body = f"""
    <html>
        <body>
            <h2 style="color: #4CAF50;">🔓 Доступ до акаунта відновлено</h2>
            <p>Шановний {first_name},</p>
            <p>Ми раді повідомити, що ваш акаунт було успішно <strong>розблоковано</strong>.</p>
            <hr>
            <p>Тепер ви знову можете:</p>
            <ul>
                <li>📚 Бронювати книги</li>
                <li>📖 Отримувати книги у тимчасове користування</li>
                <li>🕓 Переглядати історію ваших бронювань</li>
            </ul>
            <hr>
            <p>Будь ласка, дотримуйтеся правил користування бібліотекою, щоб уникнути блокування у майбутньому.</p>
            <br>
            <p>📚 З повагою,<br><strong>Ваша бібліотека</strong></p>
        </body>
    </html>
    """

    loop = asyncio.get_event_loop()
    loop.create_task(send_email(user_email, subject, body, html=True))


@celery_app.task
def check_and_send_return_reminders():
    print("✅ check_and_send_return_reminders started!")

    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    loop.run_until_complete(_check_and_send_return_reminders())


async def _check_and_send_return_reminders():
    async with SessionLocal() as db:
        now = datetime.now()
        reminder_date = now + timedelta(days=3)

        result = await db.execute(
            select(Reservation)
            .options(joinedload(Reservation.book), joinedload(Reservation.user))
            .where(
                Reservation.expires_at.between(
                    reminder_date - timedelta(seconds=30),
                    reminder_date + timedelta(seconds=30),
                ),
                Reservation.status == ReservationStatus.ACTIVE,
            ),
        )
        reservations = result.scalars().all()
        print(f"🔔 Знайдено {len(reservations)} резервацій для нагадування")

        for reservation in reservations:
            book = reservation.book
            user = reservation.user

            send_return_reminder_email.delay(
                user.email,
                book.title,
                reservation.expires_at.strftime("%Y-%m-%d"),
            )

        await db.commit()


@celery_app.task
def check_and_cleanup_reservations():
    print("✅check_and_cleanup_reservations started!")

    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    loop.run_until_complete(_check_and_cleanup_reservations())


async def _check_and_cleanup_reservations():
    async with SessionLocal() as db:
        now = datetime.now()

        # 1. Не забрали книгу (CONFIRMED → CANCELLED)
        result: Result = await db.execute(
            select(Reservation)
            .options(joinedload(Reservation.book), joinedload(Reservation.user))
            .where(
                Reservation.expires_at < now,
                Reservation.status == ReservationStatus.CONFIRMED,
            ),
        )

        to_cancel: List[Reservation] = result.scalars().all()
        print(f"[CLEANUP] 🔔 Знайдено {len(to_cancel)} резервацій для скасування")

        for r in to_cancel:
            r.status = ReservationStatus.CANCELLED
            r.book.status = BookStatus.AVAILABLE
            await db.flush()
            send_reservation_cancellation_email.delay(r.user.email, r.book.title)

        # 2. Не повернули книгу (ACTIVE → EXPIRED, OVERDUE)
        result2: Result = await db.execute(
            select(Reservation)
            .options(joinedload(Reservation.book), joinedload(Reservation.user))
            .where(
                Reservation.expires_at < now,
                Reservation.status == ReservationStatus.ACTIVE,
            ),
        )
        to_expire: List[Reservation] = result2.scalars().all()

        for r in to_expire:
            r.status = ReservationStatus.EXPIRED
            r.book.status = BookStatus.OVERDUE
            await db.flush()
            logger.info(f"[OVERDUE] Book '{r.book.title}' → user: {r.user.email}")

        # 3. Блокуємо користувачів з 2+ OVERDUE
        result3: Result = await db.execute(
            select(User).options(
                joinedload(User.reservations).joinedload(Reservation.book),
            ),
        )
        users: List[User] = result3.unique().scalars().all()

        for user in users:
            count = sum(
                1
                for r in user.reservations
                if r.book and r.book.status == BookStatus.OVERDUE
            )
            if count >= 2 and not user.is_blocked:
                user.is_blocked = True
                await db.flush()
                logger.warning(
                    f"[BLOCKED] {user.email} через {count} прострочених книг",
                )
                send_user_blocked_email.delay(user.email, count)

        await db.commit()
