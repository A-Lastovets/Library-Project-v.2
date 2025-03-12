from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.dependencies.database import get_db
from app.models.book import Book, BookStatus
from app.models.reservation import Reservation, ReservationStatus
from app.schemas.schemas import ReservationCreate, ReservationResponse
from app.services.user_service import get_current_user_id, librarian_required

router = APIRouter(prefix="/reservations", tags=["Reservations"])


@router.post(
    "/",
    response_model=ReservationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_reservation(
    reservation_data: ReservationCreate,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """📌 Створення бронювання книги (тільки якщо книга доступна)."""
    book = await db.get(Book, reservation_data.book_id)

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

    # Створюємо нове бронювання
    expires_at = datetime.now() + timedelta(days=5)
    reservation = Reservation(
        book_id=reservation_data.book_id,
        user_id=user_id,
        status=ReservationStatus.PENDING,
        expires_at=expires_at,
    )

    book.status = BookStatus.RESERVED  # Оновлюємо статус книги

    db.add(reservation)
    await db.commit()
    await db.refresh(reservation)

    return reservation


@router.patch("/{reservation_id}/confirm", response_model=ReservationResponse)
async def confirm_reservation(
    reservation_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(librarian_required),
):
    """✅ Підтвердження бронювання бібліотекарем."""
    reservation = await db.get(Reservation, reservation_id)

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

    book = await db.get(Book, reservation.book_id)
    book.status = BookStatus.CHECKED_OUT  # Книга видається читачеві

    reservation.status = ReservationStatus.CONFIRMED
    await db.commit()
    await db.refresh(reservation)

    return reservation


@router.patch("/{reservation_id}/cancel", response_model=ReservationResponse)
async def cancel_reservation(
    reservation_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """❌ Скасування бронювання користувачем або бібліотекарем."""
    reservation = await db.get(Reservation, reservation_id)

    if not reservation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reservation not found",
        )

    if reservation.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only cancel your own reservations",
        )

    book = await db.get(Book, reservation.book_id)
    book.status = BookStatus.AVAILABLE  # Книга знову доступна

    reservation.status = ReservationStatus.CANCELLED
    await db.commit()
    await db.refresh(reservation)

    return reservation


@router.get("/", response_model=list[ReservationResponse])
async def get_reservations(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(librarian_required),
):
    """📄 Отримання всіх бронювань (тільки для бібліотекаря)."""
    result = await db.execute(select(Reservation))
    reservations = result.scalars().all()
    if not reservations:
        raise HTTPException(
            status_code=404,
            detail="No active reservations found.",
        )

    return reservations
