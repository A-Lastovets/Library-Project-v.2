from enum import Enum as PyEnum

from sqlalchemy import Boolean, Column, Enum, Integer, String
from sqlalchemy.orm import relationship

from app.dependencies.database import Base
from app.models.rating import Rating


class UserRole(str, PyEnum):
    READER = "reader"
    LIBRARIAN = "librarian"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    first_name = Column(String, index=True, nullable=False)
    last_name = Column(String, index=True, nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(
        Enum(UserRole, native_enum=False),
        default=UserRole.READER,
        nullable=False,
    )
    is_blocked = Column(Boolean, default=False, nullable=False)

    ratings = relationship(
        "Rating",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    reservations = relationship(
        "Reservation",
        back_populates="user",
        cascade="all, delete-orphan",
    )
