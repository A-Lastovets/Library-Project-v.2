import json

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.comments import Comment
from app.schemas.schemas import CommentResponse, SubCommentResponse


async def get_book_comments(
    book_id: int,
    db: AsyncSession,
    redis,
) -> list[CommentResponse]:
    cache_key = f"comments:book:{book_id}"

    # Перевірити кеш
    cached = await redis.get(cache_key)
    if cached:
        raw = json.loads(cached)
        return [CommentResponse.model_validate(c) for c in raw]

    # Якщо кешу немає — читаємо з БД
    stmt = (
        select(Comment)
        .options(
            selectinload(Comment.sub_comments).selectinload(Comment.user),
            selectinload(Comment.user),
        )
        .where(Comment.book_id == book_id, Comment.parent_id.is_(None))
        .order_by(Comment.created_at.desc())
    )
    result = await db.execute(stmt)
    comments = result.scalars().all()

    comment_response = []
    for comment in comments:
        sub = next(iter(sorted(comment.sub_comments, key=lambda s: s.created_at)), None)

        sub_comment_data = (
            SubCommentResponse(
                subcomment_id=sub.id,
                subcomment=sub.content,
                author=f"{sub.user.first_name} {sub.user.last_name}",
                author_id=sub.user.id,
                created_at=sub.created_at,
            )
            if sub
            else None
        )

        comment_response.append(
            CommentResponse(
                comment_id=comment.id,
                comment=comment.content,
                author=f"{comment.user.first_name} {comment.user.last_name}",
                author_id=comment.user.id,
                created_at=comment.created_at,
                sub_comment=sub_comment_data,
            ),
        )

    # Кешуємо відповідь на 5 хвилин
    await redis.setex(
        cache_key,
        300,  # 5 хв
        json.dumps([c.model_dump() for c in comment_response], default=str),
    )

    return comment_response
