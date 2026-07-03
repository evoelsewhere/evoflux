"""browser_use tool — built-in browser automation via browser-use.

Provides direct browser control without requiring an external LLM agent.
Manages a persistent :class:`BrowserSession` per agent session stored in
``state.metadata["_browser_session"]`` so the browser stays alive across
tool calls.

CDP Exposure
------------
Each browser session gets a dedicated CDP (Chrome DevTools Protocol)
endpoint.  The CDP WebSocket URL and HTTP URL are stored in
: data:`_cdp_info` and exposed via :func:`get_browser_info` so the API
layer and frontend can connect for live screencasting.

Actions
-------
start     — Launch a headless Chromium session (auto-called on first action).
stop      — Close the browser and release resources.
navigate  — Go to a URL.
click     — Click an element by CSS selector.
fill      — Type text into an element by CSS selector.
select    — Select an option in a <select> element.
extract   — Extract text content from the page (or a CSS selector).
screenshot — Capture a PNG screenshot (full page or element).
evaluate  — Run JavaScript in the page context.
scroll    — Scroll the page up/down.
back      — Navigate back in history.
forward   — Navigate forward in history.
wait      — Wait for a selector to appear or a fixed duration.
new_tab   — Open a URL in a new tab.
close_tab — Close a tab by index.
get_tabs  — List open tabs with URLs and titles.
switch_tab — Switch to a tab by index.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any, Literal

from loguru import logger
from pydantic import BaseModel, Field

from app.agent.tools.registry import InjectedArg, tool

# ---------------------------------------------------------------------------
# Session cache — keyed by agent session_id
# ---------------------------------------------------------------------------

_sessions: dict[str, Any] = {}
_pages: dict[str, Any] = {}
_cdp_info: dict[str, dict[str, Any]] = {}


def get_browser_info(session_id: str) -> dict[str, Any] | None:
    """Return browser session info for *session_id*, or ``None`` if inactive.

    Called by the ``/api/team/{sid}/browser`` endpoint.
    """
    info = _cdp_info.get(session_id)
    if info is None:
        return None
    return {
        "active": True,
        "cdp_url": info.get("cdp_url"),
        "cdp_http": info.get("cdp_http"),
        "current_url": info.get("current_url"),
        "current_title": info.get("current_title"),
        "tabs": info.get("tabs", []),
    }


def get_browser_page(session_id: str) -> Any | None:
    """Return the live Page object for *session_id*, or ``None``.

    Called by the screencast WebSocket endpoint to capture frames.
    """
    return _pages.get(session_id)


def get_browser_session(session_id: str) -> Any | None:
    """Return the live BrowserSession for *session_id*, or ``None``.

    Called by the screencast WebSocket endpoint for tab enumeration.
    """
    return _sessions.get(session_id)


async def _refresh_cdp_info(sid: str, session: Any, page: Any, *, action: str) -> None:
    """Update :data:`_cdp_info` from the live session and emit an SSE event."""
    try:
        cdp_url = getattr(session, "cdp_url", None)
        cdp_http: str | None = None
        if cdp_url and isinstance(cdp_url, str):
            # Derive HTTP URL from ws://127.0.0.1:PORT/...
            # cdp_url looks like: ws://127.0.0.1:9222/devtools/browser/...
            if cdp_url.startswith("ws://"):
                cdp_http = "http://" + cdp_url[len("ws://") :].split("/")[0]
            elif cdp_url.startswith("wss://"):
                cdp_http = "https://" + cdp_url[len("wss://") :].split("/")[0]

        url = await page.get_url() if page else None
        title = await page.get_title() if page else None

        tabs: list[dict[str, Any]] = []
        try:
            pages = await session.get_pages()
            for i, p in enumerate(pages):
                t_url = await p.get_url()
                t_title = await p.get_title()
                tabs.append({"index": i, "url": t_url, "title": t_title})
        except Exception:
            pass

        _cdp_info[sid] = {
            "cdp_url": cdp_url,
            "cdp_http": cdp_http,
            "current_url": url,
            "current_title": title,
            "tabs": tabs,
        }

        await _emit_browser_event(
            sid,
            active=True,
            action=action,
            cdp_url=cdp_url,
            cdp_http=cdp_http,
            current_url=url,
            current_title=title,
            tabs=tabs,
        )
    except Exception as e:
        logger.debug("browser_cdp_info_refresh_failed sid={} error={}", sid, e)


async def _emit_browser_event(
    sid: str,
    *,
    active: bool,
    action: str,
    cdp_url: str | None = None,
    cdp_http: str | None = None,
    current_url: str | None = None,
    current_title: str | None = None,
    tabs: list[dict[str, Any]] | None = None,
) -> None:
    """Push a ``browser_session`` SSE event to the stream store."""
    try:
        from app.services.memory_stream_store import push_event
        from app.services.stream_envelope import StreamEnvelope

        data: dict[str, Any] = {
            "type": "browser_session",
            "agent": "",
            "active": active,
            "action": action,
        }
        if cdp_url is not None:
            data["cdp_url"] = cdp_url
        if cdp_http is not None:
            data["cdp_http"] = cdp_http
        if current_url is not None:
            data["current_url"] = current_url
        if current_title is not None:
            data["current_title"] = current_title
        if tabs is not None:
            data["tabs"] = tabs

        envelope = StreamEnvelope.from_parts(event="browser_session", data=data)
        await push_event(sid, envelope)
    except Exception as e:
        logger.debug("browser_sse_emit_failed sid={} error={}", sid, e)


def _get_sid(state: Any) -> str:
    return state.metadata.get("session_id", "default") if state else "default"


async def _get_session(state: Any) -> tuple[Any, Any]:
    """Return ``(BrowserSession, current Page)``, launching if needed."""
    sid = _get_sid(state)
    if sid in _sessions:
        session = _sessions[sid]
        page = _pages.get(sid) or await session.get_current_page()
        _pages[sid] = page
        return session, page

    return await _launch_session(sid, headless=True)


async def _launch_session(
    sid: str, *, headless: bool = True, user_data_dir: str | None = None
) -> tuple[Any, Any]:
    """Launch a new BrowserSession and register it."""
    from browser_use import BrowserProfile, BrowserSession

    profile_kwargs: dict[str, Any] = {"headless": headless}
    if user_data_dir:
        profile_kwargs["user_data_dir"] = user_data_dir

    profile = BrowserProfile(**profile_kwargs)
    session = BrowserSession(browser_profile=profile)
    await session.start()
    page = await session.get_current_page()

    _sessions[sid] = session
    _pages[sid] = page

    logger.info("browser_session_started session_id={}", sid)
    await _refresh_cdp_info(sid, session, page, action="started")
    return session, page


async def _close_session(state: Any) -> str:
    sid = _get_sid(state)
    session = _sessions.pop(sid, None)
    _pages.pop(sid, None)
    _cdp_info.pop(sid, None)
    if session is None:
        return "No active browser session."
    try:
        await session.stop()
    except Exception:
        pass
    logger.info("browser_session_stopped session_id={}", sid)
    await _emit_browser_event(sid, active=False, action="stopped")
    return "Browser session closed."


# ---------------------------------------------------------------------------
# Action models
# ---------------------------------------------------------------------------


class StartAction(BaseModel):
    action: Literal["start"]
    headless: bool = Field(
        default=True, description="Run headless (no visible window)."
    )
    user_data_dir: str | None = Field(
        default=None,
        description="Browser profile directory for persistent state. None = incognito.",
    )


class StopAction(BaseModel):
    action: Literal["stop"]


class NavigateAction(BaseModel):
    action: Literal["navigate"]
    url: str = Field(description="URL to navigate to.")


class ClickAction(BaseModel):
    action: Literal["click"]
    selector: str = Field(description="CSS selector of the element to click.")


class FillAction(BaseModel):
    action: Literal["fill"]
    selector: str = Field(description="CSS selector of the input element.")
    text: str = Field(description="Text to type into the element.")
    clear: bool = Field(default=True, description="Clear the field before typing.")


class SelectAction(BaseModel):
    action: Literal["select"]
    selector: str = Field(description="CSS selector of the <select> element.")
    value: str = Field(description="Option value to select.")


class ExtractAction(BaseModel):
    action: Literal["extract"]
    selector: str | None = Field(
        default=None,
        description="CSS selector to extract from. None = full page body text.",
    )
    attribute: str | None = Field(
        default=None,
        description="Extract an attribute instead of text (e.g. 'href', 'src').",
    )


class ScreenshotAction(BaseModel):
    action: Literal["screenshot"]
    selector: str | None = Field(
        default=None,
        description="CSS selector of element to screenshot. None = full page.",
    )


class EvaluateAction(BaseModel):
    action: Literal["evaluate"]
    script: str = Field(
        description="JavaScript to execute. Use 'return <expr>' for a value.",
    )


class ScrollAction(BaseModel):
    action: Literal["scroll"]
    direction: Literal["up", "down"] = Field(description="Scroll direction.")
    pixels: int = Field(default=500, description="Pixels to scroll.")


class BackAction(BaseModel):
    action: Literal["back"]


class ForwardAction(BaseModel):
    action: Literal["forward"]


class WaitAction(BaseModel):
    action: Literal["wait"]
    selector: str | None = Field(
        default=None,
        description="CSS selector to wait for. None = just sleep.",
    )
    seconds: float = Field(default=2.0, description="Seconds to wait (max 30).")


class NewTabAction(BaseModel):
    action: Literal["new_tab"]
    url: str = Field(description="URL to open in the new tab.")


class CloseTabAction(BaseModel):
    action: Literal["close_tab"]
    index: int = Field(description="Zero-based tab index to close.")


class GetTabsAction(BaseModel):
    action: Literal["get_tabs"]


class SwitchTabAction(BaseModel):
    action: Literal["switch_tab"]
    index: int = Field(description="Zero-based tab index to switch to.")


# Discriminated union
AnyAction = Annotated[
    StartAction
    | StopAction
    | NavigateAction
    | ClickAction
    | FillAction
    | SelectAction
    | ExtractAction
    | ScreenshotAction
    | EvaluateAction
    | ScrollAction
    | BackAction
    | ForwardAction
    | WaitAction
    | NewTabAction
    | CloseTabAction
    | GetTabsAction
    | SwitchTabAction,
    Field(discriminator="action"),
]

# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------

_DESCRIPTION = """\
Control a headless Chromium browser. Pass one or more actions in a single call;
they are executed in order.

