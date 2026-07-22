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

import asyncio
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

#: Shared description for the per-action tab target. Any action can carry a
#: ``tab_id`` (from ``get_tabs``) to drive that exact tab — including a
#: background tab — without switching Chrome's focus to it. Omit it to act on
#: the currently active tab.
_TAB_ID_DESC = (
    "Target tab ID from get_tabs. Drives that tab in the background without "
    "focusing/switching to it. Omit to use the active tab."
)


class StatusAction(BaseModel):
    action: Literal["status"]


class NavigateAction(BaseModel):
    action: Literal["navigate"]
    url: str = Field(description="URL to navigate to.")
    tab_id: int | None = Field(default=None, description=_TAB_ID_DESC)


class ClickAction(BaseModel):
    action: Literal["click"]
    x: float = Field(description="X coordinate to click.")
    y: float = Field(description="Y coordinate to click.")
    button: Literal["left", "right", "middle"] = Field(default="left")
    tab_id: int | None = Field(default=None, description=_TAB_ID_DESC)


class DblClickAction(BaseModel):
    action: Literal["dblclick"]
    x: float = Field(description="X coordinate to double-click.")
    y: float = Field(description="Y coordinate to double-click.")
    tab_id: int | None = Field(default=None, description=_TAB_ID_DESC)


class TypeAction(BaseModel):
    action: Literal["type"]
    text: str = Field(description="Text to type.")
    tab_id: int | None = Field(default=None, description=_TAB_ID_DESC)


class KeyAction(BaseModel):
    action: Literal["key"]
    key: str = Field(description="Key to press (e.g. Enter, Tab, Escape, ArrowUp).")
    tab_id: int | None = Field(default=None, description=_TAB_ID_DESC)


class ScrollAction(BaseModel):
    action: Literal["scroll"]
    dx: int = Field(default=0, description="Horizontal scroll delta.")
    dy: int = Field(default=0, description="Vertical scroll delta.")
    tab_id: int | None = Field(default=None, description=_TAB_ID_DESC)


class ScreenshotAction(BaseModel):
    action: Literal["screenshot"]
    format: Literal["png", "jpeg"] = Field(default="png")
    quality: int = Field(default=80, ge=10, le=100)
    full_page: bool = Field(
        default=False,
        description="Capture the whole scrollable page instead of just the viewport.",
    )
    tab_id: int | None = Field(default=None, description="Target tab ID (default: active tab).")


class ExtractAction(BaseModel):
    action: Literal["extract"]
    format: Literal["text", "markdown", "html"] = Field(
        default="text",
        description="Output form: plain text, structure-preserving markdown (best for LLM crawling), or raw HTML.",
    )
    selector: str | None = Field(
        default=None,
        description="Scope to the first element matching this CSS selector (default: whole page).",
    )
    max_chars: int = Field(default=15000, ge=100, le=200000)
    tab_id: int | None = Field(default=None, description="Target tab ID (default: active tab).")


class ExtractElementsAction(BaseModel):
    action: Literal["extract_elements"]
    selector: str = Field(description="CSS selector for the records to extract (e.g. a product card, a table row).")
    fields: dict[str, str] | None = Field(
        default=None,
        description=(
            "Map of field name → sub-selector relative to each match. The "
            "sub-element's text is taken; append '@attr' to pull an attribute, "
            "e.g. {'title': 'h3', 'url': 'a@href', 'img': 'img@src'}. Omit to "
            "get {text, href} per match."
        ),
    )
    limit: int = Field(default=100, ge=1, le=1000)
    tab_id: int | None = Field(default=None, description="Target tab ID (default: active tab).")


class ScrollToBottomAction(BaseModel):
    action: Literal["scroll_to_bottom"]
    max_scrolls: int = Field(default=10, ge=1, le=100, description="Max scroll steps.")
    delay_ms: int = Field(default=600, ge=50, le=5000, description="Wait after each scroll for content to load.")
    tab_id: int | None = Field(default=None, description="Target tab ID (default: active tab).")


