"""retire the ``<sleep>`` text sentinel from saved messages

Revision ID: 00000074
Revises: 00000073
Create Date: 2026-10-07

Waiting is now the ``sleep`` tool call, not a ``<sleep>`` / ``[sleep]`` marker
at the end of an assistant reply, and the runtime no longer recognizes the
marker. Saved history still carries it two ways: raw text in conversations
recorded before the marker moved into metadata, and an ``extra.lifecycle``
flag on those recorded since. Left alone, the first would show a literal
``<sleep>`` in the transcript and teach the model to keep writing it.

Both are cleaned in place: the trailing marker is cut from ``content`` (any
text before it is kept) and ``extra.lifecycle`` is dropped. Rows are never
deleted, so per-message usage and timing stay in the session totals.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "00000074"
down_revision: Union[str, Sequence[str], None] = "00000073"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SENTINELS = ("<sleep>", "[sleep]")

_messages = sa.table(
    "session_messages",
    sa.column("id", sa.Uuid()),
    sa.column("role", sa.String()),
    sa.column("content", sa.Text()),
    sa.column("extra", sa.JSON()),
)


def _strip_sentinel(content: str | None) -> tuple[str | None, bool]:
    trimmed = (content or "").rstrip()
    for sentinel in _SENTINELS:
        if trimmed.endswith(sentinel):
            return (trimmed[: -len(sentinel)].rstrip() or None), True
    return content, False


def upgrade() -> None:
    bind = op.get_bind()
    candidates = bind.execute(
        sa.select(_messages.c.id, _messages.c.content, _messages.c.extra).where(
            _messages.c.role == "assistant",
            sa.or_(
                _messages.c.content.like("%<sleep>%"),
                _messages.c.content.like("%[sleep]%"),
                sa.cast(_messages.c.extra, sa.Text()).like('%"lifecycle"%'),
            ),
        )
    ).all()

    for row_id, content, extra in candidates:
        new_content, content_changed = _strip_sentinel(content)

        new_extra = extra
        extra_changed = False
        if isinstance(extra, dict) and extra.get("lifecycle") == "sleep":
            new_extra = {k: v for k, v in extra.items() if k != "lifecycle"} or None
            extra_changed = True

        if not (content_changed or extra_changed):
            continue
        changes: dict[str, object] = {}
        if content_changed:
            changes["content"] = new_content
        if extra_changed:
            changes["extra"] = new_extra
        bind.execute(
            sa.update(_messages).where(_messages.c.id == row_id).values(**changes)
        )


def downgrade() -> None:
    # The removed markers are not recorded, so they cannot be put back.
    pass
