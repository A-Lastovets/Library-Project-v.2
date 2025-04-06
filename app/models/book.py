from enum import Enum as PyEnum

from sqlalchemy import Column, DateTime
from sqlalchemy import Enum as SAEnum
from sqlalchemy import Integer, String, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import relationship

from app.dependencies.database import Base


class BookStatus(str, PyEnum):
    AVAILABLE = "available"
    RESERVED = "reserved"
    CHECKED_OUT = "checked_out"
    OVERDUE = "overdue"


class Book(Base):
    __tablename__ = "books"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False, index=True)
    author = Column(String, nullable=False, index=True)
    year = Column(Integer, nullable=False, index=True)
    category = Column(ARRAY(String), nullable=False, index=True)
    language = Column(String, nullable=False, index=True)
    description = Column(String, nullable=False)
    cover_image = Column(String, nullable=False)
    status = Column(SAEnum(BookStatus), default=BookStatus.AVAILABLE, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    ratings = relationship(
        "Rating",
        back_populates="book",
        cascade="all, delete-orphan",
    )
    reservations = relationship(
        "Reservation",
        back_populates="book",
        cascade="all, delete-orphan",
    )
