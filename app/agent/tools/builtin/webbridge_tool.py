"""webbridge tool — control the user's real browser via the WebBridge extension.

Unlike ``browser_use`` which controls EvoFlux's visible in-app browser with no
external-browser fallback, ``webbridge`` sends commands through a
WebSocket relay to a Chrome/Edge extension running in the user's external
browser. This gives the agent access to that browser's login sessions, cookies,
and open tabs.

Architecture::

    Agent → webbridge tool → WebBridgeManager → relay → Chrome Extension → Real Browser (CDP)

The tool runs in the same process as the relay, so it talks to
:data:`app.services.webbridge_service.webbridge_manager` directly — no
loopback WebSocket. The extension must be installed and connected for this
tool to work. Check connection with ``status`` action before issuing commands.
"""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from datetime import datetime
import json
from pathlib import Path
from typing import Annotated, Any, Literal, cast
from urllib.parse import urlsplit

from loguru import logger
from pydantic import BaseModel, Field, model_validator

from app.agent.schemas.chat import ImageDataBlock, TextBlock, ToolResult
from app.agent.tools.builtin.browser_shared import (
    combine_browser_results,
    mark_untrusted_browser_result,
)
from app.agent.tools.registry import InjectedArg, tool
from app.services.webbridge_service import webbridge_manager


_webbridge_target_id: ContextVar[str | None] = ContextVar(
    "webbridge_target_id", default=None
)


def _get_sid(state: Any) -> str:
    if not state:
        return "default"
    metadata = state.metadata or {}
    return metadata.get("webbridge_session_id") or metadata.get("session_id", "default")


#: Set when a command comes back unsuccessful. Handlers report failure by
#: *returning* a message rather than raising — which reads well for the model
#: and leaves the caller with nothing but prose to inspect. This records the
#: fact itself, so a sequence can stop without guessing from the text.
_webbridge_command_failed: ContextVar[bool] = ContextVar(
    "webbridge_command_failed", default=False
)

#: How the extension animates the agent's pointer. Work sessions keep the
#: human-paced cursor so the user can follow what the agent does in a browser
#: they share; a Coding session is verifying its own app, where that
#: 72–360 ms glide before every press is only latency.
_webbridge_pointer_motion: ContextVar[Literal["human", "instant"] | None] = ContextVar(
    "webbridge_pointer_motion", default=None
)

#: Coding sessions have the extension record console and network from their
#: first command, so the page load the agent triggers is already there when it
#: asks. Work sessions start recording only on an explicit console/network
#: read — the page-visible `Runtime.enable` is not something to switch on
#: unasked in the user's everyday browsing.
_webbridge_devtools_capture: ContextVar[bool] = ContextVar(
    "webbridge_devtools_capture", default=False
)


