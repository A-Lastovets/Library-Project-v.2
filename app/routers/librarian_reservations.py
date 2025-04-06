import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload
from sqlalchemy.sql import func

from app.dependencies.database import get_db
from app.exceptions.pagination import paginate_response
from app.models.book import BookStatus
from app.models.reservation import Reservation, ReservationStatus
from app.schemas.schemas import BookResponse, ReservationResponse
from app.services.email_tasks import (
    send_book_checked_out_email,
    send_reservation_cancelled_email,
    send_reservation_confirmation_email,
    send_thank_you_email,
)
from app.services.user_service import librarian_required

router = APIRouter(prefix="/reservations", tags=["Librarian Reservations"])

logger = logging.getLogger(__name__)


@router.patch(
    "/{reservation_id}/confirm/librarian",
    response_model=ReservationResponse,
)
async def confirm_reservation_by_librarian(
    reservation_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(librarian_required),
):
    """Бібліотекар підтверджує бронювання (читач має 5 днів, щоб забрати книгу)."""

    result = await db.execute(
        select(Reservation)
        .options(joinedload(Reservation.book), joinedload(Reservation.user))
        .where(Reservation.id == reservation_id),
    )
    reservation = result.scalars().first()

    if not reservation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reservation not found",
        )

    if reservation.status != ReservationStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reservation is not pending",
        )

    # Отримуємо книгу, щоб оновити її статус
    book = reservation.book

    if not book:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Associated book not found",
        )

    if book.status in [BookStatus.CHECKED_OUT, BookStatus.OVERDUE]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Book is currently {book.status.lower()} and cannot be reserved.",
        )

    # Обмеження: книгу потрібно забрати протягом 5 днів
    reservation.expires_at = datetime.now() + timedelta(days=5)
    reservation.status = ReservationStatus.CONFIRMED

    await db.commit()
    await db.refresh(reservation, ["book", "user"])

    # Відправляємо e-mail користувачу про підтвердження бронювання
    send_reservation_confirmation_email(
        reservation.user.email,
        BookResponse.model_validate(book).model_dump(),
        reservation.expires_at.strftime("%Y-%m-%d %H:%M"),
    )

    # Логування підтвердження бронювання
    logger.info(
        f"Reservation {reservation.id} confirmed by librarian. Expires at: {reservation.expires_at}",
    )

    return reservation


@router.patch(
    "/{reservation_id}/decline/librarian",
    response_model=ReservationResponse,
)
async def decline_reservation_by_librarian(
    reservation_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(librarian_required),
):
    """Бібліотекар скасовує бронювання."""

    result = await db.execute(
        select(Reservation)
        .options(joinedload(Reservation.book), joinedload(Reservation.user))
        .where(Reservation.id == reservation_id),
    )
    reservation = result.scalars().first()

    if not reservation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reservation not found",
        )

    # Отримуємо книгу
    book = reservation.book
    if not book:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Associated book not found",
        )

    # Перевірка: не можна скасувати вже отриману книгу
    if book.status in [BookStatus.CHECKED_OUT, BookStatus.OVERDUE]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This book is already checked out or overdue and cannot be cancelled. The user must return it first.",
        )

    # Оновлення статусу книги та бронювання
    book.status = BookStatus.AVAILABLE  # Книга знову доступна
    reservation.status = ReservationStatus.CANCELLED  # Бронювання скасовано
    reservation.cancelled_by = "librarian"

    await db.commit()
    await db.refresh(reservation, ["book", "user"])

    # Відправка e-mail про скасування бронювання
    send_reservation_cancelled_email(
        reservation.user.email,
        book.title,
        cancelled_by="librarian",
    )

    # Логування скасування
    logger.info(
        f"Reservation {reservation.id} was cancelled by librarian. Book {book.title} is now available.",
    )

    return reservation


