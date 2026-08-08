"""Permission system — tool-call approval with wildcard rule matching.

Architecture mirrors opencode's ``permission/index.ts`` + ``evaluate.ts``:

Rule evaluation
---------------
A ``Rule`` maps ``(permission, pattern, action)`` where:

- ``permission``: glob that matches a tool name (e.g. ``"bash"``, ``"*"``)
- ``pattern``:    glob that matches a command/path string (e.g. ``"git *"``, ``"*"``)
- ``action``:     ``"allow"`` | ``"deny"`` | ``"ask"``

Rules are evaluated last-match-wins (``findLast`` semantics), so more specific
rules appended after broad defaults override them — the same behaviour as
opencode's ``evaluate.ts``.

Default when no rule matches: ``"ask"`` (prompt user).

Permission service
------------------
``PermissionService`` is a per-session, *mode-aware* service.  The session's
persisted ``permission_mode`` decides how an unresolved ``"ask"`` action is
handled:

- ``"ask"``          — block the tool call, publish a ``permission_asked`` SSE
  event, and wait for the user's reply.
- ``"accept-edits"`` — like ``"ask"`` but file-edit tools are auto-allowed.
- ``"plan"`` / ``"auto"`` — auto-allow (plan gating happens in the plan tools).
- ``"bypass"``       — skip rule evaluation entirely.

The mode lives on the service (not baked into subclasses) so the API can flip
it mid-run and immediately resolve any now-allowed pending requests — the
frontend never has to reason about modes; it only renders events.

The service is scoped via a ``contextvars.ContextVar`` for tool-call sites
*and* registered in a module-level ``session_id → service`` map so HTTP
endpoints (which run in a different async context) can find it — the same
pattern as ``plan.py`` / ``ask_user.py``.

Permission flow
---------------
1. Before executing a tool, call ``service.ask(tool_name, patterns)``.
2. If the resolved action is ``"allow"`` → proceed immediately.
3. If ``"deny"`` → raise ``PermissionDeniedError``.
4. If ``"ask"`` → mode decides: auto-allow, or publish ``permission_asked``
   and block until the reply endpoint resolves the request.
"""

from __future__ import annotations

import asyncio
import contextvars
import fnmatch
import uuid
from dataclasses import dataclass, field
from typing import Callable, Literal

from loguru import logger

# ── Types ─────────────────────────────────────────────────────────────────────

Action = Literal["allow", "deny", "ask"]
Reply = Literal["once", "always", "reject"]
Mode = Literal["ask", "accept-edits", "plan", "auto", "bypass"]


@dataclass(frozen=True, slots=True)
class Rule:
    """A single permission rule."""

    permission: str  # glob matching tool name
    pattern: str  # glob matching command/path argument
    action: Action


Ruleset = list[Rule]


# ── Errors ───────────────────────────────────────────────────────────────────


class PermissionDeniedError(PermissionError):
    """Raised when a rule explicitly denies a tool call."""

    def __init__(self, tool: str, pattern: str, ruleset: Ruleset) -> None:
        self.tool = tool
        self.pattern = pattern
        self.ruleset = ruleset
        rules_str = "; ".join(
            f"{r.permission}/{r.pattern}={r.action}"
            for r in ruleset
            if fnmatch.fnmatch(tool, r.permission)
        )
        super().__init__(
            f"Permission denied for tool '{tool}' pattern '{pattern}'. "
            f"Matching rules: [{rules_str}]"
        )


class PermissionRejectedError(PermissionError):
    """Raised when the user explicitly rejects a permission request."""

    def __init__(self, request_id: str) -> None:
        self.request_id = request_id
        super().__init__(
            f"The user rejected permission request {request_id}. "
            "Do not retry the same call; ask the user how to proceed."
        )


# ── Rule evaluation ───────────────────────────────────────────────────────────


def evaluate(tool: str, pattern: str, *rulesets: Ruleset) -> Rule:
    """Return the last matching rule across all rulesets.

    Implements ``findLast`` semantics: later rules (appended per-session)
    override earlier ones, so session-specific ``always-allow`` rules win
    over the default ``ask`` fallback.

    Falls back to ``Rule(tool, "*", "ask")`` when no rule matches.
    """
    all_rules = [r for rs in rulesets for r in rs]
    match: Rule | None = None
    for rule in all_rules:
        if fnmatch.fnmatch(tool, rule.permission) and fnmatch.fnmatch(
            pattern, rule.pattern
        ):
            match = rule
    return match or Rule(permission=tool, pattern="*", action="ask")


# ── Safe-by-default tools ─────────────────────────────────────────────────────

