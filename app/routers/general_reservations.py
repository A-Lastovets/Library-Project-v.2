import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload
from sqlalchemy.sql import func

from app.dependencies.database import get_db
from app.models.book import Book, BookStatus
from app.models.reservation import Reservation, ReservationStatus
from app.schemas.schemas import ReservationCreate, ReservationResponse
from app.services.books_service import book_to_dict_for_email
from app.services.email_tasks import send_reservation_email
from app.services.user_service import check_and_block_user, get_active_user_id

router = APIRouter(prefix="/reservations", tags=["General Reservations"])

logger = logging.getLogger(__name__)


@router.post(
    "/reservation",
    response_model=ReservationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_reservation(
    reservation_data: ReservationCreate,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_active_user_id),
):

    await check_and_block_user(db, user_id)

    result = await db.execute(
        select(func.count())
        .select_from(Reservation)
        .where(
            Reservation.user_id == user_id,
            Reservation.status.in_(
                [
                    ReservationStatus.PENDING,
                    ReservationStatus.CONFIRMED,
                    ReservationStatus.ACTIVE,
                    ReservationStatus.EXPIRED,
                ],
            ),
        ),
    )
    total_relevant_reservations = result.scalar()

    if total_relevant_reservations >= 3:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You can have up to 3 active or pending reservations in total. "
            "Please complete or cancel an existing one to proceed.",
        )

    # Отримуємо книгу
    result = await db.execute(
        select(Book)
        .options(joinedload(Book.reservations))
        .where(Book.id == reservation_data.book_id),
    )
    book = result.scalars().first()

    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    # **Перевіряємо, чи книга вже має активні бронювання**
    result_existing_reservation = await db.execute(
        select(Reservation).where(
            Reservation.book_id == book.id,
            Reservation.status.in_(
                [ReservationStatus.PENDING, ReservationStatus.CONFIRMED],
            ),
        ),
    )
    existing_reservation = result_existing_reservation.scalars().first()

    if existing_reservation:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This book is already reserved by another user.",
        )

    if book.status != BookStatus.AVAILABLE:
        raise HTTPException(
            status_code=400,
            detail=f"Book is currently {book.status.lower()} and cannot be reserved.",
        )

    # Створюємо бронювання
    new_reservation = Reservation(
        book_id=book.id,
        user_id=user_id,
        status=ReservationStatus.PENDING,
        expires_at=datetime.now() + timedelta(days=5),
    )

    book.status = BookStatus.RESERVED

    db.add(new_reservation)
    await db.commit()
    await db.refresh(new_reservation, ["book"])

    result = await db.execute(
        select(Reservation)
        .options(joinedload(Reservation.user))
        .where(Reservation.id == new_reservation.id),
    )
    new_reservation = result.scalars().first()

    if not new_reservation.user:
        raise HTTPException(
            status_code=500,
            detail="User data not found for reservation.",
        )

    # Відправляємо e-mail
    send_reservation_email(
        new_reservation.user.email,
        book_to_dict_for_email(book),
        new_reservation.expires_at.strftime("%Y-%m-%d"),
    )

    return new_reservation
