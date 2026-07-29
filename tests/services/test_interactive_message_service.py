from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.models.chat import ChatSession
from app.services import interactive_message_service


@pytest.mark.asyncio
@pytest.mark.parametrize("reset_to_default", [False, True])
async def test_forge_interactive_restore_syncs_persisted_workspace(
    setup_db, monkeypatch, tmp_path, reset_to_default
):
    from app.core import db as db_module

    session_id = uuid.uuid7()
    selected = tmp_path / "forge-interactive-workspace"
    selected.mkdir()
    persisted_workspace = None if reset_to_default else str(selected)

    async with db_module.async_session_factory() as db:
        db.add(
            ChatSession(
                id=session_id,
                agent_name="lead",
                mode="forge",
                workspace=persisted_workspace,
            )
        )
        await db.commit()

    team = SimpleNamespace(
        workspace=str(selected) if reset_to_default else None,
        session_tags=frozenset(),
        permission_mode="auto",
    )

    async def get_team(_session_id: str):
        return team

    monkeypatch.setattr(
        "app.services.team_manager.get_or_start_team_for_session",
        get_team,
    )

    async with db_module.async_session_factory() as db:
        (
            session,
            restored_team,
        ) = await interactive_message_service.resolve_team_for_session(
            db,
            str(session_id),
            require_existing=True,
        )

    assert session is not None
    assert restored_team is team
    assert team.workspace == persisted_workspace
