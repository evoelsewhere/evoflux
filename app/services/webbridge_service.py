"""WebBridge manager — in-process bridge between the agent and browser extensions.

The WebBridge feature lets the agent drive the user's *real* Chrome/Edge
browser (with its login sessions) through a browser extension::

    agent → webbridge tool → WebBridgeManager → Chrome extension → CDP → real browser

The extension holds a persistent WebSocket to the relay endpoint
(:mod:`app.api.routes.team.webbridge`). This manager owns the extension
registry, request/response correlation (``request_id`` + per-request
``asyncio.Future``), event/state tracking and stale-extension reaping.

Beyond routing it enforces the production guardrails that make it safe to
point at a logged-in browser:

- **Session routing** — each chat session sticks to the extension it first
  drove, so two windows/sessions do not stomp on each other. An explicit
  ``extension_id`` overrides the binding. (Commands stay request-id
  correlated, so several may be in flight and resolve out of order.)
- **Domain policy** — a navigate/page action is refused when its URL is on
  the blocklist, or (when an allowlist is configured) not on it. ``evaluate``
  can be disabled wholesale.
- **Audit trail** — every command is recorded in a ring buffer surfaced at
  ``GET /webbridge/audit``.

Both consumers are thin adapters over the singleton:

- the ``webbridge`` agent tool calls :meth:`WebBridgeManager.send_command`
  directly (same process — no loopback WebSocket), and
- the relay's WS endpoints translate wire messages into manager calls.

The manager is deliberately framework-light: an extension is registered
with a plain ``send`` callable (the relay passes ``ws.send_text``), so the
service never imports FastAPI.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlparse

from loguru import logger

#: Extensions silent for longer than this are considered gone.
_IDLE_TIMEOUT = 300.0  # 5 minutes
#: Default time a command may wait for the extension's response.
_RESPONSE_TIMEOUT = 30.0
#: Per-action response budgets that must exceed the extension's own internal
#: waits (e.g. ``cmdNavigate`` waits up to 25s, so the manager allows 45s).
#: For ``wait*`` actions the budget is derived from the caller's timeout.
_ACTION_TIMEOUTS: dict[str, float] = {
    "navigate": 45.0,
    "reload": 45.0,
    "wait_for_load": 45.0,
    "wait_for_selector": 45.0,
}
#: How often the stale-extension cleanup pass runs.
_CLEANUP_INTERVAL = 60.0
#: Hard cap on the audit ring buffer (the configured size only bounds reads).
_AUDIT_HARD_CAP = 1000

#: Actions answered/handled without touching page content — never gated by the
#: domain policy (they neither navigate nor read the current page).
_UNGATED_ACTIONS: frozenset[str] = frozenset(
    {"status", "get_tabs", "wait", "switch_tab", "close_tab"}
)
#: Actions whose *target* URL lives in ``params["url"]`` rather than the
#: extension's current page.
_TARGET_URL_ACTIONS: frozenset[str] = frozenset({"navigate", "open_tab"})
_PAGE_READ_ACTIONS: frozenset[str] = frozenset(
    {"extract", "extract_elements", "snapshot", "screenshot", "evaluate"}
)
# Actions resolved by the extension's ``resolveTab`` helper. A visible
# session/tab binding pins these actions without stealing browser focus.
_TAB_SCOPED_ACTIONS: frozenset[str] = frozenset(
    {
        "navigate",
        "click",
        "dblclick",
        "type",
        "key",
        "scroll",
        "screenshot",
        "extract",
        "evaluate",
        "back",
        "forward",
        "reload",
        "wait_for_selector",
        "wait_for_text",
        "wait_for_load",
        "wait_for_network_idle",
        "click_selector",
        "click_text",
        "hover",
        "focus",
        "select_option",
        "set_checked",
        "drag",
        "fill",
        "snapshot",
        "extract_elements",
        "scroll_to_bottom",
    }
)

#: Error returned when a command is issued with no usable extension.
NO_EXTENSION_ERROR = (
    "No browser extension connected. "
    "Install the EvoFlux WebBridge extension and open Chrome/Edge."
)

#: Send half of an extension's WebSocket, supplied by the relay adapter
#: (typically ``ws.send_text``).
SendText = Callable[[str], Awaitable[None]]
CloseSocket = Callable[[int], Awaitable[None]]


def _host_of(url: str) -> str:
    """Lower-cased hostname of *url*, or ``""`` when it has none."""
    if not url:
        return ""
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def _origin_of(url: str) -> str:
    """Normalized scheme + authority for an HTTP(S) URL, or ``""``."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
    except ValueError:
        return ""
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return ""
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def _binding_scope(value: str) -> str:
    origin = _origin_of(value)
    if origin:
        return origin
    if value.startswith("tab:") and value[4:].isdigit():
        return value
    return ""