class CrawlAction(BaseModel):
    action: Literal["crawl"]
    urls: list[str] = Field(description="URLs to fetch and extract, crawled in parallel across background tabs.")
    wait: Literal["load", "networkidle", "none"] = Field(
        default="load",
        description="Per page: wait for full load, for network idle (SPAs), or don't wait.",
    )
    wait_selector: str | None = Field(
        default=None, description="Also wait for this selector before extracting (optional)."
    )
    scroll: bool = Field(default=False, description="Auto-scroll to bottom before extracting (lazy/infinite content).")
    # Extraction mode: set elements_selector for structured records, else page content.
    elements_selector: str | None = Field(
        default=None,
        description="If set, scrape records matching this selector (like extract_elements); otherwise extract page content.",
    )
    fields: dict[str, str] | None = Field(
        default=None, description="Field map for elements_selector mode (name → sub-selector, 'sel@attr' for attributes)."
    )
    format: Literal["text", "markdown", "html"] = Field(
        default="markdown", description="Content format when not using elements_selector."
    )
    selector: str | None = Field(default=None, description="Scope content extraction to this selector.")
    concurrency: int = Field(default=3, ge=1, le=8, description="Max pages fetched at once.")
    max_chars: int = Field(default=15000, ge=100, le=200000)
    limit: int = Field(default=100, ge=1, le=1000, description="Max records per page in elements mode.")
    timeout_ms: int = Field(default=30000, ge=1000, le=60000)
    close_tabs: bool = Field(default=True, description="Close the tabs opened for the crawl when done.")


class GetTabsAction(BaseModel):
    action: Literal["get_tabs"]


class SwitchTabAction(BaseModel):
    action: Literal["switch_tab"]
    index: int = Field(description="Zero-based tab index.")
    id: int | None = Field(default=None, description="Tab ID (overrides index).")


class WaitAction(BaseModel):
    action: Literal["wait"]
    ms: int = Field(default=1000, ge=0, le=60000, description="Milliseconds to pause.")


class WaitForSelectorAction(BaseModel):
    action: Literal["wait_for_selector"]
    selector: str = Field(description="CSS selector to wait for.")
    state: Literal["visible", "attached", "hidden"] = Field(default="visible")
    timeout_ms: int = Field(default=10000, ge=100, le=60000)
    tab_id: int | None = Field(default=None, description="Target tab ID (default: active tab).")


class WaitForLoadAction(BaseModel):
    action: Literal["wait_for_load"]
    state: Literal["load", "domcontentloaded"] = Field(default="load")
    timeout_ms: int = Field(default=30000, ge=100, le=60000)
    tab_id: int | None = Field(default=None, description="Target tab ID (default: active tab).")


class WaitForNetworkIdleAction(BaseModel):
    action: Literal["wait_for_network_idle"]
    idle_ms: int = Field(
        default=500, ge=100, le=10000,
        description="Consider the network idle after this many ms with no in-flight requests.",
    )
    timeout_ms: int = Field(default=20000, ge=500, le=60000)
    tab_id: int | None = Field(default=None, description="Target tab ID (default: active tab).")


class ClickSelectorAction(BaseModel):
    action: Literal["click_selector"]
    selector: str = Field(description="CSS selector of the element to click.")
    index: int = Field(default=0, ge=0, description="Which match to click when several exist.")
    tab_id: int | None = Field(default=None, description="Target tab ID (default: active tab).")


class ClickTextAction(BaseModel):
    action: Literal["click_text"]
    text: str = Field(description="Visible text of the element to click.")
    tag: str | None = Field(default=None, description="Restrict to this tag (e.g. 'button', 'a').")
    exact: bool = Field(default=False, description="Require an exact (not substring) text match.")
    tab_id: int | None = Field(default=None, description="Target tab ID (default: active tab).")


class FillAction(BaseModel):
    action: Literal["fill"]
    selector: str = Field(description="CSS selector of the input/textarea to fill.")
    value: str = Field(description="Value to set.")
    clear: bool = Field(default=True, description="Clear existing content first.")
    submit: bool = Field(default=False, description="Press Enter after filling.")
    tab_id: int | None = Field(default=None, description="Target tab ID (default: active tab).")


class OpenTabAction(BaseModel):
    action: Literal["open_tab"]
    url: str = Field(description="URL to open in a new tab.")
    active: bool = Field(default=True, description="Focus the new tab.")


class CloseTabAction(BaseModel):
    action: Literal["close_tab"]
    id: int | None = Field(default=None, description="Tab ID to close.")
    index: int | None = Field(default=None, description="Zero-based tab index to close.")


class SnapshotAction(BaseModel):
    action: Literal["snapshot"]
    max_elements: int = Field(default=80, ge=1, le=300)
    tab_id: int | None = Field(default=None, description="Target tab ID (default: active tab).")


