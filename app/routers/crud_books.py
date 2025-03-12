from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.sql import func

from app.dependencies.database import get_db
from app.models.book import Book, BookStatus
from app.models.rating import Rating
from app.oauth2 import validate_cover_image
from app.schemas.schemas import BookCreate, BookResponse, BookUpdate, RateBook
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

    validate_cover_image(book_data.cover_image)

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

    validate_cover_image(book_data.cover_image)

    for key, value in book_data.model_dump(exclude_unset=True).items():
        setattr(book, key, value)

    await db.commit()
    await db.refresh(book)
    return book


@router.delete(
    "/{book_id}",
    response_model=dict,
    status_code=status.HTTP_200_OK,
)
async def delete_book(
    book_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(librarian_required),
):
    """🗑 Видалення книги (тільки бібліотекар, перевіряємо бронювання)."""
    book = await db.get(Book, book_id)
    if not book:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Book not found",
        )
    if book.status in {BookStatus.RESERVED, BookStatus.CHECKED_OUT}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Book is reserved or checked out",
        )

    await db.delete(book)
    await db.commit()
    return {"message": "Book deleted successfully"}


# Отримати одну книгу за ID
@router.get(
    "/find/{book_id}",
    response_model=BookResponse,
    status_code=status.HTTP_200_OK,
)
async def find_book(book_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Book).where(Book.id == book_id))
    book = result.scalar_one_or_none()
    if not book:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Book not found",
        )
    return book


@router.get("/all", response_model=dict)
async def list_books(
    db: AsyncSession = Depends(get_db),
    title: Optional[str] = None,
    author: Optional[str] = None,
    category: Optional[str] = None,
    year: Optional[int] = None,
    language: Optional[str] = None,
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
        base_stmt = base_stmt.where(Book.year == year)
    if language:
        base_stmt = base_stmt.where(Book.language.ilike(f"%{language}%"))

    # Отримуємо загальну кількість книг, які відповідають фільтрам
    total_books = await db.scalar(
        select(func.count()).select_from(base_stmt.subquery()),
    )

    if total_books == 0:
        raise HTTPException(
            status_code=404,
            detail="No books found with the given criteria.",
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