def _scope_matches_tab(scope: str, tab_id: int, url: str) -> bool:
    if scope == f"tab:{tab_id}":
        return True
    return bool(scope) and _origin_of(url) == scope


def _domain_matches(host: str, patterns: list[str]) -> bool:
    """True when *host* equals or is a sub-domain of any configured pattern."""
    if not host:
        return False
    for raw in patterns:
        pat = raw.strip().lower().lstrip(".")
        if not pat:
            continue
        if host == pat or host.endswith("." + pat):
            return True
    return False


class ExtensionConnection:
    """A registered browser extension and its last-reported state."""

    def __init__(
        self,
        *,
        extension_id: str,
        browser: str,
        version: str,
        send: SendText,
        protocol_version: int = 1,
        capabilities: dict[str, Any] | None = None,
        close: CloseSocket | None = None,
    ) -> None:
        self.extension_id = extension_id
        self.browser = browser
        self.version = version
        self.protocol_version = protocol_version
        self.capabilities = capabilities or {}
        self.send = send
        self.close = close
        self.connected_at = time.time()
        self.last_seen = time.time()
        self.tabs: list[dict[str, Any]] = []
        self.current_url: str = ""
        self.current_title: str = ""

    def is_active(self, now: float) -> bool:
        return now - self.last_seen < _IDLE_TIMEOUT

    def info(self) -> dict[str, Any]:
        """Serializable state — superset of the REST ``ExtensionInfo`` shape."""
        return {
            "extension_id": self.extension_id,
            "browser": self.browser,
            "version": self.version,
            "protocol_version": self.protocol_version,
            "capabilities": self.capabilities,
            "connected_at": self.connected_at,
            "current_url": self.current_url,
            "current_title": self.current_title,
            "tabs": self.tabs,
        }


