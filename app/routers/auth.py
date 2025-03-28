import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func
from fastapi.responses import JSONResponse
from app.config import config
from app.dependencies.cache import redis_client
from app.dependencies.database import get_db
from app.models.user import User
from app.oauth2 import update_password, validate_password
from app.roles import create_user
from app.schemas.schemas import (
    BulkUpdateRequest,
    BulkUpdateResponse,
    LoginRequest,
    PasswordReset,
    PasswordResetRequest,
    Token,
    UserCreate,
    UserResponse,
)
from app.services.email_tasks import (
    send_password_reset_email,
    send_user_blocked_email,
    send_user_unblocked_email,
    send_welcome_email,
)
from app.services.user_service import (
    authenticate_user,
    get_user_by_email,
    librarian_required,
)
from app.utils import (
    create_access_token,
    create_password_reset_token,
    create_refresh_token,
    decode_jwt_token,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Auth"])


# 🔑 Логін користувача (отримання JWT-токена)
@router.post("/sign-in", response_model=Token, status_code=status.HTTP_200_OK)
async def sign_in(
    request: Request,
    login_data: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """🔐 Вхід користувача — токени в HTTP-only cookies"""

    user = await authenticate_user(db, str(login_data.email), str(login_data.password))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "Invalid Credentials",
                "message": "Invalid email or password. Please check your credentials and try again.",
                "suggestion": "If you forgot your password, use the password recovery option.",
            },
        )

    access_token = create_access_token(user)
    refresh_token = create_refresh_token(user)

    user_data = UserResponse.model_validate(user).model_dump(by_alias=True)

    response = JSONResponse(content={"message": "Login successful", "user": user_data})

    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=True,
        samesite="Lax",
        max_age=3600,  # 1 година
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="Lax",
        max_age=7 * 24 * 60 * 60,  # 7 днів
    )

    return response


# Реєстрація користувача
@router.post("/sign-up", response_model=Token, status_code=status.HTTP_201_CREATED)
async def sign_up(user: UserCreate, db: AsyncSession = Depends(get_db)):
    existing_user = await get_user_by_email(db, user.email)
    if existing_user:
        error_detail = {
            "error": "User Already Exists",
            "message": "A user with this email is already registered.",
            "suggestion": "Try logging in or use password recovery.",
        }
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_detail,
        )

    # Валідація пароля перед створенням користувача
    validate_password(user.password)

    role = (
        "librarian"
        if user.secret_code and user.secret_code.strip() == config.SECRET_LIBRARIAN_CODE
        else "reader"
    )

    created_user = await create_user(db, user, role)

    access_token = create_access_token(created_user)
    refresh_token = create_refresh_token(created_user)

    send_welcome_email(user.email, user.first_name)

    return Token(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
    )


@router.post("/logout", response_model=dict, status_code=200)
async def logout(request: Request, response: Response):
    """🔓 Вихід — видалення HTTP-only cookies та відкликання refresh_token"""

    redis = await redis_client.get_redis()
    refresh_token = request.cookies.get("refresh_token")

    if not refresh_token:
        raise HTTPException(status_code=401, detail="Missing refresh token")

    # Перевіряємо, чи токен вже відкликано
    if await redis.exists(f"blacklist:{refresh_token}"):
        raise HTTPException(status_code=401, detail="Token already revoked")

    try:
        decode_jwt_token(refresh_token)
    except HTTPException:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    # Додаємо у Redis blacklist
    await redis.setex(f"blacklist:{refresh_token}", 7 * 24 * 60 * 60, "revoked")
    logger.info(f"Refresh token revoked: {refresh_token}")

    # Видаляємо куки
    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token")

    return {"message": "Successfully logged out"}


# Запит на скидання пароля
@router.post("/password-recovery", status_code=status.HTTP_200_OK)
async def request_password_reset(
    data: PasswordResetRequest,
    db: AsyncSession = Depends(get_db),
):
    redis = await redis_client.get_redis()
    user = await get_user_by_email(db, data.email)
    # Завжди повертаємо однакове повідомлення для безпеки
    response_message = {
        "message": "If an account with that email exists, a password reset email has been sent.",
    }

    # Якщо користувача немає — одразу повертаємо відповідь
    if not user:
        return response_message

    # Якщо користувач є, створюємо токен і відправляємо email
    token = create_password_reset_token(user.email)
    await redis.setex(
        f"password-reset:{token}",
        config.RESET_TOKEN_EXPIRE_MINUTES * 60,
        user.email,
    )

    reset_link = f"{config.frontend_url_for_links}/auth/reset-password?token={token}"

    send_password_reset_email(user.email, reset_link)

    return response_message


# Скидання пароля (повертаємо оновлену інформацію про користувача)
@router.post("/password-reset", status_code=status.HTTP_200_OK)
async def reset_password(
    data: PasswordReset,
    db: AsyncSession = Depends(get_db),
):
    redis = await redis_client.get_redis()
    try:
        email = await redis.get(f"password-reset:{data.token}")
        if not email:
            logger.warning(f"Invalid or expired token: {data.token}")
            raise HTTPException(status_code=400, detail="Invalid or expired token")

    except Exception as e:
        logger.error(f"Error accessing Redis: {e}")
        raise HTTPException(
            status_code=500,
            detail="Temporary server issue. Try again later. Invalid or expired token.",
        )

    user = await get_user_by_email(db, email)
    if not user:
        logger.warning(f"User not found for email: {email}")
        raise HTTPException(status_code=404, detail="User not found")

    try:
        validate_password(data.new_password)
    except ValueError as e:
        logger.warning(
            f"Invalid password attempt for user {email}: {e}",
        )
        raise HTTPException(status_code=400, detail=str(e))

    if not await update_password(db, user.email, data.new_password):
        logger.error(
            f"Failed to update password for user {email}",
        )  # Лог якщо пароль не змінився
        raise HTTPException(
            status_code=500,
            detail="Could not update password. Try again later.",
        )
    # Видаляємо токен тільки після успішного оновлення пароля
    await redis.delete(f"password-reset:{data.token}")

    logger.info(f"Password reset successful for {email}")
    return {"message": "Password has been reset successfully. Please log in again."}


