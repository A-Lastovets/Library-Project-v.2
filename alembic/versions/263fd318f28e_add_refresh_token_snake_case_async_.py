"""add refresh_token, snake_case, async alembic settings

Revision ID: 263fd318f28e
Revises:
Create Date: 2025-03-09 16:42:49.921740

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "263fd318f28e"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
