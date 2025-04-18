import logging
from contextlib import asynccontextmanager
from logging.config import dictConfig

from fastapi import FastAPI

from app.config import LogConfig
from app.dependencies.cache import redis_client
from app.dependencies.database import SessionLocal, init_db
from app.middlewares.middlewares import setup_middlewares
from app.roles import create_admin
from app.routers import auth, crud_books, crud_reservation, statistics

dictConfig(LogConfig().dict())
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управління ресурсами під час життєвого циклу API"""

    try:
        await init_db()  # Створення таблиць БД

        async with SessionLocal() as db:
            await create_admin(db)  # Створення адміна

        redis = await redis_client.get_redis()  # Отримуємо підключення
        if redis:
            logger.info("✅ Redis успішно підключено")
        else:
            logger.error("❌ Не вдалося підключитися до Redis!")

        yield

    except Exception as e:
        logger.error(f"❌ Помилка при запуску сервера: {e}")
        raise e

    finally:
        await redis_client.close_redis()
        logger.info("🔴 Підключення до Redis закрито")


app = FastAPI(
    lifespan=lifespan,
    title="Library API",
    description="API для управління бібліотекою",
    version="1.0",
    swagger_ui_parameters={"persistAuthorization": True},
)

setup_middlewares(app)

app.include_router(auth.router, prefix="/api/v1")
app.include_router(crud_books.router, prefix="/api/v1")
app.include_router(crud_reservation.router, prefix="/api/v1")
app.include_router(statistics.router, prefix="/api/v1")

logger.info("✅ Library API успішно запущено!")
