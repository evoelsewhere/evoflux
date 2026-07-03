"""Browser session status + screencast WebSocket endpoint.

Provides:
- ``GET  /{session_id}/browser`` — one-shot JSON status
- ``WS   /{session_id}/browser/screencast`` — live JPEG frame stream
"""

from __future__ import annotations

import asyncio
import base64
import json
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger
from pydantic import BaseModel, Field

router = APIRouter()

# Screencast config
_FRAME_INTERVAL = 0.2  # 5 fps
_JPEG_QUALITY = 60
_MAX_WIDTH = 1280


# ── REST endpoint ────────────────────────────────────────────────────────────


class BrowserTabInfo(BaseModel):
    index: int
    url: str
    title: str


class BrowserSessionResponse(BaseModel):
    active: bool
    cdp_url: str | None = None
    cdp_http: str | None = None
    current_url: str | None = None
    current_title: str | None = None
    tabs: list[BrowserTabInfo] = Field(default_factory=list)


@router.get("/{session_id}/browser")
async def get_browser_session(session_id: str) -> BrowserSessionResponse:
    """Return the live browser session info for *session_id*.

    Includes the CDP WebSocket URL (``cdp_url``), the HTTP equivalent
    (``cdp_http``), the current page URL/title, and all open tabs.

    Returns ``active: false`` when no browser session is running for this
    agent session.
    """
    from app.agent.tools.builtin.browser_use_tool import get_browser_info

    info = get_browser_info(session_id)
    if info is None:
        return BrowserSessionResponse(active=False)

    tabs = [
        BrowserTabInfo(
            index=t.get("index", i),
            url=t.get("url", ""),
            title=t.get("title", ""),
        )
        for i, t in enumerate(info.get("tabs", []))
    ]
    return BrowserSessionResponse(
        active=True,
        cdp_url=info.get("cdp_url"),
        cdp_http=info.get("cdp_http"),
        current_url=info.get("current_url"),
        current_title=info.get("current_title"),
        tabs=tabs,
    )


# ── Screencast WebSocket ─────────────────────────────────────────────────────


async def _capture_frame(page: Any) -> bytes | None:
    """Capture a JPEG screenshot from the page, or ``None`` on failure."""
    try:
        b64 = await page.screenshot(format="jpeg", quality=_JPEG_QUALITY)
        return base64.b64decode(b64)
    except Exception:
        return None


async def _build_control_message(session_id: str) -> str:
    """Build a JSON control frame with current browser metadata."""
    from app.agent.tools.builtin.browser_use_tool import (
        get_browser_info,
        get_browser_page,
        get_browser_session,
    )

    info = get_browser_info(session_id)
    if info is None:
        return json.dumps({"type": "status", "active": False})

    page = get_browser_page(session_id)
    session = get_browser_session(session_id)

    url = None
    title = None
    if page:
        try:
            url = await page.get_url()
            title = await page.get_title()
        except Exception:
            pass

    tabs: list[dict] = []
    if session:
        try:
            pages = await session.get_pages()
            for i, p in enumerate(pages):
                t_url = await p.get_url()
                t_title = await p.get_title()
                tabs.append({"index": i, "url": t_url, "title": t_title})
        except Exception:
            pass

    return json.dumps(
        {
            "type": "status",
            "active": True,
            "url": url,
            "title": title,
            "tabs": tabs,
            "cdp_http": info.get("cdp_http"),
        }
    )


@router.websocket("/{session_id}/browser/screencast")
async def browser_screencast(ws: WebSocket, session_id: str) -> None:
    """Stream JPEG screenshots at ~5 fps over a WebSocket.

    Protocol
    --------
    Server → Client:
    - **Binary frame**: raw JPEG bytes (one screenshot)
    - **JSON text frame**: ``{"type": "status", "active": true, "url": "...",
      "title": "...", "tabs": [...]}`` — sent after every frame so the
      client can update its URL bar and tab list without a separate request.

    Client → Server:
    - ``{"action": "navigate", "url": "..."}`` — navigate to URL
    - ``{"action": "back"}`` — history back
    - ``{"action": "forward"}`` — history forward
    - ``{"action": "reload"}`` — reload current page
    - ``{"action": "switch_tab", "index": N}`` — switch to tab N
    - ``{"action": "stop"}`` — close the browser session
    - ``{"action": "click", "x": N, "y": N, "button": "left"}`` — click at coordinates
    - ``{"action": "dblclick", "x": N, "y": N}`` — double-click at coordinates
    - ``{"action": "type", "text": "..."}`` — type text (keyboard.press)
    - ``{"action": "key", "key": "Enter"}`` — press a key
    - ``{"action": "scroll", "dx": N, "dy": N}`` — scroll by delta
    - ``{"action": "mouse_move", "x": N, "y": N}`` — move mouse cursor
    """
    await ws.accept()
    logger.debug("screencast_ws_open session_id={}", session_id)

    try:
        while True:
            from app.agent.tools.builtin.browser_use_tool import get_browser_page

            page = get_browser_page(session_id)

            if page is None:
                # Browser not active — send status and wait
                await ws.send_text(json.dumps({"type": "status", "active": False}))
                await asyncio.sleep(1.0)
                # Check for client messages (e.g. to close)
                try:
                    raw = await asyncio.wait_for(ws.receive_text(), timeout=0.1)
                    await _handle_client_message(raw, session_id)
                except (asyncio.TimeoutError, Exception):
                    pass
                continue

            # Capture and send frame
            frame = await _capture_frame(page)
            if frame:
                await ws.send_bytes(frame)

            # Send control message
            ctrl = await _build_control_message(session_id)
            await ws.send_text(ctrl)

            # Drain client messages (non-blocking)
            try:
                raw = await asyncio.wait_for(ws.receive_text(), timeout=0.01)
                await _handle_client_message(raw, session_id)
            except asyncio.TimeoutError:
                pass

            # Pace to target frame rate
            await asyncio.sleep(_FRAME_INTERVAL)

    except WebSocketDisconnect:
        logger.debug("screencast_ws_close session_id={}", session_id)
    except Exception as e:
        logger.debug("screencast_ws_error session_id={} error={}", session_id, e)
    finally:
        try:
            await ws.close()
        except Exception:
            pass


