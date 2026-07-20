"""webbridge tool — control the user's real browser via the WebBridge extension.

Unlike ``browser_use`` which launches a headless Chromium, ``webbridge``
sends commands through a WebSocket relay to a Chrome/Edge extension running
in the user's actual browser.  This gives the agent access to the user's
real login sessions, cookies, and open tabs.

Architecture::

    Agent → webbridge tool → WebBridgeManager → relay → Chrome Extension → Real Browser (CDP)

The tool runs in the same process as the relay, so it talks to
:data:`app.services.webbridge_service.webbridge_manager` directly — no
loopback WebSocket. The extension must be installed and connected for this
tool to work. Check connection with ``status`` action before issuing commands.
"""

from __future__ import annotations

import base64
import json
from typing import Annotated, Any, Literal

from loguru import logger
from pydantic import BaseModel, Field

from app.agent.schemas.chat import ContentBlock, ImageDataBlock, TextBlock, ToolResult
from app.agent.tools.registry import InjectedArg, tool
from app.services.webbridge_service import webbridge_manager


def _get_sid(state: Any) -> str:
    return state.metadata.get("session_id", "default") if state else "default"


async def _send_command(session_id: str, action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Send a command to the extension via the manager and wait for response."""
    return await webbridge_manager.send_command(session_id, action, params)


# ---------------------------------------------------------------------------
# Action models
# ---------------------------------------------------------------------------


class StatusAction(BaseModel):
    action: Literal["status"]


class NavigateAction(BaseModel):
    action: Literal["navigate"]
    url: str = Field(description="URL to navigate to.")


class ClickAction(BaseModel):
    action: Literal["click"]
    x: float = Field(description="X coordinate to click.")
    y: float = Field(description="Y coordinate to click.")
    button: Literal["left", "right", "middle"] = Field(default="left")


class DblClickAction(BaseModel):
    action: Literal["dblclick"]
    x: float = Field(description="X coordinate to double-click.")
    y: float = Field(description="Y coordinate to double-click.")


class TypeAction(BaseModel):
    action: Literal["type"]
    text: str = Field(description="Text to type.")


class KeyAction(BaseModel):
    action: Literal["key"]
    key: str = Field(description="Key to press (e.g. Enter, Tab, Escape, ArrowUp).")


class ScrollAction(BaseModel):
    action: Literal["scroll"]
    dx: int = Field(default=0, description="Horizontal scroll delta.")
    dy: int = Field(default=0, description="Vertical scroll delta.")


class ScreenshotAction(BaseModel):
    action: Literal["screenshot"]
    format: Literal["png", "jpeg"] = Field(default="png")
    quality: int = Field(default=80, ge=10, le=100)


class ExtractAction(BaseModel):
    action: Literal["extract"]


class GetTabsAction(BaseModel):
    action: Literal["get_tabs"]


class SwitchTabAction(BaseModel):
    action: Literal["switch_tab"]
    index: int = Field(description="Zero-based tab index.")
    id: int | None = Field(default=None, description="Tab ID (overrides index).")


class EvaluateAction(BaseModel):
    action: Literal["evaluate"]
    script: str = Field(description="JavaScript to evaluate.")


class BackAction(BaseModel):
    action: Literal["back"]


class ForwardAction(BaseModel):
    action: Literal["forward"]


class ReloadAction(BaseModel):
    action: Literal["reload"]


AnyAction = Annotated[
    StatusAction
    | NavigateAction
    | ClickAction
    | DblClickAction
    | TypeAction
    | KeyAction
    | ScrollAction
    | ScreenshotAction
    | ExtractAction
    | GetTabsAction
    | SwitchTabAction
    | EvaluateAction
    | BackAction
    | ForwardAction
    | ReloadAction,
    Field(discriminator="action"),
]

_DESCRIPTION = """\
Control the user's real Chrome/Edge browser via the WebBridge extension.

Unlike browser_use (which launches a headless browser), this tool connects to
the user's actual browser through a Chrome extension. The user must install
the EvoFlux WebBridge extension and have it connected.

Actions:
  status     — Check if the extension is connected.
  navigate   — Go to a URL in the active tab.
  click      — Click at x,y coordinates.
  dblclick   — Double-click at x,y coordinates.
  type       — Type text into the focused element.
  key        — Press a key (Enter, Tab, Escape, etc.).
  scroll     — Scroll by dx,dy pixels.
  screenshot — Capture the visible page as PNG/JPEG image.
  extract    — Extract page text, title, and URL.
  get_tabs   — List all open tabs.
  switch_tab — Switch to a tab by index or ID.
  evaluate   — Run JavaScript in the page context.
  back       — Navigate back in history.
  forward    — Navigate forward in history.
  reload     — Reload the current page.

Verify workflow: status → navigate → wait → screenshot → interact → extract.\
"""


@tool(name="webbridge")
async def webbridge(
    actions: Annotated[
        list[AnyAction],
        Field(description="Ordered list of browser actions to execute."),
    ],
    _state: Annotated[Any, InjectedArg()] = None,
) -> str | ToolResult:
    """Control the user's real browser via the WebBridge Chrome extension."""
    session_id = _get_sid(_state)
    results: list[str | ToolResult] = []

    for act in actions:
        try:
            result = await _dispatch_webbridge(act, session_id)
            results.append(result)
        except Exception as e:
            logger.debug("webbridge_error action={} error={}", act.action, e)
            results.append(f"Error ({act.action}): {e}")

    if not results:
        return "No actions executed."

    if not any(isinstance(r, ToolResult) for r in results):
        return "\n---\n".join(r for r in results if isinstance(r, str))

    # Mix text and image results into a single ToolResult
    parts: list[ContentBlock] = []
    text_acc: list[str] = []

    def _flush() -> None:
        if text_acc:
            parts.append(TextBlock(text="\n---\n".join(text_acc)))
            text_acc.clear()

    for r in results:
        if isinstance(r, ToolResult):
            _flush()
            parts.extend(r.parts)
        else:
            text_acc.append(r)
    _flush()
    return ToolResult(parts=parts)


async def _dispatch_webbridge(act: Any, session_id: str) -> str | ToolResult:
    action = act.action

    if action == "status":
        return await _handle_status(session_id)
    if action == "navigate":
        return await _handle_navigate(session_id, act)
    if action == "click":
        return await _handle_click(session_id, act)
    if action == "dblclick":
        return await _handle_dblclick(session_id, act)
    if action == "type":
        return await _handle_type(session_id, act)
    if action == "key":
        return await _handle_key(session_id, act)
    if action == "scroll":
        return await _handle_scroll(session_id, act)
    if action == "screenshot":
        return await _handle_screenshot(session_id, act)
    if action == "extract":
        return await _handle_extract(session_id)
    if action == "get_tabs":
        return await _handle_get_tabs(session_id)
    if action == "switch_tab":
        return await _handle_switch_tab(session_id, act)
    if action == "evaluate":
        return await _handle_evaluate(session_id, act)
    if action == "back":
        return await _handle_back(session_id)
    if action == "forward":
        return await _handle_forward(session_id)
    if action == "reload":
        return await _handle_reload(session_id)

    return f"Unknown action: {action}"


# ── Action handlers ───────────────────────────────────────────────────────────


async def _handle_status(session_id: str) -> str:
    resp = await _send_command(session_id, "status")
    if not resp.get("success"):
        return f"WebBridge not connected: {resp.get('error', 'unknown error')}"

    data = resp.get("data", {})
    extensions = data.get("extensions", [])

    if not extensions:
        return (
            "WebBridge: No browser extension connected. "
            "Install the EvoFlux WebBridge extension in Chrome/Edge "
            "and ensure it's connected to the relay server."
        )

    ext = extensions[0]
    return (
        f"WebBridge connected.\n"
        f"Browser: {ext.get('browser', 'unknown')}\n"
        f"Active tab: {ext.get('current_url', 'N/A')}\n"
        f"Title: {ext.get('current_title', 'N/A')}"
    )


async def _handle_navigate(session_id: str, act: NavigateAction) -> str:
    resp = await _send_command(session_id, "navigate", {"url": act.url})
    if resp.get("success"):
        return f"Navigated to {act.url}"
    return f"Navigate failed: {resp.get('error', 'unknown')}"


async def _handle_click(session_id: str, act: ClickAction) -> str:
    resp = await _send_command(session_id, "click", {
        "x": act.x,
        "y": act.y,
        "button": act.button,
    })
    if resp.get("success"):
        return f"Clicked at ({act.x}, {act.y})"
    return f"Click failed: {resp.get('error', 'unknown')}"


async def _handle_dblclick(session_id: str, act: DblClickAction) -> str:
    resp = await _send_command(session_id, "dblclick", {"x": act.x, "y": act.y})
    if resp.get("success"):
        return f"Double-clicked at ({act.x}, {act.y})"
    return f"Double-click failed: {resp.get('error', 'unknown')}"


async def _handle_type(session_id: str, act: TypeAction) -> str:
    resp = await _send_command(session_id, "type", {"text": act.text})
    if resp.get("success"):
        return f"Typed {len(act.text)} characters"
    return f"Type failed: {resp.get('error', 'unknown')}"


async def _handle_key(session_id: str, act: KeyAction) -> str:
    resp = await _send_command(session_id, "key", {"key": act.key})
    if resp.get("success"):
        return f"Pressed key: {act.key}"
    return f"Key press failed: {resp.get('error', 'unknown')}"


async def _handle_scroll(session_id: str, act: ScrollAction) -> str:
    resp = await _send_command(session_id, "scroll", {"dx": act.dx, "dy": act.dy})
    if resp.get("success"):
        return f"Scrolled ({act.dx}, {act.dy})"
    return f"Scroll failed: {resp.get('error', 'unknown')}"


async def _handle_screenshot(session_id: str, act: ScreenshotAction) -> ToolResult:
    resp = await _send_command(session_id, "screenshot", {
        "format": act.format,
        "quality": act.quality,
    })

    if not resp.get("success"):
        return ToolResult(parts=[TextBlock(text=f"Screenshot failed: {resp.get('error', 'unknown')}")])

    data = resp.get("data", {})
    b64_image = data.get("data", "")
    fmt = data.get("format", act.format)

    if not b64_image:
        return ToolResult(parts=[TextBlock(text="Screenshot returned empty image data.")])

    # Decode base64 to bytes
    image_bytes = base64.b64decode(b64_image)
    mime = "image/jpeg" if fmt == "jpeg" else "image/png"

    return ToolResult(parts=[
        ImageDataBlock(
            data=b64_image,
            media_type=mime,
        ),
        TextBlock(text=f"Screenshot captured ({fmt}, {len(image_bytes)} bytes)."),
    ])


async def _handle_extract(session_id: str) -> str:
    resp = await _send_command(session_id, "extract")
    if not resp.get("success"):
        return f"Extract failed: {resp.get('error', 'unknown')}"

    data = resp.get("data", {})
    title = data.get("title", "")
    url = data.get("url", "")
    text = data.get("text", "")

    return (
        f"Page: {title}\n"
        f"URL: {url}\n"
        f"---\n"
        f"{text[:15000]}"
    )


async def _handle_get_tabs(session_id: str) -> str:
    resp = await _send_command(session_id, "get_tabs")
    if not resp.get("success"):
        return f"Get tabs failed: {resp.get('error', 'unknown')}"

    data = resp.get("data", {})
    tabs = data.get("tabs", [])

    lines = [f"Open tabs ({len(tabs)}):"]
    for tab in tabs:
        active = " [ACTIVE]" if tab.get("active") else ""
        lines.append(f"  [{tab.get('index')}] {tab.get('title', 'Untitled')}{active}")
        lines.append(f"       {tab.get('url', '')}")

    return "\n".join(lines)


async def _handle_switch_tab(session_id: str, act: SwitchTabAction) -> str:
    params: dict[str, Any] = {}
    if act.id is not None:
        params["id"] = act.id
    else:
        params["index"] = act.index

    resp = await _send_command(session_id, "switch_tab", params)
    if resp.get("success"):
        return f"Switched to tab {act.index if act.id is None else f'id={act.id}'}"
    return f"Switch tab failed: {resp.get('error', 'unknown')}"


async def _handle_evaluate(session_id: str, act: EvaluateAction) -> str:
    resp = await _send_command(session_id, "evaluate", {"script": act.script})
    if not resp.get("success"):
        return f"Evaluate failed: {resp.get('error', 'unknown')}"

    data = resp.get("data", {})
    value = data.get("value")
    return f"Result: {json.dumps(value, indent=2, default=str)}"


async def _handle_back(session_id: str) -> str:
    resp = await _send_command(session_id, "back")
    if resp.get("success"):
        return "Navigated back."
    return f"Back failed: {resp.get('error', 'unknown')}"


async def _handle_forward(session_id: str) -> str:
    resp = await _send_command(session_id, "forward")
    if resp.get("success"):
        return "Navigated forward."
    return f"Forward failed: {resp.get('error', 'unknown')}"


async def _handle_reload(session_id: str) -> str:
    resp = await _send_command(session_id, "reload")
    if resp.get("success"):
        return "Page reloaded."
    return f"Reload failed: {resp.get('error', 'unknown')}"
