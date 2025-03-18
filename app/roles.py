import logging
import os

from fastapi import HTTPException
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.schemas.schemas import UserCreate
from app.services.user_service import get_user_by_email

logger = logging.getLogger("app")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


async def create_admin(db: AsyncSession):
    """Функція для створення адміністратора під час запуску сервера."""

    admin_username = os.getenv("ADMIN_USERNAME", "Admin")
    admin_lastname = "Admin"
    admin_email = os.getenv("ADMIN_EMAIL")
    admin_password = os.getenv("ADMIN_PASS")

    if not admin_email or not admin_password:
        logger.warning(
            "⚠️ ADMIN_EMAIL або ADMIN_PASS не встановлені в .env! Пропускаємо створення адміністратора.",
        )
        return

    # Перевіряємо, чи існує адміністратор з таким email
    result = await db.execute(select(User).where(User.email == admin_email))
    existing_admin = result.scalar_one_or_none()

    if existing_admin:
        logger.info(
            f"✅ Адміністратор {admin_username} вже існує. Пропускаємо створення.",
        )
        return

    # Створюємо адміністратора
    admin = User(
        first_name=admin_username,
        last_name=admin_lastname,
        email=admin_email,
        hashed_password=pwd_context.hash(admin_password),
        role="librarian",
        is_blocked=False,
    )

    db.add(admin)
    await db.commit()
    logger.info(f"🆕 Адміністратор {admin_username} створений успішно!")


async def create_user(db: AsyncSession, user_data: UserCreate, role: str):
    """Створення користувача без явної валідації пароля (бо вона вже в `UserCreate`)."""

    existing_user = await get_user_by_email(db, user_data.email)
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        first_name=user_data.first_name.capitalize(),
        last_name=user_data.last_name.capitalize(),
        email=user_data.email.lower(),
        hashed_password=pwd_context.hash(user_data.password),
        role=role,
        is_blocked=False,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user