class WebBridgeManager:
    """Registry, command router and event hub for WebBridge extensions."""

    def __init__(self) -> None:
        self._extensions: dict[str, ExtensionConnection] = {}
        # request_id → (extension_id, future resolving to the response dict)
        self._pending: dict[str, tuple[str, asyncio.Future[dict[str, Any]]]] = {}
        # session_id → queues of connected agent-WS consumers (event stream)
        self._agent_queues: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}
        # session_id → extension_id it is bound to (sticky routing)
        self._session_targets: dict[str, str] = {}
        # session_id → (extension_id, tab_id) explicitly selected by the user.
        self._session_tabs: dict[str, tuple[str, int]] = {}
        # session_id → HTTP origin or tab:<id> scope for the live binding.
        self._session_tab_origins: dict[str, str] = {}
        # session_id → durable binding expiry as UNIX seconds.
        self._session_tab_expires: dict[str, float] = {}
        # session_id → (extension_id, reason) after a binding fails validation.
        # This tombstone prevents a later command from falling back to the
        # active tab until the user explicitly binds or unbinds the session.
        self._invalid_session_tabs: dict[str, tuple[str, str]] = {}
        # Persisted bindings loaded after a reconnect stay fail-closed until
        # the extension's complete tab snapshot confirms both tab ID + origin.
        self._pending_session_tabs: dict[str, tuple[str, int, str]] = {}
        # Newest-last audit ring buffer of executed commands.
        self._audit: deque[dict[str, Any]] = deque(maxlen=_AUDIT_HARD_CAP)
        # In-memory WebBridge policy; refreshed off the request path by
        # reload_policy(). None until first loaded → _policy() defaults open.
        self._policy_cache: Any = None
        # Serializes frame writes to the extension socket so concurrent
        # commands (parallel crawl) don't interleave bytes. Only wraps the
        # send, never the response wait.
        self._send_lock = asyncio.Lock()

    # ── Policy ──────────────────────────────────────────────────────────

    def _policy(self) -> Any:
        """The active :class:`WebBridgeSettings` — a pure in-memory read.

        Returns the value last loaded by :meth:`reload_policy` (called at
        startup and periodically by the cleanup loop), or permissive defaults
        if it has not run yet. Never does I/O, so the command hot path stays
        free of blocking file reads *and* of any ``await`` — the WebSocket
        relay must forward a command without yielding the loop between
        receiving it and sending it on.
        """
        if self._policy_cache is not None:
            return self._policy_cache
        from app.core.runtime_settings import WebBridgeSettings

        return WebBridgeSettings()

    def reload_policy(self) -> Any:
        """Re-read ``settings.yaml`` into the policy cache (blocking I/O).

        Call this off the request path — at startup and from the background
        cleanup loop — so policy edits take effect without a restart while the
        per-command :meth:`_policy` read stays I/O-free.
        """
        try:
            from app.core.runtime_settings import load_runtime_settings

            self._policy_cache = load_runtime_settings().webbridge
        except Exception:  # pragma: no cover - defensive
            from app.core.runtime_settings import WebBridgeSettings

            self._policy_cache = WebBridgeSettings()
        return self._policy_cache

    def check_policy(self, action: str, params: dict[str, Any], url: str) -> str | None:
        """Return a refusal message when *action* is not allowed, else None.

        *url* is the action's effective URL — the navigation target for
        ``navigate``/``open_tab``, otherwise the extension's current page.
        Reads the cached policy (refreshed off-path by :meth:`reload_policy`).
        """
        pol = self._policy()
        if not pol.enabled:
            return "WebBridge is disabled by policy (webbridge.enabled=false)."
        if action == "evaluate" and not pol.allow_evaluate:
            return (
                "The evaluate action is disabled by policy "
                "(webbridge.allow_evaluate=false). Use selector/snapshot "
                "actions instead."
            )
        if action in _UNGATED_ACTIONS:
            return None

        host = _host_of(url)
        if not host and (pol.allowed_domains or pol.blocked_domains):
            return (
                "WebBridge domain policy is active but the target page URL "
                "is unknown. Refresh the browser tab state and try again."
            )
        if host and _domain_matches(host, pol.blocked_domains):
            return f"Domain '{host}' is blocked by WebBridge policy."
        if (
            action in _PAGE_READ_ACTIONS
            and host
            and _domain_matches(host, pol.sharing.blocked_domains)
        ):
            return (
                f"Reading page data from domain '{host}' is blocked by "
                "WebBridge sharing policy."
            )
        if pol.allowed_domains:
            if not host:
                return (
                    "WebBridge allowlist is active but the target page is "
                    "unknown; navigate to an allowed domain first."
                )
            if not _domain_matches(host, pol.allowed_domains):
                return (
                    f"Domain '{host}' is not in the WebBridge allowlist "
                    f"({', '.join(pol.allowed_domains)})."
                )
        return None

    def check_interaction_policy(
        self,
        *,
        origin: str,
        user_gesture: bool,
        context_type: str | None,
    ) -> str | None:
        """Return a refusal for browser-to-EvoFlux sharing, else ``None``."""
        policy = self._policy()
        if not policy.enabled:
            return "WebBridge is disabled by policy."
        sharing = policy.sharing
        interactions = policy.interactions
        host = _host_of(origin)
        if host and _domain_matches(host, sharing.blocked_domains):
            return f"Sharing from domain '{host}' is blocked by WebBridge policy."
        if sharing.default == "block":
            return "Browser-to-EvoFlux sharing is disabled by policy."
        if not user_gesture and (
            sharing.default == "ask" or not interactions.allow_background_triggers
        ):
            return "Browser interaction requires an explicit user gesture."
        if context_type == "selection" and not sharing.allow_selection:
            return "Sharing browser selections is disabled by policy."
        if context_type == "readable_page" and not sharing.allow_readable_page:
            return "Sharing readable page content is disabled by policy."
        if context_type == "screenshot" and not sharing.allow_screenshot:
            return "Sharing browser screenshots is disabled by policy."
        return None

    @staticmethod
    def _effective_url(
        ext: ExtensionConnection, action: str, params: dict[str, Any]
    ) -> str:
        """Resolve the URL a command will affect for policy enforcement."""
        if action in _TARGET_URL_ACTIONS:
            return str(params.get("url", ""))

        tab_id = params.get("tab_id")
        if tab_id is not None:
            for tab in ext.tabs:
                if tab.get("id") == tab_id:
                    return str(tab.get("url", ""))
            return ""

        return ext.current_url

    # ── Audit ───────────────────────────────────────────────────────────

    def _record_audit(
        self,
        *,
        session_id: str,
        extension_id: str | None,
        action: str,
        url: str,
        success: bool,
        error: str | None,
    ) -> None:
        self._audit.append(
            {
                "ts": time.time(),
                "session_id": session_id,
                "extension_id": extension_id,
                "action": action,
                "url": url,
                "success": success,
                "error": error,
            }
        )

    def audit_entries(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Most-recent-first audit records, capped by *limit* or the setting."""
        if limit is None:
            try:
                limit = int(self._policy().audit_log_size)
            except Exception:  # pragma: no cover - defensive
                limit = 200
        entries = list(self._audit)[::-1]
        return entries[: max(0, limit)]

    # ── Extension lifecycle ─────────────────────────────────────────────

    def register_extension(
        self,
        *,
        extension_id: str,
        browser: str,
        version: str,
        send: SendText,
        protocol_version: int = 1,
        capabilities: dict[str, Any] | None = None,
        close: CloseSocket | None = None,
    ) -> ExtensionConnection:
        """Register (or replace) a connected extension."""
        previous = self._extensions.get(extension_id)
        if previous is not None:
            for request_id, (ext_id, future) in list(self._pending.items()):
                if ext_id != extension_id:
                    continue
                self._pending.pop(request_id, None)
                if not future.done():
                    future.set_result(
                        {
                            "success": False,
                            "data": None,
                            "error": "extension reconnected",
                        }
                    )
        conn = ExtensionConnection(
            extension_id=extension_id,
            browser=browser,
            version=version,
            send=send,
            protocol_version=protocol_version,
            capabilities=capabilities,
            close=close,
        )
        self._extensions[extension_id] = conn
        logger.info(
            "webbridge_ext_connected extension_id={} browser={} version={}",
            extension_id,
            browser,
            version,
        )
        return conn

    def unregister_extension(
        self,
        extension_id: str,
        *,
        connection: ExtensionConnection | None = None,
    ) -> None:
        """Drop an extension and fail every command still pending on it."""
        conn = self._extensions.get(extension_id)
        if conn is None:
            return
        if connection is not None and conn is not connection:
            return
        self._extensions.pop(extension_id, None)
        logger.info("webbridge_ext_disconnected extension_id={}", extension_id)
        for request_id, (ext_id, fut) in list(self._pending.items()):
            if ext_id != extension_id:
                continue
            self._pending.pop(request_id, None)
            if not fut.done():
                fut.set_result(
                    {"success": False, "data": None, "error": "extension disconnected"}
                )
        # Drop sessions pinned to this extension so they rebind to a live one.
        for sid, eid in list(self._session_targets.items()):
            if eid == extension_id:
                self._session_targets.pop(sid, None)
                self._session_tabs.pop(sid, None)
                self._session_tab_origins.pop(sid, None)
                self._pending_session_tabs.pop(sid, None)
                self._session_tab_expires.pop(sid, None)

    def get_extension(self, extension_id: str) -> ExtensionConnection | None:
        return self._extensions.get(extension_id)

    async def close_extension(self, extension_id: str, *, code: int = 1000) -> bool:
        """Close and unregister an extension, if connected."""
        conn = self._extensions.get(extension_id)
        if conn is None:
            return False
        if conn.close is not None:
            try:
                await conn.close(code)
            except Exception as exc:
                logger.debug(
                    "webbridge_ext_close_failed extension_id={} error={}",
                    extension_id,
                    exc,
                )
        self.unregister_extension(extension_id)
        return True

    def touch(
        self,
        extension_id: str,
        *,
        connection: ExtensionConnection | None = None,
    ) -> None:
        """Refresh an extension's liveness timestamp (heartbeat)."""
        conn = self._extensions.get(extension_id)
        if conn is not None and (connection is None or conn is connection):
            conn.last_seen = time.time()

    # ── Status ──────────────────────────────────────────────────────────

    def active_extensions(self) -> list[ExtensionConnection]:
        now = time.time()
        return [ext for ext in self._extensions.values() if ext.is_active(now)]

    def get_active_extension(self) -> ExtensionConnection | None:
        """Return the most recently seen active extension, or None."""
        active = self.active_extensions()
        if not active:
            return None
        return max(active, key=lambda e: e.last_seen)

    def has_active_extension(self) -> bool:
        return self.get_active_extension() is not None

    def resolve_target(
        self, session_id: str, extension_id: str | None = None
    ) -> ExtensionConnection | None:
        """Pick the extension a *session*'s command should drive.

        Explicit *extension_id* wins. Otherwise the session sticks to the
        extension it was last bound to (if still active); failing that it
        binds to — and returns — the current active extension.
        """
        if extension_id:
            ext = self._extensions.get(extension_id)
            if ext is None or not ext.is_active(time.time()):
                return None
            # An explicit target also (re)binds the session so its events and
            # follow-up commands stick to the same extension.
            previous = self._session_targets.get(session_id)
            self._session_targets[session_id] = extension_id
            if previous is not None and previous != extension_id:
                self._session_tabs.pop(session_id, None)
                self._session_tab_origins.pop(session_id, None)
                self._pending_session_tabs.pop(session_id, None)
                self._session_tab_expires.pop(session_id, None)
            return ext

        bound = self._session_targets.get(session_id)
        if bound:
            ext = self._extensions.get(bound)
            if ext is not None and ext.is_active(time.time()):
                return ext
            self._session_targets.pop(session_id, None)
            self._session_tabs.pop(session_id, None)
            self._session_tab_origins.pop(session_id, None)
            self._pending_session_tabs.pop(session_id, None)
            self._session_tab_expires.pop(session_id, None)

        ext = self.get_active_extension()
        if ext is not None:
            self._session_targets[session_id] = ext.extension_id
        return ext

    def bind_session_tab(
        self,
        session_id: str,
        extension_id: str,
        tab_id: int,
        origin: str = "",
        expires_at: float | None = None,
    ) -> None:
        """Pin page-scoped commands for *session_id* to one extension tab."""
        for other_session, target in list(self._session_tabs.items()):
            if other_session != session_id and target == (extension_id, tab_id):
                self.unbind_session_tab(other_session, extension_id=extension_id)
        for other_session, pending in list(self._pending_session_tabs.items()):
            if (
                other_session != session_id
                and pending[0] == extension_id
                and pending[1] == tab_id
            ):
                self.unbind_session_tab(other_session, extension_id=extension_id)
        self._session_targets[session_id] = extension_id
        self._session_tabs[session_id] = (extension_id, tab_id)
        self._invalid_session_tabs.pop(session_id, None)
        expected_origin = _binding_scope(origin)
        self._invalid_session_tabs.pop(session_id, None)
        if expected_origin:
            self._session_tab_origins[session_id] = expected_origin
        else:
            self._session_tab_origins.pop(session_id, None)
        if expires_at is not None:
            self._session_tab_expires[session_id] = expires_at
        else:
            self._session_tab_expires.pop(session_id, None)
        self._pending_session_tabs.pop(session_id, None)

    def stage_session_tab_binding(
        self,
        session_id: str,
        extension_id: str,
        tab_id: int,
        origin: str,
        expires_at: float | None = None,
    ) -> None:
        """Load a durable binding without trusting a stale browser tab ID yet."""
        for other_session, target in list(self._session_tabs.items()):
            if other_session != session_id and target == (extension_id, tab_id):
                self.unbind_session_tab(other_session, extension_id=extension_id)
        for other_session, pending in list(self._pending_session_tabs.items()):
            if (
                other_session != session_id
                and pending[0] == extension_id
                and pending[1] == tab_id
            ):
                self.unbind_session_tab(other_session, extension_id=extension_id)
        expected_origin = _binding_scope(origin)
        if (
            self._session_tabs.get(session_id) == (extension_id, tab_id)
            and self._session_tab_origins.get(session_id) == expected_origin
        ):
            return
        self._session_targets[session_id] = extension_id
        self._session_tabs.pop(session_id, None)
        if expires_at is not None:
            self._session_tab_expires[session_id] = expires_at
        else:
            self._session_tab_expires.pop(session_id, None)
        self._pending_session_tabs[session_id] = (
            extension_id,
            tab_id,
            expected_origin,
        )

    def validate_pending_tab_bindings(
        self,
        extension_id: str,
        tabs: list[dict[str, Any]],
    ) -> list[tuple[str, int]]:
        """Activate matching pending bindings; return stale bindings to delete."""
        tab_urls = {
            tab.get("id"): str(tab.get("url", ""))
            for tab in tabs
            if tab.get("id") is not None
        }
        stale: list[tuple[str, int]] = []
        for session_id, (bound_extension, tab_id, expected_origin) in list(
            self._pending_session_tabs.items()
        ):
            if bound_extension != extension_id:
                continue
            actual_url = tab_urls.get(tab_id)
            if actual_url is not None:
                restored_scope = (
                    expected_origin
                    if _scope_matches_tab(expected_origin, tab_id, actual_url)
                    else f"tab:{tab_id}"
                )
                self.bind_session_tab(
                    session_id,
                    extension_id,
                    tab_id,
                    restored_scope,
                    self._session_tab_expires.get(session_id),
                )
            else:
                self._invalid_session_tabs[session_id] = (
                    extension_id,
                    "Bound browser tab is unavailable or changed origin; bind this tab again before continuing.",
                )
                self._pending_session_tabs.pop(session_id, None)
                self._session_targets.pop(session_id, None)
                self._session_tab_expires.pop(session_id, None)
                stale.append((session_id, tab_id))
        return stale

    def validate_active_tab_bindings(
        self,
        extension_id: str,
        tabs: list[dict[str, Any]],
    ) -> list[tuple[str, int]]:
        """Drop live bindings whose tab vanished or navigated cross-origin."""
        tab_urls = {
            tab.get("id"): str(tab.get("url", ""))
            for tab in tabs
            if tab.get("id") is not None
        }
        stale: list[tuple[str, int]] = []
        for session_id, (bound_extension, tab_id) in list(self._session_tabs.items()):
            if bound_extension != extension_id:
                continue
            expected_origin = self._session_tab_origins.get(session_id)
            if not expected_origin:
                continue
            actual_url = tab_urls.get(tab_id)
            if actual_url is not None and _scope_matches_tab(
                expected_origin, tab_id, actual_url
            ):
                continue
            if actual_url is not None:
                self._session_tab_origins[session_id] = f"tab:{tab_id}"
                self._invalid_session_tabs.pop(session_id, None)
                continue
            self._invalid_session_tabs[session_id] = (
                extension_id,
                "Bound browser tab changed origin; bind this tab again before continuing.",
            )
            self._session_tabs.pop(session_id, None)
            self._session_tab_origins.pop(session_id, None)
            self._session_targets.pop(session_id, None)
            self._session_tab_expires.pop(session_id, None)
            stale.append((session_id, tab_id))
        return stale

    def unbind_session_tab(
        self, session_id: str, *, extension_id: str | None = None
    ) -> bool:
        binding = self._session_tabs.get(session_id)
        pending = self._pending_session_tabs.get(session_id)
        invalid = self._invalid_session_tabs.get(session_id)
        bound_extension = (
            binding[0]
            if binding is not None
            else pending[0]
            if pending
            else invalid[0]
            if invalid
            else None
        )
        if bound_extension is None or (
            extension_id is not None and bound_extension != extension_id
        ):
            return False
        self._session_tabs.pop(session_id, None)
        self._session_tab_origins.pop(session_id, None)
        self._pending_session_tabs.pop(session_id, None)
        self._session_targets.pop(session_id, None)
        self._session_tab_expires.pop(session_id, None)
        self._invalid_session_tabs.pop(session_id, None)
        return True

    def session_tab_binding(self, session_id: str) -> tuple[str, int] | None:
        return self._session_tabs.get(session_id)

    def session_tab_binding_pending(self, session_id: str) -> bool:
        return session_id in self._pending_session_tabs

    def status(self) -> dict[str, Any]:
        """Connection status — the shape behind ``GET /webbridge/status``."""
        active = self.active_extensions()
        return {
            "connected": len(active) > 0,
            "extensions": [ext.info() for ext in active],
        }

    # ── Events / responses coming from the extension ────────────────────

    def handle_event(
        self,
        extension_id: str,
        event: str,
        data: dict[str, Any],
        *,
        connection: ExtensionConnection | None = None,
    ) -> None:
        """Track extension state and broadcast the event to agent consumers."""
        conn = self._extensions.get(extension_id)
        if connection is not None and conn is not connection:
            return
        if conn is not None:
            conn.last_seen = time.time()
            if event == "tab_updated":
                conn.tabs = data.get("tabs", [])
                conn.current_url = data.get("url", "")
                conn.current_title = data.get("title", "")

        envelope = {
            "type": "event",
            "event": event,
            "data": data,
            "extension_id": extension_id,
        }
        # Deliver only to sessions bound to this extension, plus sessions with
        # no binding yet (legacy/unscoped consumers) — never cross sessions
        # pinned to a *different* browser.
        for session_id, queues in self._agent_queues.items():
            bound = self._session_targets.get(session_id)
            if bound is not None and bound != extension_id:
                continue
            for queue in queues:
                try:
                    queue.put_nowait(envelope)
                except asyncio.QueueFull:
                    pass

    def handle_response(
        self,
        request_id: str,
        *,
        success: bool,
        data: Any,
        error: str | None,
        extension_id: str | None = None,
        connection: ExtensionConnection | None = None,
    ) -> bool:
        """Resolve the pending command for *request_id*. False if unknown."""
        if extension_id is not None and connection is not None:
            if self._extensions.get(extension_id) is not connection:
                return False
        entry = self._pending.pop(request_id, None)
        if entry is None:
            logger.debug("webbridge_orphan_response request_id={}", request_id)
            return False
        _, fut = entry
        if not fut.done():
            fut.set_result({"success": success, "data": data, "error": error})
        return True

    # ── Commands (agent → extension) ────────────────────────────────────

    @staticmethod
    def _timeout_for(action: str, params: dict[str, Any]) -> float:
        """Response budget for *action*, honouring caller ``timeout_ms``."""
        caller = params.get("timeout_ms")
        if isinstance(caller, (int, float)) and caller > 0:
            # Give the extension 10s of slack over its own internal deadline.
            return float(caller) / 1000.0 + 10.0
        return _ACTION_TIMEOUTS.get(action, _RESPONSE_TIMEOUT)

    async def send_command(
        self,
        session_id: str,
        action: str,
        params: dict[str, Any] | None = None,
        *,
        extension_id: str | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Send *action* to the session's extension and await its response.

        Always resolves to ``{"success": bool, "data": ..., "error": ...}``
        (plus ``request_id`` for wire correlation) — never raises for
        routine failures like a missing extension or a timeout.
        """
        params = dict(params or {})

        if action == "status":
            # Answered locally — does not need an extension.
            return {"success": True, "data": self.status(), "error": None}

        invalid_binding = self._invalid_session_tabs.get(session_id)
        if action in _TAB_SCOPED_ACTIONS and invalid_binding is not None:
            return {
                "success": False,
                "data": None,
                "error": invalid_binding[1],
            }

        ext = self.resolve_target(session_id, extension_id)
        if ext is None:
            return {"success": False, "data": None, "error": NO_EXTENSION_ERROR}

        binding = self._session_tabs.get(session_id)
        pending_binding = self._pending_session_tabs.get(session_id)
        binding_expires_at = self._session_tab_expires.get(session_id)
        if (
            action in _TAB_SCOPED_ACTIONS
            and (binding is not None or pending_binding is not None)
            and binding_expires_at is not None
            and binding_expires_at <= time.time()
        ):
            if binding is not None:
                invalid_extension_id = binding[0]
            elif pending_binding is not None:
                invalid_extension_id = pending_binding[0]
            else:  # pragma: no cover — guarded by the condition above
                invalid_extension_id = ext.extension_id
            self._invalid_session_tabs[session_id] = (
                invalid_extension_id,
                "Bound browser tab expired; bind this tab again before continuing.",
            )
            self._session_tabs.pop(session_id, None)
            self._session_tab_origins.pop(session_id, None)
            self._pending_session_tabs.pop(session_id, None)
            self._session_targets.pop(session_id, None)
            self._session_tab_expires.pop(session_id, None)
            return {
                "success": False,
                "data": None,
                "error": "Bound browser tab expired; bind this tab again before continuing.",
            }
        if (
            action in _TAB_SCOPED_ACTIONS
            and "tab_id" not in params
            and pending_binding is not None
            and pending_binding[0] == ext.extension_id
        ):
            return {
                "success": False,
                "data": None,
                "error": "Bound browser tab is pending validation; wait for tab state.",
            }
        if (
            action in _TAB_SCOPED_ACTIONS
            and "tab_id" not in params
            and binding is not None
            and binding[0] == ext.extension_id
        ):
            expected_origin = self._session_tab_origins.get(session_id)
            if expected_origin:
                current_url = next(
                    (
                        str(tab.get("url", ""))
                        for tab in ext.tabs
                        if tab.get("id") == binding[1]
                    ),
                    "",
                )
                if not current_url:
                    return {
                        "success": False,
                        "data": None,
                        "error": "Bound browser tab is pending origin validation; wait for tab state.",
                    }
                if expected_origin.startswith("tab:"):
                    if _origin_of(current_url):
                        return {
                            "success": False,
                            "data": None,
                            "error": "Browser tab entered an HTTP(S) page; refresh Side Chat before using browser tools.",
                        }
                    return {
                        "success": False,
                        "data": None,
                        "error": "Browser tools are unavailable on this internal page; Side Chat remains available.",
                    }
                if _origin_of(current_url) != expected_origin:
                    self._session_tab_origins[session_id] = f"tab:{binding[1]}"
                    return {
                        "success": False,
                        "data": None,
                        "error": "Bound browser tab changed page scope; refresh Side Chat before continuing.",
                    }
            params["tab_id"] = binding[1]
            if expected_origin and not expected_origin.startswith("tab:"):
                params["_webbridge_expected_origin"] = expected_origin

        # A session starts with one primary tab. If it opens additional tabs,
        # the extension groups them with that primary tab while keeping the
        # fail-closed default target unchanged.
        if action == "open_tab":
            params["_webbridge_session_id"] = session_id
            if (
                binding is not None
                and binding[0] == ext.extension_id
                and (binding_expires_at is None or binding_expires_at > time.time())
            ):
                params["_webbridge_parent_tab_id"] = binding[1]

        # Guardrail check before anything reaches the browser. The policy is
        # an in-memory read (reload_policy refreshes it off the request path),
        # so this adds no I/O or await between receiving and forwarding.
        effective_url = self._effective_url(ext, action, params)
        refusal = self.check_policy(action, params, effective_url)
        if refusal is not None:
            self._record_audit(
                session_id=session_id,
                extension_id=ext.extension_id,
                action=action,
                url=effective_url,
                success=False,
                error=refusal,
            )
            logger.warning(
                "webbridge_policy_refused action={} url={}", action, effective_url
            )
            return {"success": False, "data": None, "error": refusal}

        result = await self._dispatch(ext, action, params, timeout)
        self._record_audit(
            session_id=session_id,
            extension_id=ext.extension_id,
            action=action,
            url=effective_url,
            success=bool(result.get("success")),
            error=result.get("error"),
        )
        return result

    async def _dispatch(
        self,
        ext: ExtensionConnection,
        action: str,
        params: dict[str, Any],
        timeout: float | None,
    ) -> dict[str, Any]:
        """Send one correlated command to *ext* and await its response."""
        request_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[request_id] = (ext.extension_id, fut)

        command = {
            "type": "command",
            "request_id": request_id,
            "action": action,
            "params": params,
        }
        budget = timeout if timeout is not None else self._timeout_for(action, params)
        try:
            # Serialize only the frame write, not the wait-for-response. This
            # keeps concurrent commands (parallel multi-tab crawl) from
            # interleaving bytes on the one extension socket, while still
            # allowing many requests to be in flight at once. An uncontended
            # acquire does not yield, so the single-command WS path is
            # unaffected (see the TestClient dual-portal note).
            async with self._send_lock:
                await ext.send(json.dumps(command))
        except Exception as e:
            self._pending.pop(request_id, None)
            logger.debug(
                "webbridge_send_failed extension_id={} error={}", ext.extension_id, e
            )
            return {
                "request_id": request_id,
                "success": False,
                "data": None,
                "error": "Extension disconnected",
            }

        try:
            result = await asyncio.wait_for(fut, timeout=budget)
        except TimeoutError:
            self._pending.pop(request_id, None)
            return {
                "request_id": request_id,
                "success": False,
                "data": None,
                "error": f"Extension response timeout ({budget:.0f}s)",
            }
        return {"request_id": request_id, **result}

    # ── Agent event subscriptions (relay's agent WS endpoint) ───────────

    def subscribe_agent(self, session_id: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        self._agent_queues.setdefault(session_id, set()).add(queue)
        return queue

    def unsubscribe_agent(
        self, session_id: str, queue: asyncio.Queue[dict[str, Any]]
    ) -> None:
        queues = self._agent_queues.get(session_id)
        if queues is None:
            return
        queues.discard(queue)
        if not queues:
            self._agent_queues.pop(session_id, None)

    # ── Stale-extension cleanup ─────────────────────────────────────────

    def cleanup_stale(self, now: float | None = None) -> list[str]:
        """Drop extensions past the idle timeout; returns removed ids."""
        now = time.time() if now is None else now
        stale = [eid for eid, ext in self._extensions.items() if not ext.is_active(now)]
        for eid in stale:
            self.unregister_extension(eid)
            logger.info("webbridge_ext_timeout extension_id={}", eid)
        return stale

    async def run_cleanup_loop(self) -> None:
        """Background task: reap silent extensions and refresh the policy.

        Both run off any command's request path, so the blocking
        ``settings.yaml`` read in :meth:`reload_policy` never touches the hot
        loop. An initial reload primes the cache before the first command.
        """
        self.reload_policy()
        while True:
            await asyncio.sleep(_CLEANUP_INTERVAL)
            self.cleanup_stale()
            self.reload_policy()


#: Process singleton.
webbridge_manager = WebBridgeManager()
