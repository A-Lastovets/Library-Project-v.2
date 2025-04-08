from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.comments import Comment
from app.schemas.schemas import CommentResponse, SubCommentResponse


async def get_book_comments(book_id: int, db: AsyncSession) -> list[CommentResponse]:
    stmt = (
        select(Comment)
        .options(
            selectinload(Comment.sub_comments)
            .selectinload(Comment.sub_comments)  # завантажуємо 2 рівень
            .selectinload(Comment.user),
            selectinload(Comment.sub_comments).selectinload(Comment.user),
            selectinload(Comment.user),
        )
        .where(Comment.book_id == book_id, Comment.parent_id.is_(None))
        .order_by(Comment.created_at.desc())
        .limit(10)
    )
    result = await db.execute(stmt)
    comments = result.scalars().all()

    def serialize_subcomments(subs: list[Comment]) -> list[SubCommentResponse]:
        return [
            SubCommentResponse(
                subcomment_id=sub.id,
                subcomment=sub.content,
                author=f"{sub.user.first_name} {sub.user.last_name}",
                created_at=sub.created_at,
                # вкладені sub_comments (другий рівень):
                sub_comments=[
                    SubCommentResponse(
                        subcomment_id=subsub.id,
                        subcomment=subsub.content,
                        author=f"{subsub.user.first_name} {subsub.user.last_name}",
                        created_at=subsub.created_at,
                    )
                    for subsub in sorted(
                        sub.sub_comments or [],
                        key=lambda s: s.created_at,
                    )[:2]
                ],
            )
            for sub in sorted(subs or [], key=lambda s: s.created_at, reverse=True)[:5]
        ]

    comment_response = []
    for comment in comments:
        sub_comments_data = serialize_subcomments(comment.sub_comments)

        comment_response.append(
            CommentResponse(
                comment_id=comment.id,
                comment=comment.content,
                author=f"{comment.user.first_name} {comment.user.last_name}",
                created_at=comment.created_at,
                sub_comments=sub_comments_data,
            ),
        )

    return comment_response
