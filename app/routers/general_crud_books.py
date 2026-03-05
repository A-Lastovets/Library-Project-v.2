from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.dependencies.cache import redis_client
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
        "query_text": query,
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
    redis=Depends(redis_client.get_redis),
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

    comments = await get_book_comments(book_id=book_id, db=db, redis=redis)

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


@router.post("/comments/{book_id}")
async def create_comment(
    book_id: int,
    content: str,
    parent_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
    redis=Depends(redis_client.get_redis),
):
    # Якщо це головний коментар — перевірити обмеження
    if parent_id is None:
        count_query = await db.execute(
            select(func.count()).where(
                Comment.book_id == book_id,
                Comment.parent_id.is_(None),
            ),
        )
        if count_query.scalar() >= 5:
            raise HTTPException(
                status_code=400,
                detail="Максимум 5 головних коментарів",
            )

    else:
        # Перевірити існування батьківського коментаря
        parent = await db.get(Comment, parent_id)
        if not parent:
            raise HTTPException(status_code=404, detail="Parent comment not found")

        if parent.parent_id is not None:
            raise HTTPException(
                status_code=400,
                detail="Неможливо відповісти на субкоментар",
            )

        # Перевірити, чи до parent вже додано сабкоментар
        reply_exists = await db.execute(
            select(Comment).where(Comment.parent_id == parent_id),
        )
        if reply_exists.scalar_one_or_none():
            raise HTTPException(
                status_code=400,
                detail="До цього коментаря вже є відповідь",
            )

    comment = Comment(
        book_id=book_id,
        user_id=user_id,
        content=content,
        parent_id=parent_id,
    )
    db.add(comment)
    await db.commit()
    await db.refresh(comment)

    await redis.delete(f"comments:book:{book_id}")
    user = await db.get(User, user_id)

    return {
        "message": "Comment created" if parent_id is None else "Reply created",
        "comment_id": comment.id,
        "author": f"{user.first_name} {user.last_name}",
        "author_id": user.id,
    }
