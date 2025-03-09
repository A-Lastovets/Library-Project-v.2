import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import config
from app.dependencies.cache import redis_client
from app.dependencies.database import get_db
from app.models.user import RoleEnum, User
from app.oauth2 import update_password, validate_password
from app.roles import create_user
from app.schemas.schemas import (
    LoginRequest,
    PasswordReset,
    PasswordResetRequest,
    Token,
    UserCreate,
    UserResponse,
)
from app.services.email_tasks import send_password_reset_email
from app.services.user_service import (
    authenticate_user,
    get_user_by_email,
)
from app.utils import (
    create_access_token,
    create_password_reset_token,
    create_refresh_token,
    decode_jwt_token,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/sign-in-swagger")


# 🔑 Логін користувача (отримання JWT-токена)
@router.post("/sign-in", response_model=Token, status_code=status.HTTP_200_OK)
async def sign_in(
    request: Request,
    login_data: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """✅ Вхід через JSON"""

    raw_body = await request.json()
    print("Received raw JSON:", raw_body)

    try:
        login_data = LoginRequest(**raw_body)
        print("Parsed LoginRequest:", login_data.model_dump())
    except ValidationError as e:
        print("Validation Error:", e.json())  # Логи для дебагу
        raise HTTPException(status_code=422, detail=e.errors())

    if login_data.email is None or login_data.password is None:
        raise HTTPException(status_code=400, detail="Email and password are required")

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

    access_token = create_access_token(
        user_id=str(user.id),
        role=user.role.value,
    )

    refresh_token = create_refresh_token(user_id=str(user.id), role=user.role.value)

    return Token(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        user=UserResponse(
            id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
            role=user.role.value,
        ),
    )


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

    # Визначення ролі користувача (лікар або читач)
    role = (
        "librarian"
        if user.secret_code and user.secret_code.strip() == config.SECRET_LIBRARIAN_CODE
        else "reader"
    )

    # Створюємо користувача
    created_user = await create_user(db, user, role)

    # Генеруємо токен після реєстрації
    access_token = create_access_token(
        user_id=str(created_user.id),
        role=created_user.role.value,
    )

    refresh_token = create_refresh_token(
        user_id=str(created_user.id),
        role=created_user.role.value,
    )

    # Використовуємо `Token` як response_model
    return Token(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        user=UserResponse(
            id=created_user.id,
            first_name=created_user.first_name,
            last_name=created_user.last_name,
            email=created_user.email,
            role=created_user.role.value,
        ),
    )


# Запит на скидання пароля
@router.post("/password-recovery", status_code=status.HTTP_200_OK)
async def request_password_reset(
    data: PasswordResetRequest,
    db: AsyncSession = Depends(get_db),
):
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
    await redis_client.setex(
        f"password-reset:{token}",
        config.RESET_TOKEN_EXPIRE_MINUTES * 60,
        user.email,
    )

    reset_link = f"{config.FRONTEND_URL}/reset-password?token={token}"
    send_password_reset_email(user.email, reset_link)

    return response_message


# Скидання пароля (повертаємо оновлену інформацію про користувача)
@router.post("/password-reset", status_code=status.HTTP_200_OK)
async def reset_password(data: PasswordReset, db: AsyncSession = Depends(get_db)):
    try:
        email = await redis_client.get(f"password-reset:{data.token}")
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
    await redis_client.delete(f"password-reset:{data.token}")

    logger.info(f"Password reset successful for {email}")
    return {"message": "Password has been reset successfully. Please log in again."}


# Отримати всіх користувачів (тільки для librarian)
@router.get("/users", response_model=list[UserResponse], status_code=status.HTTP_200_OK)
async def get_all_users(
    db: AsyncSession = Depends(get_db),
    token: str = Depends(oauth2_scheme),
):
    """Отримати всіх користувачів (тільки для librarian)."""

    token_data = decode_jwt_token(token)
    role = token_data["role"]

    if role != RoleEnum.librarian:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions",
        )

    result = await db.execute(select(User))
    users = result.scalars().all()

    return [
        UserResponse(
            id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
            role=user.role.value,
        )
        for user in users
    ]


# 🔑 Логін через Swagger UI (OAuth2 Password Flow)
@router.post(
    "/sign-in-swagger",
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
async def sign_in_swagger(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """🔄 Вхід через Swagger UI (OAuth2 Password Flow)"""

    email = form_data.username
    password = form_data.password

    user = await authenticate_user(db, email, password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    access_token = create_access_token(
        user_id=str(user.id),
        role=user.role.value,
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
    }


@router.post("/refresh-token", response_model=Token, status_code=200)
async def refresh_token(refresh_token: str, db: AsyncSession = Depends(get_db)):
    """✅ Оновлення `access_token` за допомогою `refresh_token`"""

    try:
        token_data = decode_jwt_token(refresh_token)
    except HTTPException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    user_id = token_data["user_id"]
    role = token_data["role"]

    # Отримуємо користувача з БД (переконуємось, що користувач існує)
    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Створюємо нові токени
    new_access_token = create_access_token(
        user_id=str(user.id),
        role=role,
    )

    new_refresh_token = create_refresh_token(
        user_id=str(user.id),
        role=token_data["role"],
    )

    return Token(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
        user=UserResponse(
            id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
            role=user.role.value,
        ),
    )