# Tools with no side effects on the user's system (read-only inspection,
# session bookkeeping, user interaction, team coordination).  Blocking these
# in "ask" mode would make the mode unusable — every file read and every
# team handoff would raise a modal — so they are allowed by default.  Config
# rules (``base_ruleset``) are evaluated after these and can still deny them.
_SAFE_TOOLS: frozenset[str] = frozenset(
    {
        # read-only filesystem & search
        "read",
        "glob",
        "grep",
        "ls",
        # code intelligence / diagnostics
        "lsp_diagnostics",
        "lsp_definition",
        "lsp_references",
        "static_diagnostics",
        "code_context",
        # read-only web / info retrieval
        "date",
        "web_search",
        "web_fetch",
        "image_search",
        "memory_search",
        "wiki_search",
        "list_code_reviews",
        "get_code_review",
        "get_code_review_checks",
        # session bookkeeping / UI-only output
        "note",
        "show_widget",
        "visualize_read_me",
        "todo_manage",
        # user interaction & plan flow (already block on the user)
        "ask_user",
        "enter_plan_mode",
        "exit_plan_mode",
        # team coordination (no system side effects)
        "team_message",
        "team_handoff",
        "team_state",
        "team_delegate",
        "team_reject",
        "team_manage",
        # background-task introspection (start stays gated through shell)
        "process",
        # instruction/schema loading only; real execution stays permission-gated
        "skill",
        "load_tool",
    }
)

_DEFAULT_BASE_RULESET: Ruleset = [
    Rule(permission=t, pattern="*", action="allow") for t in sorted(_SAFE_TOOLS)
]

# File-edit tools additionally auto-allowed in "accept-edits" mode.
_ACCEPT_EDITS_TOOLS: frozenset[str] = frozenset({"edit", "write", "patch"})


# ── Permission request ────────────────────────────────────────────────────────


@dataclass
class PermissionRequest:
    """A pending approval request, stored until the user replies."""

    id: str
    session_id: str
    tool: str  # tool name
    patterns: list[str]  # command fragments / path globs to approve
    always_patterns: list[str]  # patterns added to session ruleset on "always"
    metadata: dict = field(default_factory=dict)
    # Future is created lazily via create() — do NOT set a default_factory here
    # because asyncio.get_event_loop() cannot be called at module import time.
    _future: "asyncio.Future | None" = field(default=None, compare=False, repr=False)

    @classmethod
    def create(
        cls,
        session_id: str,
        tool: str,
        patterns: list[str],
        always_patterns: list[str],
        metadata: dict | None = None,
    ) -> "PermissionRequest":
        req = cls(
            id=str(uuid.uuid4()),
            session_id=session_id,
            tool=tool,
            patterns=patterns,
            always_patterns=always_patterns,
            metadata=metadata or {},
        )
        req._future = asyncio.get_event_loop().create_future()
        return req


# ── Permission service ────────────────────────────────────────────────────────


