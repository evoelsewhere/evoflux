"""Direct EvoFlux Desktop browser bridge endpoints.

The browser surface is a Tauri child WebView. The backend only brokers
session-scoped commands; it does not launch Chromium, expose CDP, or stream a
duplicate screencast of a browser that is already visible in the desktop UI.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket
from pydantic import BaseModel, Field

router = APIRouter()


@router.websocket("/{session_id}/browser/agent")
async def direct_browser_agent_bridge(ws: WebSocket, session_id: str) -> None:
    """Attach the user-visible browser to agent ``browser_use`` calls."""
    from app.services.direct_browser_bridge import direct_browser_bridge

    await ws.accept()
    await direct_browser_bridge.attach(session_id, ws)


@router.websocket("/{session_id}/browser/presence")
async def direct_browser_presence(ws: WebSocket, session_id: str) -> None:
    """Register a desktop chat that can mount its Browser panel on demand."""
    from app.services.direct_browser_bridge import direct_browser_bridge

    await ws.accept()
    await direct_browser_bridge.attach_presence(session_id, ws)


class BrowserTabInfo(BaseModel):
    index: int
    url: str
    title: str = ""


class BrowserSessionResponse(BaseModel):
    """Compatibility status shape for callers of the former CDP endpoint."""

    active: bool
    cdp_url: None = None
    cdp_http: None = None
    current_url: str | None = None
    current_title: str | None = None
    tabs: list[BrowserTabInfo] = Field(default_factory=list)


class DirectBrowserAgentStatus(BaseModel):
    connected: bool
    available: bool


class DirectBrowserCommandRequest(BaseModel):
    action: str
    params: dict[str, Any] = Field(default_factory=dict)


class DirectBrowserCommandResponse(BaseModel):
    result: Any


@router.get("/browser/agent/sessions", response_model=list[str])
async def list_direct_browser_agent_sessions() -> list[str]:
    from app.services.direct_browser_bridge import direct_browser_bridge

    return direct_browser_bridge.available_session_ids()


async def _ensure_mounted(session_id: str) -> None:
    from app.services.direct_browser_bridge import direct_browser_bridge

    if direct_browser_bridge.is_connected(session_id):
        return
    mounted = await direct_browser_bridge.request_mount(session_id)
    if not mounted or not await direct_browser_bridge.wait_connected(session_id):
        raise HTTPException(
            status_code=409,
            detail="EvoFlux Desktop in-app browser is unavailable for this session",
        )


@router.post(
    "/{session_id}/browser/agent/command",
    response_model=DirectBrowserCommandResponse,
)
async def run_direct_browser_agent_command(
    session_id: str,
    body: DirectBrowserCommandRequest,
) -> DirectBrowserCommandResponse:
    from app.services.direct_browser_bridge import direct_browser_bridge

    await _ensure_mounted(session_id)
    try:
        result = await direct_browser_bridge.request(
            session_id, body.action, body.params
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return DirectBrowserCommandResponse(result=result)


@router.get("/{session_id}/browser/agent", response_model=DirectBrowserAgentStatus)
async def get_direct_browser_agent_status(
    session_id: str,
) -> DirectBrowserAgentStatus:
    from app.services.direct_browser_bridge import direct_browser_bridge

    return DirectBrowserAgentStatus(
        connected=direct_browser_bridge.is_connected(session_id),
        available=direct_browser_bridge.is_available(session_id),
    )


@router.get("/{session_id}/browser", response_model=BrowserSessionResponse)
async def get_browser_session(session_id: str) -> BrowserSessionResponse:
    """Return live in-app status without exposing a CDP endpoint."""
    from app.services.direct_browser_bridge import direct_browser_bridge

    if not direct_browser_bridge.is_connected(session_id):
        return BrowserSessionResponse(active=False)
    try:
        status = await direct_browser_bridge.request(session_id, "status", {})
    except Exception:
        return BrowserSessionResponse(active=True)
    if not isinstance(status, dict):
        return BrowserSessionResponse(active=True)
    raw_tabs = status.get("tabs")
    tabs = [BrowserTabInfo.model_validate(tab) for tab in raw_tabs or ()]
    return BrowserSessionResponse(
        active=True,
        current_url=status.get("url") if isinstance(status.get("url"), str) else None,
        current_title=(
            status.get("title") if isinstance(status.get("title"), str) else None
        ),
        tabs=tabs,
    )
