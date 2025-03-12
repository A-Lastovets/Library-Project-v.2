"""Manually update book model

Revision ID: c77ada28189d
Revises:
Create Date: 2025-03-12 20:26:16.514526

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op
from app.models.book import BookStatus

# revision identifiers, used by Alembic.
revision: str = "c77ada28189d"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    # Видаляємо старі колонки
    op.drop_column("books", "is_reserved")
    op.drop_column("books", "is_checked_out")

    # Додаємо новий Enum-стовпець "status"
    op.add_column(
        "books",
        sa.Column(
            "status",
            sa.Enum(BookStatus, name="bookstatus"),
            nullable=False,
            server_default="available",
        ),
    )


def downgrade():
    # Додаємо назад старі колонки (якщо потрібно скасувати міграцію)
    op.add_column(
        "books",
        sa.Column("is_reserved", sa.Boolean(), nullable=True, server_default="false"),
    )
    op.add_column(
        "books",
        sa.Column(
            "is_checked_out",
            sa.Boolean(),
            nullable=True,
            server_default="false",
        ),
    )

    # Видаляємо колонку status
    op.drop_column("books", "status")
