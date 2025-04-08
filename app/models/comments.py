from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import relationship

from app.dependencies.database import Base


class Comment(Base):
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True, index=True)
    book_id = Column(Integer, ForeignKey("books.id", ondelete="CASCADE"))
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    content = Column(Text, nullable=False)
    parent_id = Column(Integer, ForeignKey("comments.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    parent = relationship("Comment", remote_side=[id], back_populates="sub_comments")
    sub_comments = relationship(
        "Comment",
        back_populates="parent",
        cascade="all, delete",
        lazy="selectin",
    )

    book = relationship("Book", back_populates="comments")
    user = relationship("User", back_populates="comments")
