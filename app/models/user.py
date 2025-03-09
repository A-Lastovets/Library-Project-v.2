from enum import Enum as PyEnum

from sqlalchemy import Column, Enum, Integer, String
from sqlalchemy.orm import relationship

from app.dependencies.database import Base


class RoleEnum(str, PyEnum):
    reader = "reader"
    librarian = "librarian"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    first_name = Column(String, index=True, nullable=False)
    last_name = Column(String, index=True, nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(
        Enum(RoleEnum, native_enum=False),
        default=RoleEnum.reader,
        nullable=False,
    )

    ratings = relationship(
        "Rating",
        back_populates="user",
        cascade="all, delete-orphan",
    )
