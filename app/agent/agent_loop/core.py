"""Core :class:`Agent` class — orchestrates one ``run()`` per turn.

The class itself is now thin: it owns construction, the iteration
loop, the hook plumbing, and the per-iteration bookkeeping.  Each
substantial piece of work is delegated to a sibling module:

- :mod:`app.agent.agent_loop.streaming` — stream + assemble one LLM call
- :mod:`app.agent.agent_loop.retry` — retry / fallback over a provider
- :mod:`app.agent.agent_loop.tool_executor` — innermost tool executor
- :mod:`app.agent.agent_loop.tool_dispatch` — parallel tool-call gather
"""

from __future__ import annotations

import asyncio
import inspect
import json
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Generic, TypeVar

import httpx
from loguru import logger

from app.agent.agent_loop.streaming import stream_and_assemble
from app.agent.agent_loop.tool_dispatch import gather_or_cancel, run_serially
from app.agent.agent_loop.tool_executor import make_tool_executor, sanitize_error
from app.agent.lifecycle import normalize_sleep_message
from app.agent.usage import usage_to_dict
from app.agent.checkpointer import Checkpointer
from app.agent.hooks import BaseAgentHook
from app.agent.providers.base import LLMProviderBase
from app.agent.providers.capabilities import ModelCapabilities, get_capabilities
from app.agent.schemas.agent import (
    AgentContext,
    AgentStats,
    RunConfig,
)
from app.agent.schemas.chat import (
    AssistantMessage,
    ChatMessage,
    ContentBlock,
    HumanMessage,
    SystemMessage,
    ToolCall,
    ToolMessage,
    Usage,
)
from app.uuid7 import uuid7 as _uuid7
from app.agent.state import (
    AgentState,
    ModelRequest,
    RunContext,
    ToolCallHandler,
    build_model_chain,
    build_tool_chain,
)
from app.agent.tools.registry import Tool, deferred_catalog_entry
from app.agent.turn_usage import current_turn_usage_snapshot

MAX_AGENT_ITERATIONS = 5000
MAX_CONCURRENT_TOOLS = 10
# How many times the loop will re-issue the model call within the same turn
# after the provider (and any fallback) exhausts its own retry budget on a
# transient connectivity failure (ReadTimeout / ConnectError).  Without this,
# such an exhaustion raises straight out of ``run()`` and abandons all
# completed tool work mid-task — the "agent stopped after a tool call" symptom.
MAX_PROVIDER_RESUME_ATTEMPTS = 5
# Base backoff (seconds) between in-loop resume attempts; grows linearly.
PROVIDER_RESUME_BASE_DELAY = 3.0

EMPTY_AFTER_TOOL_RECOVERY_PROMPT = (
    "Your previous response after the tool results was empty. Continue the task now. "
    "If the requested work is complete, briefly summarize the outcome; otherwise, "
    "make the next required tool call. Do not return an empty response."
)

_OBSERVATION_CHECKPOINTS: dict[str, tuple[int, ...]] = {
    "trivial": (8, 16, 32),
    "simple": (12, 24, 48),
    "multi_step": (16, 32, 64),
    "complex": (24, 48, 96),
}


def _observation_checkpoint_prompt(state: AgentState) -> str | None:
    """Return one ephemeral evidence-budget reminder at adaptive milestones.

    This is deliberately a soft checkpoint, not a global iteration cap. A
    difficult investigation can continue, but it must identify the unresolved
    claim instead of silently accumulating overlapping source observations.
    """

    stats = state.metadata.get("tool_observation_stats")
    if not isinstance(stats, dict):
        return None
    executed = stats.get("executed")
    if not isinstance(executed, int) or executed <= 0:
        return None
    complexity = str(state.metadata.get("execution_complexity") or "simple")
    thresholds = _OBSERVATION_CHECKPOINTS.get(
        complexity, _OBSERVATION_CHECKPOINTS["simple"]
    )
    reached = [threshold for threshold in thresholds if executed >= threshold]
    if not reached:
        return None
    emitted: set[int] = state.metadata.setdefault(
        "_observation_checkpoints_emitted", set()
    )
    pending = [threshold for threshold in reached if threshold not in emitted]
    if not pending:
        return None
    threshold = max(pending)
    emitted.update(value for value in reached if value <= threshold)
    reused = stats.get("reused") if isinstance(stats.get("reused"), int) else 0
    return (
        "[Evidence checkpoint — soft guidance]\n"
        f"This turn has executed {executed} source/retrieval/discovery "
        f"observations and reused {reused}. Before another observation, identify "
        "one unresolved material claim and choose the cheapest tool call that can "
        "settle it. If the requested conclusion already has direct implementation "
        "evidence plus focused regression or runtime evidence, answer now. Reuse "
        "covered ranges and batch independent reads in one model turn. This is not "
        "a hard limit; continue when a named evidence gap remains."
    )


TContext = TypeVar("TContext", bound=AgentContext)


