from fastapi import APIRouter, Depends
from sqlalchemy import exists, func, not_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.database import get_db
from app.models.book import Book, BookStatus
from app.models.reservation import Reservation, ReservationStatus
from app.models.user import User, UserRole

router = APIRouter(prefix="/stats", tags=["Statistics"])


@router.get("/")
async def get_statistics(db: AsyncSession = Depends(get_db)):
    # Активні читачі (мають хоча б одну резервацію з певним статусом)
    active_users = await db.scalar(
        select(func.count())
        .select_from(User)
        .where(
            User.role == UserRole.READER,
            exists().where(
                Reservation.user_id == User.id,
                Reservation.status.in_(
                    [
                        ReservationStatus.ACTIVE,
                        ReservationStatus.COMPLETED,
                        ReservationStatus.EXPIRED,
                    ],
                ),
            ),
        ),
    )

    # Неактивні читачі (не мають жодної резервації)
    unactive_users = await db.scalar(
        select(func.count())
        .select_from(User)
        .where(
            User.role == UserRole.READER,
            not_(exists().where(Reservation.user_id == User.id)),
        ),
    )

    # Підрахунок total_readers вручну
    total_readers = active_users + unactive_users

    # Кількість заблокованих користувачів
    blocked_users = await db.scalar(select(func.count()).where(User.is_blocked))

    # Загальна кількість книжок
    total_books = await db.scalar(select(func.count()).select_from(Book))

    # Кількість книг по статусах
    available_books = await db.scalar(
        select(func.count()).where(Book.status == BookStatus.AVAILABLE),
    )
    reserved_books = await db.scalar(
        select(func.count()).where(Book.status == BookStatus.RESERVED),
    )
    checked_out_books = await db.scalar(
        select(func.count()).where(Book.status == BookStatus.CHECKED_OUT),
    )
    overdue_books = await db.scalar(
        select(func.count()).where(Book.status == BookStatus.OVERDUE),
    )

    # Кількість книжок за мовами
    books_by_language_q = await db.execute(
        select(Book.language, func.count()).group_by(Book.language),
    )
    books_by_language = dict(books_by_language_q.all())

    # Кількість книжок за категоріями
    books_by_category_q = await db.execute(
        select(Book.category, func.count()).group_by(Book.category),
    )
    books_by_category = dict(books_by_category_q.all())

    # Кількість повернутих книг — completed
    returned_books = await db.scalar(
        select(func.count()).where(Reservation.status == ReservationStatus.COMPLETED),
    )

    return {
        "total_readers": total_readers,
        "active_users": active_users,
        "unactive_users": unactive_users,
        "blocked_users": blocked_users,
        "total_books": total_books,
        "available_books": available_books,
        "checked_out_books": checked_out_books,
        "reserved_books": reserved_books,
        "overdue_books": overdue_books,
        "books_by_language": books_by_language,
        "books_by_category": books_by_category,
        "returned_books": returned_books,
    }
