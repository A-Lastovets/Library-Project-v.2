import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload
from sqlalchemy.sql import func

from app.dependencies.database import get_db
from app.exceptions.pagination import paginate_response
from app.models.book import BookStatus
from app.models.reservation import Reservation, ReservationStatus
from app.schemas.schemas import ReservationResponse
from app.services.email_tasks import send_reservation_cancelled_email
from app.services.user_service import get_current_user_id

router = APIRouter(prefix="/reservations", tags=["User Reservations"])

logger = logging.getLogger(__name__)


@router.patch(
    "/{reservation_id}/decline/user",
    response_model=ReservationResponse,
)
async def decline_reservation_user(
    reservation_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Читач скасовує СВОЄ бронювання."""

    result = await db.execute(
        select(Reservation)
        .options(
            joinedload(Reservation.book),
            joinedload(Reservation.user),
        )
        .where(Reservation.id == reservation_id),
    )
    reservation = result.scalars().first()

    if not reservation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reservation not found",
        )

    # Перевіряємо, чи це бронювання належить користувачеві
    if reservation.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only cancel your own reservations",
        )

    book = reservation.book
    if not book:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Associated book not found",
        )

    # Заборона скасування, якщо книга вже `CHECKED_OUT`
    if book.status in [BookStatus.CHECKED_OUT, BookStatus.OVERDUE]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "You cannot cancel this reservation because the book has already been taken or is overdue. "
                "Please return it instead."
            ),
        )

    # Дозволяємо скасування тільки для `PENDING` або `CONFIRMED`
    if reservation.status not in [
        ReservationStatus.PENDING,
        ReservationStatus.CONFIRMED,
    ]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only pending or confirmed reservations can be cancelled.",
        )

    # **Оновлення статусу бронювання та книги**
    book.status = BookStatus.AVAILABLE
    reservation.status = ReservationStatus.CANCELLED
    reservation.cancelled_by = "user"

    await db.commit()
    await db.refresh(
        reservation,
        ["book", "user"],
    )

    # Відправка e-mail про скасування бронювання
    send_reservation_cancelled_email(
        reservation.user.email,
        book.title,
        cancelled_by="user",
    )

    # Логування події
    logger.info(
        f"User {user_id} cancelled reservation {reservation.id}. Book {book.title} is now available.",
    )

    return reservation


@router.get("/user/all", response_model=dict)
async def get_user_reservations(
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
    status: Optional[Literal["pending", "confirmed", "cancelled", "completed"]] = Query(
        None,
        description="Фільтр за статусом бронювання (PENDING, CONFIRMED, CANCELLED, COMPLETED)",
    ),
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
        .options(
            joinedload(Reservation.book),
            joinedload(Reservation.user),
        )
        .where(
            Reservation.user_id == user_id,
            Reservation.status != ReservationStatus.ACTIVE,
        )
    )

    if status is not None:
        query = query.where(Reservation.status == ReservationStatus(status))

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