@router.patch(
    "/{reservation_id}/checkout/librarian",
    response_model=ReservationResponse,
)
async def confirm_book_checkout_by_librarian(
    reservation_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(librarian_required),
):
    """Бібліотекар підтверджує, що видав книгу читачу (починається відлік 14 днів)."""

    result = await db.execute(
        select(Reservation)
        .options(joinedload(Reservation.book), joinedload(Reservation.user))
        .where(
            Reservation.id == reservation_id,
            Reservation.status == ReservationStatus.CONFIRMED,
        ),
    )
    reservation = result.scalars().first()

    if not reservation:
        raise HTTPException(
            status_code=404,
            detail="Reservation not found or not eligible for confirmation",
        )

    book = reservation.book  # Використовуємо завантажену книгу

    if not book:
        raise HTTPException(
            status_code=404,
            detail="Associated book not found",
        )

    if book.status != BookStatus.RESERVED:
        raise HTTPException(
            status_code=400,
            detail="Book is not in 'reserved' status and cannot be issued.",
        )

    reservation.expires_at = datetime.now() + timedelta(days=14)
    reservation.status = ReservationStatus.ACTIVE
    book.status = BookStatus.CHECKED_OUT  # Книга видана користувачу

    await db.commit()
    await db.refresh(reservation, ["book", "user"])

    # Відправляємо e-mail користувачу з нагадуванням про 14 днів
    send_book_checked_out_email(
        reservation.user.email,
        book.title,
        reservation.expires_at.strftime("%Y-%m-%d %H:%M"),
    )

    # Логування підтвердження видачі книги
    logger.info(
        f"Reservation {reservation.id} confirmed by librarian. Due date: {reservation.expires_at}",
    )

    return reservation


@router.patch(
    "/{reservation_id}/return/librarian",
    response_model=ReservationResponse,
)
async def confirm_book_return_by_librarian(
    reservation_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(librarian_required),
):
    """Бібліотекар підтверджує повернення книги. Статус змінюється на AVAILABLE."""

    result = await db.execute(
        select(Reservation)
        .options(joinedload(Reservation.book), joinedload(Reservation.user))
        .where(Reservation.id == reservation_id),
    )
    reservation = result.scalars().first()

    if not reservation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reservation not found",
        )

    # Отримуємо книгу
    book = reservation.book
    if not book:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Associated book not found",
        )

    # Перевіряємо, чи книга була видана читачеві
    if book.status not in {BookStatus.CHECKED_OUT, BookStatus.OVERDUE}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This book is not currently checked out or overdue.",
        )

    # Оновлення статусу книги та бронювання
    book.status = BookStatus.AVAILABLE  # Книга знову доступна
    reservation.status = ReservationStatus.COMPLETED  # Бронювання завершене

    await db.commit()
    await db.refresh(reservation, ["book", "user"])

    # Відправка e-mail підтвердження повернення книги
    send_thank_you_email(
        reservation.user.email,
        BookResponse.model_validate(book).model_dump(),
    )

    # Логування події
    logger.info(
        f"Librarian confirmed return of book '{book.title}' for user {reservation.user.email}.",
    )

    return reservation


@router.get("/librarian/all", response_model=dict)
async def get_reservations(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(librarian_required),
    status: Optional[ReservationStatus] = Query(
        None,
        description="Фільтр за статусом бронювання",
    ),
    page: int = Query(1, ge=1, description="Номер сторінки"),
    per_page: int = Query(10, ge=1, le=100, description="Кількість записів"),
):
    """📄 Отримання всіх бронювань (тільки для бібліотекаря) з можливістю фільтрації та пагінації."""
    query = select(Reservation).options(
        joinedload(Reservation.book),
        joinedload(Reservation.user),
    )

    if status is not None:
        query = query.where(Reservation.status == status)

    total_reservations = await db.scalar(
        select(func.count()).select_from(query.subquery()),
    )

    result = await db.execute(
        query.order_by(Reservation.created_at.desc())
        .limit(per_page)
        .offset((page - 1) * per_page),
    )
    reservations = result.scalars().unique().all()

    return paginate_response(
        total=total_reservations,
        page=page,
        per_page=per_page,
        items=[ReservationResponse.model_validate(r) for r in reservations],
    )
