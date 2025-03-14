from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload

from app.dependencies.database import get_db
from app.models.book import Book, BookStatus
from app.models.reservation import Reservation, ReservationStatus
from app.schemas.schemas import ReservationCreate, ReservationResponse
from app.services.user_service import get_current_user_id, librarian_required

router = APIRouter(tags=["Reservations"])


@router.post(
    "/reservations/reservation",
    response_model=ReservationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_reservation(
    reservation_data: ReservationCreate,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Створення бронювання книги (тільки якщо книга доступна)."""
    result = await db.execute(
        select(Book)
        .options(joinedload(Book.reservations))
        .where(Book.id == reservation_data.book_id),
    )
    book = result.scalars().first()

    if not book:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Book not found",
        )

    if book.status != BookStatus.AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Book is not available for reservation",
        )

    new_reservation = Reservation(
        book_id=book.id,
        user_id=user_id,
        status=ReservationStatus.PENDING,
        expires_at=datetime.now() + timedelta(days=5),
    )

    db.add(new_reservation)
    book.status = BookStatus.RESERVED

    db.add(new_reservation)
    await db.commit()
    await db.refresh(new_reservation, ["book"])

    return new_reservation


@router.patch(
    "/reservations/reservation_id/{reservation_id}/confirm",
    response_model=ReservationResponse,
)
async def confirm_reservation(
    reservation_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(librarian_required),
):
    """Підтвердження бронювання бібліотекарем (обмеження на отримання книги 5 днів)."""

    result = await db.execute(
        select(Reservation)
        .options(joinedload(Reservation.book))  # Завантажуємо book разом із бронюванням
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
    book = await db.get(Book, reservation.book_id)
    if not book:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Associated book not found",
        )

    book.status = BookStatus.CHECKED_OUT  # Книга видається читачеві

    # Обмеження: книгу потрібно забрати протягом 5 днів
    reservation.expires_at = datetime.now() + timedelta(days=5)
    reservation.status = ReservationStatus.CONFIRMED

    await db.commit()
    await db.refresh(reservation, ["book"])

    return reservation


@router.patch(
    "/reservations/reservation_id/{reservation_id}/decline",
    response_model=ReservationResponse,
)
async def decline_reservation(
    reservation_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
    librarian: dict = Depends(librarian_required),
):
    """Скасування бронювання користувачем або бібліотекарем."""

    reservation = await db.get(Reservation, reservation_id)

    if not reservation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reservation not found",
        )

    # Бібліотекар може скасувати будь-яке бронювання
    if reservation.user_id != user_id and not librarian:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only cancel your own reservations",
        )

    # Отримуємо книгу
    book = await db.get(Book, reservation.book_id)
    if not book:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Associated book not found",
        )

    book.status = BookStatus.AVAILABLE  # Книга знову доступна

    reservation.status = ReservationStatus.CANCELLED

    await db.commit()
    await db.refresh(reservation, ["book"])

    return reservation


@router.get("/reservations/all", response_model=list[ReservationResponse])
async def get_reservations(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(librarian_required),
    status: Optional[ReservationStatus] = Query(
        None,
        description="Фільтр за статусом бронювання",
    ),
):
    """📄 Отримання всіх бронювань (тільки для бібліотекаря) з можливістю фільтрації за статусом."""
    query = select(Reservation).options(joinedload(Reservation.book))

    if status:  # Якщо передано параметр статусу, додаємо фільтр
        query = query.where(Reservation.status == status)

    result = await db.execute(query)
    reservations = result.scalars().unique().all()

    if not reservations:
        raise HTTPException(
            status_code=404,
            detail="No reservations found with the given criteria.",
        )

    return reservations
