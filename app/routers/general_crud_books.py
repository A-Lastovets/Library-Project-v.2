from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.dependencies.database import get_db
from app.exceptions.pagination import paginate_response
from app.models.book import Book
from app.models.comments import Comment
from app.models.rating import Rating
from app.models.user import User
from app.schemas.schemas import (
    BookResponse,
    MyRate,
    MyRateResponse,
    RateBook,
    RateBookResponse,
)
from app.services.books_service import format_book_list, get_filtered_books
from app.services.comments_service import get_book_comments
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

    filters = {
        "title": title,
        "author": author,
        "category": category,
        "year": year,
        "language": language,
        "status": status,
        "query": query,
    }

    total, books = await get_filtered_books(db, filters, page, per_page)
    book_list = format_book_list(books)

    return paginate_response(total, page, per_page, book_list)


# Отримати одну книгу за ID
@router.get(
    "/find/{book_id}",
    response_model=BookResponse,
    status_code=status.HTTP_200_OK,
)
async def find_book(
    book_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
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

    user_rating_result = await db.execute(
        select(Rating).where(Rating.book_id == book_id, Rating.user_id == user_id),
    )
    user_rating = user_rating_result.scalar_one_or_none()

    my_rate = MyRate(
        id_rating=user_rating.id if user_rating else None,
        value=user_rating.rating if user_rating else None,
        can_rate=user_rating is None,
    )

    comments = await get_book_comments(book_id=book_id, db=db)

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
        my_rate=my_rate,
        comments=comments,
    )


@router.post(
    "/rate/{book_id}",
    response_model=RateBookResponse,
    status_code=status.HTTP_200_OK,
)
async def rate_book(
    book_id: int,
    rating_data: RateBook,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_active_user_id),
):
    """Додати або оновити рейтинг книги"""
    book = await db.get(Book, book_id)
    if not book:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Book not found",
        )

    # Шукаємо існуючий рейтинг
    stmt = select(Rating).where(Rating.book_id == book_id, Rating.user_id == user_id)
    result = await db.execute(stmt)
    existing_rating = result.scalars().first()

    if existing_rating:
        existing_rating.rating = rating_data.rating  # оновлюємо рейтинг
        await db.commit()
        await db.refresh(existing_rating)
        return RateBookResponse(
            my_rate=MyRateResponse(
                id_rating=existing_rating.id,
                value=existing_rating.rating,
                can_rate=False,
            ),
        )

    # Якщо ще не голосував — створюємо новий рейтинг
    new_rating = Rating(book_id=book_id, user_id=user_id, rating=rating_data.rating)
    db.add(new_rating)
    await db.commit()
    await db.refresh(new_rating)

    return RateBookResponse(
        my_rate=MyRateResponse(
            id_rating=new_rating.id,
            value=new_rating.rating,
            can_rate=False,
        ),
    )


@router.post("/comment/{book_id}")
async def add_comment(
    book_id: int,
    content: str,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_active_user_id),
):
    comment = Comment(book_id=book_id, user_id=user_id, content=content)
    db.add(comment)
    await db.commit()
    await db.refresh(comment)

    user = await db.get(User, user_id)
    author = f"{user.first_name} {user.last_name}" if user else "Unknown user"

    return {
        "message": "Comment added",
        "comment_id": comment.id,
        "author": author,
    }


@router.post("/comment/{comment_id}/reply")
async def reply_comment(
    comment_id: int,
    content: str,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_active_user_id),
):
    parent_comment = await db.get(Comment, comment_id)
    if not parent_comment:
        raise HTTPException(status_code=404, detail="Parent comment not found")

    reply = Comment(
        book_id=parent_comment.book_id,
        user_id=user_id,
        content=content,
        parent_id=comment_id,
    )
    db.add(reply)
    await db.commit()
    await db.refresh(reply)
    user = await db.get(User, user_id)
    author = f"{user.first_name} {user.last_name}" if user else "Unknown user"

    return {
        "message": "Reply added",
        "subcomment_id": reply.id,
        "author": author,
    }
