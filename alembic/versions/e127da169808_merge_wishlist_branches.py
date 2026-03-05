"""merge wishlist branches

Revision ID: e127da169808
Revises: 1484035ba1bf, 39dff8215af5, c77ada28189d
Create Date: 2025-04-06 13:34:09.423791

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e127da169808'
down_revision: Union[str, None] = ('1484035ba1bf', '39dff8215af5', 'c77ada28189d')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
