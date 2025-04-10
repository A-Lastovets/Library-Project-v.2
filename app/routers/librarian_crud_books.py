from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.dependencies.cache import redis_client
from app.dependencies.database import get_db
from app.exceptions.pagination import paginate_response
from app.exceptions.serialization import serialize_book_with_user_reservation
from app.exceptions.subquery_reserv import get_latest_reservation_alias
from app.models.book import Book, BookStatus
from app.models.comments import Comment
from app.models.user import User
from app.schemas.schemas import (
    BookCreate,
    BookResponse,
    BookUpdate,
    BulkUpdateRequest,
    BulkUpdateResponse,
)
from app.services.comments_service import get_book_comments
from app.services.user_service import librarian_required

router = APIRouter(prefix="/books", tags=["Librarian Books"])


@router.post(
    "",
    response_model=BookResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_book(
    book_data: BookCreate,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(librarian_required),
    redis=Depends(redis_client.get_redis),
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

    data = book_data.model_dump()
    new_book = Book(**data)

    db.add(new_book)
    await db.commit()
    await db.refresh(new_book)

    comments = await get_book_comments(book_id=new_book.id, db=db, redis=redis)

    return BookResponse(
        id=new_book.id,
        title=new_book.title,
        author=new_book.author,
        year=new_book.year,
        category=new_book.category,
        language=new_book.language,
        description=new_book.description,
        cover_image=new_book.cover_image,
        status=new_book.status,
        average_rating=0.0,
        my_rate={"id_rating": None, "value": None, "can_rate": True},
        comments=comments,
    )


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
    redis=Depends(redis_client.get_redis),
):
    """Оновлення книги (тільки бібліотекар)."""
    book = await db.get(Book, book_id)
    if not book:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Book not found",
        )

    update_data = book_data.model_dump(exclude_unset=True)

    for key, value in update_data.items():
        setattr(book, key, value)

    await db.commit()
    await db.refresh(book)

    comments = await get_book_comments(book_id=book.id, db=db, redis=redis)

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
        average_rating=0.0,
        my_rate={"id_rating": None, "value": None, "can_rate": True},
        comments=comments,
    )


@router.delete(
    "",
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


@router.delete("/librarian/comments/{comment_id}")
async def delete_comment_by_librarian(
    comment_id: int,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(librarian_required),
    redis=Depends(redis_client.get_redis),
):
    comment = await db.get(Comment, comment_id)
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    book_id = comment.book_id

    # Якщо головний — видаляємо саб (якщо є)
    if comment.parent_id is None:
        sub_result = await db.execute(
            select(Comment).where(Comment.parent_id == comment_id),
        )
        sub_comment = sub_result.scalar_one_or_none()
        if sub_comment:
            await db.delete(sub_comment)

    await db.delete(comment)
    await db.commit()
    await redis.delete(f"comments:book:{book_id}")

    return {"message": "Comment deleted by librarian"}


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