def _partition_tool_call_batch(
    tool_calls: list[ToolCall],
    run_tools: dict[str, Tool],
) -> tuple[list[ToolCall], list[tuple[ToolCall, str]]]:
    """Apply explicit per-tool model-turn batch contracts."""
    allowed: list[ToolCall] = []
    blocked: list[tuple[ToolCall, str]] = []
    counts: dict[str, int] = {}
    fingerprints: set[tuple[str, str]] = set()

    for tool_call in tool_calls:
        tool = run_tools.get(tool_call.function.name)
        if tool is None:
            allowed.append(tool_call)
            continue

        arguments = tool_call.function.arguments
        try:
            canonical_arguments = json.dumps(
                json.loads(arguments or "{}"), sort_keys=True, separators=(",", ":")
            )
        except (json.JSONDecodeError, TypeError, ValueError):
            canonical_arguments = arguments or "{}"
        fingerprint = (tool.name, canonical_arguments)

        if getattr(tool, "deduplicate_in_batch", False) and fingerprint in fingerprints:
            blocked.append(
                (tool_call, f"Skipped duplicate '{tool.name}' call in this model turn.")
            )
            continue

        count = counts.get(tool.name, 0)
        max_calls = getattr(tool, "max_calls_per_batch", None)
        if max_calls is not None and count >= max_calls:
            blocked.append(
                (
                    tool_call,
                    f"Skipped '{tool.name}' call: maximum "
                    f"{max_calls} calls per model turn.",
                )
            )
            continue

        fingerprints.add(fingerprint)
        counts[tool.name] = count + 1
        allowed.append(tool_call)

    return allowed, blocked


def _build_tool_call_waves(
    tool_calls: list[ToolCall],
    run_tools: dict[str, Tool],
) -> list[tuple[bool, list[ToolCall]]]:
    """Build ordered dispatch waves without moving calls across barriers.

    Consecutive tools that explicitly declare ``concurrency_safe`` may run in
    parallel. Every other tool becomes a serial barrier, so later calls cannot
    observe state before that mutation has completed.
    """
    waves: list[tuple[bool, list[ToolCall]]] = []
    parallel_wave: list[ToolCall] = []

    def flush_parallel_wave() -> None:
        if parallel_wave:
            waves.append((True, parallel_wave.copy()))
            parallel_wave.clear()

    for tool_call in tool_calls:
        tool = run_tools.get(tool_call.function.name)
        if tool is not None and getattr(tool, "concurrency_safe", False):
            parallel_wave.append(tool_call)
            continue

        flush_parallel_wave()
        waves.append((False, [tool_call]))

    flush_parallel_wave()
    return waves


