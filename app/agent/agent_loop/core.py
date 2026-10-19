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
import random
import inspect
import json
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Generic, TypeVar

from loguru import logger

from app.agent.agent_loop.retry import TRANSIENT_TRANSPORT_ERRORS
from app.agent.agent_loop.streaming import stream_and_assemble
from app.agent.agent_loop.tool_dispatch import gather_or_cancel, run_serially
from app.agent.agent_loop.tool_executor import make_tool_executor
from app.agent.usage import usage_to_dict
from app.agent.checkpointer import Checkpointer
from app.agent.errors import ContextOverflowError
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
from app.agent.tools.registry import Tool
from app.agent.turn_usage import current_turn_usage_snapshot

MAX_AGENT_ITERATIONS = 5000
MAX_CONCURRENT_TOOLS = 10
# How many times the loop will re-issue the model call within the same turn
# after the provider (and any fallback) exhausts its own retry budget on a
# transient connectivity failure (timeout, dropped or half-closed connection).
# Without this, such an exhaustion raises straight out of ``run()`` and abandons all
# completed tool work mid-task — the "agent stopped after a tool call" symptom.
MAX_PROVIDER_RESUME_ATTEMPTS = 5
# In-loop provider resume uses bounded exponential backoff with jitter.
PROVIDER_RESUME_BASE_DELAY = 1.0
PROVIDER_RESUME_MAX_DELAY = 12.0
PROVIDER_RESUME_MAX_DURATION_SECONDS = 60.0
PROVIDER_RESUME_JITTER_LOW = 0.8
PROVIDER_RESUME_JITTER_HIGH = 1.2

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
        interrupt_event: asyncio.Event | None = None,
        checkpointer: Checkpointer | None = None,
        llm_provider: LLMProviderBase | None = None,
        model_id: str | None = None,
        final_model_hooks: Sequence[BaseAgentHook] | None = None,
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

        ``checkpointer`` is an optional :class:`~app.agent.checkpointer.Checkpointer`
        that the loop calls at defined sync points to persist state.  When
        provided, ``DatabaseHook`` is not needed — the loop owns persistence.

        ``final_model_hooks`` are runtime-owned terminal model wrappers. They
        run after ordinary and plugin hooks, and are reserved for invariants
        that must be the last request transform before provider serialization
        (for example, a session-level frozen prompt prefix).

        Agent role for plugin ``applies_to`` filtering is read from the
        :mod:`app.agent.plugins.role` contextvar — team callers wrap the
        ``run()`` invocation with :func:`set_role`.
        """
        from app.agent.plugins.role import current_role

        role = current_role()
        self.run_config = config
        plugin_hooks = await self._load_plugin_hooks(role)
        # ``final_model_hooks`` run after plugin hooks. They are reserved for
        # runtime-owned terminal request invariants, such as a frozen session
        # prefix, which must be the last authority before provider serialization.
        combined_hooks = (
            list(self.hooks)
            + list(hooks or [])
            + plugin_hooks
            + list(final_model_hooks or [])
        )
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

        # Every tool is always eager in tool_defs. The definitions are
        # computed once per run in a stable order: some tools (skill) have a
        # callable description factory that does real work (filesystem scans,
        # string building); recomputing this list every iteration would redo
        # that work for nothing on every turn of every team run.
        tool_defs = [t.definition for t in run_tools.values()]

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
        state.metadata["run_id"] = ctx.run_id
        state.metadata["agent_name"] = ctx.agent_name
        # Keep pre-model stages aligned with per-run provider overrides.
        # The value is ephemeral and is never persisted or model-visible.
        state.metadata["_runtime_provider"] = active_provider
        # The catalog-qualified model for this run (``xiaomi:mimo-v2.5``).
        # Streams report the provider's own bare name for the model, which
        # matches no catalog row, so anything pricing a call from the stream
        # alone silently prices it at zero. ``effective_model`` only appears
        # after a provider fallback, so it cannot serve as the baseline.
        if active_model_id:
            state.metadata["active_model"] = active_model_id

        # Surface caller-supplied per-run metadata to tools/hooks.  Used by
        # team leads to pass ``mode`` and ``workspace`` so the schedule tool
        # can derive routing targets without trusting LLM-supplied values.
        if config is not None and config.metadata:
            for key, value in config.metadata.items():
                state.metadata.setdefault(key, value)

        def _merge_dynamic_tools(candidates: list[Tool]) -> tuple[str, ...]:
            """Add newly-available runtime MCP tools to this run's eager set.

            Only names this run does not already expose are appended, keeping
            the computed-once tool_defs list in a stable order.
            """

            added: list[str] = []
            side_chat_session = bool(state.metadata.get("side_chat_session"))
            for run_tool in candidates:
                if excluded_tools and run_tool.name in excluded_tools:
                    continue
                if side_chat_session and not getattr(run_tool, "read_only", False):
                    continue
                if run_tool.name in run_tools:
                    continue
                run_tools[run_tool.name] = run_tool
                # Rebind instead of mutating so every already-sent model call
                # keeps the exact tool_defs snapshot it was given.
                state.tool_defs = [*state.tool_defs, run_tool.definition]
                added.append(run_tool.name)
            if added:
                state.tool_names = sorted(run_tools)
            return tuple(added)

        def _grant_plugin_mcp_tools(installation_id: str) -> tuple[str, ...]:
            """Grant tools belonging to the plugin Skill being activated.

            Skill activation is an explicit grant: the plugin's MCP tools join
            the eager tool set and are callable from the next model call.
            """

            from app.plugin_platform.runtime import plugin_mcp_runtime

            state.metadata.setdefault("plugin_mcp_grants", set()).add(installation_id)
            tools = plugin_mcp_runtime.get_tools_for_installation(installation_id)
            added = _merge_dynamic_tools(tools)
            if added:
                logger.debug(
                    "plugin_skill_mcp_tools_granted agent={} installation={} tools={}",
                    self.name,
                    installation_id,
                    list(added),
                )
            return added

        state.metadata["_grant_plugin_mcp_tools"] = _grant_plugin_mcp_tools

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

        # Build the hook chain around the executor.
        tool_chain: ToolCallHandler = build_tool_chain(
            combined_hooks,
            make_tool_executor(run_tools, self.name),
        )

        iteration = 0
        total_tokens = 0
        # Streaming returns ``last_usage`` per call; the loop tracks the latest
        # value so it can fold it into per-iteration logging and ``state.usage``.
        last_usage: Usage | None = None
        empty_after_tool_continuations = 0
        max_empty_after_tool_continuations = 3
        provider_resume_attempts = 0
        provider_resume_started_at: float | None = None
        # Set while the next model call is the one retry after a context
        # overflow; a second overflow before any call succeeds is surfaced.
        overflow_compaction_pending = False

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
            # Terminal hooks may expose a preflight method so prompt-producing
            # hooks can skip rebuilding a persisted/frozen system prefix before
            # the terminal wrapper gets its final authority.
            for hook in final_model_hooks or ():
                preflight = getattr(hook, "preflight_before_model", None)
                if preflight is not None:
                    await preflight(ctx, state, model_request)
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
                    tool_defs=state.tool_defs,
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

            model_attempt_started_at = time.monotonic()
            usage_before = current_turn_usage_snapshot() or {}
            resume_timeout = None
            if provider_resume_started_at is not None:
                resume_remaining = PROVIDER_RESUME_MAX_DURATION_SECONDS - (
                    time.monotonic() - provider_resume_started_at
                )
                resume_timeout = asyncio.timeout(max(0.0, resume_remaining))

            try:
                if resume_timeout is None:
                    assistant_msg = await model_chain(model_request)
                else:
                    async with resume_timeout:
                        assistant_msg = await model_chain(model_request)
            except ContextOverflowError as exc:
                # The prompt outgrew the window before the usage-based
                # threshold caught it (a large tool result, a stale
                # threshold, or a catalogue window larger than the real one).
                # Force one compaction and replay the call; the summarisation
                # hook's before_model runs again at the top of the loop.
                if overflow_compaction_pending:
                    state.metadata.pop("force_summarization", None)
                    raise
                overflow_compaction_pending = True
                state.metadata["force_summarization"] = True
                logger.warning(
                    "agent_context_overflow_compact agent={} iteration={} status={}",
                    self.name,
                    iteration,
                    exc.status_code,
                )
                iteration -= 1  # this iteration produced no assistant message
                continue
            except Exception as exc:
                resume_timed_out = (
                    resume_timeout is not None and resume_timeout.expired()
                )
                if (
                    not isinstance(exc, TRANSIENT_TRANSPORT_ERRORS)
                    and not resume_timed_out
                ):
                    raise

                # Resume a failed provider call within one wall-clock budget.
                # This keeps a stream that stalls during a resumed attempt from
                # restarting the full retry allowance indefinitely.
                now = time.monotonic()
                if provider_resume_started_at is None:
                    provider_resume_started_at = now
                resume_elapsed = now - provider_resume_started_at
                resume_remaining = PROVIDER_RESUME_MAX_DURATION_SECONDS - resume_elapsed
                provider_resume_attempts += 1
                exhausted = (
                    provider_resume_attempts > MAX_PROVIDER_RESUME_ATTEMPTS
                    or resume_remaining <= 0
                    or resume_timed_out
                )
                exponential_delay = min(
                    PROVIDER_RESUME_MAX_DELAY,
                    PROVIDER_RESUME_BASE_DELAY * (2 ** (provider_resume_attempts - 1)),
                )
                delay = (
                    min(
                        exponential_delay
                        * random.uniform(
                            PROVIDER_RESUME_JITTER_LOW,
                            PROVIDER_RESUME_JITTER_HIGH,
                        ),
                        max(0.0, resume_remaining),
                    )
                    if not exhausted
                    else 0.0
                )
                usage_after = current_turn_usage_snapshot() or {}
                usage_delta = {
                    key: value - usage_before.get(key, 0)
                    for key, value in usage_after.items()
                    if isinstance(value, (int, float))
                    and isinstance(usage_before.get(key, 0), (int, float))
                }
                logger.warning(
                    "agent_provider_resume_attempt agent={} iteration={} "
                    "attempt={}/{} error={} call_elapsed={:.2f}s "
                    "resume_elapsed={:.2f}s remaining={:.2f}s delay={:.2f}s "
                    "turn_usage_delta={}",
                    self.name,
                    iteration,
                    provider_resume_attempts,
                    MAX_PROVIDER_RESUME_ATTEMPTS,
                    type(exc).__name__,
                    now - model_attempt_started_at,
                    resume_elapsed,
                    max(0.0, resume_remaining),
                    delay,
                    usage_delta,
                )
                if exhausted:
                    reason = (
                        "duration"
                        if resume_remaining <= 0 or resume_timed_out
                        else "attempt_limit"
                    )
                    logger.error(
                        "agent_provider_resume_exhausted agent={} iteration={} "
                        "attempts={} elapsed={:.2f}s reason={} error={}",
                        self.name,
                        iteration,
                        max(0, provider_resume_attempts - 1),
                        resume_elapsed,
                        reason,
                        type(exc).__name__,
                    )
                    from app.agent.errors import ProviderConnectionError

                    raise ProviderConnectionError(
                        f"Could not reach the LLM provider — exhausted "
                        f"{max(0, provider_resume_attempts - 1)} resume attempts "
                        f"within a {PROVIDER_RESUME_MAX_DURATION_SECONDS:.0f}s "
                        f"retry budget after a transient connectivity failure "
                        f"({type(exc).__name__}). Check your network connection and "
                        f"the provider's base URL in Settings → Providers.",
                        error_type=type(exc).__name__,
                        provider=active_model_id or "primary",
                    ) from exc
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
            provider_resume_started_at = None
            if overflow_compaction_pending:
                overflow_compaction_pending = False
                state.metadata.pop("force_summarization", None)

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
                (assistant_msg.content and assistant_msg.content.strip())
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
                    "agent_iteration_done agent={} iteration={} action=final_response",
                    self.name,
                    iteration,
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
            # including calls rejected by batch contracts. Paired with the call
            # they came from so a failure can still be reported against it.
            results = [
                (tool_call, result_by_call_id[tool_call.id])
                for tool_call in tc_list
                if tool_call.id in result_by_call_id
            ]

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
            permission_refused = False
            for source_call, item in results:
                if isinstance(item, BaseException):
                    logger.error("tool_gather_error error={}", item)
                    if isinstance(item, PermissionError):
                        # Tell the model, not just the log.
                        #
                        # A raising tool used to leave its call with no
                        # ToolMessage at all, so the model saw an unanswered
                        # tool call and did the obvious thing: called again.
                        # That is what turned one rejection into an endless
                        # round of identical approval prompts. It also left
                        # the provider with a dangling tool call, which the
                        # OpenAI sanitiser then had to strip.
                        messages.append(
                            ToolMessage(
                                content=str(item),
                                tool_call_id=source_call.id,
                                name=source_call.function.name,
                            )
                        )
                        permission_refused = True
                    continue
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

            if permission_refused:
                # Refusing is the user taking the wheel, so hand it to them
                # rather than looping the model against a wall it cannot get
                # past. Without this the turn kept iterating on the refusal
                # for as long as the model felt like retrying, at full token
                # cost and with nothing to show for it.
                logger.info(
                    "agent_iteration_done agent={} iteration={} "
                    "action=permission_refused",
                    self.name,
                    iteration,
                )
                break

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

        # Turn-end auto-release: if this turn opened a Chrome tab-group, tear it
        # down (tabs + overlay + badge). Best-effort; manual toggle still works.
        try:
            from app.services.webbridge_service import webbridge_manager

            _turn_session = (
                config.session_id if config is not None else None
            ) or getattr(ctx, "session_id", None)
            await webbridge_manager.release_browsing(_turn_session)
        except Exception:  # pragma: no cover - teardown must never break a turn
            logger.debug("webbridge_turn_release_failed", exc_info=True)

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
