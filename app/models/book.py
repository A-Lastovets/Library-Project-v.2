from sqlalchemy import Boolean, Column, DateTime, Integer, String, func
from sqlalchemy.orm import relationship

from app.dependencies.database import Base


class Book(Base):
    __tablename__ = "books"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False, index=True)
    author = Column(String, nullable=False, index=True)
    year = Column(Integer, nullable=False, index=True)
    category = Column(String, nullable=False, index=True)
    language = Column(String, nullable=False, index=True)
    description = Column(String, nullable=False)
    cover_image = Column(String, nullable=True)
    is_reserved = Column(Boolean, default=False)
    is_checked_out = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    ratings = relationship(
        "Rating",
        back_populates="book",
        cascade="all, delete-orphan",
    )
