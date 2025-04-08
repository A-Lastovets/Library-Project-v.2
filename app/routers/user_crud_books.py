from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload
from sqlalchemy.sql import func

from app.dependencies.database import get_db
from app.exceptions.pagination import paginate_response
from app.exceptions.serialization import serialize_book_with_reservation
from app.exceptions.subquery_reserv import get_latest_reservation_alias
from app.models.book import Book, BookStatus
from app.models.reservation import Reservation, ReservationStatus
from app.models.wishlist import Wishlist
from app.schemas.schemas import (
    ReservationResponse,
    WishlistAddRequest,
    WishlistItemResponse,
)
from app.services.user_service import get_current_user_id

router = APIRouter(prefix="/books", tags=["User Books"])


@router.get("/user/status", response_model=dict)
async def get_books_by_status_user(
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
    status: Optional[Literal["checked_out", "overdue"]] = Query(
        None,
        description="Фільтр за статусом книги (checked_out, overdue)",
    ),
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=100),
):
    allowed_statuses = [BookStatus.CHECKED_OUT, BookStatus.OVERDUE]

    if status and status not in allowed_statuses:
        raise HTTPException(
            status_code=400,
            detail="Only 'CHECKED_OUT' and 'OVERDUE' statuses are allowed for users.",
        )

    r_alias, subquery = get_latest_reservation_alias()

    base_query = (
        select(Book, r_alias)
        .join(r_alias, Book.id == r_alias.book_id)
        .join(
            subquery,
            (subquery.c.book_id == r_alias.book_id)
            & (subquery.c.latest_created == r_alias.created_at),
        )
        .where(r_alias.user_id == user_id)
    )

    if status:
        base_query = base_query.where(Book.status == status)
    else:
        base_query = base_query.where(Book.status.in_(allowed_statuses))

    total_books = await db.scalar(
        select(func.count()).select_from(base_query.subquery()),
    )
    result = await db.execute(
        base_query.order_by(Book.created_at.desc())
        .limit(per_page)
        .offset((page - 1) * per_page),
    )

    books = [
        serialize_book_with_reservation(book, reservation)
        for book, reservation in result.all()
    ]

    return paginate_response(total_books, page, per_page, books)


@router.get("/user/current", response_model=dict)
async def get_current_books_user(
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
    status: Optional[Literal["checked_out", "overdue"]] = Query(
        None,
        description="Фільтр за статусом книги (checked_out, overdue)",
    ),
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=100),
):
    allowed_statuses = [BookStatus.CHECKED_OUT, BookStatus.OVERDUE]

    if status and status not in allowed_statuses:
        raise HTTPException(
            status_code=400,
            detail="Only 'CHECKED_OUT' and 'OVERDUE' statuses are allowed for users.",
        )

    r_alias, subquery = get_latest_reservation_alias()

    base_query = (
        select(Book, r_alias)
        .join(r_alias, Book.id == r_alias.book_id)
        .join(
            subquery,
            (subquery.c.book_id == r_alias.book_id)
            & (subquery.c.latest_created == r_alias.created_at),
        )
        .where(r_alias.user_id == user_id)
    )

    if status:
        base_query = base_query.where(Book.status == status)
    else:
        base_query = base_query.where(Book.status.in_(allowed_statuses))

    total_books = await db.scalar(
        select(func.count()).select_from(base_query.subquery()),
    )
    result = await db.execute(
        base_query.order_by(Book.created_at.desc())
        .limit(per_page)
        .offset((page - 1) * per_page),
    )

    books = [
        serialize_book_with_reservation(book, reservation)
        for book, reservation in result.all()
    ]

    return paginate_response(total_books, page, per_page, books)


@router.get("/user/completed", response_model=dict)
async def get_completed_books_user(
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
    page: int = Query(1, ge=1, description="Номер сторінки"),
    per_page: int = Query(
        10,
        ge=1,
        le=100,
        description="Кількість записів на сторінку",
    ),
):
    query = (
        select(Reservation)
        .options(joinedload(Reservation.book), joinedload(Reservation.user))
        .where(
            Reservation.user_id == user_id,
            Reservation.status == ReservationStatus.COMPLETED,
        )
    )

    total_reservations = await db.scalar(
        select(func.count()).select_from(query.subquery()),
    )
    query = (
        query.order_by(Reservation.created_at.desc())
        .limit(per_page)
        .offset((page - 1) * per_page)
    )
    result = await db.execute(query)
    reservations = result.scalars().unique().all()

    return paginate_response(
        total=total_reservations,
        page=page,
        per_page=per_page,
        items=[ReservationResponse.model_validate(r) for r in reservations],
    )


@router.post("/user/favorite", status_code=201)
async def add_to_favorite(
    data: WishlistAddRequest,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    # перевірка чи книга існує
    book = await db.get(Book, data.book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Книгу не знайдено")

    # перевірка чи вже в списку
    existing = await db.scalar(
        select(Wishlist).where(
            Wishlist.user_id == user_id,
            Wishlist.book_id == data.book_id,
        ),
    )
    if existing:
        raise HTTPException(status_code=400, detail="Книга вже у списку бажаного")

    wishlist = Wishlist(user_id=user_id, book_id=data.book_id)
    db.add(wishlist)
    await db.commit()
    return {"message": "Книга додана у список бажаного"}


@router.delete("/user/favorite/{book_id}")
async def remove_from_favorite(
    book_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    wishlist_item = await db.scalar(
        select(Wishlist).where(
            Wishlist.user_id == user_id,
            Wishlist.book_id == book_id,
        ),
    )
    if not wishlist_item:
        raise HTTPException(
            status_code=404,
            detail="Книгу не знайдено у списку бажаного",
        )

    await db.delete(wishlist_item)
    await db.commit()
    return {"message": "Книга видалена зі списку бажаного"}


@router.get("/user/favorite", response_model=List[WishlistItemResponse])
async def get_favorite(
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    result = await db.execute(
    select(Wishlist)
    .options(
        joinedload(Wishlist.book),
        joinedload(Wishlist.user),
    )
    .where(Wishlist.user_id == user_id),
    )
    wishlist = result.scalars().all()
    return wishlist
