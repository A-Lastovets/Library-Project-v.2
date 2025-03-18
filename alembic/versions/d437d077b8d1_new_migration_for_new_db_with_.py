"""new migration for new db with additional changes(prefix, routes, status by users)

Revision ID: d437d077b8d1
Revises: ad8de16f3f7b
Create Date: 2025-03-18 22:09:51.224376

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d437d077b8d1"
down_revision: Union[str, None] = "ad8de16f3f7b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
