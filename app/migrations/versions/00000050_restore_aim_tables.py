"""restore AIM rebuildable index tables

Revision ID: 00000050
Revises: 00000049

Revision 00000043 is published history and remains in the chain because later
revisions depend on it. Restoring AIM therefore gets a new forward migration
that applies the exact inverse table operations from that revision.
"""

from importlib import import_module
from typing import Sequence, Union

revision: str = "00000050"
down_revision: Union[str, Sequence[str], None] = "00000049"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_AIM_REMOVAL_REVISION = "app.migrations.versions.00000043_drop_aim_tables"


def upgrade() -> None:
    import_module(_AIM_REMOVAL_REVISION).downgrade()


def downgrade() -> None:
    import_module(_AIM_REMOVAL_REVISION).upgrade()