async def _handle_client_message(raw: str, session_id: str) -> None:
    """Handle a JSON message from the screencast client."""
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        return

    action = msg.get("action")

    if action == "navigate":
        url = msg.get("url")
        if isinstance(url, str) and url:
            page = _get_page(session_id)
            if page:
                try:
                    await page.goto(url)
                except Exception as e:
                    logger.debug(
                        "screencast_navigate_error session_id={} error={}",
                        session_id,
                        e,
                    )

    elif action == "back":
        page = _get_page(session_id)
        if page:
            try:
                await page.go_back()
            except Exception:
                pass

    elif action == "forward":
        page = _get_page(session_id)
        if page:
            try:
                await page.go_forward()
            except Exception:
                pass

    elif action == "reload":
        page = _get_page(session_id)
        if page:
            try:
                await page.reload()
            except Exception:
                pass

    elif action == "switch_tab":
        index = msg.get("index")
        if isinstance(index, int):
            from app.agent.tools.builtin.browser_use_tool import get_browser_session

            session = get_browser_session(session_id)
            if session:
                try:
                    pages = await session.get_pages()
                    if 0 <= index < len(pages):
                        from app.agent.tools.builtin.browser_use_tool import (
                            _pages,
                            _refresh_cdp_info,
                        )

                        _pages[session_id] = pages[index]
                        await _refresh_cdp_info(
                            session_id,
                            session,
                            pages[index],
                            action="tab_switched",
                        )
                except Exception as e:
                    logger.debug(
                        "screencast_switch_tab_error session_id={} error={}",
                        session_id,
                        e,
                    )

    elif action == "stop":
        from app.agent.tools.builtin.browser_use_tool import _close_session

        # Build a minimal state shim for _close_session
        class _Shim:
            metadata: dict = {"session_id": session_id}

        await _close_session(_Shim())

    # ── User interaction forwarding (M8) ────────────────────────────

    elif action == "click":
        x = msg.get("x")
        y = msg.get("y")
        button = msg.get("button", "left")
        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
            page = _get_page(session_id)
            if page:
                try:
                    mouse = await page.mouse
                    await mouse.click(
                        float(x),
                        float(y),
                        button=button
                        if button in ("left", "right", "middle")
                        else "left",
                    )
                except Exception as e:
                    logger.debug(
                        "screencast_click_error session_id={} error={}",
                        session_id,
                        e,
                    )

    elif action == "dblclick":
        x = msg.get("x")
        y = msg.get("y")
        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
            page = _get_page(session_id)
            if page:
                try:
                    mouse = await page.mouse
                    await mouse.click(float(x), float(y), click_count=2)
                except Exception:
                    pass

    elif action == "type":
        text = msg.get("text", "")
        if text:
            page = _get_page(session_id)
            if page:
                try:
                    await page.press(text)
                except Exception:
                    # Fallback: try keyboard.type if press fails
                    try:
                        keyboard = await page.keyboard
                        await keyboard.type(text)
                    except Exception:
                        pass

    elif action == "key":
        key = msg.get("key", "")
        if key:
            page = _get_page(session_id)
            if page:
                try:
                    await page.press(key)
                except Exception:
                    pass

    elif action == "scroll":
        dx = msg.get("dx", 0)
        dy = msg.get("dy", 0)
        page = _get_page(session_id)
        if page:
            try:
                mouse = await page.mouse
                await mouse.scroll(delta_x=float(dx), delta_y=float(dy))
            except Exception:
                pass

    elif action == "mouse_move":
        x = msg.get("x")
        y = msg.get("y")
        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
            page = _get_page(session_id)
            if page:
                try:
                    mouse = await page.mouse
                    await mouse.move(float(x), float(y))
                except Exception:
                    pass


def _get_page(session_id: str) -> Any:
    """Return the live page for *session_id*, or ``None``."""
    from app.agent.tools.builtin.browser_use_tool import get_browser_page

    return get_browser_page(session_id)
