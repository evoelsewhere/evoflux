"""Browser session status + screencast WebSocket endpoint.

Provides:
- ``GET  /{session_id}/browser`` — one-shot JSON status
- ``WS   /{session_id}/browser/screencast`` — live JPEG frame stream
- ``WS   /{session_id}/browser/agent`` — agent ↔ direct desktop WebView bridge
"""

from __future__ import annotations

import asyncio
import base64
import json
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from loguru import logger
from pydantic import BaseModel, Field

router = APIRouter()

# Screencast config
_FRAME_INTERVAL = 0.2  # 5 fps
_JPEG_QUALITY = 60
_MAX_WIDTH = 1280


@router.websocket("/{session_id}/browser/agent")
async def direct_browser_agent_bridge(ws: WebSocket, session_id: str) -> None:
    """Attach the user-visible desktop browser to agent ``browser_use`` calls."""
    from app.services.direct_browser_bridge import direct_browser_bridge

    await ws.accept()
    await direct_browser_bridge.attach(session_id, ws)


@router.websocket("/{session_id}/browser/presence")
async def direct_browser_presence(ws: WebSocket, session_id: str) -> None:
    """Register a Tauri client that can mount the direct Browser panel."""
    from app.services.direct_browser_bridge import direct_browser_bridge

    await ws.accept()
    await direct_browser_bridge.attach_presence(session_id, ws)


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


