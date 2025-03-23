from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from app.config import config

engine = create_async_engine(
    config.DATABASE_URL,
    echo=True,
    future=True,
    connect_args={"ssl": True},
    execution_options={"compiled_cache": None},
)

SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()


async def get_db():
    async with SessionLocal() as session:
        yield session
