from datetime import datetime, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy import exists, func, not_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from app.dependencies.database import get_db
from app.models.book import Book, BookStatus
from app.models.reservation import Reservation, ReservationStatus
from app.models.user import User, UserRole
from app.schemas.schemas import BookShortResponse
from app.dependencies.cache import redis_client
import json

router = APIRouter(prefix="/stats", tags=["Statistics"])


@router.get("")
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
        select(func.unnest(Book.category).label("cat"), func.count()).group_by("cat"),
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


@router.get("/month-top", response_model=list[BookShortResponse])
async def get_month_top_books(db: AsyncSession = Depends(get_db)):
    redis = await redis_client.get_redis()
    cache_key = "month_top_books"
    cached_data = await redis.get(cache_key)

    if cached_data:
        return json.loads(cached_data)

    now = datetime.now()
    month_ago = now - timedelta(days=30)

    result = await db.execute(
        select(Book)
        .join(Reservation)
        .where(
            Reservation.status == ReservationStatus.COMPLETED,
            Reservation.expires_at >= month_ago,
        )
        .distinct()
        .limit(10)
    )
    completed_books = result.scalars().all()

    if len(completed_books) < 10:
        exclude_ids = [book.id for book in completed_books]
        extra_result = await db.execute(
            select(Book)
            .where(
                ~Book.id.in_(exclude_ids),
                Book.status == BookStatus.AVAILABLE,
            )
            .order_by(func.random())
            .limit(10 - len(completed_books))
        )
        completed_books += extra_result.scalars().all()

    serialized_books = [
        BookShortResponse.model_validate(book) for book in completed_books
    ]
    await redis.set(
        cache_key,
        json.dumps([book.model_dump() for book in serialized_books]),
        ex=600,
    )

    return serialized_books
