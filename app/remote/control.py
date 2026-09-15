"""Mode/model/lead-agent/health/diff control for the phone's /settings,
/health, and /changes commands.

Each write function replicates the exact persistence sequence its HTTP
route sibling already uses (app/api/routes/team/chat.py's
set_session_permission_mode/update_team_session_lead,
app/api/routes/team/webbridge.py's update_browser_session_model), as a
plain async function app/remote/actions.py can call directly — remote
and desktop must stay behaviorally identical, but app/remote/ never
depends on app/api/routes/* except two narrow, deliberate departures:

- list_model_ids/set_model call app.api.routes.agents.get_registry — the
  model catalog has no service-layer equivalent.
- get_health_diagnostics/get_file_diff call
  app.api.routes.health.health_diagnostics and
  app.api.routes.team.git.get_diff_view directly — each already carries
  nontrivial, security-sensitive logic (health's ~250 lines of db/
  provider/team/MCP/disk checks; diff-view's path-traversal guard and
  staged/unstaged/untracked detection) with no service-layer equivalent
  either. Reimplementing either in app/remote/ would risk silently
  diverging from the desktop's own behavior, or worse, subtly
  reintroducing a path-traversal bug. Both are called with explicit
  arguments, never relying on their Depends(...) defaults, which are
  FastAPI dependency-injection sentinels outside a real request.

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
    "set_model",
    "list_model_ids",
    "get_health_diagnostics",
    "get_file_diff",
    "ALLOWED_RESPONSE_MODES",
    "set_response_mode",
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


async def list_model_ids(app_mode: str | None = None, *, limit: int = 5) -> list[str]:
    """A short, catalog-order list of registered model ids — bounded for a
    phone's button row. There is no curated "recommended models" concept
    in the registry today (every provider-visible model is returned
    unbounded), so this is a simple positional cap, not a ranking.

    One deliberate departure from this module's own "service layer only"
    rule: get_registry lives in app.api.routes.agents (a route module),
    not a service — there is no equivalent service-layer function to call
    instead. It is a plain async function with no Request/Depends-injected
    state (its Query(...) annotations are OpenAPI metadata on otherwise
    plain defaults), so calling it directly here is safe.
    """
    from app.api.routes.agents import get_registry

    mode_arg = cast("Literal['work', 'coding'] | None", app_mode)
    registry = await get_registry(mode=mode_arg)
    return [entry.id for entry in registry.models][:limit]


async def set_model(
    db: AsyncSession,
    session_id: str,
    model_id: str,
    *,
    thinking_level: str | None = None,
) -> ControlResult:
    from app.agent.providers.thinking import accepts_thinking_level
    from app.api.routes.agents import get_registry

    try:
        session_uuid = UUID(session_id)
    except ValueError:
        return ControlResult(status="not_found")
    session = await db.get(ChatSession, session_uuid)
    if session is None:
        return ControlResult(status="not_found")

    registry = await get_registry()
    selected = next((entry for entry in registry.models if entry.id == model_id), None)
    if selected is None:
        return ControlResult(status="invalid", detail=model_id)
    if thinking_level is not None and not accepts_thinking_level(
        model_id, thinking_level
    ):
        return ControlResult(status="invalid", detail=thinking_level)

    session.model = model_id
    session.thinking_level = thinking_level
    db.add(session)
    await db.commit()

    return ControlResult(status="ok")


async def get_health_diagnostics() -> dict:
    """The same active health check the desktop UI's Diagnostics screen
    uses, called directly rather than duplicated — see this module's
    docstring for why app/remote/ makes an exception to "service layer
    only" for this one function. Uses read_session_factory (not
    async_session_factory) since this mirrors a GET route — app.core.db's
    own get_session dependency picks the same read lane for GET requests."""
    from app.api.routes.health import health_diagnostics
    from app.core.db import read_session_factory

    async with read_session_factory() as db:
        return await health_diagnostics(session=db)


async def get_file_diff(workspace: str, path: str) -> str:
    """One file's unified diff (staged, unstaged, or untracked-as-additions)
    — delegates to the same route function the desktop UI's diff viewer
    uses, which already carries the path-traversal and staged/unstaged/
    untracked detection logic; reimplementing that here would risk
    subtly reintroducing a path-traversal bug."""
    from app.api.routes.team.git import get_diff_view

    result = await get_diff_view(workspace=workspace, path=path)
    return result.get("diff", "")


#: The two response modes a phone may choose between (AC-55). Unlike
#: ALLOWED_REMOTE_MODES (permission modes, chat-session-scoped), this
#: preference lives on RemotePairing — one phone, one pairing, one
#: notion of how chatty its own turns should be.
ALLOWED_RESPONSE_MODES: tuple[str, ...] = ("summary", "live")


async def set_response_mode(
    db: AsyncSession, pairing_id: str, mode: str
) -> ControlResult:
    if mode not in ALLOWED_RESPONSE_MODES:
        return ControlResult(status="invalid", detail=mode)

    from app.models.remote import RemotePairing

    try:
        pairing_uuid = UUID(pairing_id)
    except ValueError:
        return ControlResult(status="not_found")
    pairing = await db.get(RemotePairing, pairing_uuid)
    if pairing is None:
        return ControlResult(status="not_found")

    pairing.response_mode = mode
    db.add(pairing)
    await db.commit()

    return ControlResult(status="ok")