async def _send_command(
    session_id: str, action: str, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Send a command to the extension via the manager and wait for response."""
    motion = _webbridge_pointer_motion.get()
    if motion is not None:
        params = {**(params or {}), "_webbridge_pointer_motion": motion}
    if _webbridge_devtools_capture.get():
        params = {**(params or {}), "_webbridge_devtools": "capture"}
    response = await webbridge_manager.send_command(
        session_id,
        action,
        params,
        extension_id=_webbridge_target_id.get(),
    )
    if not response.get("success"):
        _webbridge_command_failed.set(True)
    return response


# ---------------------------------------------------------------------------
# Action models
# ---------------------------------------------------------------------------

#: Every action takes an optional ``tab_id`` (from ``get_tabs``) to drive that
#: exact tab — including a background tab — without switching Chrome's focus
#: to it; omitted, it acts on the active tab. That is explained once, in the
#: tool guide: repeated as a field description on ~50 actions it was the
#: largest single cost of the schema.

_REF_DESC = "Snapshot ref such as 'e12'; preferred over a selector."


class StatusAction(BaseModel):
    action: Literal["status"]


class NavigateAction(BaseModel):
    action: Literal["navigate"]
    url: str = Field(description="URL to navigate to.")
    tab_id: int | None = None


class ClickAction(BaseModel):
    action: Literal["click"]
    x: float = Field(description="X coordinate to click.")
    y: float = Field(description="Y coordinate to click.")
    button: Literal["left", "right", "middle"] = Field(default="left")
    tab_id: int | None = None


class DblClickAction(BaseModel):
    action: Literal["dblclick"]
    x: float = Field(description="X coordinate to double-click.")
    y: float = Field(description="Y coordinate to double-click.")
    tab_id: int | None = None


class TypeAction(BaseModel):
    action: Literal["type"]
    text: str = Field(description="Text to type.")
    tab_id: int | None = None


class KeyAction(BaseModel):
    action: Literal["key"]
    key: str = Field(description="Key to press (e.g. Enter, Tab, Escape, ArrowUp).")
    modifiers: list[Literal["Alt", "Control", "Meta", "Shift"]] = Field(
        default_factory=list,
        description="Modifier keys held during the press (e.g. ['Meta'] for Cmd on macOS).",
    )
    tab_id: int | None = None


class ScrollAction(BaseModel):
    action: Literal["scroll"]
    dx: int = Field(default=0, description="Horizontal scroll delta.")
    dy: int = Field(default=0, description="Vertical scroll delta.")
    tab_id: int | None = None


class ResizeAction(BaseModel):
    action: Literal["resize"]
    preset: Literal["mobile", "tablet", "desktop"] | None = None
    width: int | None = Field(default=None, ge=200, le=4000)
    height: int | None = Field(default=None, ge=200, le=4000)
    device_scale_factor: float = Field(default=1.0, ge=0.5, le=4.0)
    mobile: bool | None = None
    touch: bool | None = None
    color_scheme: Literal["light", "dark"] | None = None
    tab_id: int | None = None

    @model_validator(mode="after")
    def _validate_size(self) -> "ResizeAction":
        if self.preset is None and (self.width is None or self.height is None):
            raise ValueError("resize requires a preset or both width and height")
        return self


class ResetViewportAction(BaseModel):
    action: Literal["reset_viewport"]
    tab_id: int | None = None


class DialogsAction(BaseModel):
    action: Literal["dialogs"]
    clear: bool = False
    limit: int = Field(default=20, ge=1, le=100)
    tab_id: int | None = None


class HandleDialogAction(BaseModel):
    action: Literal["handle_dialog"]
    accept: bool = False
    prompt_text: str | None = Field(default=None, max_length=10_000)
    tab_id: int | None = None


_DEVTOOLS_SCOPE_DESC = (
    "'page' (default): only what the current page produced since it loaded. "
    "'all': include earlier pages of this tab too."
)


class ConsoleAction(BaseModel):
    action: Literal["console"]
    level: Literal["all", "debug", "log", "info", "warning", "error"] = Field(
        default="all",
        description="Minimum level: 'warning' returns warnings and errors.",
    )
    contains: str | None = Field(
        default=None, description="Only messages containing this text."
    )
    limit: int = Field(default=50, ge=1, le=200, description="Newest N messages.")
    scope: Literal["page", "all"] = Field(
        default="page", description=_DEVTOOLS_SCOPE_DESC
    )
    clear: bool = Field(
        default=False,
        description="Empty the recorded console after reading, so the next read shows only what happens from here.",
    )
    tab_id: int | None = None


class NetworkAction(BaseModel):
    action: Literal["network"]
    filter: Literal["all", "failed"] = Field(
        default="all", description="'failed': HTTP status >= 400 or no response."
    )
    resource: Literal[
        "all", "fetch", "document", "script", "stylesheet", "image", "font", "websocket"
    ] = Field(default="all", description="'fetch' covers fetch, XHR and EventSource.")
    url_contains: str | None = None
    method: (
        Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"] | None
    ) = None
    limit: int = Field(default=50, ge=1, le=200, description="Newest N requests.")
    scope: Literal["page", "all"] = Field(
        default="page", description=_DEVTOOLS_SCOPE_DESC
    )
    clear: bool = Field(
        default=False, description="Empty the recorded requests after reading."
    )
    tab_id: int | None = None


class NetworkBodyAction(BaseModel):
    action: Literal["network_body"]
    request_id: str = Field(description="The request id shown by the network action.")
    max_chars: int = Field(default=20_000, ge=100, le=100_000)
    tab_id: int | None = None


_PAGE_POWER_DESC = (
    "Needs webbridge.allow_evaluate: it reads secrets or changes the page as "
    "fully as running script would."
)


class StorageAction(BaseModel):
    action: Literal["storage"]
    area: Literal["local", "session"] = "local"
    operation: Literal["get", "set", "remove", "clear"] = "get"
    key: str | None = Field(
        default=None, description="One key (get) or the key to set/remove."
    )
    value: str | None = Field(default=None, max_length=100_000)
    include_values: bool = Field(
        default=False,
        description=f"Return values, not just keys and sizes. {_PAGE_POWER_DESC}",
    )
    tab_id: int | None = None


class CookiesAction(BaseModel):
    action: Literal["cookies"]
    operation: Literal["get", "set", "delete"] = "get"
    include_values: bool = Field(
        default=False,
        description=(
            "Return cookie values; HttpOnly values stay redacted except on a "
            f"localhost page. {_PAGE_POWER_DESC}"
        ),
    )
    name: str | None = None
    value: str | None = Field(default=None, max_length=4096)
    path: str | None = Field(
        default=None,
        description="Defaults to / when setting, every path when deleting.",
    )
    domain: str | None = Field(default=None, description="Defaults to the page's host.")
    max_age: int | None = Field(
        default=None, description="Seconds; omit for a session cookie."
    )
    same_site: Literal["Strict", "Lax", "None"] | None = None
    secure: bool = False
    http_only: bool = False
    tab_id: int | None = None


class InspectAction(BaseModel):
    action: Literal["inspect"]
    ref: str | None = Field(default=None, description=_REF_DESC)
    selector: str | None = Field(default=None, description="CSS selector, if no ref.")
    index: int = Field(default=0, ge=0)
    properties: list[str] | None = Field(
        default=None,
        max_length=60,
        description="Computed CSS properties to read; default is a layout/visibility set.",
    )
    tab_id: int | None = None

    @model_validator(mode="after")
    def _needs_target(self) -> InspectAction:
        if not self.ref and not self.selector:
            raise ValueError("inspect needs a ref or a selector")
        return self


class UploadFileAction(BaseModel):
    action: Literal["upload_file"]
    ref: str | None = Field(default=None, description=_REF_DESC)
    selector: str | None = Field(default=None, description="CSS selector, if no ref.")
    index: int = Field(default=0, ge=0)
    paths: list[str] = Field(
        min_length=1,
        max_length=10,
        description="Files in the workspace (or this session's uploads) to put in the <input type=file>.",
    )
    tab_id: int | None = None

    @model_validator(mode="after")
    def _needs_target(self) -> UploadFileAction:
        if not self.ref and not self.selector:
            raise ValueError("upload_file needs a ref or a selector")
        return self


class GeoPoint(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy: float = Field(default=50, gt=0)


class EmulateAction(BaseModel):
    action: Literal["emulate"]
    network: Literal["none", "offline", "slow_3g", "fast_3g", "fast_4g"] | None = Field(
        default=None,
        description="Throttle or cut the tab's network; 'none' restores it.",
    )
    cpu_throttling: float | None = Field(
        default=None, ge=1, le=20, description="CPU slowdown factor; 1 restores it."
    )
    geolocation: GeoPoint | None = None
    timezone: str | None = Field(
        default=None,
        description="IANA zone such as 'Asia/Ho_Chi_Minh'; '' restores it.",
    )
    locale: str | None = Field(
        default=None, description="Such as 'vi-VN'; '' restores it."
    )
    clear: bool = Field(default=False, description="Remove every override first.")
    tab_id: int | None = None


class MockAction(BaseModel):
    action: Literal["mock"]
    operation: Literal["add", "remove", "list", "clear"] = "list"
    url_pattern: str | None = Field(
        default=None,
        description="URL glob with * wildcards; without one it matches as a prefix.",
    )
    method: (
        Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"] | None
    ) = None
    status: int = Field(default=200, ge=100, le=599)
    body: str = Field(default="", max_length=200_000)
    content_type: str = "application/json"
    headers: dict[str, str] = Field(default_factory=dict)
    fail: (
        Literal[
            "Failed",
            "Aborted",
            "TimedOut",
            "AccessDenied",
            "ConnectionRefused",
            "ConnectionReset",
            "NameNotResolved",
            "InternetDisconnected",
            "BlockedByClient",
        ]
        | None
    ) = Field(
        default=None, description="Fail the request this way instead of answering it."
    )
    delay_ms: int = Field(default=0, ge=0, le=30_000)
    times: int = Field(
        default=0, ge=0, description="Stop after this many hits; 0 = until removed."
    )
    id: str | None = Field(default=None, description="Rule id to remove.")
    tab_id: int | None = None

    @model_validator(mode="after")
    def _check(self) -> MockAction:
        if self.operation == "add" and not self.url_pattern:
            raise ValueError("mock add needs a url_pattern")
        if self.operation == "remove" and not self.id:
            raise ValueError("mock remove needs the rule id")
        return self


class PerformanceAction(BaseModel):
    action: Literal["performance"]
    tab_id: int | None = None


class DebugSummaryAction(BaseModel):
    action: Literal["debug_summary"]
    limit: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Most recent errors / failed requests listed.",
    )
    tab_id: int | None = None


class ScreenshotAction(BaseModel):
    action: Literal["screenshot"]
    format: Literal["png", "jpeg"] = Field(default="png")
    quality: int = Field(default=80, ge=10, le=100)
    full_page: bool = Field(
        default=False,
        description="Capture the whole scrollable page instead of just the viewport.",
    )
    tab_id: int | None = None


class ExtractAction(BaseModel):
    action: Literal["extract"]
    format: Literal["text", "markdown", "html"] = Field(
        default="text",
        description="Output form: plain text, structure-preserving markdown (best for LLM crawling), or raw HTML.",
    )
    ref: str | None = Field(
        default=None,
        description=(
            "Scope to this element handle from a snapshot — the only way to "
            "read content inside a shadow root, which no CSS selector reaches."
        ),
    )
    selector: str | None = Field(
        default=None,
        description="Scope to the first element matching this CSS selector (default: whole page).",
    )
    max_chars: int = Field(default=15000, ge=100, le=200000)
    tab_id: int | None = None


class ExtractElementsAction(BaseModel):
    action: Literal["extract_elements"]
    selector: str = Field(
        description="CSS selector for the records to extract (e.g. a product card, a table row)."
    )
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
    ref: str | None = Field(
        default=None,
        description="Search inside this element handle instead of the whole page.",
    )
    deep: bool = Field(
        default=True,
        description=(
            "Search through shadow roots and same-origin frames, where CSS "
            "selectors do not reach. On by default: a list rendered by web "
            "components returns nothing without it."
        ),
    )
    tab_id: int | None = None


class ScrollToBottomAction(BaseModel):
    action: Literal["scroll_to_bottom"]
    max_scrolls: int = Field(default=10, ge=1, le=100, description="Max scroll steps.")
    delay_ms: int = Field(
        default=600,
        ge=50,
        le=5000,
        description="Wait after each scroll for content to load.",
    )
    ref: str | None = Field(
        default=None,
        description=(
            "Scroll this element instead of the window — a chat log, a data "
            "grid, a drawer. Scrolling the window does nothing for a list "
            "that scrolls inside a pane of its own."
        ),
    )
    selector: str | None = Field(
        default=None, description="The scrolling element, if no ref."
    )
    tab_id: int | None = None


class CrawlAction(BaseModel):
    action: Literal["crawl"]
    urls: list[str] = Field(
        description="URLs to fetch and extract, crawled in parallel across background tabs."
    )
    wait: Literal["load", "networkidle", "none"] = Field(
        default="load",
        description="Per page: wait for full load, for network idle (SPAs), or don't wait.",
    )
    wait_selector: str | None = Field(
        default=None,
        description="Also wait for this selector before extracting (optional).",
    )
    scroll: bool = Field(
        default=False,
        description="Auto-scroll to bottom before extracting (lazy/infinite content).",
    )
    # Extraction mode: set elements_selector for structured records, else page content.
    elements_selector: str | None = Field(
        default=None,
        description="If set, scrape records matching this selector (like extract_elements); otherwise extract page content.",
    )
    fields: dict[str, str] | None = Field(
        default=None,
        description="Field map for elements_selector mode (name → sub-selector, 'sel@attr' for attributes).",
    )
    format: Literal["text", "markdown", "html"] = Field(
        default="markdown",
        description="Content format when not using elements_selector.",
    )
    selector: str | None = Field(
        default=None, description="Scope content extraction to this selector."
    )
    concurrency: int = Field(
        default=3, ge=1, le=8, description="Max pages fetched at once."
    )
    max_chars: int = Field(default=15000, ge=100, le=200000)
    limit: int = Field(
        default=100, ge=1, le=1000, description="Max records per page in elements mode."
    )
    timeout_ms: int = Field(default=30000, ge=1000, le=60000)
    close_tabs: bool = Field(
        default=True, description="Close the tabs opened for the crawl when done."
    )


class GetTabsAction(BaseModel):
    action: Literal["get_tabs"]


class SwitchTabAction(BaseModel):
    action: Literal["switch_tab"]
    index: int = Field(default=0, ge=0, description="Zero-based tab index.")
    id: int | None = Field(default=None, description="Tab ID (overrides index).")


class WaitAction(BaseModel):
    action: Literal["wait"]
    ms: int = Field(default=1000, ge=0, le=60000, description="Milliseconds to pause.")


class WaitForSelectorAction(BaseModel):
    action: Literal["wait_for_selector"]
    selector: str = Field(description="CSS selector to wait for.")
    state: Literal["visible", "attached", "hidden"] = Field(default="visible")
    timeout_ms: int = Field(default=10000, ge=100, le=60000)
    tab_id: int | None = None


class WaitForTextAction(BaseModel):
    action: Literal["wait_for_text"]
    text: str = Field(description="Text to wait for.")
    selector: str | None = Field(
        default=None,
        description="Optional CSS selector that scopes the text lookup.",
    )
    state: Literal["visible", "hidden"] = Field(default="visible")
    exact: bool = Field(default=False, description="Match the normalized text exactly.")
    timeout_ms: int = Field(default=10000, ge=100, le=60000)
    tab_id: int | None = None


class WaitForLoadAction(BaseModel):
    action: Literal["wait_for_load"]
    state: Literal["load", "domcontentloaded"] = Field(default="load")
    timeout_ms: int = Field(default=30000, ge=100, le=60000)
    tab_id: int | None = None


class WaitForNetworkIdleAction(BaseModel):
    action: Literal["wait_for_network_idle"]
    idle_ms: int = Field(
        default=500,
        ge=100,
        le=10000,
        description="Consider the network idle after this many ms with no in-flight requests.",
    )
    timeout_ms: int = Field(default=20000, ge=500, le=60000)
    tab_id: int | None = None


class WaitForUrlAction(BaseModel):
    """Wait for the address to become *url*.

    The one wait that works for a single-page app that changes route without
    loading anything: no document load fires, no selector is reliably new,
    but the address does change.
    """

    action: Literal["wait_for_url"]
    url: str = Field(
        description="URL to wait for. '*' matches any run of characters, "
        "e.g. 'https://app.example.com/orders/*'.",
    )
    timeout_ms: int = Field(default=15000, ge=100, le=60000)
    tab_id: int | None = None


class TargetMixin(BaseModel):
    """One element, named either by handle or by CSS.

    Both are accepted because they fail in different ways: a handle is exact
    but belongs to a snapshot of a page that may since have navigated, while
    a selector survives that but may match something else — or, inside a
    shadow root, nothing at all.
    """

    ref: str | None = Field(default=None, description=_REF_DESC)
    selector: str | None = Field(
        default=None, description="CSS selector of the element, if no ref."
    )
    index: int = Field(
        default=0,
        ge=0,
        description="Which match to use when a selector matches several.",
    )
    tab_id: int | None = None

    @model_validator(mode="after")
    def _one_target(self) -> "TargetMixin":
        if not self.ref and not self.selector:
            raise ValueError("needs a ref (from a snapshot) or a selector")
        return self


class ClickSelectorAction(TargetMixin):
    action: Literal["click_selector"]


class ClickTextAction(BaseModel):
    action: Literal["click_text"]
    text: str = Field(description="Visible text of the element to click.")
    tag: str | None = Field(
        default=None, description="Restrict to this tag (e.g. 'button', 'a')."
    )
    exact: bool = Field(
        default=False, description="Require an exact (not substring) text match."
    )
    tab_id: int | None = None


class HoverAction(TargetMixin):
    action: Literal["hover"]


class FocusAction(TargetMixin):
    action: Literal["focus"]


class SelectOptionAction(TargetMixin):
    action: Literal["select_option"]
    values: list[str] = Field(
        min_length=1,
        max_length=100,
        description="Option values or visible labels to select.",
    )
    match: Literal["value", "label"] = Field(
        default="value",
        description="Whether entries in values match option values or visible labels.",
    )


class SetCheckedAction(TargetMixin):
    action: Literal["set_checked"]
    checked: bool = Field(description="Desired checked state.")


class DragAction(BaseModel):
    action: Literal["drag"]
    source_ref: str | None = Field(default=None, description=_REF_DESC)
    target_ref: str | None = Field(default=None, description=_REF_DESC)
    source_selector: str | None = Field(
        default=None, description="CSS selector of the element to drag, if no ref."
    )
    target_selector: str | None = Field(
        default=None, description="CSS selector of the drop target, if no ref."
    )
    source_index: int = Field(default=0, ge=0)
    target_index: int = Field(default=0, ge=0)
    steps: int = Field(
        default=10,
        ge=2,
        le=50,
        description="Number of pointer-move steps between source and target.",
    )
    tab_id: int | None = None

    @model_validator(mode="after")
    def _both_ends(self) -> "DragAction":
        if not (self.source_ref or self.source_selector):
            raise ValueError("drag needs source_ref or source_selector")
        if not (self.target_ref or self.target_selector):
            raise ValueError("drag needs target_ref or target_selector")
        return self


class DragToPointAction(BaseModel):
    """Drag an element to a coordinate rather than onto another element.

    What a slider, a canvas, a map or a resize handle needs: there is no
    element under the drop point to name.
    """

    action: Literal["drag_to_point"]
    ref: str | None = Field(default=None, description=_REF_DESC)
    source_selector: str | None = Field(
        default=None, description="CSS selector of the element to drag, if no ref."
    )
    source_index: int = Field(default=0, ge=0)
    target_x: float = Field(description="X coordinate to drop at, in CSS pixels.")
    target_y: float = Field(description="Y coordinate to drop at, in CSS pixels.")
    steps: int = Field(
        default=30,
        ge=2,
        le=60,
        description="Number of pointer-move steps along the way.",
    )
    tab_id: int | None = None

    @model_validator(mode="after")
    def _needs_source(self) -> "DragToPointAction":
        if not (self.ref or self.source_selector):
            raise ValueError("drag_to_point needs a ref or source_selector")
        return self


class FillAction(TargetMixin):
    action: Literal["fill"]
    value: str = Field(description="Value to set.")
    clear: bool = Field(default=True, description="Clear existing content first.")
    submit: bool = Field(default=False, description="Press Enter after filling.")


class OpenTabAction(BaseModel):
    action: Literal["open_tab"]
    url: str = Field(description="URL to open in a new tab.")
    active: bool = Field(default=True, description="Focus the new tab.")


class CloseTabAction(BaseModel):
    action: Literal["close_tab"]
    id: int | None = Field(default=None, description="Tab ID to close.")
    index: int | None = Field(
        default=None, description="Zero-based tab index to close."
    )


class SnapshotAction(BaseModel):
    action: Literal["snapshot"]
    max_elements: int = Field(default=80, ge=1, le=300)
    diff: bool = Field(
        default=False,
        description=(
            "Return only what changed since the last snapshot of this tab — "
            "new, changed and gone elements. After an action that changes one "
            "part of a page this is a few lines instead of the whole listing. "
            "Falls back to a full snapshot when there is nothing to compare to."
        ),
    )
    tab_id: int | None = None


class SemanticRefTarget(BaseModel):
    kind: Literal["ref"]
    snapshot_id: str = Field(min_length=1, max_length=128)
    target_id: str = Field(min_length=1, max_length=128)


class SemanticActiveTextTarget(BaseModel):
    kind: Literal["active_text"]
    scope: Literal["caret", "selection"] = "selection"


class SemanticDocumentTarget(BaseModel):
    kind: Literal["document"]
    scope: Literal["visible", "all"] = "visible"


class SemanticRangeTarget(BaseModel):
    kind: Literal["range"]
    address: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z]{1,3}[1-9][0-9]{0,6}(?::[A-Za-z]{1,3}[1-9][0-9]{0,6})?$",
    )
    sheet: str | None = Field(default=None, max_length=200)


class SemanticSlideTarget(BaseModel):
    kind: Literal["slide"]
    index: int = Field(ge=1, le=10_000)


class SemanticSlideObjectTarget(BaseModel):
    kind: Literal["slide_object"]
    slide_index: int = Field(ge=1, le=10_000)
    role: Literal["title", "body", "notes", "text"] = "text"
    ordinal: int = Field(default=0, ge=0, le=1_000)


SemanticTarget = Annotated[
    SemanticRefTarget
    | SemanticActiveTextTarget
    | SemanticDocumentTarget
    | SemanticRangeTarget
    | SemanticSlideTarget
    | SemanticSlideObjectTarget,
    Field(discriminator="kind"),
]


class SemanticTextChange(BaseModel):
    kind: Literal["text"]
    mode: Literal["insert", "replace"] = "replace"
    at: Literal["caret", "start", "end"] = "caret"
    text: str = Field(max_length=50_000)


class SemanticMatrixCell(BaseModel):
    kind: Literal["value", "formula", "blank", "skip"]
    value: str | float | int | bool | None = None
    formula: str | None = Field(default=None, max_length=4_000)

    @model_validator(mode="after")
    def _validate_payload(self) -> "SemanticMatrixCell":
        if self.kind == "formula" and not self.formula:
            raise ValueError("formula cells require formula")
        if self.kind == "value" and self.value is None:
            raise ValueError("value cells require value")
        if self.kind in {"blank", "skip"} and (
            self.value is not None or self.formula is not None
        ):
            raise ValueError(f"{self.kind} cells cannot carry value/formula")
        return self


class SemanticMatrixChange(BaseModel):
    kind: Literal["matrix"]
    rows: list[list[SemanticMatrixCell]] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def _validate_rectangle(self) -> "SemanticMatrixChange":
        widths = {len(row) for row in self.rows}
        if not widths or 0 in widths or len(widths) != 1:
            raise ValueError("matrix rows must form a non-empty rectangle")
        if sum(len(row) for row in self.rows) > 100:
            raise ValueError("matrix writes support at most 100 cells")
        if any(cell.kind == "skip" for row in self.rows for cell in row):
            raise ValueError(
                "skip cells are unsafe in matrix paste; read/merge existing values first"
            )
        return self


class SemanticClearChange(BaseModel):
    kind: Literal["clear"]


SemanticChange = Annotated[
    SemanticTextChange | SemanticMatrixChange | SemanticClearChange,
    Field(discriminator="kind"),
]


class SemanticSnapshotAction(BaseModel):
    action: Literal["semantic_snapshot"]
    kinds: list[Literal["text", "grid", "slide", "control"]] = Field(
        default_factory=lambda: cast(
            list[Literal["text", "grid", "slide", "control"]],
            ["text", "grid", "slide", "control"],
        ),
        min_length=1,
        max_length=4,
    )
    include_values: bool = False
    max_items: int = Field(default=80, ge=1, le=200)
    max_chars: int = Field(default=20_000, ge=100, le=50_000)
    tab_id: int | None = None


class SemanticReadAction(BaseModel):
    action: Literal["semantic_read"]
    target: SemanticTarget
    value_mode: Literal["display", "formula", "both"] = "both"
    max_chars: int = Field(default=20_000, ge=100, le=50_000)
    max_cells: int = Field(default=500, ge=1, le=500)
    tab_id: int | None = None


class SemanticSelectAction(BaseModel):
    action: Literal["semantic_select"]
    target: SemanticTarget
    tab_id: int | None = None


class SemanticWriteAction(BaseModel):
    action: Literal["semantic_write"]
    target: SemanticTarget
    change: SemanticChange
    verify: Literal["none", "normalized"] = "normalized"
    timeout_ms: int = Field(default=15_000, ge=1_000, le=60_000)
    tab_id: int | None = None


class EvaluateAction(BaseModel):
    action: Literal["evaluate"]
    script: str = Field(description="JavaScript to evaluate.")
    tab_id: int | None = None


class BackAction(BaseModel):
    action: Literal["back"]
    tab_id: int | None = None


class ForwardAction(BaseModel):
    action: Literal["forward"]
    tab_id: int | None = None


class ReloadAction(BaseModel):
    action: Literal["reload"]
    tab_id: int | None = None


AnyAction = Annotated[
    StatusAction
    | NavigateAction
    | ClickAction
    | DblClickAction
    | TypeAction
    | KeyAction
    | ScrollAction
    | ResizeAction
    | ResetViewportAction
    | DialogsAction
    | HandleDialogAction
    | ConsoleAction
    | NetworkAction
    | NetworkBodyAction
    | DebugSummaryAction
    | StorageAction
    | CookiesAction
    | InspectAction
    | UploadFileAction
    | EmulateAction
    | MockAction
    | PerformanceAction
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
    | WaitForTextAction
    | WaitForLoadAction
    | ClickSelectorAction
    | ClickTextAction
    | HoverAction
    | FocusAction
    | SelectOptionAction
    | SetCheckedAction
    | DragAction
    | FillAction
    | OpenTabAction
    | CloseTabAction
    | SnapshotAction
    | SemanticSnapshotAction
    | SemanticReadAction
    | SemanticSelectAction
    | SemanticWriteAction
    | ExtractElementsAction
    | ScrollToBottomAction
    | WaitForNetworkIdleAction
    | WaitForUrlAction
    | DragToPointAction
    | CrawlAction,
    Field(discriminator="action"),
]

_DESCRIPTION = """\
Control the user's real Chrome/Edge browser — their logins, cookies and tabs —
through the WebBridge extension, which must be installed and connected.
(browser_use drives EvoFlux's in-app browser instead.)

How to work
- Snapshot, then act by ref. snapshot lists interactive elements, inside
  shadow roots and same-origin frames too, each with a ref like `e12`; pass
  `ref` to click_selector, fill, hover, focus, set_checked, select_option,
  drag, drag_to_point, inspect or upload_file. Refs are exact and survive
  re-renders; they end when the page navigates. A good CSS selector works too.
- Targeted actions scroll to the element, name what covers it ("covered by
  div.cookie-banner") and report whether the page changed.
  `snapshot {diff: true}` returns only what changed since the last one.
- navigate, back, forward and reload wait for the page and report the URL it
  landed on (redirects included) and its title; ending a call with one also
  returns a compact snapshot of the new page.
- Put a whole sequence in one call: actions run in order and stop at the
  first failure (`continue_on_error: true` only for independent actions).
  Consecutive clicks, fills, keys and scrolls travel as one message.
- Screenshots are for canvas/WebGL, cross-origin frames the snapshot cannot
  read, or questions about appearance. Their pixels are CSS pixels, so x,y
  read off one can be clicked directly.
- tab_id (from get_tabs) on any action drives that tab in the background
  without switching focus; open_tab {active: false} opens one there. A hidden
  tab may screenshot blank — use the DOM actions on it.
- A snapshot shows a link's address only when it has no label; collect URLs
  with extract_elements and a field such as {'url': 'a@href'}.

Debugging a web app
debug_summary is the check after each change: the current page's console
errors and warnings with source location and stack (source-mapped in Coding
sessions), and its failed and pending requests. console and network list
everything with filters; network_body reads a recorded response by its id.
Coding sessions record from their first command; elsewhere the first read
starts recording and says so — reload to capture the page load. inspect shows
an element's box, computed styles and, in development builds, the component
chain and source files that rendered it. mock fakes or fails matching
requests; emulate throttles network or CPU, goes offline, or fakes location,
time zone and locale; performance reports load timing and Web Vitals.
storage and cookies list keys and names — values, writes and mock add need
webbridge.allow_evaluate. Loop: preview start → open_tab the dev URL →
debug_summary → fix → reload → debug_summary.

Actions
- Pages and tabs: status, navigate, back, forward, reload, get_tabs,
  open_tab, switch_tab (the only one that changes focus), close_tab.
- Reading: snapshot, extract (text/markdown/html, optionally one selector),
  extract_elements (records by selector with per-field sub-selectors and
  attributes), screenshot (viewport or full_page), dialogs, evaluate (page
  JavaScript; may be disabled by policy).
- Acting: click_selector, click_text, fill (optionally submit),
  select_option, set_checked, hover, focus, drag, drag_to_point (sliders,
  canvases, maps), type (into the focused element), key (with modifiers),
  scroll, click/dblclick (x,y fallback), handle_dialog, upload_file.
- Waiting: wait, wait_for_load, wait_for_selector, wait_for_text,
  wait_for_url (`*` wildcard — an SPA route change), wait_for_network_idle
  (an SPA's data loads).
- Viewport and environment: resize (device, DPR, touch, color scheme),
  reset_viewport, emulate.
- Debugging: debug_summary, console, network, network_body, inspect,
  performance, mock, storage, cookies.
- Rich editors (Google Docs/Sheets, Excel/PowerPoint online):
  semantic_snapshot, semantic_read, semantic_select, semantic_write —
  accessibility-first targets; unsupported operations fail rather than fall
  back to coordinates.
- Collecting: scroll_to_bottom (lazy lists; ref/selector for a scrolling
  pane), crawl {urls, wait, elements_selector or format} — many URLs at once
  in background tabs (3 at a time by default; wait: "networkidle" for SPAs).\
"""

_UNTRUSTED_BROWSER_ACTIONS = frozenset(
    {
        # Page-loading actions report the page's own title.
        "navigate",
        "back",
        "forward",
        "reload",
        # Console text, URLs and response bodies are the page's words.
        "console",
        "network",
        "network_body",
        "debug_summary",
        "storage",
        "cookies",
        "inspect",
        "performance",
        "crawl",
        "evaluate",
        "extract",
        "extract_elements",
        "get_tabs",
        "dialogs",
        "screenshot",
        "snapshot",
        "semantic_snapshot",
        "semantic_read",
        "semantic_select",
        "semantic_write",
    }
)


@tool(
    name="webbridge",
    description=_DESCRIPTION,
    deferred=True,
    deferred_summary=(
        "Drive an external Chrome/Edge browser through the opt-in WebBridge extension."
    ),
)
async def webbridge(
    actions: Annotated[
        list[AnyAction],
        Field(description="Ordered list of browser actions to execute."),
    ],
    continue_on_error: Annotated[
        bool,
        Field(
            description=(
                "Keep going after a failed action. Default false: a sequence "
                "is normally a chain — clicking, filling and submitting a form "
                "the first step never opened does nothing but hide which step "
                "broke. Set true only for independent actions, such as "
                "extracting from several tabs."
            )
        ),
    ] = False,
    _state: Annotated[Any, InjectedArg()] = None,
) -> str | ToolResult:
    """Control the user's real browser via the WebBridge Chrome extension."""
    session_id = _get_sid(_state)
    metadata = _state.metadata if _state else {}
    target_token = _webbridge_target_id.set(
        metadata.get("webbridge_extension_id") if metadata else None
    )
    coding = bool(metadata) and metadata.get("team_mode") == "coding"
    motion: Literal["human", "instant"] | None = None
    if metadata:
        motion = "instant" if coding else "human"
    motion_token = _webbridge_pointer_motion.set(motion)
    devtools_token = _webbridge_devtools_capture.set(coding)
    results: list[str | ToolResult] = []
    try:
        index = 0
        while index < len(actions):
            act = actions[index]
            run = _batchable_run(actions, index) if _supports_batch(session_id) else 1
            failed_token = _webbridge_command_failed.set(False)
            try:
                if run > 1:
                    lines, failed = await _run_batch(
                        session_id, actions[index : index + run], continue_on_error
                    )
                    results.extend(lines)
                    index += run
                else:
                    result = await _dispatch_webbridge(act, session_id)
                    # A crawl is a batch of its own and reports each URL's
                    # outcome in its result; one unreachable page is not a
                    # broken chain.
                    failed = _webbridge_command_failed.get() and act.action != "crawl"
                    index += 1
                    if (
                        not failed
                        and index == len(actions)
                        and act.action in _PAGE_LOADING_ACTIONS
                        and isinstance(result, str)
                    ):
                        landed = await _landing_snapshot(session_id, act)
                        if landed:
                            result = f"{result}\n{landed}"
                    if act.action in _UNTRUSTED_BROWSER_ACTIONS:
                        result = mark_untrusted_browser_result(result)
                    results.append(result)
            except Exception as e:
                logger.debug("webbridge_error action={} error={}", act.action, e)
                results.append(f"Error ({act.action}): {e}")
                failed = True
                index += 1
            finally:
                _webbridge_command_failed.reset(failed_token)
            if failed and not continue_on_error:
                skipped = len(actions) - index
                if skipped:
                    results.append(
                        f"Stopped after {act.action} failed: {skipped} later "
                        "action(s) not run. Fix the step that failed, or pass "
                        "continue_on_error for actions that do not depend on it."
                    )
                break
        return combine_browser_results(results)
    finally:
        _webbridge_devtools_capture.reset(devtools_token)
        _webbridge_pointer_motion.reset(motion_token)
        _webbridge_target_id.reset(target_token)


#: Actions that leave the tab on a different document. The model's next move
#: after one is almost always "what is on this page now?".
_PAGE_LOADING_ACTIONS = frozenset({"navigate", "back", "forward", "reload"})

#: Enough of the new page to orient by without paying for the full listing.
_LANDING_SNAPSHOT_ELEMENTS = 40


async def _landing_snapshot(session_id: str, act: Any) -> str | None:
    """A compact snapshot of the page a call ended on.

    Returned only when the page-loading action was the last one: a chain that
    goes on to click something has already decided what it needs, and a
    snapshot in the middle of it would be read by nobody. Best-effort — the
    navigation itself succeeded, so a snapshot that cannot be taken is left
    out rather than reported as a failure.
    """
    failed_token = _webbridge_command_failed.set(False)
    try:
        resp = await _send_command(
            session_id,
            "snapshot",
            _tab_params(act, max_elements=_LANDING_SNAPSHOT_ELEMENTS),
        )
    except Exception as e:
        logger.debug("webbridge_landing_snapshot_error error={}", e)
        return None
    finally:
        _webbridge_command_failed.reset(failed_token)
    if not resp.get("success"):
        return None
    data = resp.get("data") or {}
    elements = data.get("elements") or []
    if not elements:
        return None
    url = data.get("url") or ""
    lines = [f"Interactive elements ({len(elements)}):"]
    lines.extend(_snapshot_line(el, url) for el in elements)
    if len(elements) >= _LANDING_SNAPSHOT_ELEMENTS:
        lines.append("(First elements only — take a snapshot for the full listing.)")
    return "\n".join(lines)


def _supports_batch(session_id: str) -> bool:
    ext = webbridge_manager.resolve_target(session_id, _webbridge_target_id.get())
    if ext is None:
        return False
    commands = ext.capabilities.get("commands")
    return not isinstance(commands, list) or "batch" in commands


def _batchable_run(actions: list[Any], start: int) -> int:
    """How many actions from *start* can travel together.

    Only a run of two or more is worth it: a batch of one is the same round
    trip with a wrapper around it.
    """
    count = 0
    for act in actions[start:]:
        if act.action not in _BATCHABLE:
            break
        count += 1
    return count if count > 1 else 1


async def _run_batch(
    session_id: str, actions: list[Any], continue_on_error: bool
) -> tuple[list[str], bool]:
    """Send a run of simple actions as one command and report each outcome."""
    commands = [
        {"action": act.action, "params": _BATCHABLE[act.action](act)} for act in actions
    ]
    resp = await _send_command(
        session_id,
        "batch",
        {"commands": commands, "stop_on_error": not continue_on_error},
    )
    if not resp.get("success"):
        return [f"batch failed: {resp.get('error', 'unknown')}"], True

    data = resp.get("data") or {}
    entries = data.get("results") or []
    lines: list[str] = []
    failed = False
    for act, entry in zip(actions, entries):
        if entry.get("success"):
            lines.append(f"{act.action}: ok.{_outcome(entry)}")
        else:
            lines.append(f"{act.action} failed: {entry.get('error', 'unknown')}")
            failed = True
    skipped = int(data.get("skipped") or 0)
    if skipped:
        lines.append(f"({skipped} later action(s) in the batch not run.)")
    return lines, failed


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
    if action == "resize":
        return await _handle_resize(session_id, act)
    if action == "reset_viewport":
        return await _handle_reset_viewport(session_id, act)
    if action == "dialogs":
        return await _handle_dialogs(session_id, act)
    if action == "console":
        return await _handle_console(session_id, act)
    if action == "network":
        return await _handle_network(session_id, act)
    if action == "network_body":
        return await _handle_network_body(session_id, act)
    if action == "debug_summary":
        return await _handle_debug_summary(session_id, act)
    if action == "storage":
        return await _handle_storage(session_id, act)
    if action == "cookies":
        return await _handle_cookies(session_id, act)
    if action == "inspect":
        return await _handle_inspect(session_id, act)
    if action == "upload_file":
        return await _handle_upload_file(session_id, act)
    if action == "emulate":
        return await _handle_emulate(session_id, act)
    if action == "mock":
        return await _handle_mock(session_id, act)
    if action == "performance":
        return await _handle_performance(session_id, act)
    if action == "handle_dialog":
        return await _handle_dialog(session_id, act)
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
    if action == "wait_for_text":
        return await _handle_wait_for_text(session_id, act)
    if action == "wait_for_load":
        return await _handle_wait_for_load(session_id, act)
    if action == "click_selector":
        return await _handle_click_selector(session_id, act)
    if action == "click_text":
        return await _handle_click_text(session_id, act)
    if action == "hover":
        return await _handle_hover(session_id, act)
    if action == "focus":
        return await _handle_focus(session_id, act)
    if action == "select_option":
        return await _handle_select_option(session_id, act)
    if action == "set_checked":
        return await _handle_set_checked(session_id, act)
    if action == "drag":
        return await _handle_drag(session_id, act)
    if action == "fill":
        return await _handle_fill(session_id, act)
    if action == "open_tab":
        return await _handle_open_tab(session_id, act)
    if action == "close_tab":
        return await _handle_close_tab(session_id, act)
    if action == "snapshot":
        return await _handle_snapshot(session_id, act)
    if action in {
        "semantic_snapshot",
        "semantic_read",
        "semantic_select",
        "semantic_write",
    }:
        return await _handle_semantic(session_id, act)
    if action == "extract_elements":
        return await _handle_extract_elements(session_id, act)
    if action == "scroll_to_bottom":
        return await _handle_scroll_to_bottom(session_id, act)
    if action == "wait_for_network_idle":
        return await _handle_wait_for_network_idle(session_id, act)
    if action == "wait_for_url":
        return await _handle_wait_for_url(session_id, act)
    if action == "drag_to_point":
        return await _handle_drag_to_point(session_id, act)
    if action == "crawl":
        return await _handle_crawl(session_id, act)

    return f"Unknown action: {action}"


def _tab_params(act: Any, **extra: Any) -> dict[str, Any]:
    """Command params, with anything unset left out.

    The extension reads every optional parameter as "absent or falsy", so a
    key carrying ``null`` says exactly what omitting it says — while making
    each command larger and each assertion about one harder to read.
    """
    params = {key: value for key, value in extra.items() if value is not None}
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


def _landed(verb: str, data: Any, requested: str | None = None) -> str:
    """Where a page-loading action actually ended up.

    The address asked for is not always the one reached — a login redirect
    is the ordinary case — and the model decides its next step from the page
    it is on, not the one it named.
    """
    data = data if isinstance(data, dict) else {}
    url = str(data.get("url") or requested or "")
    line = f"{verb} {url}" if url else verb
    if requested and data.get("redirected"):
        line += f" (redirected from {requested})"
    if data.get("title"):
        line += f"\nTitle: {data['title']}"
    if data.get("timed_out"):
        line += "\nThe page had not finished loading when the wait ran out."
    if data.get("devtools_started"):
        line += (
            "\nConsole/network recording started after this load (the previous "
            "page could not be recorded); reload to capture the load itself."
        )
    return line


async def _handle_navigate(session_id: str, act: NavigateAction) -> str:
    resp = await _send_command(session_id, "navigate", _tab_params(act, url=act.url))
    if resp.get("success"):
        return _landed("Navigated to", resp.get("data"), act.url)
    return f"Navigate failed: {resp.get('error', 'unknown')}"


async def _handle_click(session_id: str, act: ClickAction) -> str:
    resp = await _send_command(
        session_id,
        "click",
        _tab_params(
            act,
            x=act.x,
            y=act.y,
            button=act.button,
        ),
    )
    if resp.get("success"):
        return f"Clicked at ({act.x}, {act.y})"
    return f"Click failed: {resp.get('error', 'unknown')}"


async def _handle_dblclick(session_id: str, act: DblClickAction) -> str:
    resp = await _send_command(
        session_id, "dblclick", _tab_params(act, x=act.x, y=act.y)
    )
    if resp.get("success"):
        return f"Double-clicked at ({act.x}, {act.y})"
    return f"Double-click failed: {resp.get('error', 'unknown')}"


async def _handle_type(session_id: str, act: TypeAction) -> str:
    resp = await _send_command(session_id, "type", _params_type(act))
    if resp.get("success"):
        return f"Typed {len(act.text)} characters"
    return f"Type failed: {resp.get('error', 'unknown')}"


async def _handle_key(session_id: str, act: KeyAction) -> str:
    resp = await _send_command(
        session_id,
        "key",
        _params_key(act),
    )
    if resp.get("success"):
        chord = "+".join([*act.modifiers, act.key])
        return f"Pressed key: {chord}"
    return f"Key press failed: {resp.get('error', 'unknown')}"


async def _handle_scroll(session_id: str, act: ScrollAction) -> str:
    resp = await _send_command(session_id, "scroll", _params_scroll(act))
    if resp.get("success"):
        return f"Scrolled ({act.dx}, {act.dy})"
    return f"Scroll failed: {resp.get('error', 'unknown')}"


async def _handle_resize(session_id: str, act: ResizeAction) -> str:
    params = {
        "device_scale_factor": act.device_scale_factor,
        **{
            key: value
            for key, value in {
                "preset": act.preset,
                "width": act.width,
                "height": act.height,
                "mobile": act.mobile,
                "touch": act.touch,
                "color_scheme": act.color_scheme,
            }.items()
            if value is not None
        },
    }
    resp = await _send_command(
        session_id,
        "resize",
        _tab_params(act, **params),
    )
    if not resp.get("success"):
        return f"Resize failed: {resp.get('error', 'unknown')}"
    data = resp.get("data") or {}
    viewport = data.get("viewport") or data
    return (
        "Responsive viewport set to "
        f"{viewport.get('width', act.width)}x{viewport.get('height', act.height)} "
        f"css-px (DPR {viewport.get('dpr', act.device_scale_factor)})."
    )


async def _handle_reset_viewport(session_id: str, act: ResetViewportAction) -> str:
    resp = await _send_command(session_id, "reset_viewport", _tab_params(act))
    if not resp.get("success"):
        return f"Reset viewport failed: {resp.get('error', 'unknown')}"
    data = resp.get("data") or {}
    viewport = data.get("viewport") or data
    return (
        "Responsive viewport reset"
        f" ({viewport.get('width', '?')}x{viewport.get('height', '?')} css-px)."
    )


async def _handle_dialogs(session_id: str, act: DialogsAction) -> str:
    resp = await _send_command(
        session_id,
        "dialogs",
        _tab_params(act, clear=act.clear, limit=act.limit),
    )
    if not resp.get("success"):
        return f"Dialogs failed: {resp.get('error', 'unknown')}"
    data = resp.get("data") or {}
    if not data.get("active") and not data.get("history"):
        return "No JavaScript dialogs captured."
    return json.dumps(data, ensure_ascii=False, indent=2)


async def _handle_dialog(session_id: str, act: HandleDialogAction) -> str:
    params: dict[str, Any] = {"accept": act.accept}
    if act.prompt_text is not None:
        params["prompt_text"] = act.prompt_text
    resp = await _send_command(
        session_id,
        "handle_dialog",
        _tab_params(act, **params),
    )
    if not resp.get("success"):
        return f"Handle dialog failed: {resp.get('error', 'unknown')}"
    data = resp.get("data") or {}
    verb = "Accepted" if data.get("accepted", act.accept) else "Dismissed"
    return f"{verb} {data.get('type', 'JavaScript')} dialog."


# ── Devtools: console, network, debug summary ────────────────────────────────


def _clock(ms: Any) -> str:
    try:
        return datetime.fromtimestamp(float(ms) / 1000).strftime("%H:%M:%S.%f")[:-3]
    except (TypeError, ValueError, OverflowError, OSError):
        return "?"


def _devtools_notes(data: dict[str, Any], kind: str) -> list[str]:
    """What the listing does not contain, so an empty one is not misread."""
    notes: list[str] = []
    if data.get("started_now"):
        notes.append(
            f"Recording began after this page loaded, so {kind} from its load is "
            "not in the log. Reload the page to capture it."
        )
    earlier = int(data.get("earlier_pages") or 0)
    if earlier:
        notes.append(f"({earlier} more from earlier pages of this tab — scope: 'all'.)")
    dropped = int(data.get("dropped") or 0)
    if dropped:
        notes.append(
            f"({dropped} oldest entries were dropped to stay within the buffer.)"
        )
    return notes


def _console_line(entry: dict[str, Any]) -> list[str]:
    level = entry.get("level", "log")
    source = entry.get("source") or "console"
    tag = {"exception": " uncaught", "console": ""}.get(source, f" {source}")
    text = str(entry.get("text") or "").rstrip()
    first, *rest = text.split("\n") or [""]
    location = ""
    if entry.get("library") and entry.get("url"):
        # Every frame is library code; its path would only point away from
        # the app, and the message itself names the component.
        name = str(entry["url"]).rsplit("/", 1)[-1].split("?", 1)[0]
        location = f" — raised inside library code ({name})"
    elif entry.get("url") and entry.get("line"):
        location = f" — {entry['url']}:{entry['line']}"
        if entry.get("column"):
            location += f":{entry['column']}"
        if entry.get("source_mapped"):
            # Positions were moved from the bundle to the original source.
            location += " (source-mapped)"
    lines = [f"  [{level}{tag}] {_clock(entry.get('ts'))} {first}{location}"]
    lines.extend(f"      {line.strip()}" for line in rest[:12] if line.strip())
    # An Error's description already carries its stack; don't print it twice.
    if not any(line.strip().startswith("at ") for line in rest):
        lines.extend(
            # "… 5 library frames" is a fold, not a frame.
            f"      {frame}" if frame.startswith("…") else f"      at {frame}"
            for frame in entry.get("stack") or []
        )
    return lines


def _network_line(entry: dict[str, Any]) -> str:
    if entry.get("failed"):
        outcome = "failed"
        if entry.get("canceled"):
            outcome = "canceled"
    elif entry.get("status"):
        outcome = str(entry["status"])
        if entry.get("status_text"):
            outcome += f" {entry['status_text']}"
    else:
        outcome = "pending"
    parts = [
        f"  [{entry.get('request_id', '?')}]",
        str(entry.get("method") or "GET"),
        outcome,
        str(entry.get("type") or "Other").lower(),
        str(entry.get("url") or ""),
    ]
    if entry.get("redirected_to"):
        parts.append(f"→ {entry['redirected_to']}")
    if entry.get("error"):
        parts.append(f"({entry['error']})")
    if entry.get("duration_ms") is not None:
        parts.append(f"{entry['duration_ms']} ms")
    if entry.get("from_cache"):
        parts.append("(cache)")
    return " ".join(parts)


async def _handle_console(session_id: str, act: ConsoleAction) -> str:
    resp = await _send_command(
        session_id,
        "console",
        _tab_params(
            act,
            level=None if act.level == "all" else act.level,
            contains=act.contains,
            limit=act.limit,
            scope=act.scope,
            clear=act.clear or None,
        ),
    )
    if not resp.get("success"):
        return f"console failed: {resp.get('error', 'unknown')}"
    data = resp.get("data") or {}
    entries = data.get("entries") or []
    total = int(data.get("total") or len(entries))
    header = f"Console for {data.get('page_url') or 'this tab'}"
    if not entries:
        lines = [f"{header}: no messages match."]
    else:
        shown = f"{len(entries)} of {total}" if total > len(entries) else str(total)
        lines = [f"{header} ({shown}, oldest first):"]
        for entry in entries:
            lines.extend(_console_line(entry))
    lines.extend(_devtools_notes(data, "console output"))
    if act.clear:
        lines.append("(Console cleared.)")
    return "\n".join(lines)


async def _handle_network(session_id: str, act: NetworkAction) -> str:
    resp = await _send_command(
        session_id,
        "network",
        _tab_params(
            act,
            filter=None if act.filter == "all" else act.filter,
            resource=None if act.resource == "all" else act.resource,
            url_contains=act.url_contains,
            method=act.method,
            limit=act.limit,
            scope=act.scope,
            clear=act.clear or None,
        ),
    )
    if not resp.get("success"):
        return f"network failed: {resp.get('error', 'unknown')}"
    data = resp.get("data") or {}
    entries = data.get("entries") or []
    total = int(data.get("total") or len(entries))
    header = f"Network for {data.get('page_url') or 'this tab'}"
    if not entries:
        lines = [f"{header}: no requests match."]
    else:
        shown = f"{len(entries)} of {total}" if total > len(entries) else str(total)
        lines = [f"{header} ({shown}, oldest first; [id] feeds network_body):"]
        lines.extend(_network_line(entry) for entry in entries)
    pending = int(data.get("pending") or 0)
    if pending:
        lines.append(f"({pending} still in flight.)")
    lines.extend(_devtools_notes(data, "network traffic"))
    if act.clear:
        lines.append("(Network log cleared.)")
    return "\n".join(lines)


async def _handle_network_body(session_id: str, act: NetworkBodyAction) -> str:
    resp = await _send_command(
        session_id,
        "network_body",
        _tab_params(act, request_id=act.request_id, max_chars=act.max_chars),
    )
    if not resp.get("success"):
        return f"network_body failed: {resp.get('error', 'unknown')}"
    data = resp.get("data") or {}
    request = data.get("request") or {}
    lines = [_network_line(request).strip()]
    if request.get("mime_type"):
        lines.append(f"Content-Type: {request['mime_type']}")
    if data.get("base64_encoded"):
        lines.append(f"Binary body ({data.get('size', 0)} bytes) — not shown.")
        return "\n".join(lines)
    body = str(data.get("body") or "")
    size = int(data.get("size") or len(body))
    lines.append(
        f"Body ({size} chars{', truncated' if data.get('truncated') else ''}):"
    )
    lines.append(body if body else "(empty)")
    return "\n".join(lines)


async def _handle_debug_summary(session_id: str, act: DebugSummaryAction) -> str:
    resp = await _send_command(
        session_id, "debug_summary", _tab_params(act, limit=act.limit)
    )
    if not resp.get("success"):
        return f"debug_summary failed: {resp.get('error', 'unknown')}"
    data = resp.get("data") or {}
    counts = data.get("console_counts") or {}
    net = data.get("network_counts") or {}
    lines = [f"Debug summary for {data.get('page_url') or 'this tab'}"]
    if data.get("title"):
        lines.append(f"Title: {data['title']}")
    lines.append(
        f"Console: {counts.get('error', 0)} error(s), {counts.get('warning', 0)} "
        f"warning(s), {counts.get('total', 0)} message(s) on this page."
    )
    lines.append(
        f"Network: {net.get('total', 0)} request(s), {net.get('failed', 0)} failed, "
        f"{net.get('pending', 0)} pending."
    )
    errors = data.get("errors") or []
    if errors:
        lines.append("Errors (newest last):")
        for entry in errors:
            lines.extend(_console_line(entry))
    warnings = data.get("warnings") or []
    if warnings:
        lines.append("Warnings (newest last):")
        for entry in warnings:
            lines.extend(_console_line(entry))
    failed = data.get("failed_requests") or []
    if failed:
        lines.append("Failed requests:")
        lines.extend(_network_line(entry) for entry in failed)
    if not errors and not failed:
        lines.append("No console errors or failed requests on this page.")
    lines.extend(_devtools_notes(data, "console and network activity"))
    return "\n".join(lines)


# ── Page state, inspection, upload, emulation, mocks, performance ────────────


async def _handle_storage(session_id: str, act: StorageAction) -> str:
    resp = await _send_command(
        session_id,
        "storage",
        _tab_params(
            act,
            area=act.area,
            operation=act.operation,
            key=act.key,
            value=act.value,
            include_values=act.include_values or None,
        ),
    )
    if not resp.get("success"):
        return f"storage failed: {resp.get('error', 'unknown')}"
    data = resp.get("data") or {}
    area = f"{data.get('area', act.area)}Storage"
    if act.operation != "get":
        return f"{area} {act.operation}: {data.get('changed', 0)} key(s) changed."
    entries = data.get("entries") or []
    if not entries:
        return f"{area}: no keys{' named ' + repr(act.key) if act.key else ''}."
    lines = [f"{area} ({data.get('total', len(entries))} keys):"]
    for entry in entries:
        line = f"  {entry.get('key')!r} ({entry.get('size', 0)} chars)"
        if "value" in entry:
            line += f" = {entry['value']!r}"
        lines.append(line)
    return "\n".join(lines)


async def _handle_cookies(session_id: str, act: CookiesAction) -> str:
    resp = await _send_command(
        session_id,
        "cookies",
        _tab_params(
            act,
            operation=act.operation,
            include_values=act.include_values or None,
            name=act.name,
            value=act.value,
            path=act.path,
            domain=act.domain,
            max_age=act.max_age,
            same_site=act.same_site,
            secure=act.secure or None,
            http_only=act.http_only or None,
        ),
    )
    if not resp.get("success"):
        return f"cookies failed: {resp.get('error', 'unknown')}"
    data = resp.get("data") or {}
    if act.operation != "get":
        return f"Cookie {act.name!r} {'set' if act.operation == 'set' else 'deleted'}."
    entries = data.get("entries") or []
    if not entries:
        return "No cookies for this page."
    lines = [f"Cookies for this page ({len(entries)}):"]
    for entry in entries:
        flags = [
            flag
            for flag, on in (
                ("HttpOnly", entry.get("http_only")),
                ("Secure", entry.get("secure")),
            )
            if on
        ]
        if entry.get("same_site"):
            flags.append(f"SameSite={entry['same_site']}")
        expires = entry.get("expires")
        if isinstance(expires, (int, float)):
            flags.append(f"expires {datetime.fromtimestamp(expires):%Y-%m-%d %H:%M}")
        elif expires:
            flags.append(str(expires))
        line = (
            f"  {entry.get('name')} — {entry.get('domain')}{entry.get('path')} "
            f"({entry.get('size', 0)} B; {', '.join(flags)})"
        )
        if "value" in entry:
            line += f" = {entry['value']!r}"
        lines.append(line)
    return "\n".join(lines)


#: Computed values that say "nothing special here" for the default property
#: set — listing them on every inspect buries the few that matter.
_UNREMARKABLE_STYLES = frozenset(
    {"", "none", "normal", "auto", "0px", "visible", "static", "rgba(0, 0, 0, 0)"}
)


def _source_location(item: dict[str, Any]) -> str:
    file = str(item.get("file") or "")
    if not file:
        return ""
    parts = urlsplit(file)
    if parts.scheme in {"http", "https"}:
        # A dev server serves the module at its project path (Vite: /src/…).
        file = parts.path
    location = file
    if item.get("line"):
        location += f":{item['line']}"
        if item.get("column"):
            location += f":{item['column']}"
    return location


async def _handle_inspect(session_id: str, act: InspectAction) -> str:
    resp = await _send_command(
        session_id,
        "inspect",
        _tab_params(
            act,
            ref=act.ref,
            selector=None if act.ref else act.selector,
            index=act.index if act.selector and not act.ref else None,
            properties=act.properties,
        ),
    )
    if not resp.get("success"):
        return f"inspect failed: {resp.get('error', 'unknown')}"
    data = resp.get("data") or {}
    box = data.get("box") or {}
    head = f"<{data.get('tag', '?')}>"
    if data.get("ref"):
        head = f"{data['ref']} {head}"
    if data.get("text"):
        head += f" {str(data['text'])[:80]!r}"
    lines = [
        f"{head} at ({box.get('x')}, {box.get('y')}) {box.get('width')}x{box.get('height')}"
    ]
    components = data.get("components") or []
    if components:
        framework = data.get("framework") or "framework"
        lines.append(f"Rendered by ({framework}, innermost first):")
        for item in components:
            where = _source_location(item)
            if where and item.get("site") == "jsx":
                # React's location is the JSX that created the element — in
                # the parent — not the file defining the component.
                where = f"rendered at {where}"
            lines.append(f"  {item.get('name', '?')}{' — ' + where if where else ''}")
        if not any(item.get("file") for item in components):
            lines.append(
                "  (No source locations: the build does not expose them — "
                "production bundle, or React 19 without a locator plugin.)"
            )
    hints = data.get("source_hints") or {}
    if hints:
        lines.append(
            "Source hints: " + ", ".join(f"{k}={v!r}" for k, v in hints.items())
        )
    styles = data.get("styles") or {}
    shown = {
        key: value
        for key, value in styles.items()
        if act.properties or str(value) not in _UNREMARKABLE_STYLES
    }
    if shown:
        lines.append(
            "Computed: " + "; ".join(f"{key}: {value}" for key, value in shown.items())
        )
    attributes = data.get("attributes") or {}
    if attributes:
        lines.append(
            "Attributes: "
            + " ".join(
                f"{key}={str(value)[:80]!r}" for key, value in attributes.items()
            )
        )
    return "\n".join(lines)


def _upload_paths(paths: list[str]) -> list[str]:
    """Resolve upload paths to files the session may hand to a web page.

    A file input is an exit: whatever it is given leaves the machine with the
    form. So only files inside the session's workspace roots (or its own
    uploads) qualify — not merely any path the sandbox would let ``read`` open.
    """
    from app.agent.sandbox import get_sandbox

    sandbox = get_sandbox()
    roots = [*sandbox.allowed_workspace_roots, *sandbox.read_only_paths]
    resolved_paths: list[str] = []
    for raw in paths:
        resolved = sandbox.validate_path(raw)
        if not any(resolved == root or resolved.is_relative_to(root) for root in roots):
            raise PermissionError(
                f"{raw} is outside the workspace; only workspace files can be uploaded."
            )
        if not resolved.is_file():
            raise FileNotFoundError(f"{raw} is not a file.")
        resolved_paths.append(str(resolved))
    return resolved_paths


async def _handle_upload_file(session_id: str, act: UploadFileAction) -> str:
    try:
        files = _upload_paths(act.paths)
    except (PermissionError, FileNotFoundError) as e:
        _webbridge_command_failed.set(True)
        return f"upload_file refused: {e}"
    resp = await _send_command(
        session_id,
        "upload_file",
        _tab_params(
            act,
            ref=act.ref,
            selector=None if act.ref else act.selector,
            index=act.index if act.selector and not act.ref else None,
            files=files,
        ),
    )
    if not resp.get("success"):
        return f"upload_file failed: {resp.get('error', 'unknown')}"
    names = ", ".join(Path(path).name for path in files)
    return f"Set {len(files)} file(s) on the input: {names}.{_outcome(resp)}"


async def _handle_emulate(session_id: str, act: EmulateAction) -> str:
    resp = await _send_command(
        session_id,
        "emulate",
        _tab_params(
            act,
            network=act.network,
            cpu_throttling=act.cpu_throttling,
            geolocation=act.geolocation.model_dump() if act.geolocation else None,
            timezone=act.timezone,
            locale=act.locale,
            clear=act.clear or None,
        ),
    )
    if not resp.get("success"):
        return f"emulate failed: {resp.get('error', 'unknown')}"
    state = (resp.get("data") or {}).get("emulation") or {}
    if not state:
        return "No emulation overrides are active on this tab."
    parts = []
    if state.get("network"):
        parts.append(f"network={state['network']}")
    if state.get("cpu_throttling"):
        parts.append(f"cpu={state['cpu_throttling']}x slower")
    if state.get("geolocation"):
        geo = state["geolocation"]
        parts.append(f"geolocation={geo.get('latitude')},{geo.get('longitude')}")
    if state.get("timezone"):
        parts.append(f"timezone={state['timezone']}")
    if state.get("locale"):
        parts.append(f"locale={state['locale']}")
    return (
        "Active emulation: "
        + ", ".join(parts)
        + ". Overrides last until cleared or the tab is released; reload to "
        "see them applied to the page load."
    )


def _mock_line(rule: dict[str, Any]) -> str:
    target = f"{rule.get('method') or 'ANY'} {rule.get('url_pattern')}"
    if rule.get("fail"):
        answer = f"fail ({rule['fail']})"
    else:
        answer = f"{rule.get('status')} {rule.get('content_type')} ({rule.get('body_chars', 0)} chars)"
    extra = []
    if rule.get("delay_ms"):
        extra.append(f"after {rule['delay_ms']} ms")
    if rule.get("times"):
        extra.append(f"{rule.get('hits', 0)}/{rule['times']} uses")
    else:
        extra.append(f"{rule.get('hits', 0)} hit(s)")
    return f"  [{rule.get('id')}] {target} → {answer}; {', '.join(extra)}"


async def _handle_mock(session_id: str, act: MockAction) -> str:
    params: dict[str, Any] = {"operation": act.operation}
    if act.operation == "add":
        params.update(
            url_pattern=act.url_pattern,
            method=act.method,
            status=act.status,
            body=act.body,
            content_type=act.content_type,
            headers=act.headers or None,
            fail=act.fail,
            delay_ms=act.delay_ms or None,
            times=act.times or None,
        )
    elif act.operation == "remove":
        params["id"] = act.id
    resp = await _send_command(session_id, "mock", _tab_params(act, **params))
    if not resp.get("success"):
        return f"mock failed: {resp.get('error', 'unknown')}"
    data = resp.get("data") or {}
    rules = data.get("rules") or []
    head = {
        "add": f"Added mock {(data.get('rule') or {}).get('id', '')}.",
        "remove": f"Removed mock {act.id}.",
        "clear": "Cleared all mocks on this tab.",
        "list": "",
    }[act.operation]
    lines = [head] if head else []
    if rules:
        lines.append(f"Active mocks ({len(rules)}):")
        lines.extend(_mock_line(rule) for rule in rules)
    else:
        lines.append("No mocks active on this tab.")
    return "\n".join(lines)


def _ms(value: Any) -> str:
    return "—" if value is None else f"{value} ms"


async def _handle_performance(session_id: str, act: PerformanceAction) -> str:
    resp = await _send_command(session_id, "performance", _tab_params(act))
    if not resp.get("success"):
        return f"performance failed: {resp.get('error', 'unknown')}"
    data = resp.get("data") or {}
    lines = [f"Performance for {data.get('page_url') or 'this tab'}"]
    nav = data.get("navigation") or {}
    if nav:
        lines.append(
            f"Load ({nav.get('type', 'navigate')}): TTFB {_ms(nav.get('ttfb'))}, "
            f"DOMContentLoaded {_ms(nav.get('dom_content_loaded'))}, "
            f"load {_ms(nav.get('load'))}"
        )
    lcp = data.get("largest_contentful_paint") or {}
    lines.append(
        f"Paint: FCP {_ms(data.get('first_contentful_paint'))}, LCP "
        f"{_ms(lcp.get('time'))}"
        + (f" ({lcp['element']})" if lcp.get("element") else "")
    )
    lines.append(
        f"CLS {data.get('cumulative_layout_shift', 0)}; slowest interaction "
        f"{_ms(data.get('slowest_interaction_ms'))}"
    )
    resources = data.get("resources") or {}
    if resources:
        lines.append(
            f"Resources: {resources.get('count', 0)}, "
            f"{round((resources.get('transfer_size') or 0) / 1024)} KiB transferred"
        )
        for item in resources.get("slowest") or []:
            lines.append(
                f"  {item.get('duration')} ms {item.get('type')} {item.get('url')}"
            )
    metrics = data.get("metrics") or {}
    if metrics:
        heap = metrics.get("JSHeapUsedSize")
        lines.append(
            "Runtime: "
            + ", ".join(
                part
                for part in (
                    f"JS heap {round(heap / 1048576, 1)} MiB" if heap else "",
                    f"{int(metrics['Nodes'])} DOM nodes" if "Nodes" in metrics else "",
                    f"{int(metrics['LayoutCount'])} layouts"
                    if "LayoutCount" in metrics
                    else "",
                    f"script {round(metrics['ScriptDuration'] * 1000)} ms"
                    if "ScriptDuration" in metrics
                    else "",
                )
                if part
            )
        )
    return "\n".join(lines)


async def _handle_screenshot(session_id: str, act: ScreenshotAction) -> ToolResult:
    resp = await _send_command(
        session_id,
        "screenshot",
        _tab_params(
            act,
            format=act.format,
            quality=act.quality,
            full_page=act.full_page,
        ),
    )

    if not resp.get("success"):
        return ToolResult(
            parts=[TextBlock(text=f"Screenshot failed: {resp.get('error', 'unknown')}")]
        )

    data = resp.get("data", {})
    b64_image = data.get("data", "")
    fmt = data.get("format", act.format)

    if not b64_image:
        return ToolResult(
            parts=[TextBlock(text="Screenshot returned empty image data.")]
        )

    # Sized from the encoding rather than by decoding it: the bytes were only
    # ever used for this one number, and a full-page PNG is megabytes. Four
    # base64 characters carry three bytes, less whatever the padding stands in
    # for — exact, not an estimate.
    image_bytes = len(b64_image) * 3 // 4 - b64_image.count("=")
    mime = "image/jpeg" if fmt == "jpeg" else "image/png"

    # Viewport metadata lets the model map screenshot pixels to click coords.
    vp = data.get("viewport") or {}
    dims = ""
    if vp.get("width") and vp.get("height"):
        dims = f", {int(vp['width'])}x{int(vp['height'])} css-px"
    scope = "full page" if data.get("full_page") else "viewport"

    return ToolResult(
        parts=[
            ImageDataBlock(
                data=b64_image,
                media_type=mime,
            ),
            TextBlock(
                text=f"Screenshot captured ({scope}, {fmt}{dims}, {image_bytes} bytes). "
                "Screenshot pixels are CSS pixels — click x,y map 1:1."
            ),
        ]
    )


async def _handle_extract(session_id: str, act: ExtractAction) -> str:
    resp = await _send_command(
        session_id,
        "extract",
        _tab_params(
            act,
            format=act.format,
            ref=act.ref,
            selector=act.selector,
            max_chars=act.max_chars,
        ),
    )
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
    resp = await _send_command(
        session_id,
        "extract_elements",
        _tab_params(
            act,
            selector=act.selector,
            fields=act.fields,
            limit=act.limit,
            ref=act.ref,
            deep=act.deep,
        ),
    )
    if not resp.get("success"):
        return f"extract_elements failed: {resp.get('error', 'unknown')}"

    records = (resp.get("data") or {}).get("records", [])
    if not records:
        return f"No elements matched selector {act.selector!r}."
    header = f"Extracted {len(records)} record(s) for {act.selector!r}:"
    return (
        header + "\n" + json.dumps(records, indent=2, ensure_ascii=False, default=str)
    )


async def _handle_scroll_to_bottom(session_id: str, act: ScrollToBottomAction) -> str:
    resp = await _send_command(
        session_id,
        "scroll_to_bottom",
        _tab_params(
            act,
            max_scrolls=act.max_scrolls,
            delay_ms=act.delay_ms,
            ref=act.ref,
            selector=act.selector,
            timeout_ms=act.max_scrolls * (act.delay_ms + 400) + 2000,
        ),
    )
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
    resp = await _send_command(
        session_id, "evaluate", _tab_params(act, script=act.script)
    )
    if not resp.get("success"):
        return f"Evaluate failed: {resp.get('error', 'unknown')}"

    data = resp.get("data", {})
    value = data.get("value")
    return f"Result: {json.dumps(value, indent=2, default=str)}"


async def _handle_back(session_id: str, act: BackAction) -> str:
    resp = await _send_command(session_id, "back", _tab_params(act))
    if resp.get("success"):
        return _landed("Navigated back to", resp.get("data"))
    return f"Back failed: {resp.get('error', 'unknown')}"


async def _handle_forward(session_id: str, act: ForwardAction) -> str:
    resp = await _send_command(session_id, "forward", _tab_params(act))
    if resp.get("success"):
        return _landed("Navigated forward to", resp.get("data"))
    return f"Forward failed: {resp.get('error', 'unknown')}"


async def _handle_reload(session_id: str, act: ReloadAction) -> str:
    resp = await _send_command(session_id, "reload", _tab_params(act))
    if resp.get("success"):
        return _landed("Reloaded", resp.get("data"))
    return f"Reload failed: {resp.get('error', 'unknown')}"


async def _handle_wait(session_id: str, act: WaitAction) -> str:
    resp = await _send_command(session_id, "wait", {"ms": act.ms, "timeout_ms": act.ms})
    if resp.get("success"):
        return f"Waited {act.ms} ms."
    return f"Wait failed: {resp.get('error', 'unknown')}"


async def _handle_wait_for_selector(session_id: str, act: WaitForSelectorAction) -> str:
    resp = await _send_command(
        session_id,
        "wait_for_selector",
        _tab_params(
            act,
            selector=act.selector,
            state=act.state,
            timeout_ms=act.timeout_ms,
        ),
    )
    if resp.get("success"):
        return f"Selector {act.selector!r} is now {act.state}."
    return f"wait_for_selector failed: {resp.get('error', 'unknown')}"


async def _handle_wait_for_text(session_id: str, act: WaitForTextAction) -> str:
    resp = await _send_command(
        session_id,
        "wait_for_text",
        _tab_params(
            act,
            text=act.text,
            selector=act.selector,
            state=act.state,
            exact=act.exact,
            timeout_ms=act.timeout_ms,
        ),
    )
    if resp.get("success"):
        return f"Text {act.text!r} is now {act.state}."
    return f"wait_for_text failed: {resp.get('error', 'unknown')}"


async def _handle_wait_for_load(session_id: str, act: WaitForLoadAction) -> str:
    resp = await _send_command(
        session_id,
        "wait_for_load",
        _tab_params(
            act,
            state=act.state,
            timeout_ms=act.timeout_ms,
        ),
    )
    if resp.get("success"):
        return f"Page reached '{act.state}'."
    return f"wait_for_load failed: {resp.get('error', 'unknown')}"


async def _handle_wait_for_network_idle(
    session_id: str, act: WaitForNetworkIdleAction
) -> str:
    resp = await _send_command(
        session_id,
        "wait_for_network_idle",
        _tab_params(
            act,
            idle_ms=act.idle_ms,
            timeout_ms=act.timeout_ms,
        ),
    )
    if not resp.get("success"):
        return f"wait_for_network_idle failed: {resp.get('error', 'unknown')}"
    data = resp.get("data", {})
    if data.get("idle"):
        return f"Network idle ({act.idle_ms}ms with 0 in-flight requests)."
    return (
        f"Network still active after {act.timeout_ms}ms "
        f"({data.get('inflight', '?')} request(s) in flight)."
    )


async def _handle_wait_for_url(session_id: str, act: WaitForUrlAction) -> str:
    resp = await _send_command(
        session_id,
        "wait_for_url",
        _tab_params(act, url=act.url, timeout_ms=act.timeout_ms),
    )
    if not resp.get("success"):
        return f"wait_for_url failed: {resp.get('error', 'unknown')}"
    return f"URL is now {(resp.get('data') or {}).get('url', act.url)}"


async def _handle_drag_to_point(session_id: str, act: DragToPointAction) -> str:
    resp = await _send_command(
        session_id,
        "drag_to_point",
        _tab_params(
            act,
            ref=act.ref,
            source_selector=act.source_selector,
            source_index=act.source_index,
            target_x=act.target_x,
            target_y=act.target_y,
            steps=act.steps,
        ),
    )
    if not resp.get("success"):
        return f"drag_to_point failed: {resp.get('error', 'unknown')}"
    source = act.ref or repr(act.source_selector)
    return f"Dragged {source} to ({int(act.target_x)},{int(act.target_y)})."


#: Actions whose whole job is one command and one short answer. A run of
#: these travels to the extension as a single message instead of one round
#: trip each — the difference between a five-step form costing five crossings
#: of the relay and costing one.
#:
#: Everything else stays out: `crawl` runs its own fan-out, `screenshot`
#: returns an image, `extract` returns a document, and the waits are where
#: the time is meant to go.
_BATCHABLE: dict[str, Any] = {}


def _batchable(action: str):
    def register(build: Any) -> Any:
        _BATCHABLE[action] = build
        return build

    return register


@_batchable("click_selector")
@_batchable("hover")
@_batchable("focus")
def _params_target(act: Any) -> dict[str, Any]:
    return _target_params(act)


@_batchable("click_text")
def _params_click_text(act: Any) -> dict[str, Any]:
    return _tab_params(act, text=act.text, tag=act.tag, exact=act.exact)


@_batchable("fill")
def _params_fill(act: Any) -> dict[str, Any]:
    return _target_params(act, value=act.value, clear=act.clear, submit=act.submit)


@_batchable("set_checked")
def _params_set_checked(act: Any) -> dict[str, Any]:
    return _target_params(act, checked=act.checked)


@_batchable("select_option")
def _params_select_option(act: Any) -> dict[str, Any]:
    return _target_params(act, values=act.values, match=act.match)


@_batchable("key")
def _params_key(act: Any) -> dict[str, Any]:
    return _tab_params(act, key=act.key, modifiers=act.modifiers)


@_batchable("type")
def _params_type(act: Any) -> dict[str, Any]:
    return _tab_params(act, text=act.text)


@_batchable("scroll")
def _params_scroll(act: Any) -> dict[str, Any]:
    return _tab_params(act, dx=act.dx, dy=act.dy)


def _target_params(act: TargetMixin, **extra: Any) -> dict[str, Any]:
    """The handle or selector, whichever the caller gave."""
    if act.ref:
        return _tab_params(act, ref=act.ref, **extra)
    return _tab_params(act, selector=act.selector, index=act.index, **extra)


def _named(act: TargetMixin) -> str:
    return act.ref or repr(act.selector)


def _outcome(resp: dict[str, Any]) -> str:
    """What the page did about it.

    An action that reports only "done" leaves the caller to spend a snapshot
    finding out whether anything happened, which is the single most repeated
    round trip in a browsing session.
    """
    data = resp.get("data") or {}
    if not isinstance(data, dict):
        return ""
    if data.get("navigated_to"):
        return f" Page went to {data['navigated_to']}."
    changes = data.get("dom_changes")
    if changes == 0:
        return " Nothing on the page changed."
    if isinstance(changes, int) and changes > 0:
        return f" The page changed ({changes} DOM updates)."
    return ""


async def _handle_click_selector(session_id: str, act: ClickSelectorAction) -> str:
    resp = await _send_command(session_id, "click_selector", _params_target(act))
    if resp.get("success"):
        # The page's own name for what was clicked when the extension knows
        # it, since that is what the snapshot called it too.
        target = (resp.get("data") or {}).get("target")
        label = repr(target) if target else _named(act)
        return f"Clicked {label}.{_outcome(resp)}"
    return f"click_selector failed: {resp.get('error', 'unknown')}"


async def _handle_click_text(session_id: str, act: ClickTextAction) -> str:
    resp = await _send_command(session_id, "click_text", _params_click_text(act))
    if resp.get("success"):
        data = resp.get("data") or {}
        handle = f" (ref {data['ref']})" if data.get("ref") else ""
        return f"Clicked element with text {act.text!r}{handle}.{_outcome(resp)}"
    return f"click_text failed: {resp.get('error', 'unknown')}"


async def _handle_hover(session_id: str, act: HoverAction) -> str:
    resp = await _send_command(session_id, "hover", _params_target(act))
    if resp.get("success"):
        return f"Hovered {_named(act)}.{_outcome(resp)}"
    return f"hover failed: {resp.get('error', 'unknown')}"


async def _handle_focus(session_id: str, act: FocusAction) -> str:
    resp = await _send_command(session_id, "focus", _params_target(act))
    if resp.get("success"):
        return f"Focused {_named(act)}."
    return f"focus failed: {resp.get('error', 'unknown')}"


async def _handle_select_option(session_id: str, act: SelectOptionAction) -> str:
    resp = await _send_command(
        session_id,
        "select_option",
        _params_select_option(act),
    )
    if not resp.get("success"):
        return f"select_option failed: {resp.get('error', 'unknown')}"
    selected = (resp.get("data") or {}).get("selected", act.values)
    return f"Selected {json.dumps(selected, ensure_ascii=False)} in {_named(act)}."


async def _handle_set_checked(session_id: str, act: SetCheckedAction) -> str:
    resp = await _send_command(session_id, "set_checked", _params_set_checked(act))
    if resp.get("success"):
        already = (resp.get("data") or {}).get("changed") is False
        note = " (already was)" if already else ""
        return f"Set {_named(act)} checked={act.checked}{note}."
    return f"set_checked failed: {resp.get('error', 'unknown')}"


async def _handle_drag(session_id: str, act: DragAction) -> str:
    resp = await _send_command(
        session_id,
        "drag",
        _tab_params(
            act,
            source_ref=act.source_ref,
            target_ref=act.target_ref,
            source_selector=act.source_selector,
            target_selector=act.target_selector,
            source_index=act.source_index,
            target_index=act.target_index,
            steps=act.steps,
        ),
    )
    source = act.source_ref or repr(act.source_selector)
    target = act.target_ref or repr(act.target_selector)
    if resp.get("success"):
        return f"Dragged {source} to {target}."
    return f"drag failed: {resp.get('error', 'unknown')}"


async def _handle_fill(session_id: str, act: FillAction) -> str:
    resp = await _send_command(
        session_id,
        "fill",
        _params_fill(act),
    )
    if resp.get("success"):
        suffix = " and submitted" if act.submit else ""
        return f"Filled {_named(act)}{suffix}.{_outcome(resp) if act.submit else ''}"
    return f"fill failed: {resp.get('error', 'unknown')}"


async def _handle_open_tab(session_id: str, act: OpenTabAction) -> str:
    resp = await _send_command(
        session_id, "open_tab", {"url": act.url, "active": act.active}
    )
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
    resp = await _send_command(
        session_id,
        "snapshot",
        _tab_params(act, max_elements=act.max_elements, diff=act.diff),
    )
    if not resp.get("success"):
        return f"snapshot failed: {resp.get('error', 'unknown')}"

    data = resp.get("data", {})
    url = data.get("url") or ""
    header = _snapshot_header(data)

    if data.get("diff"):
        return "\n".join(header + _snapshot_diff_lines(data, url))

    elements = data.get("elements", [])
    if not elements:
        return "No interactive elements found on the page."
    lines = header + [f"Interactive elements ({len(elements)}):"]
    lines.extend(_snapshot_line(el, url) for el in elements)
    return "\n".join(lines)


def _snapshot_header(data: dict[str, Any]) -> list[str]:
    lines = [f"Page snapshot: {data.get('title') or 'Untitled'}"]
    if data.get("url"):
        lines.append(f"URL: {data['url']}")
    viewport = data.get("viewport") or {}
    if viewport.get("width") and viewport.get("height"):
        lines.append(
            f"Viewport: {viewport['width']}x{viewport['height']} css-px "
            f"at ({viewport.get('scrollX', 0)}, {viewport.get('scrollY', 0)})"
        )
    return lines


def _snapshot_diff_lines(data: dict[str, Any], url: str) -> list[str]:
    """Only what moved since the last snapshot.

    Most actions change one thing. Re-reading eighty elements to learn which
    one is the most repeated waste in a browsing session, and the parts that
    did not change are exactly the parts already in the conversation.
    """
    added = data.get("added") or []
    changed = data.get("changed") or []
    removed = data.get("removed") or []
    unchanged = data.get("unchanged") or 0
    if not added and not changed and not removed:
        return [f"No change since the last snapshot ({unchanged} elements)."]

    lines = [f"Changes since the last snapshot ({unchanged} unchanged):"]
    if added:
        lines.append(f"New ({len(added)}):")
        lines.extend(_snapshot_line(el, url) for el in added)
    if changed:
        lines.append(f"Changed ({len(changed)}):")
        lines.extend(_snapshot_line(el, url) for el in changed)
    if removed:
        lines.append(f"Gone: {', '.join(str(ref) for ref in removed)}")
    return lines


def _snapshot_line(el: dict[str, Any], url: str) -> str:
    box = el.get("box") or {}
    ref = el.get("ref")
    center = ""
    # Coordinates are how you act on an element when you have no handle for
    # it. With a handle they are 10% of a snapshot spent on a fallback that
    # is no longer the way in — and a screenshot gives pixels when a drop
    # point genuinely needs them.
    if not ref and box.get("x") is not None and box.get("y") is not None:
        center = f" @({int(box['x'])},{int(box['y'])})"
    label = (el.get("text") or el.get("name") or "").strip().replace("\n", " ")
    if len(label) > 80:
        label = label[:77] + "…"
    handle = f"{ref} " if ref else ""
    # A selector is only worth printing when it says something the handle
    # does not — and for anything inside a shadow root there is none.
    selector = el.get("selector") or ""
    tail = f" — {selector}" if selector and not ref else ""
    flags = ""
    if el.get("offscreen"):
        # Not visible from here: acting by ref scrolls to it first, and any
        # coordinates it has are not clickable ones.
        flags += " (offscreen)"
    if el.get("cross_origin"):
        flags += " (cross-origin frame — only screenshot/coordinates reach inside)"
    state_text = _snapshot_state(el.get("state") or {})
    attribute_text = _snapshot_attributes(el.get("attributes") or {}, label, url)
    return (
        f"  {handle}[{el.get('role', 'element')}]{center}{state_text} "
        f"{label!r}{attribute_text}{flags}{tail}"
    )


def _snapshot_state(state: dict[str, Any]) -> str:
    """The parts of an element's state worth spending tokens on.

    A page's worth of ``disabled=false`` says nothing — that is the ordinary
    condition of every control on it. Being *unchecked* is different: it is
    the thing the next click is about to change, so it stays even when false.
    """
    shown = {
        key: value
        for key, value in state.items()
        if value or key in {"checked", "selected"}
    }
    if not shown:
        return ""
    return " [" + ", ".join(f"{k}={str(v).lower()}" for k, v in shown.items()) + "]"


def _snapshot_attributes(attributes: dict[str, Any], label: str, page_url: str) -> str:
    """Attributes worth showing beside a labelled element.

    ``href`` was half of every snapshot this tool produced — measured at 50%
    of an 80-element listing of a Wikipedia article, because each of the 74
    links carried its absolute URL in full. An element that already says
    "History" does not also need to say where History lives: the model clicks
    it by its label or its selector, and `extract_elements` is the action for
    harvesting URLs. So a link keeps its address only when it has no label to
    be recognised by, and then only the part that distinguishes it.
    """
    shown: list[str] = []
    for key in ("type", "placeholder"):
        if attributes.get(key):
            shown.append(f"{key}={attributes[key]!r}")
    href = attributes.get("href")
    if href and not label:
        shown.append(f"href={_short_href(str(href), page_url)!r}")
    return " {" + ", ".join(shown) + "}" if shown else ""


def _short_href(href: str, page_url: str) -> str:
    """Drop what the address shares with the page it was found on."""
    origin = ""
    if page_url:
        parts = urlsplit(page_url)
        if parts.scheme and parts.netloc:
            origin = f"{parts.scheme}://{parts.netloc}"
    if origin and href.startswith(origin):
        href = href[len(origin) :] or "/"
    return href if len(href) <= 60 else href[:59] + "…"


async def _handle_semantic(
    session_id: str,
    act: SemanticSnapshotAction
    | SemanticReadAction
    | SemanticSelectAction
    | SemanticWriteAction,
) -> str:
    params = act.model_dump(exclude={"action", "tab_id"}, exclude_none=True)
    params = _tab_params(act, **params)
    resp = await _send_command(session_id, act.action, params)
    if not resp.get("success"):
        return f"{act.action} failed: {resp.get('error', 'unknown')}"
    data = resp.get("data") or {}
    return json.dumps(data, indent=2, ensure_ascii=False, default=str)


async def _crawl_page(session_id: str, act: CrawlAction, url: str) -> dict[str, Any]:
    """Run navigate → wait → (scroll) → extract for one URL in its own background tab.

    Never raises — every failure mode (open_tab, wait, extract, a stray
    exception) collapses into ``{"url", "ok": False, "error"}`` so one bad
    page can't sink the rest of a concurrent :func:`asyncio.gather`.
    """
    try:
        open_resp = await _send_command(
            session_id, "open_tab", {"url": url, "active": False}
        )
        if not open_resp.get("success"):
            return {
                "url": url,
                "ok": False,
                "error": f"open_tab failed: {open_resp.get('error', 'unknown')}",
            }
        tab_id = (open_resp.get("data") or {}).get("tab_id")
        if tab_id is None:
            return {"url": url, "ok": False, "error": "open_tab returned no tab_id"}

        try:
            if act.wait != "none":
                wait_action = (
                    "wait_for_load" if act.wait == "load" else "wait_for_network_idle"
                )
                wr = await _send_command(
                    session_id,
                    wait_action,
                    {"tab_id": tab_id, "timeout_ms": act.timeout_ms},
                )
                if not wr.get("success"):
                    return {
                        "url": url,
                        "ok": False,
                        "error": f"{wait_action} failed: {wr.get('error', 'unknown')}",
                    }

            if act.wait_selector:
                wsr = await _send_command(
                    session_id,
                    "wait_for_selector",
                    {
                        "tab_id": tab_id,
                        "selector": act.wait_selector,
                        "state": "visible",
                        "timeout_ms": act.timeout_ms,
                    },
                )
                if not wsr.get("success"):
                    return {
                        "url": url,
                        "ok": False,
                        "error": f"wait_for_selector failed: {wsr.get('error', 'unknown')}",
                    }

            if act.scroll:
                await _send_command(
                    session_id,
                    "scroll_to_bottom",
                    {
                        "tab_id": tab_id,
                        "max_scrolls": 10,
                        "delay_ms": 600,
                        "timeout_ms": act.timeout_ms,
                    },
                )

            if act.elements_selector:
                er = await _send_command(
                    session_id,
                    "extract_elements",
                    {
                        "tab_id": tab_id,
                        "selector": act.elements_selector,
                        "fields": act.fields,
                        "limit": act.limit,
                    },
                )
                if not er.get("success"):
                    return {
                        "url": url,
                        "ok": False,
                        "error": f"extract_elements failed: {er.get('error', 'unknown')}",
                    }
                records = (er.get("data") or {}).get("records", [])
                return {"url": url, "ok": True, "records": records}

            er = await _send_command(
                session_id,
                "extract",
                {
                    "tab_id": tab_id,
                    "format": act.format,
                    "selector": act.selector,
                    "max_chars": act.max_chars,
                },
            )
            if not er.get("success"):
                return {
                    "url": url,
                    "ok": False,
                    "error": f"extract failed: {er.get('error', 'unknown')}",
                }
            data = er.get("data") or {}
            content = data.get("content")
            if content is None:
                content = data.get("text", "")
            return {
                "url": url,
                "ok": True,
                "title": data.get("title", ""),
                "content": content[: act.max_chars],
            }
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
    lines = [
        f"Crawled {len(pages)} URL(s) ({act.concurrency} at a time): {ok_count} ok, {len(pages) - ok_count} failed."
    ]
    for p in pages:
        lines.append(f"\n## {p['url']}")
        if not p.get("ok"):
            lines.append(f"ERROR: {p.get('error', 'unknown')}")
        elif "records" in p:
            lines.append(f"{len(p['records'])} record(s):")
            lines.append(
                json.dumps(p["records"], indent=2, ensure_ascii=False, default=str)
            )
        else:
            if p.get("title"):
                lines.append(f"Title: {p['title']}")
            lines.append(p.get("content", ""))

    return "\n".join(lines)