class EvaluateAction(BaseModel):
    action: Literal["evaluate"]
    script: str = Field(description="JavaScript to evaluate.")
    tab_id: int | None = Field(default=None, description=_TAB_ID_DESC)


class BackAction(BaseModel):
    action: Literal["back"]
    tab_id: int | None = Field(default=None, description=_TAB_ID_DESC)


class ForwardAction(BaseModel):
    action: Literal["forward"]
    tab_id: int | None = Field(default=None, description=_TAB_ID_DESC)


class ReloadAction(BaseModel):
    action: Literal["reload"]
    tab_id: int | None = Field(default=None, description=_TAB_ID_DESC)


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
    | ReloadAction
    | WaitAction
    | WaitForSelectorAction
    | WaitForLoadAction
    | ClickSelectorAction
    | ClickTextAction
    | FillAction
    | OpenTabAction
    | CloseTabAction
    | SnapshotAction
    | ExtractElementsAction
    | ScrollToBottomAction
    | WaitForNetworkIdleAction
    | CrawlAction,
    Field(discriminator="action"),
]

_DESCRIPTION = """\
Control the user's real Chrome/Edge browser via the WebBridge extension.

Unlike browser_use (which launches a headless browser), this tool connects to
the user's actual browser through a Chrome extension. The user must install
the EvoFlux WebBridge extension and have it connected.

Prefer the element-based actions (snapshot → click_selector/click_text/fill)
over coordinate clicks: they are robust to layout and HiDPI scaling. Use
screenshot coordinates only when no selector works. Screenshot pixels equal
CSS pixels (the extension normalizes device scaling), so click x,y read off a
screenshot map directly.

Actions:
  status          — Check if the extension is connected.
  navigate        — Go to a URL in the active tab.
  snapshot        — List interactive elements (selector, text, role, box) — use this to find click/fill targets.
  click_selector  — Click the element matching a CSS selector.
  click_text      — Click the element whose visible text matches.
  fill            — Set an input/textarea value by selector (optionally submit).
  click           — Click at x,y coordinates (fallback when no selector fits).
  dblclick        — Double-click at x,y coordinates.
  type            — Type text into the focused element.
  key             — Press a key (Enter, Tab, Escape, etc.).
  scroll          — Scroll by dx,dy pixels.
  wait            — Pause for N milliseconds.
  wait_for_selector — Wait until a selector is visible/attached/hidden.
  wait_for_load   — Wait until the page finishes loading.
  wait_for_network_idle — Wait until in-flight XHR/fetch requests go quiet (SPA data loads).
  screenshot      — Capture the viewport (or full_page) as PNG/JPEG image.
  extract         — Extract page content as text / markdown / html (optionally scoped to a selector).
  extract_elements— Scrape many records by selector into structured JSON (with per-field sub-selectors / attributes).
  scroll_to_bottom— Auto-scroll to load lazy / infinite-scroll content before extracting.
  crawl           — Fetch + extract many URLs at once, running concurrently across background tabs.
  get_tabs        — List all open tabs.
  switch_tab      — Switch to a tab by index or ID.
  open_tab        — Open a URL in a new tab.
  close_tab       — Close a tab by ID or index.
  evaluate        — Run JavaScript in the page context (may be disabled by policy).
  back / forward / reload — History and reload.

Multiple tabs at once (no focus switching): call get_tabs to read each tab's
id, then pass tab_id on any action to drive that exact tab in the background.
The debugger attaches per-tab, so you can navigate/click/fill/extract across
several tabs without ever switching Chrome's active tab (only switch_tab
changes focus — you rarely need it). Use open_tab {active:false} to open a
page in the background. Caveat: screenshots of a fully hidden/occluded tab may
be blank or stale (it isn't painting) — for background tabs prefer the DOM
actions (snapshot / extract / click_selector / fill / evaluate).

Verify workflow: status → navigate → wait_for_load → snapshot → click_selector/fill → extract.
Crawl workflow (one page): navigate → wait_for_load (or wait_for_network_idle
for an SPA that fetches its data after load) → scroll_to_bottom (if lazy) →
extract_elements {selector, fields} for lists, or extract {format:"markdown"}
for article/body content → follow links (open_tab {active:false}) and repeat.
Crawl workflow (many pages, one call): use crawl {urls, wait, elements_selector
or format} — it opens each URL in its own background tab and runs them
concurrently (default 3 at a time via ``concurrency``), returning every page's
result together. Pass wait:"networkidle" when the target pages are SPAs.\
"""


