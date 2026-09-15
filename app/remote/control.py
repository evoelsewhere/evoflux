"""Mode/model/lead-agent control for the phone's /settings command.

Each write function replicates the exact persistence sequence its HTTP
route sibling already uses (app/api/routes/team/chat.py's
set_session_permission_mode/update_team_session_lead,
app/api/routes/team/webbridge.py's update_browser_session_model), as a
plain async function app/remote/actions.py can call directly — remote
and desktop must stay behaviorally identical, but app/remote/ never
depends on app/api/routes/* (see list_model_ids/set_model for the one
deliberate departure: the model registry).

bypass is deliberately excluded from ALLOWED_REMOTE_MODES, checked by
name (not by list length or position) before anything else runs — a
phone that could enable bypass could silently disable every approval
prompt an operator relies on (AC-48).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast
from uuid import UUID

from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.chat import ChatSession

__all__ = [
    "ALLOWED_REMOTE_MODES",
    "ControlResult",
    "set_permission_mode",
    "set_lead_agent",
    "list_lead_names",
]

#: Every permission mode this phone may set — bypass excluded on purpose.
ALLOWED_REMOTE_MODES: tuple[str, ...] = ("ask", "accept-edits", "plan", "auto")

ControlStatus = Literal["ok", "invalid", "not_found", "conflict"]


@dataclass(frozen=True)
class ControlResult:
    """A bounded, adapter-neutral outcome for one control write."""

    status: ControlStatus
    detail: str = ""


async def set_permission_mode(
    db: AsyncSession, session_id: str, mode: str
) -> ControlResult:
    if mode not in ALLOWED_REMOTE_MODES:
        return ControlResult(status="invalid", detail=mode)

    try:
        session_uuid = UUID(session_id)
    except ValueError:
        return ControlResult(status="not_found")
    session = await db.get(ChatSession, session_uuid)
    if session is None:
        return ControlResult(status="not_found")

    session.permission_mode = mode
    session_mode = session.mode
    session_workspace = session.workspace
    db.add(session)
    await db.commit()

    from app.services import team_manager

    team_obj = team_manager.current_team_for_session(session_id)
    if team_obj is None and session_mode == "coding" and session_workspace:
        team_obj = team_manager.current_coding_team_for_session(
            session_workspace, session_id
        )
    if team_obj is not None:
        team_obj.permission_mode = mode

    from app.agent.permission import Mode, get_services_for_stream

    for service in get_services_for_stream(session_id):
        service.set_mode(cast(Mode, mode))

    return ControlResult(status="ok")


async def list_lead_names(app_mode: str, *, limit: int = 5) -> list[str]:
    """A short, stable-order list of configured lead-agent names for
    *app_mode* ("work"/"coding") — bounded for a phone's button row, same
    pattern already used for workflow/project menu items in actions.py."""
    from app.services import team_manager

    try:
        _default_lead, rosters = team_manager.configured_lead_rosters(app_mode)
    except ValueError:
        return []
    return [lead.name for lead, _path, _members in rosters][:limit]


async def set_lead_agent(
    db: AsyncSession, session_id: str, lead_name: str
) -> ControlResult:
    from app.models.chat import normalize_mode
    from app.services import memory_stream_store as stream_store
    from app.services import team_manager

    try:
        session_uuid = UUID(session_id)
    except ValueError:
        return ControlResult(status="not_found")
    session = await db.get(ChatSession, session_uuid)
    if session is None:
        return ControlResult(status="not_found")
    if session.parent_session_id is not None:
        return ControlResult(status="not_found")

    live_team = team_manager.find_team_for_session(session_id)
    if session_id in stream_store.running_session_ids() or (
        live_team is not None
        and any(member.state == "working" for member in live_team.all_members)
    ):
        return ControlResult(
            status="conflict",
            detail="Finish or stop the active task before changing lead.",
        )

    app_mode = normalize_mode(session.mode)
    try:
        selected = team_manager.resolve_configured_lead(app_mode, lead_name)
    except ValueError as exc:
        return ControlResult(status="invalid", detail=str(exc))

    if session.agent_name != selected:
        session.agent_name = selected
        db.add(session)
        await db.commit()
        await db.refresh(session)
        await team_manager.stop_sessions({session_id})

    return ControlResult(status="ok")