# Отримати всіх користувачів (тільки для librarian)
@router.get("/users", response_model=dict, status_code=status.HTTP_200_OK)
async def get_all_users(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(librarian_required),
    page: int = Query(1, ge=1, description="Номер сторінки"),
    per_page: int = Query(
        10,
        ge=1,
        le=100,
        description="Кількість записів на сторінку",
    ),
):
    """📋 Отримати всіх користувачів з пагінацією (тільки для librarian)."""

    # Загальна кількість користувачів
    total_users = await db.scalar(select(func.count()).select_from(User))

    # Пагінований вибір
    result = await db.execute(
        select(User).order_by(User.id).limit(per_page).offset((page - 1) * per_page),
    )
    users = result.scalars().all()

    return {
        "total_users": total_users,
        "total_pages": (total_users // per_page) + (1 if total_users % per_page else 0),
        "current_page": page,
        "per_page": per_page,
        "items": [UserResponse.model_validate(user) for user in users],
    }


@router.patch("/users/block", response_model=BulkUpdateResponse)
async def block_users(
    request: BulkUpdateRequest,
    db: AsyncSession = Depends(get_db),
    librarian: dict = Depends(librarian_required),
):
    """Блокування одного або кількох користувачів бібліотекарем."""

    user_ids = request.ids

    if not user_ids:
        raise HTTPException(
            status_code=400,
            detail="No user IDs provided.",
        )

    # Забороняємо блокувати самого себе
    librarian_id = int(librarian["id"])
    if librarian_id in user_ids:
        raise HTTPException(
            status_code=400,
            detail="You cannot block your own account.",
        )

    # Отримуємо користувачів за їх ID
    stmt = select(User).where(User.id.in_(user_ids))
    result = await db.execute(stmt)
    users = result.scalars().all()

    if not users:
        raise HTTPException(
            status_code=404,
            detail="No users found with the given IDs.",
        )

    # Фільтруємо лише тих, хто ще не заблокований
    users_to_block = [user for user in users if not user.is_blocked]

    if not users_to_block:
        raise HTTPException(
            status_code=400,
            detail="All provided users are already blocked.",
        )

    # Блокуємо користувачів
    for user in users_to_block:
        user.is_blocked = True

    await db.commit()

    send_user_blocked_email(user.email, user.first_name)

    return BulkUpdateResponse(
        message="Users blocked successfully",
        updated_items=[user.id for user in users_to_block],
    )


@router.patch("/users/unblock", response_model=BulkUpdateResponse)
async def unblock_users(
    request: BulkUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(librarian_required),
):
    """🔓 Розблокування одного або кількох користувачів бібліотекарем."""

    user_ids = request.ids  # Отримуємо список ID користувачів

    if not user_ids:
        raise HTTPException(
            status_code=400,
            detail="No user IDs provided.",
        )

    # Отримуємо користувачів за їх ID
    stmt = select(User).where(User.id.in_(user_ids))
    result = await db.execute(stmt)
    users = result.scalars().all()

    if not users:
        raise HTTPException(
            status_code=404,
            detail="No users found with the given IDs.",
        )

    # Фільтруємо лише заблокованих користувачів
    users_to_unblock = [user for user in users if user.is_blocked]

    if not users_to_unblock:
        raise HTTPException(
            status_code=400,
            detail="No blocked users found in the provided list.",
        )

    # Розблоковуємо користувачів
    for user in users_to_unblock:
        user.is_blocked = False

    await db.commit()

    send_user_unblocked_email(user.email, user.first_name)

    return BulkUpdateResponse(
        message="Users unblocked successfully",
        updated_items=[user.id for user in users_to_unblock],
    )


@router.post("/refresh-token", status_code=200)
async def refresh_token(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Оновлення access_token з HTTP-only refresh_token cookie"""

    redis = await redis_client.get_redis()
    refresh_token = request.cookies.get("refresh_token")

    if not refresh_token:
        raise HTTPException(status_code=401, detail="Missing refresh token")

    if await redis.exists(f"blacklist:{refresh_token}"):
        raise HTTPException(status_code=401, detail="Refresh token is revoked")

    try:
        token_data = decode_jwt_token(refresh_token)
    except HTTPException:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    result = await db.execute(select(User).where(User.id == int(token_data["id"])))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    new_access_token = create_access_token(user)
    new_refresh_token = create_refresh_token(user)

    # Встановлюємо оновлені токени у куки
    response.set_cookie(
        key="access_token",
        value=new_access_token,
        httponly=True,
        secure=True,
        samesite="Lax",
        max_age=3600,
    )
    response.set_cookie(
        key="refresh_token",
        value=new_refresh_token,
        httponly=True,
        secure=True,
        samesite="Lax",
        max_age=7 * 24 * 60 * 60,
    )

    return {"message": "Access token refreshed"}