@tool(
    name="webbridge",
    deferred=True,
    deferred_summary="Drive the user's real browser through the WebBridge extension.",
)
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
        return await _handle_extract(session_id, act)
    if action == "get_tabs":
        return await _handle_get_tabs(session_id)
    if action == "switch_tab":
        return await _handle_switch_tab(session_id, act)
    if action == "evaluate":
        return await _handle_evaluate(session_id, act)
    if action == "back":
        return await _handle_back(session_id, act)
    if action == "forward":
        return await _handle_forward(session_id, act)
    if action == "reload":
        return await _handle_reload(session_id, act)
    if action == "wait":
        return await _handle_wait(session_id, act)
    if action == "wait_for_selector":
        return await _handle_wait_for_selector(session_id, act)
    if action == "wait_for_load":
        return await _handle_wait_for_load(session_id, act)
    if action == "click_selector":
        return await _handle_click_selector(session_id, act)
    if action == "click_text":
        return await _handle_click_text(session_id, act)
    if action == "fill":
        return await _handle_fill(session_id, act)
    if action == "open_tab":
        return await _handle_open_tab(session_id, act)
    if action == "close_tab":
        return await _handle_close_tab(session_id, act)
    if action == "snapshot":
        return await _handle_snapshot(session_id, act)
    if action == "extract_elements":
        return await _handle_extract_elements(session_id, act)
    if action == "scroll_to_bottom":
        return await _handle_scroll_to_bottom(session_id, act)
    if action == "wait_for_network_idle":
        return await _handle_wait_for_network_idle(session_id, act)
    if action == "crawl":
        return await _handle_crawl(session_id, act)

    return f"Unknown action: {action}"


def _tab_params(act: Any, **extra: Any) -> dict[str, Any]:
    """Command params with ``tab_id`` folded in only when the action set one."""
    params = dict(extra)
    tab_id = getattr(act, "tab_id", None)
    if tab_id is not None:
        params["tab_id"] = tab_id
    return params


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
    resp = await _send_command(session_id, "navigate", _tab_params(act, url=act.url))
    if resp.get("success"):
        return f"Navigated to {act.url}"
    return f"Navigate failed: {resp.get('error', 'unknown')}"


async def _handle_click(session_id: str, act: ClickAction) -> str:
    resp = await _send_command(session_id, "click", _tab_params(
        act,
        x=act.x,
        y=act.y,
        button=act.button,
    ))
    if resp.get("success"):
        return f"Clicked at ({act.x}, {act.y})"
    return f"Click failed: {resp.get('error', 'unknown')}"


async def _handle_dblclick(session_id: str, act: DblClickAction) -> str:
    resp = await _send_command(session_id, "dblclick", _tab_params(act, x=act.x, y=act.y))
    if resp.get("success"):
        return f"Double-clicked at ({act.x}, {act.y})"
    return f"Double-click failed: {resp.get('error', 'unknown')}"


async def _handle_type(session_id: str, act: TypeAction) -> str:
    resp = await _send_command(session_id, "type", _tab_params(act, text=act.text))
    if resp.get("success"):
        return f"Typed {len(act.text)} characters"
    return f"Type failed: {resp.get('error', 'unknown')}"


async def _handle_key(session_id: str, act: KeyAction) -> str:
    resp = await _send_command(session_id, "key", _tab_params(act, key=act.key))
    if resp.get("success"):
        return f"Pressed key: {act.key}"
    return f"Key press failed: {resp.get('error', 'unknown')}"


async def _handle_scroll(session_id: str, act: ScrollAction) -> str:
    resp = await _send_command(session_id, "scroll", _tab_params(act, dx=act.dx, dy=act.dy))
    if resp.get("success"):
        return f"Scrolled ({act.dx}, {act.dy})"
    return f"Scroll failed: {resp.get('error', 'unknown')}"


