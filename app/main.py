import logging
from contextlib import asynccontextmanager
from logging.config import dictConfig

from fastapi import FastAPI

from app.config import LogConfig
from app.dependencies.database import Base, SessionLocal, engine
from app.middlewares.middlewares import setup_middlewares
from app.roles import create_admin
from app.routers import auth, crud_books, crud_reservation

dictConfig(LogConfig().dict())
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)  # Спочатку створення таблиць

    async with SessionLocal() as db:
        await create_admin(db)  # Створення адміна

    yield


app = FastAPI(
    lifespan=lifespan,
    title="Library API",
    description="API для управління бібліотекою",
    version="1.0",
    swagger_ui_parameters={"persistAuthorization": True},
)

setup_middlewares(app)

app.include_router(auth.router)
app.include_router(crud_books.router)
app.include_router(crud_reservation.router)
