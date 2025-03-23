from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import String, and_, desc, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import aliased
from sqlalchemy.sql import func

from app.dependencies.database import get_db
from app.models.book import Book, BookStatus
from app.models.rating import Rating
from app.models.reservation import Reservation
from app.models.user import User
from app.schemas.schemas import (
    BookCreate,
    BookResponse,
    BookUpdate,
    BulkUpdateRequest,
    BulkUpdateResponse,
    RateBook,
)
from app.services.user_service import get_current_user_id, librarian_required

router = APIRouter(prefix="/books", tags=["Books"])


@router.post(
    "/",
    response_model=BookResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_book(
    book_data: BookCreate,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(librarian_required),
):

    stmt = select(Book).where(
        Book.title == book_data.title,
        Book.author == book_data.author,
        Book.year == book_data.year,
    )
    result = await db.execute(stmt)
    existing_book = result.scalars().first()

    if existing_book:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A book with this title and author already exists.",
        )

    new_book = Book(**book_data.model_dump(), status=BookStatus.AVAILABLE)
    db.add(new_book)
    await db.commit()
    await db.refresh(new_book)
    return new_book


@router.patch(
    "/{book_id}",
    response_model=BookResponse,
    status_code=status.HTTP_200_OK,
)
async def update_book(
    book_id: int,
    book_data: BookUpdate,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(librarian_required),
):
    """✏️ Оновлення книги (тільки бібліотекар)."""
    book = await db.get(Book, book_id)
    if not book:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Book not found",
        )

    for key, value in book_data.model_dump(exclude_unset=True).items():
        setattr(book, key, value)

    await db.commit()
    await db.refresh(book)
    return book


@router.delete(
    "/",
    response_model=BulkUpdateResponse,
    status_code=status.HTTP_200_OK,
)
async def delete_multiple_books(
    request: BulkUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(librarian_required),
):
    """🗑 Видалення кількох книг (тільки бібліотекар, перевіряємо бронювання)."""
    book_ids = request.ids

    if not book_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No book IDs provided.",
        )

    # Отримуємо книги за їх ID
    stmt = select(Book).where(Book.id.in_(book_ids))
    result = await db.execute(stmt)
    books = result.scalars().all()

    if not books:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No books found with the given IDs.",
        )

    # Перевіряємо, чи є серед книг ті, які не можна видаляти
    restricted_books = [
        book.id
        for book in books
        if book.status in {BookStatus.RESERVED, BookStatus.CHECKED_OUT}
    ]

    if restricted_books:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete books with IDs {restricted_books} as they are reserved or checked out.",
        )

    for book in books:
        await db.delete(book)

    await db.commit()

    return {
        "message": "Books deleted successfully",
        "updated_items": [book.id for book in books],
    }


# Отримати одну книгу за ID
@router.get(
    "/find/{book_id}",
    response_model=BookResponse,
    status_code=status.HTTP_200_OK,
)
async def find_book(
    book_id: int,
    db: AsyncSession = Depends(get_db),
    _: int = Depends(get_current_user_id),
):

    result = await db.execute(select(Book).where(Book.id == book_id))
    book = result.scalar_one_or_none()

    if not book:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Book not found",
        )
    return book


