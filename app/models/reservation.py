from enum import Enum as PyEnum

from sqlalchemy import Column, DateTime
from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Integer, func
from sqlalchemy.orm import relationship

from app.dependencies.database import Base


class ReservationStatus(str, PyEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class Reservation(Base):
    __tablename__ = "reservations"

    id = Column(Integer, primary_key=True, index=True)
    book_id = Column(
        Integer,
        ForeignKey("books.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    status = Column(
        SAEnum(ReservationStatus),
        default=ReservationStatus.PENDING,
        nullable=False,
    )
    created_at = Column(DateTime, server_default=func.now())
    expires_at = Column(DateTime, nullable=False)  # Автоматичне скасування через 5 днів

    book = relationship("Book", back_populates="reservations")
    user = relationship("User", back_populates="reservations")
