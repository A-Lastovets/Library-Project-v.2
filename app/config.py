import os
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()


class DatabaseSettings(BaseSettings):
    DATABASE_URL: str


class AuthSettings(BaseSettings):
    SECRET_KEY: str
    ALGORITHM: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int
    RESET_TOKEN_EXPIRE_MINUTES: int
    REFRESH_TOKEN_EXPIRE_DAYS: int


class FrontendSettings(BaseSettings):
    FRONTEND_URL: str

    @property
    def allowed_origins(self) -> list[str]:
        return [url.strip() for url in self.FRONTEND_URLS.split(",")]


class RedisSettings(BaseSettings):
    REDIS_PASSWORD: Optional[str] = None
    REDIS_HOST: str
    REDIS_PORT: int

    @property
    def redis_url(self) -> str:
        password_part = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{password_part}{self.REDIS_HOST}:{self.REDIS_PORT}/0"


class CelerySettings(BaseSettings):
    CELERY_BROKER_URL: Optional[str] = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.CELERY_BROKER_URL:
            redis_settings = RedisSettings()
            self.CELERY_BROKER_URL = redis_settings.redis_url


class SecuritySettings(BaseSettings):
    SECRET_LIBRARIAN_CODE: str


class EmailSettings(BaseSettings):
    SMTP_SERVER: str
    SMTP_PORT: int
    SMTP_USERNAME: str
    SMTP_PASSWORD: str
    EMAIL_FROM: str


class AppSettings(
    DatabaseSettings,
    AuthSettings,
    FrontendSettings,
    RedisSettings,
    CelerySettings,
    SecuritySettings,
    EmailSettings,
):
    class Config:
        env_file = "./.env"
        env_file_encoding = "utf-8"
        extra = "allow"


class LogConfig(BaseSettings):
    LOGGER_NAME: str = "app"
    LOG_FORMAT: str = "%(levelprefix)s | %(asctime)s | %(message)s"
    LOG_LEVEL: str = "DEBUG"

    version: int = 1
    disable_existing_loggers: bool = False
    formatters: Dict[str, Any] = {
        "default": {
            "()": "uvicorn.logging.DefaultFormatter",
            "fmt": LOG_FORMAT,
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    }
    handlers: Dict[str, Any] = {
        "default": {
            "formatter": "default",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stderr",
        },
    }
    loggers: Dict[str, Any] = {
        LOGGER_NAME: {"handlers": ["default"], "level": LOG_LEVEL},
    }


config = AppSettings()