class PermissionService:
    """Per-session, mode-aware permission service.

    Holds:
    - ``mode``: the session's permission mode (may be flipped mid-run)
    - ``base_ruleset``: global rules loaded from config (read-only reference)
    - ``session_ruleset``: per-session ``always-allow`` rules accumulated
      from user replies during this session
    - ``pending``: map of request_id → PermissionRequest awaiting reply
    - ``stream_session_id``: the SSE stream to publish ask/reply events on
      (the lead session for team members)
    """

    def __init__(
        self,
        session_id: str,
        base_ruleset: Ruleset | None = None,
        *,
        mode: Mode = "ask",
        stream_session_id: str | None = None,
        on_ask: Callable[[PermissionRequest], None] | None = None,
    ) -> None:
        self.session_id = session_id
        self.mode: Mode = mode
        self.stream_session_id = stream_session_id or session_id
        self.base_ruleset: Ruleset = list(base_ruleset or [])
        self.session_ruleset: Ruleset = []
        self.pending: dict[str, PermissionRequest] = {}
        # Optional observer fired when a blocking request is created (tests).
        self._on_ask = on_ask

    # ── Core API ──────────────────────────────────────────────────────────

    async def ask(
        self,
        tool: str,
        patterns: list[str],
        always_patterns: list[str] | None = None,
        metadata: dict | None = None,
        *,
        important: bool = False,
    ) -> None:
        """Check permission for *tool* against *patterns*.

        - ``"allow"`` → returns immediately.
        - ``"deny"``  → raises ``PermissionDeniedError``.
        - ``"ask"``   → resolved by ``self.mode``: auto-allow in
          ``auto``/``plan`` (and ``accept-edits`` for edit tools), otherwise
          publish a ``permission_asked`` SSE event and await the reply.

        Raises:
            PermissionDeniedError: if any rule explicitly denies the call.
            PermissionRejectedError: if the user rejects the request.
        """
        if self.mode == "bypass":
            return

        needs_ask = False
        for pattern in patterns:
            rule = evaluate(
                tool,
                pattern,
                _DEFAULT_BASE_RULESET,
                self.base_ruleset,
                self.session_ruleset,
            )
            if rule.action == "deny":
                raise PermissionDeniedError(
                    tool, pattern, self.base_ruleset + self.session_ruleset
                )
            if rule.action == "ask":
                needs_ask = True

        if not needs_ask:
            return
        if not important and not self._blocks(tool):
            return

        req = PermissionRequest.create(
            session_id=self.session_id,
            tool=tool,
            patterns=patterns,
            always_patterns=always_patterns or patterns,
            metadata=metadata or {},
        )
        self.pending[req.id] = req

        if self._on_ask is not None:
            self._on_ask(req)
        await self._publish_asked(req)

        assert req._future is not None, "PermissionRequest must be created via create()"
        try:
            reply: Reply = await req._future
        except asyncio.CancelledError:
            # Agent interrupted while waiting — clear FE + reconnect state.
            await self._push_replied(req.id, "reject")
            raise
        finally:
            self.pending.pop(req.id, None)

        if reply == "reject":
            raise PermissionRejectedError(req.id)

        if reply == "always":
            for p in req.always_patterns:
                rule = Rule(permission=tool, pattern=p, action="allow")
                if rule not in self.session_ruleset:
                    self.session_ruleset.append(rule)

    def _blocks(self, tool: str) -> bool:
        """Whether an unresolved ``ask`` action blocks on the user in ``self.mode``."""
        if self.mode in ("auto", "plan"):
            return False
        if self.mode == "accept-edits" and tool in _ACCEPT_EDITS_TOOLS:
            return False
        return True

    def reply(self, request_id: str, reply: Reply) -> bool:
        """Resolve a pending permission request with *reply*.

        Publishes a ``permission_replied`` SSE event so every connected client
        closes its approval UI.  Returns True if the request was found and
        resolved, False if unknown.
        """
        req = self.pending.get(request_id)
        if req is None:
            return False
        if req._future is not None and not req._future.done():
            req._future.set_result(reply)
            self._publish_replied(req.id, reply)
        return True

    def set_mode(self, mode: Mode) -> list[str]:
        """Switch the permission mode mid-run.

        Pending requests that the new mode no longer gates are resolved with
        ``"once"`` so a blocked agent resumes immediately.  Returns the ids
        of the requests that were auto-resolved.
        """
        self.mode = mode
        resolved: list[str] = []
        for req_id, req in list(self.pending.items()):
            if mode == "bypass" or not self._blocks(req.tool):
                if self.reply(req_id, "once"):
                    resolved.append(req_id)
        return resolved

    def auto_allow_pending(self, request_id: str) -> bool:
        """Auto-allow a specific pending request (used for now-defaulting)."""
        return self.reply(request_id, "always")

    def auto_allow_all_pending(self) -> int:
        """Auto-allow all pending requests. Returns number resolved."""
        count = 0
        for req_id in list(self.pending):
            if self.auto_allow_pending(req_id):
                count += 1
        return count

    def list_pending(self) -> list[PermissionRequest]:
        return list(self.pending.values())

    def add_rule(self, rule: Rule) -> None:
        """Append a rule to the session ruleset."""
        self.session_ruleset.append(rule)

    # ── SSE publishing ────────────────────────────────────────────────────

    async def _publish_asked(self, req: PermissionRequest) -> None:
        try:
            from app.agent.schemas.events import PermissionAskedEvent
            from app.services import memory_stream_store as stream_store
            from app.services.stream_envelope import StreamEnvelope

            await stream_store.push_event(
                self.stream_session_id,
                StreamEnvelope.from_event(
                    PermissionAskedEvent(
                        request_id=req.id,
                        session_id=self.session_id,
                        tool=req.tool,
                        patterns=req.patterns,
                        metadata=req.metadata,
                    )
                ),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("permission_asked_sse_push_failed error={}", exc)

    def _publish_replied(self, request_id: str, reply: Reply) -> None:
        """Fire-and-forget ``permission_replied`` push (reply() is sync)."""

        async def _emit() -> None:
            await self._push_replied(request_id, reply)

        try:
            asyncio.get_running_loop().create_task(_emit())
        except RuntimeError:
            pass  # no running loop (sync tests) — nothing to publish to

    async def _push_replied(self, request_id: str, reply: Reply) -> None:
        """Best-effort ``permission_replied`` so every client closes."""
        try:
            from app.agent.schemas.events import PermissionRepliedEvent
            from app.services import memory_stream_store as stream_store
            from app.services.stream_envelope import StreamEnvelope

            await stream_store.push_event(
                self.stream_session_id,
                StreamEnvelope.from_event(
                    PermissionRepliedEvent(
                        request_id=request_id,
                        session_id=self.session_id,
                        reply=reply,
                    )
                ),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("permission_replied_sse_push_failed error={}", exc)


# ── Context-var + session-registry integration ────────────────────────────────

_permission_ctx: contextvars.ContextVar[PermissionService] = contextvars.ContextVar(
    "permission_ctx"
)

# session_id → active service, so HTTP endpoints (different async context than
# the agent task) can resolve replies.  Same pattern as plan.py / ask_user.py.
_active_services: dict[str, PermissionService] = {}

_default_service: PermissionService | None = None


def get_permission_service() -> PermissionService:
    """Return the active ``PermissionService`` for the current context.

    Falls back to a module-level auto-allow service when no context is set
    (e.g. during tests or standalone tool invocations).
    """
    global _default_service
    try:
        return _permission_ctx.get()
    except LookupError:
        if _default_service is None:
            _default_service = PermissionService(session_id="default", mode="auto")
        return _default_service


def set_permission_service(service: PermissionService) -> contextvars.Token:
    """Scope *service* to the current async context and register globally."""
    _active_services[service.session_id] = service
    return _permission_ctx.set(service)


def reset_permission_service(token: contextvars.Token, session_id: str) -> None:
    """Restore the previous context and unregister from the global registry."""
    _active_services.pop(session_id, None)
    _permission_ctx.reset(token)


def get_service_for_session(session_id: str) -> PermissionService | None:
    """Look up an active service by its own session_id."""
    return _active_services.get(session_id)


def get_services_for_stream(session_id: str) -> list[PermissionService]:
    """All active services publishing to *session_id*'s SSE stream.

    A team session has one service per member, all publishing to the lead's
    stream — the reply endpoint receives the lead session id and must reach
    the member service that owns the pending request.
    """
    return [
        s
        for s in _active_services.values()
        if s.session_id == session_id or s.stream_session_id == session_id
    ]


# ── "Always allow" pattern extraction ─────────────────────────────────────────

# Number of leading command tokens that form the approval prefix, mirroring
# opencode's BashArity: `git push` approves `git push *`, not all of git.
_COMMAND_ARITY: dict[str, int] = {
    "git": 2,
    "npm": 2,
    "pnpm": 2,
    "yarn": 2,
    "bun": 2,
    "uv": 2,
    "docker": 2,
    "kubectl": 2,
    "cargo": 2,
    "go": 2,
    "pip": 2,
    "brew": 2,
    "make": 1,
    "python": 1,
    "node": 1,
}


def command_always_pattern(command: str) -> str:
    """Glob added to the session ruleset when the user picks "always allow".

    Uses the command's leading tokens (per ``_COMMAND_ARITY``, default 1) so
    approval covers the command family, not just the exact string.
    """
    tokens = command.split()
    if not tokens:
        return command
    arity = _COMMAND_ARITY.get(tokens[0], 1)
    prefix = " ".join(tokens[:arity])
    return f"{prefix} *" if len(tokens) > arity else prefix


# ── Config-based ruleset builder ──────────────────────────────────────────────


def ruleset_from_config(config: dict) -> Ruleset:
    """Build a Ruleset from a config dict.

    Config format (mirrors opencode's permission config)::

        {
            "bash": "allow",          # allow all bash calls
            "*": "ask",               # ask for everything else
            "bash": {                 # per-pattern rules
                "git *": "allow",
                "rm *": "ask",
            }
        }

    Wildcard tool names (``"*"``, ``"mcp_*"``) are sorted before specific
    names so that specific tool rules override the broad default — same
    behaviour as opencode's ``fromConfig``.
    """
    entries = sorted(
        config.items(),
        key=lambda kv: ("*" not in kv[0], kv[0]),
    )
    rules: Ruleset = []
    for tool_glob, value in entries:
        if isinstance(value, str):
            rules.append(Rule(permission=tool_glob, pattern="*", action=value))  # type: ignore[arg-type]
        elif isinstance(value, dict):
            for pattern, action in value.items():
                rules.append(Rule(permission=tool_glob, pattern=pattern, action=action))  # type: ignore[arg-type]
    return rules
