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
snapshot  — Indexed map of interactive elements (browser-use selector map).
console   — Recent console messages captured via CDP listeners.
network   — Recent network requests with status, captured via CDP listeners.
click     — Click an element by snapshot index or CSS selector.
fill      — Type text into an element by snapshot index or CSS selector.
select    — Select an option in a <select> element.
extract   — Extract text content from the page (or a CSS selector), capped.
screenshot — JPEG screenshot returned as a multimodal image part.
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
import time
from collections import deque
from typing import Annotated, Any, Literal

from loguru import logger
from pydantic import BaseModel, Field

from app.agent.schemas.chat import ContentBlock, ImageDataBlock, TextBlock, ToolResult
from app.agent.tools.registry import InjectedArg, tool

# ---------------------------------------------------------------------------
# Session cache — keyed by agent session_id
# ---------------------------------------------------------------------------

_sessions: dict[str, Any] = {}
_pages: dict[str, Any] = {}
_cdp_info: dict[str, dict[str, Any]] = {}

# Observability buffers (console + network) — bounded per session so a chatty
# page can't grow memory without limit. Populated by CDP event listeners
# attached in :func:`_attach_observability`.
_CONSOLE_BUFFER = 300
_NETWORK_BUFFER = 400
_console_logs: dict[str, deque[dict[str, Any]]] = {}
_network_events: dict[str, deque[dict[str, Any]]] = {}
# CDP session ids we already registered listeners on (per agent session) —
# re-attaching after new_tab/switch_tab must not double-register.
_observed_cdp_sessions: dict[str, set[str]] = {}

_MAX_IMAGE_BYTES = 10_485_760  # 10 MB — matches the read tool's vision cap


def _fmt_remote_object(obj: dict[str, Any]) -> str:
    """Render a CDP RemoteObject as a short human string."""
    if "value" in obj:
        return str(obj["value"])
    return str(obj.get("description") or obj.get("type") or "?")


async def _attach_observability(sid: str, session: Any) -> None:
    """Register CDP listeners that feed the console/network ring buffers.

    Best-effort: a failure here must never break the action that triggered
    it — observability degrades to "no data yet" instead.
    """
    try:
        cdp = await session.get_or_create_cdp_session()
        cdp_session_id = getattr(cdp, "session_id", None)
        seen = _observed_cdp_sessions.setdefault(sid, set())
        if cdp_session_id in seen:
            return

        console_buf = _console_logs.setdefault(sid, deque(maxlen=_CONSOLE_BUFFER))
        network_buf = _network_events.setdefault(sid, deque(maxlen=_NETWORK_BUFFER))
        # requestId → {method, url} so responses/failures can name their request.
        pending: dict[str, dict[str, str]] = {}

        async def on_console(event: dict[str, Any], session_id: str | None = None) -> None:
            args = event.get("args", [])
            console_buf.append(
                {
                    "ts": time.time(),
                    "level": event.get("type", "log"),
                    "text": " ".join(_fmt_remote_object(a) for a in args)[:2000],
                }
            )

        async def on_exception(event: dict[str, Any], session_id: str | None = None) -> None:
            details = event.get("exceptionDetails", {})
            exc = details.get("exception") or {}
            text = exc.get("description") or details.get("text") or "Uncaught exception"
            console_buf.append(
                {"ts": time.time(), "level": "error", "text": str(text)[:2000]}
            )

        async def on_request(event: dict[str, Any], session_id: str | None = None) -> None:
            req = event.get("request", {})
            rid = event.get("requestId", "")
            if len(pending) > _NETWORK_BUFFER:
                pending.clear()
            pending[rid] = {
                "method": req.get("method", "GET"),
                "url": req.get("url", "?"),
            }

        async def on_response(event: dict[str, Any], session_id: str | None = None) -> None:
            rid = event.get("requestId", "")
            req = pending.pop(rid, None) or {}
            resp = event.get("response", {})
            network_events_url = resp.get("url") or req.get("url", "?")
            network_buf.append(
                {
                    "ts": time.time(),
                    "method": req.get("method", "GET"),
                    "url": network_events_url,
                    "status": resp.get("status", 0),
                }
            )

        async def on_failed(event: dict[str, Any], session_id: str | None = None) -> None:
            rid = event.get("requestId", "")
            req = pending.pop(rid, None) or {}
            network_buf.append(
                {
                    "ts": time.time(),
                    "method": req.get("method", "GET"),
                    "url": req.get("url", "?"),
                    "status": 0,
                    "error": event.get("errorText", "failed"),
                }
            )

        client = cdp.cdp_client
        await client.send.Runtime.enable(session_id=cdp_session_id)
        await client.send.Network.enable(session_id=cdp_session_id)
        client.register.Runtime.consoleAPICalled(on_console)
        client.register.Runtime.exceptionThrown(on_exception)
        client.register.Network.requestWillBeSent(on_request)
        client.register.Network.responseReceived(on_response)
        client.register.Network.loadingFailed(on_failed)
        if cdp_session_id:
            seen.add(cdp_session_id)
        logger.debug("browser_observability_attached sid={}", sid)
    except Exception as e:
        logger.debug("browser_observability_attach_failed sid={} error={}", sid, e)


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
    await _attach_observability(sid, session)
    await _refresh_cdp_info(sid, session, page, action="started")
    return session, page


