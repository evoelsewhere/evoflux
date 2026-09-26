"""Computer App Control bridge endpoints.

The desktop shell performs every capture and input natively; the backend only
brokers session-scoped commands from the ``computer_app`` tool to the chat
that is open in EvoFlux Desktop.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, WebSocket
from pydantic import BaseModel, Field

from app.core.desktop_auth import websocket_authorized

router = APIRouter()


@router.websocket("/{session_id}/computer/agent")
async def direct_computer_agent_bridge(ws: WebSocket, session_id: str) -> None:
    """Attach the desktop shell to agent ``computer_app`` calls."""
    from app.services.direct_computer_bridge import direct_computer_bridge

    if not await websocket_authorized(ws):
        return
    await ws.accept()
    await direct_computer_bridge.attach(session_id, ws)


@router.post("/{session_id}/computer/closed", status_code=204)
async def close_direct_computer_card(session_id: str) -> None:
    """The user closed the session's preview card: the agent may not attach an
    app again until its turn ends."""
    from app.services.direct_computer_bridge import direct_computer_bridge

    direct_computer_bridge.mark_closed(session_id)


class DirectComputerAgentStatus(BaseModel):
    connected: bool
    protocol_version: int = 0
    capabilities: dict[str, Any] = Field(default_factory=dict)


@router.get("/{session_id}/computer/agent", response_model=DirectComputerAgentStatus)
async def get_direct_computer_agent_status(
    session_id: str,
) -> DirectComputerAgentStatus:
    from app.services.direct_computer_bridge import direct_computer_bridge

    protocol_version, capabilities = direct_computer_bridge.connection_info(session_id)
    return DirectComputerAgentStatus(
        connected=direct_computer_bridge.is_connected(session_id),
        protocol_version=protocol_version,
        capabilities=capabilities,
    )