async def _handle_screenshot(session_id: str, act: ScreenshotAction) -> ToolResult:
    resp = await _send_command(session_id, "screenshot", _tab_params(
        act,
        format=act.format,
        quality=act.quality,
        full_page=act.full_page,
    ))

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

    # Viewport metadata lets the model map screenshot pixels to click coords.
    vp = data.get("viewport") or {}
    dims = ""
    if vp.get("width") and vp.get("height"):
        dims = f", {int(vp['width'])}x{int(vp['height'])} css-px"
    scope = "full page" if data.get("full_page") else "viewport"

    return ToolResult(parts=[
        ImageDataBlock(
            data=b64_image,
            media_type=mime,
        ),
        TextBlock(
            text=f"Screenshot captured ({scope}, {fmt}{dims}, {len(image_bytes)} bytes). "
            "Screenshot pixels are CSS pixels — click x,y map 1:1."
        ),
    ])


async def _handle_extract(session_id: str, act: ExtractAction) -> str:
    resp = await _send_command(session_id, "extract", _tab_params(
        act,
        format=act.format,
        selector=act.selector,
        max_chars=act.max_chars,
    ))
    if not resp.get("success"):
        return f"Extract failed: {resp.get('error', 'unknown')}"

    data = resp.get("data", {})
    title = data.get("title", "")
    url = data.get("url", "")
    # The extension returns the chosen representation under "content" (text/
    # markdown/html), falling back to legacy "text" for older extensions.
    content = data.get("content")
    if content is None:
        content = data.get("text", "")

    return (
        f"Page: {title}\n"
        f"URL: {url}\n"
        f"Format: {act.format}\n"
        f"---\n"
        f"{content[: act.max_chars]}"
    )


async def _handle_extract_elements(session_id: str, act: ExtractElementsAction) -> str:
    resp = await _send_command(session_id, "extract_elements", _tab_params(
        act,
        selector=act.selector,
        fields=act.fields,
        limit=act.limit,
    ))
    if not resp.get("success"):
        return f"extract_elements failed: {resp.get('error', 'unknown')}"

    records = (resp.get("data") or {}).get("records", [])
    if not records:
        return f"No elements matched selector {act.selector!r}."
    header = f"Extracted {len(records)} record(s) for {act.selector!r}:"
    return header + "\n" + json.dumps(records, indent=2, ensure_ascii=False, default=str)


