import asyncio
import os
from logging.config import fileConfig

from dotenv import load_dotenv
from sqlalchemy import create_engine
# from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from app.dependencies.database import Base
from app.models.book import Book
from app.models.rating import Rating
from app.models.reservation import Reservation
from app.models.user import User

load_dotenv()
print("[ENV]", os.environ.get("ALEMBIC_DATABASE_URL"))
ALEMBIC_DATABASE_URL = os.getenv("ALEMBIC_DATABASE_URL")
if not ALEMBIC_DATABASE_URL:
    raise ValueError("❌ DATABASE_URL is not set in the environment variables!")

config = context.config

config.set_main_option("sqlalchemy.url", ALEMBIC_DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

if "sslmode" not in ALEMBIC_DATABASE_URL:
    if "?" in ALEMBIC_DATABASE_URL:
        ALEMBIC_DATABASE_URL += "&sslmode=require"
    else:
        ALEMBIC_DATABASE_URL += "?sslmode=require"

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    context.configure(
        url=ALEMBIC_DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(
        ALEMBIC_DATABASE_URL,
        poolclass=None,
        execution_options={"compiled_cache": None},
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
