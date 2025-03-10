import re
import base64
from typing import Optional
from fastapi import HTTPException
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.user_service import get_user_by_email

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


async def update_password(db: AsyncSession, email: str, new_password: str):
    user = await get_user_by_email(db, email)
    if not user:
        return None

    validate_password_schema(new_password)
    user.hashed_password = pwd_context.hash(new_password)
    await db.commit()
    return user


def validate_password(password: str):
    """
    Перевіряє, чи пароль відповідає вимогам безпеки:
    - Мінімум 8 символів
    - Хоча б одна велика літера
    - Хоча б одна цифра
    - Хоча б один спеціальний символ (!@#$%^&*()_+ і т.д.)
    """
    if len(password) < 8:
        raise HTTPException(
            status_code=400,
            detail="Password must be at least 8 characters long.",
        )
    if not re.search(r"[A-Z]", password):
        raise HTTPException(
            status_code=400,
            detail="Password must contain at least one uppercase letter.",
        )
    if not re.search(r"\d", password):
        raise HTTPException(
            status_code=400,
            detail="Password must contain at least one digit.",
        )
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
        raise HTTPException(
            status_code=400,
            detail="Password must contain at least one special character.",
        )
    return password


def validate_password_schema(password: str):
    """
    Версія `validate_password`, яка підходить для використання в Pydantic-схемах
    (викидає ValueError замість HTTPException).
    """
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters long.")
    if not any(c.isupper() for c in password):
        raise ValueError("Password must contain at least one uppercase letter.")
    if not any(c.isdigit() for c in password):
        raise ValueError("Password must contain at least one digit.")
    if not any(c in '!@#$%^&*(),.?":{}|<>' for c in password):
        raise ValueError("Password must contain at least one special character.")
    return password

def is_valid_base64(data: str) -> bool:
    """Перевіряє, чи є рядок дійсним Base64"""
    try:
        if data.startswith(
            "data:image",
        ):  # 🔹 Видаляємо `data:image/png;base64,` якщо є
            print("Detected data:image, stripping prefix")  # 🛠 Логування
            data = data.split(",")[1]
        base64.b64decode(data, validate=True)
        return True
    except Exception as e:
        print(f"❌ Invalid Base64: {e}")  # 🛠 Логування помилки
        return False


def validate_cover_image(cover_image: Optional[str]):
    """Перевіряє коректність cover_image у форматі Base64."""
    if cover_image:
        print("Checking Base64 validity...")
        if not is_valid_base64(cover_image):
            raise HTTPException(
                status_code=400,
                detail="Invalid cover_image format. Expected a valid Base64 string.",
            )
        print("✅ Base64 is valid!")
