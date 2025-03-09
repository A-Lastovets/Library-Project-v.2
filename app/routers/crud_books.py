import base64
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.sql import func

from app.dependencies.database import get_db
from app.models.book import Book
from app.models.rating import Rating
from app.schemas.schemas import BookCreate, BookResponse, BookUpdate, RateBook
from app.services.user_service import get_current_user_id, librarian_required

router = APIRouter(prefix="/books", tags=["Books"])


def is_valid_base64(data: str) -> bool:
    """Перевіряє, чи є рядок дійсним Base64"""
    try:
        if data.startswith(
            "data:image",
        ):  # 🔹 Видаляємо `data:image/png;base64,` якщо є
            print("Detected data:image, stripping prefix")  # 🛠 Логування
            data = data.split(",")[1]
        base64.b64decode(data, validate=True)
        return True
    except Exception as e:
        print(f"❌ Invalid Base64: {e}")  # 🛠 Логування помилки
        return False


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

    # Якщо передано `cover_image`, перевіряємо його коректність
    if book_data.cover_image:
        print("Checking Base64 validity...")
        if not is_valid_base64(book_data.cover_image):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid cover_image format. Expected a valid Base64 string.",
            )
        print("✅ Base64 is valid!")

    new_book = Book(**book_data.model_dump())
    db.add(new_book)
    await db.commit()
    await db.refresh(new_book)
    return new_book


@router.put(
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

    if book_data.cover_image:
        print("Checking Base64 validity...")
        if not is_valid_base64(book_data.cover_image):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid cover_image format. Expected a valid Base64 string.",
            )
        print("✅ Base64 is valid!")

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
    if book.is_reserved or book.is_checked_out:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Book is reserved or checked out",
        )

    await db.delete(book)
    await db.commit()
    return {"message": "Book deleted successfully"}


@router.get("/all", response_model=list[BookResponse])
async def list_books(
    db: AsyncSession = Depends(get_db),
    title: Optional[str] = None,
    author: Optional[str] = None,
    category: Optional[str] = None,
    year: Optional[int] = None,
    language: Optional[str] = None,
):

    stmt = (
        select(Book, func.coalesce(func.avg(Rating.rating), 0).label("average_rating"))
        .outerjoin(Rating)
        .group_by(Book.id)
    )

    if title:
        stmt = stmt.where(Book.title.ilike(f"%{title}%"))
    if author:
        stmt = stmt.where(Book.author.ilike(f"%{author}%"))
    if category:
        stmt = stmt.where(Book.category.ilike(f"%{category}%"))
    if year:
        stmt = stmt.where(Book.year == year)
    if language:
        stmt = stmt.where(Book.language.ilike(f"%{language}%"))

    result = await db.execute(stmt)
    books = result.fetchall()

    if not books:
        raise HTTPException(
            status_code=404,
            detail="No books found with the given criteria.",
        )

    return [
        {
            "id": book.id,
            "title": book.title,
            "author": book.author,
            "year": book.year,
            "category": book.category,
            "language": book.language,
            "description": book.description,
            "is_reserved": book.is_reserved,
            "is_checked_out": book.is_checked_out,
            "average_rating": round(float(average_rating), 1),
            "coverImage": book.cover_image,
        }
        for book, average_rating in books
    ]


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
