"""new migration for new db with additional changes(prefix, routes, status by users)

Revision ID: ad8de16f3f7b
Revises: 4369c7c014b8
Create Date: 2025-03-18 22:09:22.734067

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ad8de16f3f7b"
down_revision: Union[str, None] = "4369c7c014b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