@router.post(
    "/{session_id}/browser/agent/command",
    response_model=DirectBrowserCommandResponse,
)
async def run_direct_browser_agent_command(
    session_id: str,
    body: DirectBrowserCommandRequest,
) -> DirectBrowserCommandResponse:
    from app.services.direct_browser_bridge import direct_browser_bridge

    if not direct_browser_bridge.is_connected(session_id):
        mounted = await direct_browser_bridge.request_mount(session_id)
        if not mounted or not await direct_browser_bridge.wait_connected(session_id):
            raise HTTPException(
                status_code=409,
                detail="EvoFlux desktop browser is not available for this session",
            )
    try:
        result = await direct_browser_bridge.request(
            session_id,
            body.action,
            body.params,
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


@router.get("/{session_id}/browser")
async def get_browser_session(session_id: str) -> BrowserSessionResponse:
    """Return the live browser session info for *session_id*.

    Includes the CDP WebSocket URL (``cdp_url``), the HTTP equivalent
    (``cdp_http``), the current page URL/title, and all open tabs.

    Returns ``active: false`` when no browser session is running for this
    agent session.
    """
    from app.agent.tools.builtin.browser_use_tool import (
        get_browser_info,
        get_browser_session as get_live_session,
    )

    info = get_browser_info(session_id)
    session = get_live_session(session_id)
    page = await _get_or_recover_page(session_id)
    if info is None or session is None or page is None:
        return BrowserSessionResponse(active=False)

    try:
        current_url = await page.get_url()
        current_title = await page.get_title()
        pages = await session.get_pages()
        tabs = [
            BrowserTabInfo(
                index=index,
                url=await tab.get_url(),
                title=await tab.get_title(),
            )
            for index, tab in enumerate(pages)
        ]
    except Exception as exc:
        logger.debug(
            "browser_status_live_read_error session_id={} error={}", session_id, exc
        )
        current_url = info.get("current_url")
        current_title = info.get("current_title")
        tabs = [
            BrowserTabInfo(
                index=tab.get("index", index),
                url=tab.get("url", ""),
                title=tab.get("title", ""),
            )
            for index, tab in enumerate(info.get("tabs", []))
        ]

    return BrowserSessionResponse(
        active=True,
        cdp_url=info.get("cdp_url"),
        cdp_http=info.get("cdp_http"),
        current_url=current_url,
        current_title=current_title,
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
        get_browser_session,
    )

    info = get_browser_info(session_id)
    if info is None:
        return json.dumps({"type": "status", "active": False})

    page = await _get_or_recover_page(session_id)
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
    - ``{"action": "start"}`` — launch the session browser
    - ``{"action": "navigate", "url": "..."}`` — navigate to URL
    - ``{"action": "back"}`` — history back
    - ``{"action": "forward"}`` — history forward
    - ``{"action": "reload"}`` — reload current page
    - ``{"action": "switch_tab", "index": N}`` — switch to tab N
    - ``{"action": "new_tab", "url": "..."}`` — open a new tab
    - ``{"action": "close_tab", "index": N}`` — close a tab
    - ``{"action": "find", "query": "..."}`` — find text in the page
    - ``{"action": "zoom", "percent": N}`` — set page zoom (50–200)
    - ``{"action": "clear_data"}`` — clear cookies, cache, and origin storage
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
            page = await _get_or_recover_page(session_id)

            if page is None:
                # Browser not active — send status and wait
                await ws.send_text(json.dumps({"type": "status", "active": False}))
                await asyncio.sleep(1.0)
                # Check for client messages (e.g. to close)
                try:
                    raw = await asyncio.wait_for(ws.receive_text(), timeout=0.1)
                    result = await _handle_client_message(raw, session_id)
                    if result:
                        await ws.send_text(json.dumps(result))
                except asyncio.TimeoutError:
                    pass
                continue

            frame = await _capture_frame(page)
            if frame:
                await ws.send_bytes(frame)

            # Send control message
            ctrl = await _build_control_message(session_id)
            await ws.send_text(ctrl)

            # Drain client messages (non-blocking)
            try:
                raw = await asyncio.wait_for(ws.receive_text(), timeout=0.01)
                result = await _handle_client_message(raw, session_id)
                if result:
                    await ws.send_text(json.dumps(result))
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


async def _handle_client_message(raw: str, session_id: str) -> dict[str, Any] | None:
    """Handle a JSON message from the screencast client."""
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        return None

    action = msg.get("action")

    if action == "start":
        from app.agent.tools.builtin.browser_use_tool import (
            _launch_session,
            get_browser_session,
        )

        try:
            if get_browser_session(session_id) is None:
                await _launch_session(session_id)
            return _action_result(action)
        except Exception as e:
            logger.debug("screencast_start_error session_id={} error={}", session_id, e)
            return _action_result(action, error=str(e))

    elif action == "navigate":
        url = msg.get("url")
        if isinstance(url, str) and url:
            page = await _get_or_recover_page(session_id)
            if page:
                try:
                    await page.goto(url)
                    return _action_result(action)
                except Exception as e:
                    logger.debug(
                        "screencast_navigate_error session_id={} error={}",
                        session_id,
                        e,
                    )
                    return _action_result(action, error=str(e))
            return _action_result(action, error="Browser page is unavailable")

    elif action == "back":
        page = await _get_or_recover_page(session_id)
        if page:
            try:
                await page.go_back()
            except Exception:
                pass

    elif action == "forward":
        page = await _get_or_recover_page(session_id)
        if page:
            try:
                await page.go_forward()
            except Exception:
                pass

    elif action == "reload":
        page = await _get_or_recover_page(session_id)
        if page:
            try:
                await page.reload()
            except Exception:
                pass

    elif action == "resize":
        # Viewport follows the viewer panel so frames fill it edge-to-edge
        # instead of letterboxing a mismatched aspect ratio.
        width = msg.get("width")
        height = msg.get("height")
        if isinstance(width, (int, float)) and isinstance(height, (int, float)):
            page = await _get_or_recover_page(session_id)
            if page:
                try:
                    await page.set_viewport_size(
                        int(max(320, min(4000, width))),
                        int(max(300, min(4000, height))),
                    )
                except Exception as e:
                    logger.debug(
                        "screencast_resize_error session_id={} error={}",
                        session_id,
                        e,
                    )

    elif action == "switch_tab":
        index = msg.get("index")
        if isinstance(index, int):
            from app.agent.tools.builtin.browser_use_tool import get_browser_session

            session = get_browser_session(session_id)
            if session:
                try:
                    pages = await session.get_pages()
                    if 0 <= index < len(pages):
                        await _activate_page(
                            session_id, session, pages[index], action="tab_switched"
                        )
                except Exception as e:
                    logger.debug(
                        "screencast_switch_tab_error session_id={} error={}",
                        session_id,
                        e,
                    )

    elif action == "new_tab":
        from app.agent.tools.builtin.browser_use_tool import get_browser_session

        session = get_browser_session(session_id)
        if session:
            try:
                url = msg.get("url")
                target = url if isinstance(url, str) and url else "about:blank"
                page = await session.new_page(target)
                await _activate_page(session_id, session, page, action="new_tab")
                return _action_result(action)
            except Exception as e:
                logger.debug(
                    "screencast_new_tab_error session_id={} error={}", session_id, e
                )
                return _action_result(action, error=str(e))

    elif action == "close_tab":
        index = msg.get("index")
        if isinstance(index, int):
            from app.agent.tools.builtin.browser_use_tool import get_browser_session

            session = get_browser_session(session_id)
            if session:
                try:
                    pages = await session.get_pages()
                    if 0 <= index < len(pages):
                        if len(pages) == 1:
                            page = pages[0]
                            await page.goto("about:blank")
                        else:
                            await session.close_page(pages[index])
                            remaining = await session.get_pages()
                            page = remaining[min(index, len(remaining) - 1)]
                        await _activate_page(
                            session_id, session, page, action="closed_tab"
                        )
                        return _action_result(action)
                    return _action_result(action, error=f"Invalid tab index: {index}")
                except Exception as e:
                    logger.debug(
                        "screencast_close_tab_error session_id={} error={}",
                        session_id,
                        e,
                    )
                    return _action_result(action, error=str(e))

    elif action == "find":
        query = msg.get("query")
        page = await _get_or_recover_page(session_id)
        if page and isinstance(query, str) and query:
            backwards = bool(msg.get("backwards"))
            try:
                await page.evaluate(
                    "() => window.find("
                    + json.dumps(query)
                    + f", false, {str(backwards).lower()}, true, false, false, false)"
                )
                return _action_result(action)
            except Exception as e:
                logger.debug(
                    "screencast_find_error session_id={} error={}", session_id, e
                )
                return _action_result(action, error=str(e))

    elif action == "zoom":
        percent = msg.get("percent")
        if isinstance(percent, (int, float)):
            from app.agent.tools.builtin.browser_use_tool import get_browser_session

            session = get_browser_session(session_id)
            if session:
                try:
                    cdp = await session.get_or_create_cdp_session()
                    await cdp.cdp_client.send.Emulation.setPageScaleFactor(
                        params={
                            "pageScaleFactor": max(0.5, min(2.0, float(percent) / 100))
                        },
                        session_id=cdp.session_id,
                    )
                    return _action_result(action)
                except Exception as e:
                    logger.debug(
                        "screencast_zoom_error session_id={} error={}", session_id, e
                    )
                    return _action_result(action, error=str(e))

    elif action == "clear_data":
        from app.agent.tools.builtin.browser_use_tool import get_browser_session

        session = get_browser_session(session_id)
        if session:
            try:
                cdp = await session.get_or_create_cdp_session()
                await cdp.cdp_client.send.Storage.clearCookies(
                    session_id=cdp.session_id
                )
                await cdp.cdp_client.send.Network.clearBrowserCache(
                    session_id=cdp.session_id
                )
                page = await _get_or_recover_page(session_id)
                current_url = await page.get_url() if page else ""
                parsed = urlsplit(current_url)
                if parsed.scheme in {"http", "https"} and parsed.netloc:
                    await cdp.cdp_client.send.Storage.clearDataForOrigin(
                        params={
                            "origin": f"{parsed.scheme}://{parsed.netloc}",
                            "storageTypes": "all",
                        },
                        session_id=cdp.session_id,
                    )
                return _action_result(action)
            except Exception as e:
                logger.debug(
                    "screencast_clear_data_error session_id={} error={}", session_id, e
                )
                return _action_result(action, error=str(e))

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
            page = await _get_or_recover_page(session_id)
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
            page = await _get_or_recover_page(session_id)
            if page:
                try:
                    mouse = await page.mouse
                    await mouse.click(float(x), float(y), click_count=2)
                except Exception:
                    pass

    elif action == "type":
        text = msg.get("text", "")
        if isinstance(text, str) and text:
            from app.agent.tools.builtin.browser_use_tool import get_browser_session

            page = await _get_or_recover_page(session_id)
            session = get_browser_session(session_id)
            if page and session:
                try:
                    cdp = await session.get_or_create_cdp_session(
                        target_id=getattr(page, "_target_id", None),
                        focus=True,
                    )
                    await cdp.cdp_client.send.Input.insertText(
                        params={"text": text},
                        session_id=cdp.session_id,
                    )
                    return _action_result(action)
                except Exception as exc:
                    logger.debug(
                        "screencast_type_error session_id={} error={}",
                        session_id,
                        exc,
                    )
                    return _action_result(action, error=str(exc))
            return _action_result(action, error="Browser page is unavailable")

    elif action == "key":
        key = msg.get("key", "")
        if key:
            page = await _get_or_recover_page(session_id)
            if page:
                try:
                    await page.press(key)
                    return _action_result(action)
                except Exception as exc:
                    logger.debug(
                        "screencast_key_error session_id={} error={}",
                        session_id,
                        exc,
                    )
                    return _action_result(action, error=str(exc))

    elif action == "scroll":
        dx = msg.get("dx", 0)
        dy = msg.get("dy", 0)
        page = await _get_or_recover_page(session_id)
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
            page = await _get_or_recover_page(session_id)
            if page:
                try:
                    mouse = await page.mouse
                    await mouse.move(float(x), float(y))
                except Exception:
                    pass

    return None


async def _get_or_recover_page(session_id: str) -> Any | None:
    """Return the active page, repairing a stale page pointer when possible."""
    from app.agent.tools.builtin.browser_use_tool import (
        _pages,
        get_browser_page,
        get_browser_session,
    )

    page = get_browser_page(session_id)
    if page is not None:
        return page

    session = get_browser_session(session_id)
    if session is None:
        return None

    try:
        page = await session.get_current_page()
        if page is None:
            pages = await session.get_pages()
            page = pages[0] if pages else None
    except Exception as exc:
        logger.debug(
            "screencast_page_recovery_error session_id={} error={}",
            session_id,
            exc,
        )
        return None

    if page is not None:
        _pages[session_id] = page
        logger.info("screencast_page_recovered session_id={}", session_id)
    return page


async def _activate_page(
    session_id: str, session: Any, page: Any, *, action: str
) -> None:
    """Make *page* the shared active page and refresh browser metadata."""
    from app.agent.tools.builtin.browser_use_tool import (
        _attach_observability,
        _pages,
        _refresh_cdp_info,
    )

    _pages[session_id] = page
    await _attach_observability(session_id, session)
    await _refresh_cdp_info(session_id, session, page, action=action)


def _action_result(
    action: str,
    *,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "type": "action_result",
        "action": action,
        "ok": error is None,
        "error": error,
    }