The browser session is persistent across calls — start it once (auto-started
on first action) and reuse it.  Close with ``stop`` when done.

Actions
-------
start      — Launch browser (auto on first action; headless by default).
stop       — Close browser and free resources.
navigate   — Go to a URL.
click      — Click element by CSS selector.
fill       — Type text into input by CSS selector.
select     — Choose a <select> option by value.
extract    — Get text content (full page or CSS selector). Set attribute="href" etc. for attributes.
screenshot — PNG screenshot (base64). Full page or element by selector.
evaluate   — Run JavaScript. Use "return <expr>" to get a value.
scroll     — Scroll up/down by N pixels.
back       — Browser back.
forward    — Browser forward.
wait       — Wait for CSS selector or fixed seconds.
new_tab    — Open URL in new tab.
close_tab  — Close tab by index.
get_tabs   — List open tabs [{url, title}].
switch_tab — Switch to tab by index.

Tips
----
- Use ``extract`` after ``navigate`` to read page content.
- Chain ``navigate`` → ``wait`` → ``extract`` for dynamic pages.
- ``screenshot`` returns base64 PNG — useful for visual verification.
- ``evaluate`` runs in page context; access DOM directly via JS.\
"""


@tool(name="browser_use")
async def browser_use(
    actions: Annotated[
        list[AnyAction],
        Field(description="Ordered list of browser actions to execute."),
    ],
    _state: Annotated[Any, InjectedArg()] = None,
) -> str:
    """Control a headless Chromium browser for web automation."""
    results: list[str] = []

    for act in actions:
        try:
            result = await _dispatch(act, _state)
            results.append(result)
        except Exception as e:
            logger.debug("browser_use_error action={} error={}", act.action, e)
            results.append(f"Error ({act.action}): {e}")

    return "\n---\n".join(results) if results else "No actions executed."


async def _dispatch(act: Any, state: Any) -> str:
    action = act.action

    if action == "start":
        return await _handle_start(act, state)
    if action == "stop":
        return await _handle_stop(state)

    # All other actions require a live session
    session, page = await _get_session(state)

    if action == "navigate":
        return await _handle_navigate(act, page, state)
    if action == "click":
        return await _handle_click(act, page, state)
    if action == "fill":
        return await _handle_fill(act, page, state)
    if action == "select":
        return await _handle_select(act, page)
    if action == "extract":
        return await _handle_extract(act, page)
    if action == "screenshot":
        return await _handle_screenshot(act, page)
    if action == "evaluate":
        return await _handle_evaluate(act, page)
    if action == "scroll":
        return await _handle_scroll(act, page, state)
    if action == "back":
        await page.go_back()
        await _refresh_cdp_info(_get_sid(state), session, page, action="navigated")
        url = await page.get_url()
        return f"Navigated back → {url}"
    if action == "forward":
        await page.go_forward()
        await _refresh_cdp_info(_get_sid(state), session, page, action="navigated")
        url = await page.get_url()
        return f"Navigated forward → {url}"
    if action == "wait":
        return await _handle_wait(act, page)
    if action == "new_tab":
        return await _handle_new_tab(act, state)
    if action == "close_tab":
        return await _handle_close_tab(act, state)
    if action == "get_tabs":
        return await _handle_get_tabs(state)
    if action == "switch_tab":
        return await _handle_switch_tab(act, state)

    return f"Unknown action: {action}"


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------


async def _handle_start(act: StartAction, state: Any) -> str:
    sid = _get_sid(state)
    if sid in _sessions:
        return "Browser session already running."

    await _launch_session(sid, headless=act.headless, user_data_dir=act.user_data_dir)
    return "Browser session started."


async def _handle_stop(state: Any) -> str:
    return await _close_session(state)


async def _handle_navigate(act: NavigateAction, page: Any, state: Any) -> str:
    await page.goto(act.url)
    session = _sessions.get(_get_sid(state))
    if session:
        await _refresh_cdp_info(_get_sid(state), session, page, action="navigated")
    url = await page.get_url()
    title = await page.get_title()
    return f"Navigated to {url}\nTitle: {title}"


async def _handle_click(act: ClickAction, page: Any, state: Any) -> str:
    elements = await page.get_elements_by_css_selector(act.selector)
    if not elements:
        return f"No element found for selector: {act.selector}"
    await elements[0].click()
    session = _sessions.get(_get_sid(state))
    if session:
        await _refresh_cdp_info(_get_sid(state), session, page, action="clicked")
    return f"Clicked: {act.selector}"


async def _handle_fill(act: FillAction, page: Any, state: Any) -> str:
    elements = await page.get_elements_by_css_selector(act.selector)
    if not elements:
        return f"No element found for selector: {act.selector}"
    await elements[0].fill(act.text, clear=act.clear)
    session = _sessions.get(_get_sid(state))
    if session:
        await _refresh_cdp_info(_get_sid(state), session, page, action="filled")
    return f"Filled {act.selector} with text ({len(act.text)} chars)."


async def _handle_select(act: SelectAction, page: Any) -> str:
    elements = await page.get_elements_by_css_selector(act.selector)
    if not elements:
        return f"No element found for selector: {act.selector}"
    await elements[0].select_option([act.value])
    return f"Selected '{act.value}' in {act.selector}"


async def _handle_extract(act: ExtractAction, page: Any) -> str:
    if act.selector:
        elements = await page.get_elements_by_css_selector(act.selector)
        if not elements:
            return f"No element found for selector: {act.selector}"
        if act.attribute:
            val = await elements[0].get_attribute(act.attribute)
            return val or f"Attribute '{act.attribute}' not found."
        texts = []
        for el in elements:
            t = await el.evaluate("() => this.textContent")
            texts.append(t.strip() if t else "")
        return "\n".join(texts) if texts else "(empty)"

    # Full page body text
    text = await page.evaluate("() => document.body.innerText")
    return text if text else "(empty page)"


async def _handle_screenshot(act: ScreenshotAction, page: Any) -> str:
    if act.selector:
        elements = await page.get_elements_by_css_selector(act.selector)
        if not elements:
            return f"No element found for selector: {act.selector}"
        b64 = await elements[0].screenshot(format="png")
    else:
        b64 = await page.screenshot(format="png")

    # Return a summary; the base64 is available but too large for inline display
    size_kb = len(b64) * 3 / 4 / 1024  # approximate decoded size
    return f"Screenshot captured ({size_kb:.0f} KB, base64). Use the read tool with a .png file to view."


async def _handle_evaluate(act: EvaluateAction, page: Any) -> str:
    result = await page.evaluate(act.script)
    return str(result) if result is not None else "(no return value)"


async def _handle_scroll(act: ScrollAction, page: Any, state: Any) -> str:
    delta = act.pixels if act.direction == "down" else -act.pixels
    mouse = await page.mouse
    await mouse.scroll(delta_y=delta)
    session = _sessions.get(_get_sid(state))
    if session:
        await _refresh_cdp_info(_get_sid(state), session, page, action="scrolled")
    return f"Scrolled {act.direction} {act.pixels}px."


async def _handle_wait(act: WaitAction, page: Any) -> str:
    seconds = min(act.seconds, 30.0)
    if act.selector:
        # Poll for the selector
        elapsed = 0.0
        interval = 0.25
        while elapsed < seconds:
            elements = await page.get_elements_by_css_selector(act.selector)
            if elements:
                return f"Selector '{act.selector}' found after {elapsed:.1f}s."
            await asyncio.sleep(interval)
            elapsed += interval
        return f"Timeout: selector '{act.selector}' not found after {seconds:.1f}s."
    await asyncio.sleep(seconds)
    return f"Waited {seconds:.1f}s."


async def _handle_new_tab(act: NewTabAction, state: Any) -> str:
    session, _ = await _get_session(state)
    page = await session.new_page(act.url)
    sid = _get_sid(state)
    _pages[sid] = page
    await _refresh_cdp_info(sid, session, page, action="new_tab")
    url = await page.get_url()
    title = await page.get_title()
    return f"New tab: {url}\nTitle: {title}"


async def _handle_close_tab(act: CloseTabAction, state: Any) -> str:
    session, _ = await _get_session(state)
    pages = await session.get_pages()
    if act.index < 0 or act.index >= len(pages):
        return f"Invalid tab index {act.index}. {len(pages)} tabs open."
    target = pages[act.index]
    url = await target.get_url()
    await session.close_page(target)
    # Switch to first available tab
    remaining = await session.get_pages()
    sid = _get_sid(state)
    if remaining:
        _pages[sid] = remaining[0]
        await _refresh_cdp_info(sid, session, remaining[0], action="closed_tab")
    else:
        _pages.pop(sid, None)
        _cdp_info.pop(sid, None)
        await _emit_browser_event(sid, active=False, action="closed_tab")
    return f"Closed tab {act.index} ({url}). {len(remaining)} tabs remaining."


async def _handle_get_tabs(state: Any) -> str:
    session, _ = await _get_session(state)
    pages = await session.get_pages()
    lines: list[str] = []
    for i, p in enumerate(pages):
        url = await p.get_url()
        title = await p.get_title()
        lines.append(f"[{i}] {title} — {url}")
    return "\n".join(lines) if lines else "No tabs open."


async def _handle_switch_tab(act: SwitchTabAction, state: Any) -> str:
    session, _ = await _get_session(state)
    pages = await session.get_pages()
    if act.index < 0 or act.index >= len(pages):
        return f"Invalid tab index {act.index}. {len(pages)} tabs open."
    page = pages[act.index]
    sid = _get_sid(state)
    _pages[sid] = page
    await _refresh_cdp_info(sid, session, page, action="tab_switched")
    url = await page.get_url()
    title = await page.get_title()
    return f"Switched to tab {act.index}: {title} — {url}"