async def _close_session(state: Any) -> str:
    sid = _get_sid(state)
    session = _sessions.pop(sid, None)
    _pages.pop(sid, None)
    _cdp_info.pop(sid, None)
    _console_logs.pop(sid, None)
    _network_events.pop(sid, None)
    _observed_cdp_sessions.pop(sid, None)
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
    selector: str | None = Field(
        default=None, description="CSS selector of the element to click."
    )
    index: int | None = Field(
        default=None,
        description="Element index from a prior `snapshot` action (preferred).",
    )


class FillAction(BaseModel):
    action: Literal["fill"]
    selector: str | None = Field(
        default=None, description="CSS selector of the input element."
    )
    index: int | None = Field(
        default=None,
        description="Element index from a prior `snapshot` action (preferred).",
    )
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
    max_chars: int = Field(
        default=15_000,
        ge=100,
        le=100_000,
        description="Truncate extracted text beyond this length.",
    )


class SnapshotAction(BaseModel):
    action: Literal["snapshot"]
    max_chars: int = Field(
        default=15_000,
        ge=500,
        le=100_000,
        description="Truncate the snapshot beyond this length.",
    )


class ConsoleAction(BaseModel):
    action: Literal["console"]
    level: Literal["all", "error", "warn"] = Field(
        default="all",
        description="'error' = errors only, 'warn' = warnings + errors.",
    )
    limit: int = Field(default=50, ge=1, le=200, description="Max entries, newest last.")


class NetworkAction(BaseModel):
    action: Literal["network"]
    filter: Literal["all", "failed"] = Field(
        default="all",
        description="'failed' = only 4xx/5xx responses and network errors.",
    )
    limit: int = Field(default=50, ge=1, le=200, description="Max entries, newest last.")


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
    | SnapshotAction
    | ConsoleAction
    | NetworkAction
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
they are executed in order. The session persists across calls (auto-started on
first action); close with ``stop`` when done.

Observation (prefer these over screenshots):
snapshot   — Indexed map of interactive elements + page structure. Use the
             returned [index] numbers with click/fill instead of guessing CSS.
console    — Recent console messages (filter: error/warn) — check after loads.
network    — Recent requests with status (filter: failed) — spot 4xx/5xx.
extract    — Text content (full page or CSS selector; attribute="href" etc.).
screenshot — Image of page/element, returned as a real image for vision — use
             as final visual proof, not as the primary observation channel.

Interaction:
navigate / click / fill / select / scroll / back / forward / wait —
click and fill accept ``index`` (from snapshot, preferred) or ``selector``.
evaluate   — Run JavaScript ("return <expr>" for a value); debugging only.

Tabs: new_tab / close_tab / get_tabs / switch_tab.

