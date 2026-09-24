from __future__ import annotations

from uuid import uuid4

import sqlalchemy as sa

from app.models.remote import RemoteConnection, RemotePairing


def test_remote_pairing_keeps_authorization_and_destination_separate() -> None:
    pairing = RemotePairing(
        connection_id=uuid4(),
        principal_id="telegram-user-1",
        destination_id="telegram-chat-9",
        label="My phone",
    )

    assert pairing.principal_id == "telegram-user-1"
    assert pairing.destination_id == "telegram-chat-9"


def test_remote_schema_is_connection_aware_without_v1_singleton_constraint() -> None:
    connection_table = RemoteConnection.__table__
    pairing_table = RemotePairing.__table__

    assert connection_table.name == "remote_connections"
    assert pairing_table.name == "remote_pairings"
    assert "connection_id" in pairing_table.c

    connection_unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in connection_table.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    }
    pairing_unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in pairing_table.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    }

    assert ("adapter",) not in connection_unique_columns
    assert ("connection_id", "principal_id") in pairing_unique_columns
    assert ("connection_id", "destination_id") in pairing_unique_columns
