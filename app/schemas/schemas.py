import re
from datetime import datetime
from typing import Annotated, List, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

# from app.config import config
from app.models.book import BookStatus
from app.models.reservation import ReservationStatus
from app.models.user import UserRole
from app.oauth2 import validate_password_schema


# Базова схема для автоматичної конвертації в camelCase
class BaseSchema(BaseModel):
    class Config:
        @staticmethod
        def alias_generator(string: str) -> str:
            """Конвертує snake_case → camelCase"""
            return "".join(
                word.capitalize() if i else word
                for i, word in enumerate(string.split("_"))
            )

        populate_by_name = True
        from_attributes = True


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserBase(BaseSchema):
    first_name: Annotated[str, Field(min_length=3, max_length=50)]
    last_name: Annotated[str, Field(min_length=3, max_length=50)]
    email: EmailStr


class UserCreate(BaseSchema):
    first_name: str = Field(..., min_length=3, max_length=50)
    last_name: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=100)
    confirm_password: str = Field(..., min_length=8, max_length=100)
    secret_code: Optional[str] = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, email: str):
        """Перевіряємо email додатково через regex"""
        pattern = (
            r"^(?!\.)(?!.*\.\.)[a-zA-Z0-9._%+-]+@[a-zA-Z0-9-]{2,63}\.[a-zA-Z]{2,63}$"
        )
        if not re.match(pattern, email):
            raise ValueError("Invalid email format")
        return email

    @field_validator("password")
    @classmethod
    def validate_password(cls, password: str):
        return validate_password_schema(password)

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, confirm_password: str, values):
        """Перевіряємо, чи `password` і `confirmPassword` співпадають."""
        if values.data.get("password") and confirm_password != values.data["password"]:
            raise ValueError("Passwords do not match")
        return confirm_password


class UserResponse(UserBase):
    id: int
    role: UserRole
    is_blocked: bool

    class Config:
        from_attributes = True


class Token(BaseSchema):
    access_token: str
    refresh_token: str
    token_type: str


class PasswordResetRequest(BaseSchema):
    email: EmailStr


class PasswordReset(BaseSchema):
    token: str
    new_password: str = Field(..., min_length=8, max_length=100)

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, new_password: str):
        return validate_password_schema(new_password)


class PasswordChange(BaseSchema):
    old_password: str
    new_password: str
    confirm_new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, new_password: str):
        return validate_password_schema(new_password)

    @field_validator("confirm_new_password")
    @classmethod
    def passwords_match(cls, confirm_new_password: str, values):
        if (
            values.data.get("new_password")
            and confirm_new_password != values.data["new_password"]
        ):
            raise ValueError("New passwords do not match")
        return confirm_new_password


class BookBase(BaseSchema):
    title: str = Field(..., min_length=1, max_length=255)
    author: str = Field(..., min_length=1, max_length=255)
    year: int
    category: List[str]
    language: str
    description: Optional[str] = None
    cover_image: str


class BookCreate(BookBase):
    pass


class BookUpdate(BookBase):
    status: Optional[BookStatus] = None


class BookResponse(BookBase):
    id: int
    status: BookStatus
    average_rating: float = 0.0

    class Config:
        from_attributes = True


class BulkUpdateRequest(BaseModel):
    ids: List[int]


class BulkUpdateResponse(BaseModel):
    message: str
    updated_items: List[int]


class RateBook(BaseModel):
    rating: float = Field(..., ge=0.5, le=5.0, multiple_of=0.1)


class ReservationCreate(BaseModel):
    book_id: int


class ReservationResponse(BaseModel):
    id: int
    book_id: int
    book: Optional[BookBase] = None
    user: UserResponse
    status: ReservationStatus
    cancelled_by: Optional[str] = None
    created_at: datetime
    expires_at: datetime

    class Config:
        from_attributes = True
