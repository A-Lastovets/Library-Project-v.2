from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.sql import func

from app.dependencies.database import get_db
from app.exceptions.book_filters import apply_book_filters
from app.exceptions.pagination import paginate_response
from app.exceptions.serialization import (
    serialize_book_with_reservation,
    serialize_book_with_user_reservation,
)
from app.exceptions.subquery_reserv import get_latest_reservation_alias
from app.models.book import Book, BookStatus
from app.models.rating import Rating
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
        if book.status
        in {BookStatus.RESERVED, BookStatus.CHECKED_OUT, BookStatus.OVERDUE}
    ]

    if restricted_books:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete books with IDs {restricted_books} as they are reserved, checked out or overdue.",
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
    rating_result = await db.execute(
        select(func.coalesce(func.avg(Rating.rating), 0.0))
        .where(Rating.book_id == book_id)
    )
    average_rating = rating_result.scalar()  # Отримуємо середній рейтинг

    # Повертаємо відповідь у потрібному форматі
    return BookResponse(
        id=book.id,
        title=book.title,
        author=book.author,
        year=book.year,
        category=book.category,
        language=book.language,
        description=book.description,
        cover_image=book.cover_image,
        status=book.status,
        average_rating=round(float(average_rating), 1),
    )


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
    base_stmt = apply_book_filters(
        base_stmt,
        title,
        author,
        category,
        year,
        language,
        status,
        query,
    )

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

    book_list = [
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
    ]

    return paginate_response(total_books, page, per_page, book_list)


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


@router.get("/librarian/status", response_model=dict)
async def get_books_by_status_librarian(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(librarian_required),
    status: Optional[BookStatus] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=100),
):
    r_alias, subquery = get_latest_reservation_alias()

    if status is None:
        # Всі книги — спочатку отримаємо список ID для поточної сторінки
        book_ids_stmt = (
            select(Book.id)
            .order_by(Book.created_at.desc())
            .limit(per_page)
            .offset((page - 1) * per_page)
        )
        book_ids_result = await db.execute(book_ids_stmt)
        book_ids = [row[0] for row in book_ids_result.fetchall()]

        # Дані книг
        book_details_stmt = (
            select(Book, r_alias, User)
            .join(r_alias, Book.id == r_alias.book_id)
            .join(User, r_alias.user_id == User.id)
            .join(
                subquery,
                (subquery.c.book_id == r_alias.book_id)
                & (subquery.c.latest_created == r_alias.created_at),
            )
            .where(Book.id.in_(book_ids))
        )
        reservation_data = await db.execute(book_details_stmt)
        reservation_map = {
            book.id: (res, usr) for book, res, usr in reservation_data.all()
        }

        # Отримуємо самі книги
        books_result = await db.execute(select(Book).where(Book.id.in_(book_ids)))
        all_books = books_result.scalars().unique().all()

        books = []
        for book in all_books:
            if book.status != BookStatus.AVAILABLE and book.id in reservation_map:
                res, usr = reservation_map[book.id]
                books.append(serialize_book_with_user_reservation(book, res, usr))
            else:
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
                    },
                )

        total_books = await db.scalar(select(func.count()).select_from(Book))

    elif status == BookStatus.AVAILABLE:
        # Доступні книги — без юзера
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
        # Книги з конкретним статусом, з резервацією і юзером
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

        books = [
            serialize_book_with_user_reservation(book, reservation, user)
            for book, reservation, user in result.all()
        ]

    return paginate_response(total_books, page, per_page, books)


@router.post("/rate/{book_id}", status_code=status.HTTP_200_OK)
async def rate_book(
    book_id: int,
    rating_data: RateBook,
    db: AsyncSession = Depends(get_db),
    user_id: dict = Depends(get_current_user_id),
):
    """Додати рейтинг книги (лише один раз)"""
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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You have already rated this book",
        )

    new_rating = Rating(book_id=book_id, user_id=user_id, rating=rating_data.rating)
    db.add(new_rating)

    await db.commit()
    return {"message": "Rating submitted successfully"}
