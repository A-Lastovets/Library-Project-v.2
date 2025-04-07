from fastapi import Depends, HTTPException, Request, status
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.sql import func
from fastapi.security import OAuth2PasswordBearer
from app.dependencies.database import get_db
from app.models.book import Book, BookStatus
from app.models.reservation import Reservation
from app.models.user import User
from app.utils import decode_jwt_token

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/sign-in-swagger")


# Отримати користувача за email
async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email.lower()))
    return result.scalar_one_or_none()

async def get_current_user_id(
    request: Request,
    token_from_header: str = Depends(oauth2_scheme)
) -> int:
    """Отримуємо user_id з куки або Authorization хедера"""

    token = request.cookies.get("access_token") or token_from_header
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    token_data = decode_jwt_token(token, check_blocked=False)
    return int(token_data["id"])


async def get_active_user_id(
    request: Request,
    token_from_header: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> int:
    """Отримує user_id з токена в куці або в Authorization-хедері. Перевіряє блокування."""

    token = request.cookies.get("access_token") or token_from_header
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    token_data = decode_jwt_token(token, check_blocked=False)
    user_id = int(token_data["id"])

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.is_blocked:
        raise HTTPException(
            status_code=403,
            detail="Your account is blocked and cannot perform this action.",
        )

    return user_id


# # Отримати користувача за токеном без перевірки блокування
# async def get_current_user_id(request: Request) -> int:
#     """Отримуємо user_id з JWT токена в куці"""
#     token = request.cookies.get("access_token")
#     if not token:
#         raise HTTPException(status_code=401, detail="Not authenticated")

#     token_data = decode_jwt_token(token, check_blocked=False)
#     user_id = int(token_data["id"])
#     return user_id


# Отримати користувача за токеном з перевіркою блокування
# async def get_active_user_id(
#     request: Request,
#     db: AsyncSession = Depends(get_db),
# ) -> int:
#     """Отримує user_id тільки якщо користувач існує і не заблокований (читається з куки)"""
#     token = request.cookies.get("access_token")
#     if not token:
#         raise HTTPException(status_code=401, detail="Not authenticated")

#     token_data = decode_jwt_token(token, check_blocked=False)
#     user_id = int(token_data["id"])

#     # 🔍 Перевіряємо статус користувача напряму в БД
#     user = await db.get(User, user_id)
#     if not user:
#         raise HTTPException(status_code=404, detail="User not found")

#     if user.is_blocked:
#         raise HTTPException(
#             status_code=403,
#             detail="Your account is blocked and cannot perform this action.",
#         )

#     return user_id


# Аутентифікація користувача
async def authenticate_user(db: AsyncSession, email: str, password: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user or not pwd_context.verify(password, user.hashed_password):
        return None
    return user


async def librarian_required(
    request: Request,
    token_from_header: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Перевіряє, чи є користувач бібліотекарем та не заблокований (з куки або токена)."""

    token = request.cookies.get("access_token") or token_from_header
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    token_data = decode_jwt_token(token, check_blocked=False)
    user_id = int(token_data["id"])
    role = token_data.get("role")

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.is_blocked:
        raise HTTPException(status_code=403, detail="User is blocked")

    if role != "librarian":
        raise HTTPException(
            status_code=403,
            detail="Access denied: Librarian role required",
        )

    return {"id": user_id, "role": role}


# async def librarian_required(request: Request) -> dict:
#     """Перевіряє, чи є користувач бібліотекарем та не заблокований (з куки)."""
#     token = request.cookies.get("access_token")
#     if not token:
#         raise HTTPException(status_code=401, detail="Not authenticated")

#     token_data = decode_jwt_token(token)
#     librarian_id = token_data.get("id")
#     role = token_data.get("role")

#     if role != "librarian":
#         raise HTTPException(
#             status_code=403,
#             detail="Access denied: Librarian role required",
#         )

#     return {"id": librarian_id, "role": role}


async def check_and_block_user(db: AsyncSession, user_id: int):
    """Перевіряє, чи потрібно заблокувати користувача через прострочені книги."""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    result = await db.execute(
        select(func.count())
        .select_from(Reservation)
        .join(Book, Book.id == Reservation.book_id)
        .where(Reservation.user_id == user_id, Book.status == BookStatus.OVERDUE),
    )
    overdue_books_count = result.scalar()

    if overdue_books_count >= 2:
        user.is_blocked = True
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are blocked due to overdue books. Contact the librarian to unblock.",
        )
