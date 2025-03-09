from datetime import datetime, timedelta

from fastapi import HTTPException, status
from jose import ExpiredSignatureError, JWTError, jwt

from app.config import config


# Створення JWT токена
def create_access_token(user_id: str, role: str):
    """Створює JWT-токен для користувача з ID та роллю."""
    expires_delta = timedelta(minutes=config.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode = {"sub": user_id, "role": role, "exp": datetime.now() + expires_delta}
    return jwt.encode(to_encode, config.SECRET_KEY, algorithm=config.ALGORITHM)


# Створення refresh JWT токена
def create_refresh_token(user_id: str, role: str):
    """Створює довгостроковий refresh_token."""
    expires_delta = timedelta(days=config.REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode = {"sub": user_id, "role": role, "exp": datetime.now() + expires_delta}
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
def decode_jwt_token(token: str):
    """Розшифровує JWT-токен (може бути як access, так і refresh)."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, config.SECRET_KEY, algorithms=[config.ALGORITHM])
        user_id: str = payload.get("sub")
        role: str = payload.get("role")
        if user_id is None or role is None:
            raise credentials_exception
        return {"user_id": user_id, "role": role}

    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")

    except JWTError:
        raise credentials_exception
