import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload
from sqlalchemy.sql import and_, func

from app.dependencies.database import get_db
from app.models.book import Book, BookStatus
from app.models.reservation import Reservation, ReservationStatus
from app.schemas.schemas import BookResponse, ReservationCreate, ReservationResponse
from app.services.email_tasks import (
    send_book_checked_out_email,
    send_reservation_cancelled_email,
    send_reservation_confirmation_email,
    send_reservation_email,
    send_thank_you_email,
)
from app.services.user_service import (
    check_and_block_user,
    get_current_user_id,
    librarian_required,
)

router = APIRouter(tags=["Reservations"])

logger = logging.getLogger(__name__)


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

    await check_and_block_user(db, user_id)

    # Перевіряємо активні бронювання та книги на руках
    result1 = await db.execute(
        select(func.count())
        .select_from(Reservation)
        .where(
            and_(
                Reservation.user_id == user_id,
                Reservation.status.in_(
                    [ReservationStatus.PENDING, ReservationStatus.CONFIRMED],
                ),
            ),
        ),
    )
    active_reservations_count = result1.scalar()

    result2 = await db.execute(
        select(func.count())
        .select_from(Book)
        .where(
            and_(
                Book.id.in_(
                    select(Reservation.book_id).where(
                        Reservation.user_id == user_id,
                        Reservation.status == ReservationStatus.CONFIRMED,
                    ),
                ),
                Book.status == BookStatus.CHECKED_OUT,
            ),
        ),
    )
    checked_out_books_count = result2.scalar()

    if active_reservations_count + checked_out_books_count >= 3:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You have reached the limit of 3 active reservations or borrowed books."
            " Cancel a reservation or return a book before making a new reservation.",
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

    # 🔹 **Перевіряємо, чи книга вже має активні бронювання**
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
        BookResponse.model_validate(book).model_dump(),
        new_reservation.expires_at.strftime("%Y-%m-%d"),
    )

    return new_reservation


@router.patch(
    "/reservations/{reservation_id}/confirm/librarian",
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
        reservation.expires_at.strftime("%Y-%m-%d"),
    )

    # Логування підтвердження бронювання
    logger.info(
        f"Reservation {reservation.id} confirmed by librarian. Expires at: {reservation.expires_at}",
    )

    return reservation


@router.patch(
    "/reservations/{reservation_id}/confirm/user",
    response_model=ReservationResponse,
)
async def confirm_reservation_by_user(
    reservation_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Читач підтверджує, що забрав книгу (починається відлік 14 днів)."""

    result = await db.execute(
        select(Reservation)
        .options(joinedload(Reservation.book), joinedload(Reservation.user))
        .where(
            Reservation.id == reservation_id,
            Reservation.user_id
            == user_id,  # Користувач може підтвердити лише свою книгу
            Reservation.status
            == ReservationStatus.CONFIRMED,  # Бронювання підтверджене бібліотекарем
        ),
    )
    reservation = result.scalars().first()

    if not reservation:
        raise HTTPException(
            status_code=404,
            detail="Reservation not found or not eligible for confirmation",
        )

    # 📚 Отримуємо книгу
    book = reservation.book  # Використовуємо завантажену книгу

    if not book:
        raise HTTPException(
            status_code=404,
            detail="Associated book not found",
        )

    if book.status == BookStatus.OVERDUE:
        raise HTTPException(
            status_code=400,
            detail="This book is already overdue and cannot be confirmed.",
        )

    # Користувач отримує 14 днів на користування книгою
    reservation.expires_at = datetime.now() + timedelta(days=14)
    book.status = BookStatus.CHECKED_OUT  # Книга видана користувачу

    await db.commit()
    await db.refresh(reservation, ["book", "user"])

    # Відправляємо e-mail користувачу з нагадуванням про 14 днів
    send_book_checked_out_email(
        reservation.user.email,
        book.title,
        reservation.expires_at.strftime("%Y-%m-%d"),
    )

    # Логування підтвердження отримання книги
    logger.info(
        f"Reservation {reservation.id} confirmed by user. Due date: {reservation.expires_at}",
    )

    return reservation


@router.patch(
    "/reservations/{reservation_id}/decline/librarian",
    response_model=ReservationResponse,
)
async def decline_reservation_librarian(
    reservation_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(librarian_required),
):
    """Бібліотекар скасовує будь-яке бронювання."""

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
    if book.status == BookStatus.CHECKED_OUT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This book is already checked out and cannot be cancelled. The user must return it first.",
        )

    # Оновлення статусу книги та бронювання
    book.status = BookStatus.AVAILABLE  # Книга знову доступна
    reservation.status = ReservationStatus.CANCELLED  # Бронювання скасовано

    await db.commit()
    await db.refresh(reservation, ["book", "user"])

    # Відправка e-mail про скасування бронювання
    send_reservation_cancelled_email(
        reservation.user.email,
        book.title,
    )

    # Логування скасування
    logger.info(
        f"Reservation {reservation.id} was cancelled by librarian. Book {book.title} is now available.",
    )

    return reservation


@router.patch(
    "/reservations/{reservation_id}/decline/user",
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
    if book.status == BookStatus.CHECKED_OUT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot cancel this reservation because you have already taken the book. Please return it instead.",
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

    await db.commit()
    await db.refresh(
        reservation,
        ["book", "user"],
    )

    # Відправка e-mail про скасування бронювання
    send_reservation_cancelled_email(
        reservation.user.email,
        book.title,
    )

    # Логування події
    logger.info(
        f"User {user_id} cancelled reservation {reservation.id}. Book {book.title} is now available.",
    )

    return reservation


@router.patch(
    "/reservations/{reservation_id}/return",
    response_model=ReservationResponse,
)
async def confirm_book_return(
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
    if book.status != BookStatus.CHECKED_OUT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This book is not currently checked out.",
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


@router.get("/reservations/librarian/all", response_model=list[ReservationResponse])
async def get_reservations(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(librarian_required),
    status: Optional[ReservationStatus] = Query(
        None,
        description="Фільтр за статусом бронювання",
    ),
):
    """📄 Отримання всіх бронювань (тільки для бібліотекаря) з можливістю фільтрації за статусом."""
    query = select(Reservation).options(
        joinedload(Reservation.book),
        joinedload(Reservation.user),
    )

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


@router.get("/reservations/user/all", response_model=list[ReservationResponse])
async def get_user_reservations(
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
    status: Optional[ReservationStatus] = Query(
        None,
        description="Фільтр за статусом бронювання (PENDING, CONFIRMED, CANCELLED, EXPIRED)",
    ),
):
    """Отримання всіх активних бронювань користувача з можливістю фільтрації."""

    query = (
        select(Reservation)
        .options(
            joinedload(Reservation.book),  # Завантажуємо книгу
            joinedload(Reservation.user),  # Завантажуємо користувача
        )
        .where(Reservation.user_id == user_id)
    )

    if status:  # Якщо передано параметр статусу, додаємо фільтр
        query = query.where(Reservation.status == status)
    else:
        # За замовчуванням показуємо тільки активні бронювання (ті, що ще не закінчились)
        query = query.where(
            Reservation.status.in_(
                [ReservationStatus.PENDING, ReservationStatus.CONFIRMED],
            ),
        )

    result = await db.execute(query)
    reservations = result.scalars().unique().all()

    if not reservations:
        raise HTTPException(
            status_code=404,
            detail="No active reservations found.",
        )

    return reservations
