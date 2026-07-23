"""repair missing WebBridge interaction dispatch lease column

Revision ID: 00000029
Revises: 00000028
Create Date: 2026-07-23
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models.chat import TZDateTime


revision: str = "00000029"
down_revision: Union[str, Sequence[str], None] = "00000028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("webbridge_interactions")
    }
    if "dispatch_lease_until" not in columns:
        op.add_column(
            "webbridge_interactions",
            sa.Column("dispatch_lease_until", TZDateTime(), nullable=True),
        )


def downgrade() -> None:
    # Revision 00000026 declares this column for clean installs, so preserve it.
    pass