async def _handle_scroll_to_bottom(session_id: str, act: ScrollToBottomAction) -> str:
    resp = await _send_command(session_id, "scroll_to_bottom", _tab_params(
        act,
        max_scrolls=act.max_scrolls,
        delay_ms=act.delay_ms,
        timeout_ms=act.max_scrolls * (act.delay_ms + 400) + 2000,
    ))
    if not resp.get("success"):
        return f"scroll_to_bottom failed: {resp.get('error', 'unknown')}"
    data = resp.get("data", {})
    return (
        f"Scrolled {data.get('scrolls', 0)} step(s); "
        f"page height {data.get('final_height', '?')}px "
        f"({'reached bottom' if data.get('at_bottom') else 'more may remain'})."
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
        # Surface the tab id — pass it as tab_id to drive that tab in the
        # background without switching focus.
        lines.append(
            f"  [{tab.get('index')}] id={tab.get('id')} "
            f"{tab.get('title', 'Untitled')}{active}"
        )
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
    resp = await _send_command(session_id, "evaluate", _tab_params(act, script=act.script))
    if not resp.get("success"):
        return f"Evaluate failed: {resp.get('error', 'unknown')}"

    data = resp.get("data", {})
    value = data.get("value")
    return f"Result: {json.dumps(value, indent=2, default=str)}"


async def _handle_back(session_id: str, act: BackAction) -> str:
    resp = await _send_command(session_id, "back", _tab_params(act))
    if resp.get("success"):
        return "Navigated back."
    return f"Back failed: {resp.get('error', 'unknown')}"


async def _handle_forward(session_id: str, act: ForwardAction) -> str:
    resp = await _send_command(session_id, "forward", _tab_params(act))
    if resp.get("success"):
        return "Navigated forward."
    return f"Forward failed: {resp.get('error', 'unknown')}"


async def _handle_reload(session_id: str, act: ReloadAction) -> str:
    resp = await _send_command(session_id, "reload", _tab_params(act))
    if resp.get("success"):
        return "Page reloaded."
    return f"Reload failed: {resp.get('error', 'unknown')}"


async def _handle_wait(session_id: str, act: WaitAction) -> str:
    resp = await _send_command(session_id, "wait", {"ms": act.ms, "timeout_ms": act.ms})
    if resp.get("success"):
        return f"Waited {act.ms} ms."
    return f"Wait failed: {resp.get('error', 'unknown')}"


async def _handle_wait_for_selector(session_id: str, act: WaitForSelectorAction) -> str:
    resp = await _send_command(session_id, "wait_for_selector", _tab_params(
        act,
        selector=act.selector,
        state=act.state,
        timeout_ms=act.timeout_ms,
    ))
    if resp.get("success"):
        return f"Selector {act.selector!r} is now {act.state}."
    return f"wait_for_selector failed: {resp.get('error', 'unknown')}"


async def _handle_wait_for_load(session_id: str, act: WaitForLoadAction) -> str:
    resp = await _send_command(session_id, "wait_for_load", _tab_params(
        act,
        state=act.state,
        timeout_ms=act.timeout_ms,
    ))
    if resp.get("success"):
        return f"Page reached '{act.state}'."
    return f"wait_for_load failed: {resp.get('error', 'unknown')}"


async def _handle_wait_for_network_idle(session_id: str, act: WaitForNetworkIdleAction) -> str:
    resp = await _send_command(session_id, "wait_for_network_idle", _tab_params(
        act,
        idle_ms=act.idle_ms,
        timeout_ms=act.timeout_ms,
    ))
    if not resp.get("success"):
        return f"wait_for_network_idle failed: {resp.get('error', 'unknown')}"
    data = resp.get("data", {})
    if data.get("idle"):
        return f"Network idle ({act.idle_ms}ms with 0 in-flight requests)."
    return (
        f"Network still active after {act.timeout_ms}ms "
        f"({data.get('inflight', '?')} request(s) in flight)."
    )


async def _handle_click_selector(session_id: str, act: ClickSelectorAction) -> str:
    resp = await _send_command(session_id, "click_selector", _tab_params(
        act,
        selector=act.selector,
        index=act.index,
    ))
    if resp.get("success"):
        return f"Clicked {act.selector!r}."
    return f"click_selector failed: {resp.get('error', 'unknown')}"


async def _handle_click_text(session_id: str, act: ClickTextAction) -> str:
    resp = await _send_command(session_id, "click_text", _tab_params(
        act,
        text=act.text,
        tag=act.tag,
        exact=act.exact,
    ))
    if resp.get("success"):
        return f"Clicked element with text {act.text!r}."
    return f"click_text failed: {resp.get('error', 'unknown')}"


async def _handle_fill(session_id: str, act: FillAction) -> str:
    resp = await _send_command(session_id, "fill", _tab_params(
        act,
        selector=act.selector,
        value=act.value,
        clear=act.clear,
        submit=act.submit,
    ))
    if resp.get("success"):
        suffix = " and submitted" if act.submit else ""
        return f"Filled {act.selector!r}{suffix}."
    return f"fill failed: {resp.get('error', 'unknown')}"


async def _handle_open_tab(session_id: str, act: OpenTabAction) -> str:
    resp = await _send_command(session_id, "open_tab", {"url": act.url, "active": act.active})
    if not resp.get("success"):
        return f"open_tab failed: {resp.get('error', 'unknown')}"
    tab_id = (resp.get("data") or {}).get("tab_id")
    return f"Opened {act.url} in new tab (id={tab_id})."


async def _handle_close_tab(session_id: str, act: CloseTabAction) -> str:
    params: dict[str, Any] = {}
    if act.id is not None:
        params["id"] = act.id
    elif act.index is not None:
        params["index"] = act.index
    else:
        return "close_tab needs an id or index."
    resp = await _send_command(session_id, "close_tab", params)
    if resp.get("success"):
        return "Closed tab."
    return f"close_tab failed: {resp.get('error', 'unknown')}"


async def _handle_snapshot(session_id: str, act: SnapshotAction) -> str:
    resp = await _send_command(session_id, "snapshot", _tab_params(act, max_elements=act.max_elements))
    if not resp.get("success"):
        return f"snapshot failed: {resp.get('error', 'unknown')}"

    data = resp.get("data", {})
    elements = data.get("elements", [])
    if not elements:
        return "No interactive elements found on the page."

    lines = [f"Interactive elements ({len(elements)}):"]
    for el in elements:
        box = el.get("box") or {}
        center = ""
        if box.get("x") is not None and box.get("y") is not None:
            center = f" @({int(box['x'])},{int(box['y'])})"
        label = (el.get("text") or el.get("name") or "").strip().replace("\n", " ")
        if len(label) > 80:
            label = label[:77] + "…"
        lines.append(
            f"  [{el.get('role', 'element')}]{center} {label!r} — {el.get('selector', '')}"
        )
    return "\n".join(lines)


async def _crawl_page(session_id: str, act: CrawlAction, url: str) -> dict[str, Any]:
    """Run navigate → wait → (scroll) → extract for one URL in its own background tab.

    Never raises — every failure mode (open_tab, wait, extract, a stray
    exception) collapses into ``{"url", "ok": False, "error"}`` so one bad
    page can't sink the rest of a concurrent :func:`asyncio.gather`.
    """
    try:
        open_resp = await _send_command(session_id, "open_tab", {"url": url, "active": False})
        if not open_resp.get("success"):
            return {"url": url, "ok": False, "error": f"open_tab failed: {open_resp.get('error', 'unknown')}"}
        tab_id = (open_resp.get("data") or {}).get("tab_id")
        if tab_id is None:
            return {"url": url, "ok": False, "error": "open_tab returned no tab_id"}

        try:
            if act.wait != "none":
                wait_action = "wait_for_load" if act.wait == "load" else "wait_for_network_idle"
                wr = await _send_command(session_id, wait_action, {"tab_id": tab_id, "timeout_ms": act.timeout_ms})
                if not wr.get("success"):
                    return {"url": url, "ok": False, "error": f"{wait_action} failed: {wr.get('error', 'unknown')}"}

            if act.wait_selector:
                wsr = await _send_command(session_id, "wait_for_selector", {
                    "tab_id": tab_id,
                    "selector": act.wait_selector,
                    "state": "visible",
                    "timeout_ms": act.timeout_ms,
                })
                if not wsr.get("success"):
                    return {"url": url, "ok": False, "error": f"wait_for_selector failed: {wsr.get('error', 'unknown')}"}

            if act.scroll:
                await _send_command(session_id, "scroll_to_bottom", {
                    "tab_id": tab_id, "max_scrolls": 10, "delay_ms": 600, "timeout_ms": act.timeout_ms,
                })

            if act.elements_selector:
                er = await _send_command(session_id, "extract_elements", {
                    "tab_id": tab_id,
                    "selector": act.elements_selector,
                    "fields": act.fields,
                    "limit": act.limit,
                })
                if not er.get("success"):
                    return {"url": url, "ok": False, "error": f"extract_elements failed: {er.get('error', 'unknown')}"}
                records = (er.get("data") or {}).get("records", [])
                return {"url": url, "ok": True, "records": records}

            er = await _send_command(session_id, "extract", {
                "tab_id": tab_id,
                "format": act.format,
                "selector": act.selector,
                "max_chars": act.max_chars,
            })
            if not er.get("success"):
                return {"url": url, "ok": False, "error": f"extract failed: {er.get('error', 'unknown')}"}
            data = er.get("data") or {}
            content = data.get("content")
            if content is None:
                content = data.get("text", "")
            return {"url": url, "ok": True, "title": data.get("title", ""), "content": content[: act.max_chars]}
        finally:
            if act.close_tabs:
                try:
                    await _send_command(session_id, "close_tab", {"id": tab_id})
                except Exception:
                    pass  # best-effort cleanup — must not mask a successful result
    except Exception as e:
        return {"url": url, "ok": False, "error": str(e)}


async def _handle_crawl(session_id: str, act: CrawlAction) -> str:
    if not act.urls:
        return "crawl requires at least one URL."

    sem = asyncio.Semaphore(act.concurrency)

    async def run_one(url: str) -> dict[str, Any]:
        async with sem:
            return await _crawl_page(session_id, act, url)

    pages = await asyncio.gather(*(run_one(u) for u in act.urls))

    ok_count = sum(1 for p in pages if p.get("ok"))
    lines = [f"Crawled {len(pages)} URL(s) ({act.concurrency} at a time): {ok_count} ok, {len(pages) - ok_count} failed."]
    for p in pages:
        lines.append(f"\n## {p['url']}")
        if not p.get("ok"):
            lines.append(f"ERROR: {p.get('error', 'unknown')}")
        elif "records" in p:
            lines.append(f"{len(p['records'])} record(s):")
            lines.append(json.dumps(p["records"], indent=2, ensure_ascii=False, default=str))
        else:
            if p.get("title"):
                lines.append(f"Title: {p['title']}")
            lines.append(p.get("content", ""))

    return "\n".join(lines)
