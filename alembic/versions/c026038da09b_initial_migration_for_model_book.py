"""Initial migration for model book

Revision ID: c026038da09b
Revises: cc2e72d98ecf
Create Date: 2025-03-23 17:40:25.445241

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c026038da09b"
down_revision: Union[str, None] = "cc2e72d98ecf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
