from sqlalchemy import Column, DateTime, ForeignKey, Integer, func
from sqlalchemy.orm import relationship

from app.dependencies.database import Base


class Wishlist(Base):
    __tablename__ = "wishlist"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(ForeignKey("users.id", ondelete="CASCADE"))
    book_id = Column(ForeignKey("books.id", ondelete="CASCADE"))
    added_at = Column(DateTime, server_default=func.now())

    user = relationship("User", back_populates="wishlist")
    book = relationship("Book")