class Agent(Generic[TContext]):
    """Core agent with a flat, simple API.

    ``TContext`` is an optional :class:`~app.schemas.agent.AgentContext` subclass
    that carries typed, validated per-invocation data (user role, locale, etc.).
    Hooks can read ``state.context`` with full IDE autocomplete.

    Example::

        class UserContext(AgentContext):
            user_group: str = "default"

        agent = Agent(
            llm_provider=GoogleGenAIProvider(api_key="...", model="gemini-3.1-flash", temperature=0.7),
            name="assistant",
            system_prompt="You are a helpful assistant.",
            tools=[web_search, get_date],
            hooks=[DatabaseHook(session_factory)],
            context=UserContext(user_group="premium"),
        )
    """

    def __init__(
        self,
        llm_provider: LLMProviderBase,
        name: str = "Agent",
        description: str | None = None,
        system_prompt: str = "You are a helpful assistant.",
        tools: list[Tool] | None = None,
        skills: list[str] | None = None,
        mcp_servers: list[str] | None = None,
        hooks: Sequence[BaseAgentHook] | None = None,
        max_iterations: int = MAX_AGENT_ITERATIONS,
        context: TContext | None = None,
        max_concurrent_tools: int = MAX_CONCURRENT_TOOLS,
        model_id: str | None = None,
        fallback_provider: LLMProviderBase | None = None,
        fallback_model_id: str | None = None,
    ):
        self.id = _uuid7()
        self.name = name
        self.description = description
        self.llm_provider = llm_provider
        # Me store original "provider:model" string from config
        self.model_id = model_id
        # Me cache multimodal capabilities — computed once from model_id
        self.capabilities: ModelCapabilities = get_capabilities(model_id)
        self.system_prompt = system_prompt
        self.skills: list[str] = list(skills) if skills else []
        # MCP server names this agent was configured with (from `mcp:` frontmatter).
        # Surface to API consumers so the UI can group tools by origin server,
        # including servers that exist but aren't ready yet (zero tools).
        self.mcp_servers: list[str] = list(mcp_servers) if mcp_servers else []
        self.hooks: list[BaseAgentHook] = list(hooks) if hooks else []
        self.max_iterations = max_iterations
        self.context = context
        self.run_config: RunConfig | None = None
        self._tool_semaphore = asyncio.Semaphore(max_concurrent_tools)
        # Cumulative agent-level statistics (updated per run)
        self.stats = AgentStats(agent_id=self.id)
        # Fallback provider — used when primary exhausts retries on retryable errors
        self.fallback_provider: LLMProviderBase | None = fallback_provider
        self.fallback_model_id: str | None = fallback_model_id

        # Build internal tool lookup from Tool objects or plain callables
        self._tools: dict[str, Tool] = {}
        for fn in tools or []:
            t = fn if isinstance(fn, Tool) else Tool(fn)
            self._tools[t.name] = t

        # Drift tracking (set by loader._build_agent for disk-loaded agents).
        self.source_path: Path | None = None
        self.config_stamp: dict[str, int | None] = {}

        # User-defined plugin hooks loaded from settings.EVOFLUX_PLUGINS_DIRS.
        # Cached on first run() so import + applies_to filtering happens once.
        # Keyed by role so the same Agent instance reused across roles
        # (theoretical) wouldn't cross-contaminate.
        self._plugin_hooks_by_role: dict[str, list[BaseAgentHook]] = {}

    async def _load_plugin_hooks(self, role: str) -> list[BaseAgentHook]:
        """Lazily load and cache user-defined plugin hooks for ``role``.

        Discovery + import happens at most once per ``(self, role)`` pair.
        Plugin failures are logged inside the loader and never propagate
        — a broken plugin must not break the agent.
        """
        cached = self._plugin_hooks_by_role.get(role)
        if cached is not None:
            return cached

        # Local imports keep cold-import cost off the hot path and avoid
        # forcing every test that constructs an Agent to set up the
        # plugins package.
        from app.agent.plugins import load_plugin_hooks
        from app.core.config import settings

        try:
            hooks = await load_plugin_hooks(
                settings.plugin_dirs(),
                agent_name=self.name,
                role=role,
                require_trust=True,
            )
        except Exception as exc:  # noqa: BLE001 — defensive, never break agent
            logger.warning(
                "plugin_load_pipeline_failed agent={} error={}", self.name, exc
            )
            hooks = []

        self._plugin_hooks_by_role[role] = hooks
        return hooks

    async def run(
        self,
        messages: list[ChatMessage],
        config: RunConfig | None = None,
        *,
        hooks: Sequence[BaseAgentHook] | None = None,
        injected_tools: list[Tool] | None = None,
        excluded_tools: frozenset[str] | None = None,
        deferred_tools: frozenset[str] | None = None,
        interrupt_event: asyncio.Event | None = None,
        checkpointer: Checkpointer | None = None,
        llm_provider: LLMProviderBase | None = None,
        model_id: str | None = None,
        **kwargs,
    ) -> list[ChatMessage]:
        """Runs the agent loop for a single turn.

        Returns the full list of messages produced.

        ``hooks`` provides additional hooks for this run, combined with the
        agent's default ``self.hooks``.

        ``injected_tools`` provides additional tools for this specific run only,
        merged with the agent's constructor tools. Callers should use this
        instead of mutating ``agent._tools`` directly.

        ``excluded_tools`` is an optional frozenset of tool names to remove
        from the run-local tool lookup after merging constructor + injected
        tools.  Used by team tier policies to restrict heavy tools for
        lower-tier tasks.

        ``deferred_tools`` optionally overrides the tool metadata that marks
        which names stay callable but start hidden from ``tool_defs`` — unlike
        ``excluded_tools`` they are never popped from the run-local lookup.
        When omitted, every run-local tool with ``deferred=True`` is hidden.
        The ``load_tool`` tool reveals one for the rest of this run by adding
        its name to ``state.metadata["activated_deferred_tools"]``; the loop
        recomputes ``tool_defs`` each iteration so an activation takes effect
        starting the very next model call. Cuts baseline per-call token cost
        for heavy/narrow tools (browser automation, LSP, ...) that most
        turns never touch.

        ``checkpointer`` is an optional :class:`~app.agent.checkpointer.Checkpointer`
        that the loop calls at defined sync points to persist state.  When
        provided, ``DatabaseHook`` is not needed — the loop owns persistence.

        Agent role for plugin ``applies_to`` filtering is read from the
        :mod:`app.agent.plugins.role` contextvar — team callers wrap the
        ``run()`` invocation with :func:`set_role`.
        """
        from app.agent.plugins.role import current_role

        role = current_role()
        self.run_config = config
        plugin_hooks = await self._load_plugin_hooks(role)
        combined_hooks = list(self.hooks) + list(hooks or []) + plugin_hooks
        active_provider = llm_provider or self.llm_provider
        active_model_id = model_id or self.model_id

        # Build run-local tool lookup: constructor tools + injected_tools.
        # Never mutate self._tools so concurrent runs are safe.
        run_tools: dict[str, Tool] = dict(self._tools)
        for t in injected_tools or []:
            run_tools[t.name] = t

        # Apply tier-based tool exclusions when requested.
        if excluded_tools:
            for name in excluded_tools:
                run_tools.pop(name, None)

        # Deferred tools stay in run_tools (so they remain callable once
        # unlocked) but are left out of tool_defs until activated. Intersect
        # with what's actually present so a name already removed by
        # excluded_tools above is simply a no-op here, never re-added.
        requested_deferred = (
            set(deferred_tools)
            if deferred_tools is not None
            else {
                name
                for name, run_tool in run_tools.items()
                if getattr(run_tool, "deferred", False)
            }
            if "load_tool" in run_tools
            else set()
        )
        deferred_names = requested_deferred & run_tools.keys()

        deferred_catalog = {
            name: deferred_catalog_entry(run_tools[name])
            for name in sorted(deferred_names)
        }

        # Work on a local copy, strip any SystemMessage — system prompt lives
        # in state.system_prompt and is prepended per-call by the loop.
        messages = [m for m in messages if not isinstance(m, SystemMessage)]

        # Me build immutable run context — identity that no change mid-run
        ctx = RunContext(
            session_id=config.session_id if config else None,
            run_id=config.run_id if config else str(_uuid7()),
            agent_name=self.name,
            session_created_at=config.session_created_at if config else None,
        )

        # Always-visible tools' definitions never change mid-run — compute once.
        # Some tools (skill, load_tool) have a callable description factory that
        # does real work (filesystem scans, string building); recomputing this
        # list every iteration would redo that work for nothing on every turn
        # of every team run, since deferred_tools is set on virtually all of
        # them. Only the (typically 0-2) activated deferred tools' definitions
        # need to be (re)looked up as activation changes.
        static_tool_defs = [
            t.definition for name, t in run_tools.items() if name not in deferred_names
        ]

        def _compute_tool_defs(activated: frozenset[str]) -> list[dict[str, Any]]:
            if not activated:
                return static_tool_defs
            return static_tool_defs + [
                run_tools[name].definition
                for name in sorted(activated)
                if name in deferred_names
            ]

        tool_defs = _compute_tool_defs(frozenset())

        # Build per-run AgentState — passed to all hooks throughout the loop
        state = AgentState(
            messages=messages,
            system_prompt=self.system_prompt,
            context=self.context,
            capabilities=get_capabilities(active_model_id),
            tool_names=sorted(run_tools.keys()),
            tool_defs=tool_defs,
        )

        # Expose session_id in state.metadata so tools (e.g. note) can read it
        # without needing direct access to RunContext.
        if ctx.session_id is not None:
            state.metadata["session_id"] = ctx.session_id
        state.metadata["agent_name"] = ctx.agent_name
        # Keep pre-model stages aligned with per-run provider overrides.
        # The value is ephemeral and is never persisted or model-visible.
        state.metadata["_runtime_provider"] = active_provider

        # Surface caller-supplied per-run metadata to tools/hooks.  Used by
        # team leads to pass ``mode`` and ``workspace`` so the schedule tool
        # can derive routing targets without trusting LLM-supplied values.
        if config is not None and config.metadata:
            for key, value in config.metadata.items():
                state.metadata.setdefault(key, value)

        # Runtime-owned metadata: the loader can only discover tools granted
        # after hard exclusions. Callers may pre-activate deferred tools
        # (e.g. composer Plan mode → exit_plan_mode) via config.metadata.
        state.metadata["deferred_tool_catalog"] = deferred_catalog
        existing_activated = state.metadata.get("activated_deferred_tools")
        if existing_activated:
            state.metadata["activated_deferred_tools"] = set(existing_activated)
        else:
            state.metadata["activated_deferred_tools"] = set()

        def _merge_dynamic_deferred_tools(
            candidates: list[Tool],
        ) -> tuple[str, ...]:
            """Add permitted runtime MCP tools to this run-local catalog."""

            added: list[str] = []
            webbridge_session = bool(state.metadata.get("webbridge_session"))
            side_chat_session = bool(state.metadata.get("side_chat_session"))
            for run_tool in candidates:
                if not getattr(run_tool, "deferred", False):
                    continue
                if excluded_tools and run_tool.name in excluded_tools:
                    continue
                capabilities = getattr(run_tool, "capabilities", frozenset())
                if webbridge_session and "webbridge-safe" not in capabilities:
                    continue
                if side_chat_session and not getattr(run_tool, "read_only", False):
                    continue
                changed = False
                if run_tools.get(run_tool.name) is not run_tool:
                    run_tools[run_tool.name] = run_tool
                    changed = True
                if run_tool.name not in deferred_names:
                    deferred_names.add(run_tool.name)
                    changed = True
                entry = deferred_catalog_entry(run_tool)
                if deferred_catalog.get(run_tool.name) != entry:
                    deferred_catalog[run_tool.name] = entry
                    changed = True
                if changed:
                    added.append(run_tool.name)
            if added:
                state.tool_names = sorted(run_tools)
            return tuple(added)

        def _grant_plugin_mcp_tools(installation_id: str) -> tuple[str, ...]:
            """Grant tools belonging to the plugin Skill being activated."""

            from app.plugin_platform.runtime import plugin_mcp_runtime

            state.metadata.setdefault("plugin_mcp_grants", set()).add(installation_id)
            tools = plugin_mcp_runtime.get_tools_for_installation(installation_id)
            added = _merge_dynamic_deferred_tools(tools)
            if added:
                logger.debug(
                    "plugin_skill_mcp_tools_granted agent={} installation={} tools={}",
                    self.name,
                    installation_id,
                    list(added),
                )
            return tuple(tool.name for tool in tools if tool.name in deferred_names)

        def _refresh_deferred_tool_catalog() -> None:
            """Merge newly-ready, newly-granted MCP tools into this live run.

            An agent can register an MCP server and wire it into its own
            frontmatter during a tool round. Rebuilding only on the next user
            turn leaves the current run's ``load_tool`` catalog stale. Refresh
            just before ``load_tool`` searches, while preserving per-agent MCP
            grants and all caller-provided hard exclusions.
            """
            from app.plugin_platform.runtime import plugin_mcp_runtime

            for installation_id in state.metadata.get("plugin_mcp_grants", set()):
                _merge_dynamic_deferred_tools(
                    plugin_mcp_runtime.get_tools_for_installation(installation_id)
                )

            if role == "member":
                return

            configured_servers = list(self.mcp_servers)
            if self.source_path is not None:
                try:
                    from app.agent.config import parse_agent_md

                    live_config = parse_agent_md(self.source_path)
                    if live_config.role == "member":
                        return
                    configured_servers = live_config.mcp
                except Exception as exc:  # noqa: BLE001 - keep last valid grant
                    logger.warning(
                        "dynamic_mcp_grant_refresh_failed agent={} error={}",
                        self.name,
                        exc,
                    )
            if not configured_servers:
                return

            from app.plugin_platform.runtime import get_mcp_tools_for_server

            changed = False
            for server_name in dict.fromkeys(configured_servers):
                server_tools = get_mcp_tools_for_server(server_name)
                if not server_tools:
                    continue
                if _merge_dynamic_deferred_tools(server_tools):
                    changed = True

            if changed:
                state.tool_names = sorted(run_tools)
                logger.debug(
                    "dynamic_mcp_tools_refreshed agent={} servers={} tools={}",
                    self.name,
                    configured_servers,
                    sorted(
                        name
                        for name in deferred_names
                        if getattr(run_tools.get(name), "origin", None) == "mcp"
                    ),
                )

        state.metadata["_refresh_deferred_tool_catalog"] = (
            _refresh_deferred_tool_catalog
        )
        state.metadata["_grant_plugin_mcp_tools"] = _grant_plugin_mcp_tools
        state.metadata["_tool_capabilities"] = {
            name: tuple(sorted(tool.capabilities)) for name, tool in run_tools.items()
        }

        # Me seed last_prompt_tokens from checkpointer so SummarizationHook
        # fires on session resume without call-site workaround
        if checkpointer is not None and ctx.session_id is not None:
            checkpointer.seed_state(ctx.session_id, state)  # no-op by default

        self.stats.status = "running"
        run_start = time.monotonic()
        logger.info(
            "agent_run_start agent={} message_count={} tools={} tools_visible={} session={}",
            self.name,
            len(messages),
            len(run_tools),
            len(tool_defs),
            ctx.session_id,
        )

        for hook in combined_hooks:
            await hook.before_agent(ctx, state)

        last_assistant_msg: AssistantMessage | None = None

        # Build the hook chain around the executor, then put the deferred gate
        # outside it. A hidden tool named directly by the model must not reach
        # permission prompts, telemetry, or plugin hooks before activation.
        hooked_tool_chain: ToolCallHandler = build_tool_chain(
            combined_hooks,
            make_tool_executor(run_tools, self.name, deferred_names),
        )

        async def tool_chain(
            tool_ctx: RunContext,
            tool_state: AgentState,
            tool_call,
        ) -> str:
            tool_name = tool_call.function.name
            activated = tool_state.metadata.get("activated_deferred_tools") or ()
            if tool_name in deferred_names and tool_name not in activated:
                logger.info(
                    "tool_call_blocked_before_hooks agent={} tool={}",
                    self.name,
                    tool_name,
                )
                return (
                    f"'{tool_name}' is not yet available — call "
                    f"load_tool(tool_name='{tool_name}') first, then "
                    f"call '{tool_name}' again on your next turn."
                )
            return await hooked_tool_chain(tool_ctx, tool_state, tool_call)

        iteration = 0
        total_tokens = 0
        # Streaming returns ``last_usage`` per call; the loop tracks the latest
        # value so it can fold it into per-iteration logging and ``state.usage``.
        last_usage: Usage | None = None
        empty_after_tool_continuations = 0
        max_empty_after_tool_continuations = 3
        provider_resume_attempts = 0
        last_activated_deferred: frozenset[str] = frozenset()

        while iteration < self.max_iterations:
            # Top-of-iteration interrupt check.  Without this, an interrupt
            # that fires between iterations (e.g. while ``after_model``
            # hooks were running, or between tool dispatch and the next
            # LLM call) wouldn't be observed until the next chunk arrived
            # from the provider — which can be many seconds with models
            # that have long thinking phases.
            if interrupt_event is not None and interrupt_event.is_set():
                logger.info(
                    "agent_iteration_interrupted agent={} iteration={}",
                    self.name,
                    iteration,
                )
                break
            iteration += 1
            iter_start = time.monotonic()
            logger.debug(
                "agent_iteration agent={} iteration={}/{} messages={}",
                self.name,
                iteration,
                self.max_iterations,
                len(messages),
            )

            # Refresh tool_defs before anything this iteration reads it (hooks
            # included) so a load_tool activation from the previous iteration's
            # tool execution is visible starting this model call. Skipped
            # entirely when the activated set hasn't changed — the common case
            # for every iteration where the agent never calls load_tool — so
            # this never redoes the (potentially non-trivial) work in
            # ``static_tool_defs``, only the small activated-tools lookup.
            if deferred_names:
                activated = frozenset(
                    state.metadata.get("activated_deferred_tools") or ()
                )
                if activated != last_activated_deferred:
                    tool_defs = _compute_tool_defs(activated)
                    state.tool_defs = tool_defs
                    last_activated_deferred = activated

            # Build per-iteration ModelRequest — immutable view of what LLM sees.
            # messages_for_llm excludes SystemMessage + excluded messages.
            model_request = ModelRequest(
                messages=tuple(state.messages_for_llm),
                system_prompt=state.system_prompt,
                context=state.context,
            )

            # before_model: hooks may return a modified ModelRequest.
            # SummarizationHook mutates state.messages and returns updated messages
            # in the new ModelRequest — so the current LLM call sees the summary.
            for hook in combined_hooks:
                updated = await hook.before_model(ctx, state, model_request)
                if updated is not None:
                    model_request = updated

            observation_checkpoint = _observation_checkpoint_prompt(state)
            if observation_checkpoint:
                model_request = model_request.override(
                    messages=(
                        *model_request.messages,
                        HumanMessage(
                            content=observation_checkpoint,
                            extra={"system_generated": True},
                        ),
                    )
                )

            # Replaying an identical post-tool request makes deterministic
            # empty completions repeat forever. Add an ephemeral user nudge to
            # the next model request so it must either continue with tools or
            # produce a final summary. It deliberately does not enter
            # ``state.messages`` and therefore is never persisted or rendered.
            if empty_after_tool_continuations:
                model_request = model_request.override(
                    messages=(
                        *model_request.messages,
                        HumanMessage(
                            content=EMPTY_AFTER_TOOL_RECOVERY_PROMPT,
                            extra={"system_generated": True},
                        ),
                    )
                )

            # Me sync after before_model — persists summarization changes
            await self._sync(checkpointer, ctx, state)

            # Build wrap_model_call chain and invoke it
            iter_usage_holder: list[Usage | None] = [None]
            before_model_only = state.metadata.get("stop_after_before_model") is True

            async def _stream(req: ModelRequest) -> AssistantMessage:
                if before_model_only:
                    return AssistantMessage(content=None)
                msg, usage = await stream_and_assemble(
                    req=req,
                    ctx=ctx,
                    state=state,
                    hooks=combined_hooks,
                    interrupt_event=interrupt_event,
                    tool_defs=tool_defs,
                    primary_provider=active_provider,
                    primary_label=active_model_id or "primary",
                    fallback_provider=self.fallback_provider,
                    fallback_label=self.fallback_model_id or "fallback",
                    agent_name=self.name,
                    agent_id=str(self.id),
                )
                iter_usage_holder[0] = usage
                return msg

            model_chain = build_model_chain(combined_hooks, ctx, state, _stream)
            if before_model_only:
                await model_chain(model_request)
                await self._sync(checkpointer, ctx, state)
                logger.debug(
                    "agent_iteration_done agent={} iteration={} action=before_model_only",
                    self.name,
                    iteration,
                )
                break

            try:
                assistant_msg = await model_chain(model_request)
            except (httpx.ConnectError, httpx.ReadTimeout, TimeoutError) as exc:
                # The provider (and any fallback) exhausted its retry budget on
                # a transient connectivity failure.  Rather than letting this
                # kill the whole turn mid-task — abandoning the tool work
                # already done — resume the same turn a bounded number of
                # times.  The next model call replays the identical message
                # history, so the model continues from exactly where it left
                # off.  Persisted work-so-far is already synced after each
                # prior iteration's tool execution.
                provider_resume_attempts += 1
                if provider_resume_attempts > MAX_PROVIDER_RESUME_ATTEMPTS:
                    logger.error(
                        "agent_provider_resume_exhausted agent={} iteration={} "
                        "attempts={} error={}",
                        self.name,
                        iteration,
                        provider_resume_attempts - 1,
                        type(exc).__name__,
                    )
                    from app.agent.errors import ProviderConnectionError

                    raise ProviderConnectionError(
                        f"Could not reach the LLM provider — exhausted "
                        f"{MAX_PROVIDER_RESUME_ATTEMPTS} resume attempts after a "
                        f"transient connectivity failure ({type(exc).__name__}). "
                        f"Check your network connection and the provider's base URL "
                        f"in Settings → Providers.",
                        error_type=type(exc).__name__,
                        provider=active_model_id or "primary",
                    ) from exc
                delay = PROVIDER_RESUME_BASE_DELAY * provider_resume_attempts
                logger.warning(
                    "agent_provider_resume agent={} iteration={} attempt={}/{} "
                    "error={} delay={:.1f}s",
                    self.name,
                    iteration,
                    provider_resume_attempts,
                    MAX_PROVIDER_RESUME_ATTEMPTS,
                    type(exc).__name__,
                    delay,
                )
                if interrupt_event is not None:
                    try:
                        await asyncio.wait_for(interrupt_event.wait(), timeout=delay)
                        break  # interrupt fired during backoff — stop the turn
                    except TimeoutError:
                        pass
                else:
                    await asyncio.sleep(delay)
                iteration -= 1  # this iteration produced no assistant message
                continue

            # A successful model call clears the transient-failure budget so a
            # later, unrelated hiccup gets the full resume allowance again.
            provider_resume_attempts = 0

            # Convert the legacy model-facing sentinel into runtime-owned
            # metadata before after_model hooks, persistence, or completion
            # logic inspect the response. Streaming providers normally arrive
            # normalized by stream_and_assemble; this also covers hooks that
            # replace it.
            _is_sleep = normalize_sleep_message(assistant_msg)

            tc_list = assistant_msg.tool_calls or []
            last_usage = iter_usage_holder[0]
            effective_model = state.metadata.pop("effective_model", None)
            provider_fallback = state.metadata.pop("provider_fallback", None)
            stream_elapsed = time.monotonic() - iter_start

            logger.debug(
                "llm_response agent={} iteration={} elapsed={:.2f}s "
                "content_len={} reasoning_len={} tool_calls={} tokens={}/{}/{}",
                self.name,
                iteration,
                stream_elapsed,
                len(assistant_msg.content or ""),
                len(assistant_msg.reasoning_content or ""),
                len(tc_list),
                last_usage.prompt_tokens if last_usage else 0,
                last_usage.completion_tokens if last_usage else 0,
                last_usage.total_tokens if last_usage else 0,
            )

            has_assistant_payload = bool(
                _is_sleep
                or (assistant_msg.content and assistant_msg.content.strip())
                or (
                    assistant_msg.reasoning_content
                    and assistant_msg.reasoning_content.strip()
                )
                or tc_list
            )
            previous_was_tool = bool(messages and isinstance(messages[-1], ToolMessage))
            if not has_assistant_payload and previous_was_tool:
                empty_after_tool_continuations += 1
                if empty_after_tool_continuations < max_empty_after_tool_continuations:
                    logger.warning(
                        "agent_empty_after_tool_continue agent={} iteration={} attempt={}/{}",
                        self.name,
                        iteration,
                        empty_after_tool_continuations,
                        max_empty_after_tool_continuations,
                    )
                    continue
                logger.warning(
                    "agent_empty_after_tool_limit agent={} iteration={} attempts={}",
                    self.name,
                    iteration,
                    empty_after_tool_continuations,
                )
                from app.agent.errors import AgentLoopError

                raise AgentLoopError(
                    f"Agent produced {max_empty_after_tool_continuations} consecutive "
                    f"empty responses after tool calls — stopping to avoid a silent loop. "
                    f"Reassign remaining work or retry."
                )
            elif has_assistant_payload:
                empty_after_tool_continuations = 0

            message_extra = dict(assistant_msg.extra or {})
            message_extra["duration_ms"] = round(
                (time.monotonic() - run_start) * 1000, 3
            )
            message_extra["model"] = effective_model or active_model_id
            if provider_fallback:
                message_extra["requested_model"] = active_model_id
                message_extra["provider_fallback"] = provider_fallback

            # Me attach usage to message + state (single dict, shared reference)
            if last_usage:
                usage_dict = usage_to_dict(
                    last_usage, effective_model or active_model_id
                )
                message_extra["usage"] = usage_dict
                total_tokens += last_usage.total_tokens
                state.usage.last_prompt_tokens = last_usage.prompt_tokens
                state.usage.last_completion_tokens = last_usage.completion_tokens
                state.usage.total_tokens = total_tokens
                state.usage.last_usage = usage_dict
                state.metadata["total_tokens"] = total_tokens
                state.metadata["last_usage"] = usage_dict

            turn_usage = current_turn_usage_snapshot()
            if turn_usage is not None:
                message_extra["turn_usage"] = turn_usage

            assistant_msg.extra = message_extra

            messages.append(assistant_msg)
            last_assistant_msg = assistant_msg
            self.stats.messages_count += 1

            for hook in combined_hooks:
                await hook.after_model(ctx, state, assistant_msg)

            # Me sync after after_model — captures assistant message + usage
            await self._sync(checkpointer, ctx, state)

            if not tc_list:
                completion_feedback: list[str] = []
                for hook in combined_hooks:
                    result = hook.before_completion(ctx, state, assistant_msg)
                    feedback = await result if inspect.isawaitable(result) else result
                    if isinstance(feedback, str) and feedback.strip():
                        completion_feedback.append(feedback)
                if completion_feedback:
                    gate_feedback = (
                        "[Completion blocked by verification gate]\n\n"
                        + "\n\n".join(completion_feedback)
                        + "\n\nFix the failures, rerun the required checks, and only "
                        "then provide the final response."
                    )
                    messages.append(
                        HumanMessage(
                            content=gate_feedback,
                            extra={"system_generated": True},
                        )
                    )
                    logger.warning(
                        "agent_completion_blocked agent={} iteration={} gates={}",
                        self.name,
                        iteration,
                        len(completion_feedback),
                    )
                    continue
                logger.debug(
                    "agent_iteration_done agent={} iteration={} action={}",
                    self.name,
                    iteration,
                    "sleep" if _is_sleep else "final_response",
                )
                break

            # Pre-dispatch interrupt check — skip tool execution entirely
            if interrupt_event is not None and interrupt_event.is_set():
                logger.info(
                    "tool_dispatch_skipped_interrupt agent={} count={}",
                    self.name,
                    len(tc_list),
                )
                for tc in tc_list:
                    messages.append(
                        ToolMessage(
                            content="Cancelled by user.",
                            tool_call_id=tc.id,
                            name=tc.function.name,
                        )
                    )
                break

            dispatch_calls, blocked_results = _partition_tool_call_batch(
                tc_list, run_tools
            )
            for tool_call, reason in blocked_results:
                for hook in combined_hooks:
                    await hook.on_tool_blocked(ctx, state, tool_call, reason)
            dispatch_waves = _build_tool_call_waves(dispatch_calls, run_tools)

            logger.debug(
                "tool_dispatch agent={} count={} waves={} tools=[{}]",
                self.name,
                len(dispatch_calls),
                len(dispatch_waves),
                ", ".join(tc.function.name for tc in dispatch_calls),
            )

            result_by_call_id: dict[str, tuple[ToolCall, str] | BaseException] = {
                tool_call.id: (tool_call, message)
                for tool_call, message in blocked_results
            }
            for wave_index, (is_parallel, wave_calls) in enumerate(dispatch_waves):
                coroutines = [
                    self._run_tool(ctx, state, tool_call, tool_chain)
                    for tool_call in wave_calls
                ]
                if is_parallel:
                    wave_results = await gather_or_cancel(
                        coroutines,
                        interrupt_event,
                        wave_calls,
                        self.name,
                    )
                else:
                    wave_results = await run_serially(
                        coroutines,
                        interrupt_event,
                        wave_calls,
                        self.name,
                    )
                result_by_call_id.update(
                    zip(
                        (tool_call.id for tool_call in wave_calls),
                        wave_results,
                        strict=True,
                    )
                )

                if interrupt_event is not None and interrupt_event.is_set():
                    for _, remaining_calls in dispatch_waves[wave_index + 1 :]:
                        for tool_call in remaining_calls:
                            result_by_call_id[tool_call.id] = (
                                tool_call,
                                "Cancelled by user.",
                            )
                    break

            # Model-visible ToolMessages must stay in the exact call order,
            # including calls rejected by batch contracts.  ``ordered_calls``
            # is kept alongside ``results`` so a raised exception (e.g. a
            # permission rejection, which never reaches ``make_tool_executor``
            # and so never gets its own try/except) can still be turned into
            # a ToolMessage instead of silently vanishing from the transcript.
            ordered_calls = [
                tool_call for tool_call in tc_list if tool_call.id in result_by_call_id
            ]
            results = [result_by_call_id[tool_call.id] for tool_call in ordered_calls]

            # Retrieve any multimodal parts stashed by ToolResult-returning tools
            multimodal_parts: dict[str, list[ContentBlock]] = state.metadata.pop(
                "_multimodal_tool_parts", {}
            )
            tool_attachments: dict[str, list[dict[str, str]]] = state.metadata.pop(
                "_tool_attachments", {}
            )
            mcp_apps: dict[str, dict[str, Any]] = state.metadata.pop("_mcp_apps", {})
            tool_result_metadata: dict[str, dict[str, Any]] = state.metadata.pop(
                "_tool_result_metadata", {}
            )

            cancelled = interrupt_event is not None and interrupt_event.is_set()
            tool_durations = state.metadata.pop("_tool_duration_ms", {})
            tool_result_chars = 0
            for call, item in zip(ordered_calls, results, strict=True):
                if isinstance(item, BaseException):
                    logger.error(
                        "tool_gather_error agent={} tool={} tool_call_id={} error={}",
                        self.name,
                        call.function.name,
                        call.id,
                        item,
                    )
                    tc, result = call, f"Error: {sanitize_error(str(item))}"
                else:
                    tc, result = item
                tool_msg = ToolMessage(
                    content=result, tool_call_id=tc.id, name=tc.function.name
                )
                if tc.id in tool_durations:
                    tool_msg.extra = {"duration_ms": tool_durations[tc.id]}
                if tc.id in tool_result_metadata:
                    tool_msg.extra = {
                        **(tool_msg.extra or {}),
                        **tool_result_metadata[tc.id],
                    }
                if tc.id in tool_attachments:
                    if tool_msg.extra is None:
                        tool_msg.extra = {}
                    tool_msg.extra["attachments"] = tool_attachments[tc.id]
                # Attach multimodal parts if the tool returned a ToolResult
                if tc.id in multimodal_parts:
                    tool_msg.parts = multimodal_parts[tc.id]
                if tc.id in mcp_apps:
                    if tool_msg.extra is None:
                        tool_msg.extra = {}
                    tool_msg.extra["mcp_app"] = mcp_apps[tc.id]
                tool_result_chars += len(result or "")
                messages.append(tool_msg)

            # Bump last_prompt_tokens to account for tool results just appended.
            # SummarizationHook reads this value at the START of the next iteration
            # (before_model); without this bump the tool results added after the
            # LLM call are invisible to the threshold check, letting the context
            # grow past the model's context limit before summarization fires.
            # Rough heuristic: ~3 chars per token — code and diffs tokenize
            # denser than prose, and over-counting only makes compaction fire
            # earlier (safe); under-counting can blow past the context limit.
            state.usage.last_prompt_tokens += max(0, tool_result_chars // 3)

            if cancelled:
                break

            # Me sync after tool execution — captures tool results
            await self._sync(checkpointer, ctx, state)

            stop_after_tool = state.metadata.pop("stop_after_tool_call", None)
            if stop_after_tool:
                logger.debug(
                    "agent_iteration_done agent={} iteration={} "
                    "action=stop_after_tool tool={}",
                    self.name,
                    iteration,
                    stop_after_tool,
                )
                break

            # Me sleep + tool calls: tools executed, now exit without another LLM call
            if _is_sleep:
                logger.debug(
                    "agent_iteration_done agent={} iteration={} action=sleep_after_tools",
                    self.name,
                    iteration,
                )
                break

        if last_assistant_msg:
            for hook in combined_hooks:
                await hook.after_agent(ctx, state, last_assistant_msg)
            turn_usage = current_turn_usage_snapshot()
            if turn_usage is not None:
                last_assistant_msg.extra = {
                    **(last_assistant_msg.extra or {}),
                    "turn_usage": turn_usage,
                }

        # Me sync after after_agent — final sync
        await self._sync(checkpointer, ctx, state)

        self.stats.status = "completed"
        self.stats.total_tokens += total_tokens
        self.run_config = None
        run_elapsed = time.monotonic() - run_start
        logger.info(
            "agent_run_done agent={} elapsed={:.2f}s iterations={} "
            "total_messages={} total_tokens={} has_response={}",
            self.name,
            run_elapsed,
            iteration,
            len(messages),
            total_tokens,
            last_assistant_msg is not None,
        )
        return messages

    async def _run_tool(
        self,
        ctx: RunContext,
        state: AgentState,
        tc,
        chain: ToolCallHandler,
    ) -> tuple:
        """Execute a single tool call through the hook chain (semaphore-bounded)."""
        async with self._tool_semaphore:
            result = await chain(ctx, state, tc)
            return tc, result

    @staticmethod
    async def _sync(
        checkpointer: Checkpointer | None,
        ctx: RunContext,
        state: AgentState,
    ) -> None:
        """Call checkpointer.sync() if a checkpointer is configured."""
        if checkpointer is None or ctx.session_id is None:
            return
        try:
            await checkpointer.sync(ctx, state)
        except Exception as exc:
            logger.error(
                "checkpointer_sync_failed session_id={} error={}",
                ctx.session_id,
                exc,
            )