Verify workflow: navigate → wait → console + snapshot → interact → screenshot.\
"""


@tool(name="browser_use")
async def browser_use(
    actions: Annotated[
        list[AnyAction],
        Field(description="Ordered list of browser actions to execute."),
    ],
    _state: Annotated[Any, InjectedArg()] = None,
) -> str | ToolResult:
    """Control a headless Chromium browser for web automation."""
    # Handlers return ``str`` for text output or ``ToolResult`` for
    # multimodal output (screenshots). Batches mixing both are folded into
    # one ToolResult so vision models receive the images inline.
    results: list[str | ToolResult] = []

    for act in actions:
        try:
            result = await _dispatch(act, _state)
            results.append(result)
        except Exception as e:
            logger.debug("browser_use_error action={} error={}", act.action, e)
            results.append(f"Error ({act.action}): {e}")

    if not results:
        return "No actions executed."

    if not any(isinstance(r, ToolResult) for r in results):
        return "\n---\n".join(r for r in results if isinstance(r, str))

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


async def _dispatch(act: Any, state: Any) -> str | ToolResult:
    action = act.action

    if action == "start":
        return await _handle_start(act, state)
    if action == "stop":
        return await _handle_stop(state)
    if action == "console":
        return _handle_console(act, state)
    if action == "network":
        return _handle_network(act, state)

    # All other actions require a live session
    session, page = await _get_session(state)

    if action == "navigate":
        return await _handle_navigate(act, page, state)
    if action == "snapshot":
        return await _handle_snapshot(act, session, page)
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


async def _resolve_element(
    page: Any,
    state: Any,
    *,
    selector: str | None,
    index: int | None,
) -> tuple[Any | None, str, str | None]:
    """Resolve an element by snapshot index (preferred) or CSS selector.

    Returns ``(element, label, error)`` — exactly one of element/error is set.
    """
    if index is not None:
        session = _sessions.get(_get_sid(state))
        node = await session.get_dom_element_by_index(index) if session else None
        if node is None:
            return (
                None,
                "",
                f"No element with index {index}. Run `snapshot` first — "
                "indices are only valid after the latest snapshot.",
            )
        element = await page.get_element(node.backend_node_id)
        return element, f"[{index}]", None
    if selector:
        elements = await page.get_elements_by_css_selector(selector)
        if not elements:
            return None, "", f"No element found for selector: {selector}"
        return elements[0], selector, None
    return None, "", "Provide either `index` (from snapshot) or `selector`."


async def _handle_click(act: ClickAction, page: Any, state: Any) -> str:
    element, label, error = await _resolve_element(
        page, state, selector=act.selector, index=act.index
    )
    if error:
        return error
    await element.click()
    session = _sessions.get(_get_sid(state))
    if session:
        await _refresh_cdp_info(_get_sid(state), session, page, action="clicked")
    return f"Clicked: {label}"


async def _handle_fill(act: FillAction, page: Any, state: Any) -> str:
    element, label, error = await _resolve_element(
        page, state, selector=act.selector, index=act.index
    )
    if error:
        return error
    await element.fill(act.text, clear=act.clear)
    session = _sessions.get(_get_sid(state))
    if session:
        await _refresh_cdp_info(_get_sid(state), session, page, action="filled")
    return f"Filled {label} with text ({len(act.text)} chars)."


async def _handle_select(act: SelectAction, page: Any) -> str:
    elements = await page.get_elements_by_css_selector(act.selector)
    if not elements:
        return f"No element found for selector: {act.selector}"
    await elements[0].select_option([act.value])
    return f"Selected '{act.value}' in {act.selector}"


def _truncate(text: str, max_chars: int, *, hint: str) -> str:
    if len(text) <= max_chars:
        return text
    return (
        text[:max_chars]
        + f"\n…[truncated {len(text) - max_chars:,} of {len(text):,} chars — {hint}]"
    )


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
        joined = "\n".join(texts) if texts else "(empty)"
        return _truncate(joined, act.max_chars, hint="narrow the selector")

    # Full page body text
    text = await page.evaluate("() => document.body.innerText")
    if not text:
        return "(empty page)"
    return _truncate(text, act.max_chars, hint="use a selector or raise max_chars")


async def _handle_snapshot(act: SnapshotAction, session: Any, page: Any) -> str:
    """Indexed map of interactive elements — the primary observation action.

    The [index] numbers in the output feed ``click``/``fill`` via ``index``;
    they stay valid until the next snapshot or navigation.
    """
    state_summary = await session.get_browser_state_summary(
        include_screenshot=False
    )
    dom_text = state_summary.dom_state.llm_representation()
    header = f"URL: {state_summary.url}\nTitle: {state_summary.title}\n"
    body = _truncate(dom_text, act.max_chars, hint="raise max_chars if needed")
    return header + "\nInteractive elements (use [index] with click/fill):\n" + body


def _handle_console(act: ConsoleAction, state: Any) -> str:
    entries = list(_console_logs.get(_get_sid(state), ()))
    if act.level == "error":
        entries = [e for e in entries if e["level"] in ("error", "assert")]
    elif act.level == "warn":
        entries = [e for e in entries if e["level"] in ("error", "assert", "warning")]
    entries = entries[-act.limit :]
    if not entries:
        return "(no console messages captured)"
    return "\n".join(f"[{e['level']}] {e['text']}" for e in entries)


def _handle_network(act: NetworkAction, state: Any) -> str:
    entries = list(_network_events.get(_get_sid(state), ()))
    if act.filter == "failed":
        entries = [e for e in entries if e.get("error") or e.get("status", 0) >= 400]
    entries = entries[-act.limit :]
    if not entries:
        return "(no network requests captured)"
    lines = []
    for e in entries:
        status = e.get("error") or e.get("status", "?")
        lines.append(f"{e['method']} {e['url']} → {status}")
    return "\n".join(lines)


async def _handle_screenshot(act: ScreenshotAction, page: Any) -> str | ToolResult:
    if act.selector:
        elements = await page.get_elements_by_css_selector(act.selector)
        if not elements:
            return f"No element found for selector: {act.selector}"
        b64 = await elements[0].screenshot(format="jpeg", quality=80)
        label = act.selector
    else:
        b64 = await page.screenshot(format="jpeg", quality=80)
        label = "page"

    decoded_size = len(b64) * 3 // 4
    if decoded_size > _MAX_IMAGE_BYTES:
        return (
            f"Screenshot too large for vision input ({decoded_size // 1024} KB > "
            f"{_MAX_IMAGE_BYTES // 1024} KB). Screenshot a specific element instead."
        )

    url = await page.get_url()
    return ToolResult(
        parts=[
            TextBlock(text=f"[Screenshot: {label} @ {url}]"),
            ImageDataBlock(data=b64, media_type="image/jpeg"),
        ]
    )


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
    await _attach_observability(sid, session)
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
    await _attach_observability(sid, session)
    await _refresh_cdp_info(sid, session, page, action="tab_switched")
    url = await page.get_url()
    title = await page.get_title()
    return f"Switched to tab {act.index}: {title} — {url}"
