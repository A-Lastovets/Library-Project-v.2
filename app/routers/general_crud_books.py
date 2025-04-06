from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.sql import func

from app.dependencies.database import get_db
from app.exceptions.book_filters import apply_book_filters
from app.exceptions.pagination import paginate_response
from app.models.book import Book
from app.models.rating import Rating
from app.schemas.schemas import BookResponse, RateBook
from app.services.user_service import get_active_user_id, get_current_user_id

router = APIRouter(prefix="/books", tags=["General Books"])


@router.get("/all", response_model=dict, status_code=status.HTTP_200_OK)
async def list_books(
    db: AsyncSession = Depends(get_db),
    _: int = Depends(get_current_user_id),
    title: Optional[str] = None,
    author: Optional[str] = None,
    category: Optional[List[str]] = Query(None),
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
        select(func.coalesce(func.avg(Rating.rating), 0.0)).where(
            Rating.book_id == book_id,
        ),
    )
    average_rating = rating_result.scalar()

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


@router.post("/rate/{book_id}", status_code=status.HTTP_200_OK)
async def rate_book(
    book_id: int,
    rating_data: RateBook,
    db: AsyncSession = Depends(get_db),
    user_id: dict = Depends(get_active_user_id),
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