@router.get("/all", response_model=dict, status_code=status.HTTP_200_OK)
async def list_books(
    db: AsyncSession = Depends(get_db),
    _: int = Depends(get_current_user_id),
    title: Optional[str] = None,
    author: Optional[str] = None,
    category: Optional[str] = None,
    year: Optional[str] = None,
    language: Optional[str] = None,
    status: Optional[str] = None,
    query: Optional[str] = None,
    page: int = Query(1, ge=1, description="Номер сторінки (починається з 1)"),
    per_page: int = Query(
        10,
        ge=1,
        le=100,
        description="Кількість книг на сторінку (1-100)",
    ),
):

    base_stmt = select(Book).outerjoin(Rating).group_by(Book.id)

    if title:
        base_stmt = base_stmt.where(Book.title.ilike(f"%{title}%"))
    if author:
        base_stmt = base_stmt.where(Book.author.ilike(f"%{author}%"))
    if category:
        base_stmt = base_stmt.where(Book.category.ilike(f"%{category}%"))
    if year:
        base_stmt = base_stmt.where(Book.year.cast(String).ilike(f"%{year}%"))
    if language:
        base_stmt = base_stmt.where(Book.language.ilike(f"%{language}%"))
    if status:
        base_stmt = base_stmt.where(Book.status.cast(String).ilike(f"%{status}%"))

    if query:
        search_terms = query.split()

        search_conditions = and_(
            *(
                (
                    Book.year == int(word)
                    if word.isdigit()
                    else or_(
                        Book.title.ilike(f"%{word}%"),
                        Book.author.ilike(f"%{word}%"),
                        Book.category.ilike(f"%{word}%"),
                        Book.language.ilike(f"%{word}%"),
                    )
                )
                for word in search_terms
            ),
        )

        base_stmt = base_stmt.where(search_conditions)

    # Отримуємо загальну кількість книг, які відповідають фільтрам
    total_books = await db.scalar(
        select(func.count()).select_from(base_stmt.subquery()),
    )

    # Додаємо сортування та пагінацію
    stmt = (
        base_stmt.add_columns(
            func.coalesce(func.avg(Rating.rating), 0).label("average_rating"),
        )
        .order_by(Book.created_at.desc())
        .limit(per_page)
        .offset((page - 1) * per_page)
    )

    result = await db.execute(stmt)
    books = result.fetchall()

    return {
        "total_books": total_books,
        "total_pages": (total_books // per_page) + (1 if total_books % per_page else 0),
        "current_page": page,
        "per_page": per_page,
        "books": [
            {
                "id": book.id,
                "title": book.title,
                "author": book.author,
                "year": book.year,
                "category": book.category,
                "language": book.language,
                "description": book.description,
                "status": book.status.value,
                "average_rating": round(float(average_rating), 1),
                "coverImage": book.cover_image,
            }
            for book, average_rating in books
        ],
    }


@router.get("/user/status", response_model=dict)
async def get_books_by_status_user(
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
    status: Optional[BookStatus] = Query(
        None,
        description="Фільтр за статусом книги (AVAILABLE, RESERVED, CHECKED_OUT, OVERDUE)",
    ),
    page: int = Query(1, ge=1, description="Номер сторінки"),
    per_page: int = Query(10, ge=1, le=100, description="Кількість книг на сторінку"),
):
    # Показуємо всі книги з різними статусами, якщо фільтр не вказано
    if status is None:
        query = select(Book)
        total_books = await db.scalar(select(func.count()).select_from(Book))
        result = await db.execute(
            query.order_by(Book.created_at.desc())
            .limit(per_page)
            .offset((page - 1) * per_page),
        )
        books = result.scalars().unique().all()

        return {
            "total_books": total_books,
            "total_pages": (total_books // per_page)
            + (1 if total_books % per_page else 0),
            "current_page": page,
            "books": [BookResponse.model_validate(book) for book in books],
        }

    # Якщо статус — AVAILABLE, також показуємо всі доступні книги
    if status == BookStatus.AVAILABLE:
        query = select(Book).where(Book.status == BookStatus.AVAILABLE)
        total_books = await db.scalar(
            select(func.count())
            .select_from(Book)
            .where(Book.status == BookStatus.AVAILABLE),
        )
        result = await db.execute(
            query.order_by(Book.created_at.desc())
            .limit(per_page)
            .offset((page - 1) * per_page),
        )
        books = result.scalars().unique().all()

        return {
            "total_books": total_books,
            "total_pages": (total_books // per_page)
            + (1 if total_books % per_page else 0),
            "current_page": page,
            "books": [BookResponse.model_validate(book) for book in books],
        }

    # Для інших статусів — книги, пов’язані з користувачем
    subquery = (
        select(
            Reservation.book_id,
            func.max(Reservation.created_at).label("max_created_at"),
        )
        .where(Reservation.user_id == user_id)
        .group_by(Reservation.book_id)
        .subquery()
    )

    r_alias = aliased(Reservation)

    query = (
        select(Book)
        .join(r_alias, Book.id == r_alias.book_id)
        .join(
            subquery,
            (subquery.c.book_id == r_alias.book_id)
            & (subquery.c.max_created_at == r_alias.created_at),
        )
        .where(r_alias.user_id == user_id)
        .where(Book.status == status)
    )

    total_books = await db.scalar(select(func.count()).select_from(query.subquery()))

    query = (
        query.order_by(Book.created_at.desc())
        .limit(per_page)
        .offset((page - 1) * per_page)
    )
    result = await db.execute(query)
    books = result.scalars().unique().all()

    return {
        "total_books": total_books,
        "total_pages": (total_books // per_page) + (1 if total_books % per_page else 0),
        "current_page": page,
        "books": [BookResponse.model_validate(book) for book in books],
    }


@router.get("/librarian/status", response_model=dict)
async def get_books_by_status_librarian(
    db: AsyncSession = Depends(get_db),
    librarian: dict = Depends(librarian_required),
    status: Optional[BookStatus] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=100),
):
    subquery = (
        select(
            Reservation.book_id,
            func.max(Reservation.created_at).label("latest_created"),
        )
        .group_by(Reservation.book_id)
        .subquery()
    )

    r_alias = aliased(Reservation)

    if status is None:
        # Всі книги з усіма статусами, додаємо дані користувача та бронювання
        book_query = (
            select(Book, r_alias, User)
            .join(r_alias, Book.id == r_alias.book_id)
            .join(User, r_alias.user_id == User.id)
            .join(
                subquery,
                (subquery.c.book_id == r_alias.book_id)
                & (subquery.c.latest_created == r_alias.created_at),
            )
        )

        result_books = await db.execute(
            select(Book)
            .order_by(Book.created_at.desc())
            .limit(per_page)
            .offset((page - 1) * per_page),
        )
        all_books = result_books.scalars().unique().all()

        # Створюємо мапу останніх резервацій
        result_details = await db.execute(book_query)
        reservation_map = {
            book.id: {"reservation": res, "user": usr}
            for book, res, usr in result_details.all()
        }

        total_books = await db.scalar(select(func.count()).select_from(Book))

        books = []
        for book in all_books:
            book_info = {
                "id": book.id,
                "title": book.title,
                "author": book.author,
                "year": book.year,
                "category": book.category,
                "language": book.language,
                "description": book.description,
                "status": book.status.value,
                "coverImage": book.cover_image,
            }

            if book.status != BookStatus.AVAILABLE and book.id in reservation_map:
                data = reservation_map[book.id]
                book_info.update(
                    {
                        "user": {
                            "id": data["user"].id,
                            "first_name": data["user"].first_name,
                            "last_name": data["user"].last_name,
                            "email": data["user"].email,
                        },
                        "reservation_status": data["reservation"].status.value,
                        "reservation_date": data["reservation"].created_at,
                        "expires_at": data["reservation"].expires_at,
                    },
                )

            books.append(book_info)

    elif status == BookStatus.AVAILABLE:
        # Тільки доступні книги (без користувача)
        query = select(Book).where(Book.status == BookStatus.AVAILABLE)
        total_books = await db.scalar(
            select(func.count()).select_from(query.subquery()),
        )
        result = await db.execute(
            query.order_by(Book.created_at.desc())
            .limit(per_page)
            .offset((page - 1) * per_page),
        )
        books = [
            {
                "id": book.id,
                "title": book.title,
                "author": book.author,
                "year": book.year,
                "category": book.category,
                "language": book.language,
                "description": book.description,
                "status": book.status.value,
                "coverImage": book.cover_image,
            }
            for book in result.scalars().unique().all()
        ]

    else:
        # Книги з конкретним статусом, з користувачем і резервацією
        query = (
            select(Book, r_alias, User)
            .join(r_alias, Book.id == r_alias.book_id)
            .join(User, r_alias.user_id == User.id)
            .join(
                subquery,
                (subquery.c.book_id == r_alias.book_id)
                & (subquery.c.latest_created == r_alias.created_at),
            )
            .where(Book.status == status)
        )

        total_books = await db.scalar(
            select(func.count()).select_from(query.subquery()),
        )
        result = await db.execute(
            query.order_by(Book.created_at.desc())
            .limit(per_page)
            .offset((page - 1) * per_page),
        )

        books = []
        for book, reservation, user in result.all():
            books.append(
                {
                    "id": book.id,
                    "title": book.title,
                    "author": book.author,
                    "year": book.year,
                    "category": book.category,
                    "language": book.language,
                    "description": book.description,
                    "status": book.status.value,
                    "coverImage": book.cover_image,
                    "user": {
                        "id": user.id,
                        "first_name": user.first_name,
                        "last_name": user.last_name,
                        "email": user.email,
                    },
                    "reservation_status": reservation.status.value,
                    "reservation_date": reservation.created_at,
                    "expires_at": reservation.expires_at,
                },
            )

    return {
        "total_books": total_books,
        "total_pages": (total_books // per_page) + (1 if total_books % per_page else 0),
        "current_page": page,
        "books": books,
    }


@router.post("/rate/{book_id}", status_code=status.HTTP_200_OK)
async def rate_book(
    book_id: int,
    rating_data: RateBook,
    db: AsyncSession = Depends(get_db),
    user_id: dict = Depends(get_current_user_id),
):
    """⭐ Додати або оновити рейтинг книги"""
    book = await db.get(Book, book_id)
    if not book:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Book not found",
        )

    # Перевіряємо, чи користувач вже голосував
    stmt = select(Rating).where(Rating.book_id == book_id, Rating.user_id == user_id)
    result = await db.execute(stmt)
    existing_rating = result.scalars().first()

    if existing_rating:
        existing_rating.rating = rating_data.rating  # Оновлюємо рейтинг
    else:
        new_rating = Rating(book_id=book_id, user_id=user_id, rating=rating_data.rating)
        db.add(new_rating)

    await db.commit()
    return {"message": "Rating submitted successfully"}
