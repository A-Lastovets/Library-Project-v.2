from typing import List, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions.book_filters import apply_book_filters
from app.models.book import Book
from app.models.rating import Rating


def format_book_list(books_with_rating: list[tuple[Book, float]]) -> list[dict]:
    return [
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
        for book, average_rating in books_with_rating
    ]


async def get_filtered_books(
    db: AsyncSession,
    filters: dict,
    page: int,
    per_page: int,
) -> tuple[int, list[tuple[Book, float]]]:
    base_stmt = select(Book).outerjoin(Rating).group_by(Book.id)
    base_stmt = apply_book_filters(base_stmt, **filters)

    total_books = await db.scalar(
        select(func.count()).select_from(base_stmt.subquery()),
    )

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

    return total_books, books
