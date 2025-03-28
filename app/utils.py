from datetime import datetime, timedelta

from fastapi import HTTPException, status
from jose import ExpiredSignatureError, JWTError, jwt

from app.config import config
from app.models.user import User


# Створення JWT токена
def create_access_token(user: User):
    """Створює JWT-токен, що містить всю інформацію про користувача."""
    expires_delta = timedelta(minutes=config.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode = {
        "id": str(user.id),
        "first_name": user.first_name,
        "last_name": user.last_name,
        "email": user.email,
        "role": user.role.value,
        "is_blocked": user.is_blocked,
        "exp": datetime.now() + expires_delta,
    }

    return jwt.encode(to_encode, config.SECRET_KEY, algorithm=config.ALGORITHM)


# Створення refresh JWT токена
def create_refresh_token(user: User):
    """Створює довгостроковий refresh_token, що містить інформацію про користувача."""
    expires_delta = timedelta(days=config.REFRESH_TOKEN_EXPIRE_DAYS)

    to_encode = {
        "id": str(user.id),
        "first_name": user.first_name,
        "last_name": user.last_name,
        "email": user.email,
        "role": user.role.value,
        "is_blocked": user.is_blocked,
        "exp": datetime.now() + expires_delta,
    }

    return jwt.encode(to_encode, config.SECRET_KEY, algorithm=config.ALGORITHM)


# Створення токена для скидання пароля
def create_password_reset_token(email: str):
    """Створює токен для скидання пароля з терміном дії."""
    return jwt.encode(
        {
            "sub": email,
            "exp": datetime.now()
            + timedelta(minutes=config.RESET_TOKEN_EXPIRE_MINUTES),
        },
        config.SECRET_KEY,
        algorithm=config.ALGORITHM,
    )


# Єдина функція для декодування токенів (access і refresh)
def decode_jwt_token(token: str, check_blocked: bool = False):
    """Розшифровує JWT-токен та повертає всі його дані"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate token",
        headers={"WWW-Authenticate": "cookie"},
    )

    try:
        payload = jwt.decode(token, config.SECRET_KEY, algorithms=[config.ALGORITHM])

        user_data = {
            "id": payload.get("id"),
            "first_name": payload.get("first_name"),
            "last_name": payload.get("last_name"),
            "email": payload.get("email"),
            "role": payload.get("role"),
            "is_blocked": payload.get("is_blocked", False),
            "exp": payload.get("exp"),
        }

        # Переконуємось, що всі ключові поля є в токені
        if None in user_data.values():
            raise credentials_exception

        if check_blocked and user_data["is_blocked"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your account is blocked and cannot perform this action.",
            )

        return user_data

    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")

    except JWTError:
        raise credentials_exception
