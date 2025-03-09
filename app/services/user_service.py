from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.user import User
from app.utils import decode_jwt_token

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/sign-in-swagger")


# Отримати користувача за email
async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email.lower()))
    return result.scalar_one_or_none()


# Отримати користувача за токеном
def get_current_user_id(token: str = Depends(oauth2_scheme)) -> int:
    """Отримуємо user_id з JWT токена"""
    token_data = decode_jwt_token(token)
    user_id = int(token_data["user_id"])
    print(f"🔹 Отримано user_id: {user_id}")  # Додаємо логування
    return int(token_data["user_id"])


# Аутентифікація користувача
async def authenticate_user(db: AsyncSession, email: str, password: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user or not pwd_context.verify(password, user.hashed_password):
        return None
    return user


async def librarian_required(token: str = Depends(oauth2_scheme)):
    """Перевірка ролі бібліотекаря через JWT-токен."""
    token_data = decode_jwt_token(token)
    role = token_data.get("role")

    if role != "librarian":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Librarian role required",
        )

    return token_data
