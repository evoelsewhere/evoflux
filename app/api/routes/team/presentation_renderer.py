"""Desktop WebView bridge used by the HTML-first PPTX renderer."""

from __future__ import annotations

from fastapi import APIRouter, WebSocket

router = APIRouter()


@router.websocket("/{session_id}/presentation-renderer")
async def desktop_presentation_renderer(ws: WebSocket, session_id: str) -> None:
    from app.services.desktop_presentation_bridge import desktop_presentation_bridge

    await ws.accept()
    await desktop_presentation_bridge.attach(session_id, ws)
