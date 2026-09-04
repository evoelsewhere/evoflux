"""Team member classes — TeamMemberBase, TeamLead, TeamMember.

TeamMemberBase holds the shared worker infrastructure (activation, inbox, history).
TeamLead and TeamMember subclass it with role-specific behaviour:
- TeamLead: no safety-net, skips user-only inbox persistence, owns lead protocol
- TeamMember: safety-net auto-reply, member protocol

Agents do **not** run persistent background loops.  Instead, they are
*activated on demand*: when a message arrives in their mailbox the team calls
``_maybe_activate()`` which spawns a single ``asyncio.Task`` that drains the
inbox, calls ``agent.run()``, and returns to ``idle`` state.

Streaming is handled by StreamPublisherHook, which pushes every LLM delta
directly to the shared in-memory stream store (keyed by the team lead's session_id).
The frontend subscribes to GET /team/{lead_session_id}/stream and receives a
unified event feed tagged by agent name.
"""

from __future__ import annotations

import abc
import asyncio
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from loguru import logger
from sqlmodel import col, select

from app.agent.agent_loop import Agent
from app.uuid7 import uuid7
from app.agent.execution_policy import resolve_execution_policy
from app.agent.checkpointer import SQLiteCheckpointer
from app.agent.drift import detect_drift, stamp_agent_files
from app.agent.hooks.cache_boundary import CacheBoundaryHook
from app.agent.hooks.code_navigation_telemetry import CodeNavigationTelemetryHook
from app.agent.hooks.continuation import ContinuationHook
from app.agent.hooks.folder_context import FolderContextHook
from app.agent.hooks.goal import GoalContextHook, GoalUsageHook
from app.agent.hooks.dynamic_prompt import inject_current_date
from app.agent.hooks.memory_context import (
    MemoryContextHook,
    default_memory_context_hook,
)
from app.agent.hooks.memory_flush import build_memory_flush_hook
from app.agent.hooks.pipeline import HookPipeline, HookStage
from app.agent.hooks.wiki_injection import default_wiki_injection_hook
from app.agent.hooks.workspace_instructions import WorkspaceInstructionsHook
from app.agent.hooks.post_edit_diagnostics import PostEditDiagnosticsHook
from app.agent.hooks.problem_capture import ProblemCaptureHook
from app.agent.verification import CompletionVerificationHook
from app.agent.hooks.otel import OpenTelemetryHook
from app.agent.hooks.conductor_telemetry import ConductorTelemetryHook
from app.conductor.constants.telemetry import CONDUCTOR_TELEMETRY_HOOK_NAME
from app.agent.hooks.stream_publisher import StreamPublisherHook
from app.agent.hooks.skill_catalog import SkillCatalogFinalizerHook
from app.agent.hooks.summarization import build_team_summarization_hook
from app.agent.hooks.title_generation import build_title_generation_hook
from app.agent.hooks.easd_context import EasdContextHook
from app.agent.hooks.memory_extraction import build_memory_extraction_hook
from app.agent.lifecycle import is_sleep_message
from app.agent.mode.team.hooks.queued_injection import QueuedMessageInjectionHook
from app.agent.mode.team.hooks.team_inbox import TeamInboxHook
from app.agent.mode.team.hooks.team_prompt import AgentTeamProtocolHook
from app.agent.hooks.tool_result_offload import ToolResultOffloadHook
from app.agent.hooks.tool_context_projection import (
    build_tool_context_projection_hook,
)
from app.agent.mode.team.shared_state import format_state_snapshot
from app.agent.mode.team.tier_policy import (
    NON_WEBBRIDGE_SESSION_DENIED_TOOLS,
    SIDE_CHAT_SESSION_TAG,
    deferred_tools_for_run,
    denied_tools_for_tier,
    resolve_member_tier,
    side_chat_session_excluded_tools,
    webbridge_session_excluded_tools,
)
from app.webbridge_tags import WEBBRIDGE_SESSION_TAG
from app.agent.plugins.role import reset_role, set_role
from app.agent.sandbox import SandboxConfig, _sandbox_ctx, set_sandbox
from app.core.paths import session_workspace_dir
from app.agent.permission import (
    Mode,
    PermissionService,
    reset_permission_service,
    set_permission_service,
)
from app.agent.plan import (
    PlanModeService,
    reset_plan_mode_service,
    set_plan_mode_service,
)
from app.agent.ask_user import (
    AskUserService,
    reset_ask_user_service,
    set_ask_user_service,
)
from app.agent.schemas.agent import RunConfig
from app.agent.schemas.chat import ChatMessage, HumanMessage
from app.agent.turn_usage import begin_turn_usage, end_turn_usage
from app.agent.mode.team.mailbox import Message
from app.core.db import DbFactory, resolve_db_factory
from app.models.chat import ChatSession, SessionMessage
from app.models.team import DelegationTask
from app.agent.providers.model_metadata import (
    get_effective_model_thinking,
    get_model_mode,
)
from app.agent.providers.thinking import honoured_levels_for
from app.agent.providers.model_discovery import ensure_runtime_model_metadata
from app.services.chat_service import get_messages_for_llm, save_message

MAX_OPEN_TASK_NUDGES = 3
MAX_LEAD_WAIT_NUDGES = 3
_MAX_RATE_LIMIT_RETRIES = 3
_RATE_LIMIT_BASE_DELAY = 5  # seconds

if TYPE_CHECKING:
    from app.agent.mode.team.mailbox import TeamMailbox
    from app.agent.mode.team.team import AgentTeam
    from app.agent.providers.base import LLMProviderBase


def _task_scoped_history(
    history: list[ChatMessage], task_id: str | None
) -> list[ChatMessage]:
    """Project a member's durable history onto one delegation contract.

    The database remains a complete audit trail. Only the provider input is
    narrowed: task-bearing user messages establish segment ownership and all
    messages in unrelated task segments are omitted. Reopened attempts retain
    their earlier task segments while intervening assignments stay excluded.
    """
    if task_id is None:
        return history

    scoped: list[ChatMessage] = []
    active_segment: str | None = None
    found = False
    for message in history:
        extra = message.extra or {}
        if isinstance(message, HumanMessage) and extra.get("kind") in {
            "delegation",
            "rejection",
        }:
            marker = extra.get("task_id")
            if isinstance(marker, str) and marker:
                active_segment = marker
                found = found or marker == task_id
        if active_segment == task_id:
            scoped.append(message)
    return scoped if found else history


# -- Protocol prompt blocks (shared by build_protocol) -------------------------

LEAD_MESSAGE_FORMAT = """\
## Message format
- `[name]: content` — coordination from a teammate; typed messages add `[question|answer|context|status id=…]` after the prefix
- `[name]  FINAL HANDOFF:` — structured deliverable from a teammate via `team_handoff` (contains Summary, Findings, Evidence, Confidence, Next actions)
- `[user]: content` — message from the user"""

MEMBER_MESSAGE_FORMAT = """\
## Message format
- `[{lead_name}]: content` — message from the team lead
- `[{lead_name}] ● TASK DELEGATION:` — structured task from the lead via `team_delegate` (contains Task ID, Goal, Expected output, Constraints, Context)
- `[{lead_name}] ❌ REJECTED — REWORK NEEDED:` — structured rejection via `team_reject` (contains Reason, Issues, Suggestions)
- `[name]: content` — coordination from a teammate; typed messages add `[question|answer|context|status id=…]` after the prefix
- `[name]  FINAL HANDOFF:` — structured deliverable received via `team_handoff`"""

LEAD_COMMUNICATION_RULES = """\
## Communication protocol
- You are working for the **user** — a real person. Everything the team does is to help them.
- Plain text output is visible to the user. Use it only for your final response, or for one brief progress note after delegation.
- **Right-size delegation.** Handle trivia and one- or two-step work yourself. Delegate only for strong role fit, parallel independent streams, noisy context isolation, or a sustained multi-step workstream; prefer reusing a relevant live member.
{{ROUTING_GUIDE}}
- **Roster management.** Members are spawned on demand, and interactive spawn waits for user confirmation of model and thinking effort. Before parallel routing or reusing a possibly busy member, call `team_manage(action='status')` to inspect live state, active Task ID, and queue depth. A bare-blueprint `team_delegate` atomically spawns or reuses an instance; if it reports `Queued behind active work`, accept the queue or intentionally spawn another instance when work must overlap.
- **Coordination.** Use `team_delegate` for structured assignments, `team_message` for quick questions/answers/status, `team_handoff` for deliverables, and `team_state` for durable shared facts. A delegation's durable Task ID must be preserved through `depends_on`, handoff, rejection, and rework. Never create a task through `team_message`; do not answer the user until every assigned member has a final handoff.
- **Waiting on a member? Respond with exactly `<sleep>`** — just the token, no tool calls and no plain text. After delegating you may send one brief "work is underway" note (see workflow step 3), but every wake after that where you're still waiting on outstanding delegations and have nothing new to verify or synthesise — no partial answer, no "here's what I have so far," no guessed conclusion — must be exactly `<sleep>`. Answering on your own before a member reports back defeats the delegation and shows the user an answer the team hasn't actually produced yet; your next real response after their handoff arrives is the answer.
- **Choose workspace isolation.** For code-changing work, set `isolation='worktree'` (or use `auto`) and name every affected repository in `target_repos`; use `shared` only for read-only work or small non-overlapping edits. The runtime gives each recipient its own branch/worktree set. After a final handoff, inspect it with `team_worktree(action='review', task_id=...)`, then explicitly `merge`, `discard`, or `team_reject`. Dependencies do not start until isolated work is merged. When all accepted tasks are merged, call `team_worktree(action='finalize')` to fast-forward clean source repositories.
- Member capabilities come from their blueprint/root configuration at spawn time. If a member lacks a required capability, use an appropriately configured blueprint or update durable settings rather than mutating a live member.
- Always format your responses in **Markdown**. No emoji."""

LEAD_PROTOCOL = """\
## Lead workflow
1. Frame the request. When a genuinely ambiguous choice would waste substantial work, call the blocking `ask_user` tool—not a plain-text question—and batch every needed question once; infer cheap, reversible details. Assess scope and use todo tiers consistently: `trivial` stays with you, `simple` normally has one straightforward owner, `multi_step` has one owner across several steps, and `complex` may need coordinated parallel members.
2. **Load specialized workflows only on demand.** The visible tool schemas and your role instructions are sufficient for ordinary work. Use the `skill` tool progressively only when the task needs a specialized artifact or operational workflow; do not list or load skills as a generic first step.
3. When delegating:
   - For multi-step work, create a todo plan first with first-class `dependencies`. Leave a member todo unassigned until its owner is live; once `team_delegate` returns a concrete handle, set `assigned_to` to that handle, never a bare blueprint or group expression. Do not spawn, delegate, or message owners of blocked tasks until their dependencies are complete.
   - Use the routing guide and `team_delegate(to=['<handle>'], goal=..., expected_output=..., constraints=[...])`; assign independent streams in parallel and keep serialized work queued intentionally.
   - **Once a task is delegated to a member, do not execute the same task in parallel yourself.** Stay in coordination/verification mode unless you explicitly reclaim or cancel the member task first.
   - For dependent workflows, keep a **peer handoff chain** and pass prerequisite delegation UUIDs in downstream `depends_on`; the runtime dispatches only after every dependency has a final handoff.
   - Do not make yourself the default relay for member outputs. Use the lead as the synthesizer/final verifier, not as a message bus between members.
4. When members report back:
   - Read `team_handoff` fields (`summary`, `findings`, `evidence`, `confidence`, `next_actions`) directly; `status: "partial"` is not complete, so wait for `"final"`.
   - **BE CRITICAL — do not rubber-stamp, but verify proportionately.** Your job is quality control, not duplicating the member's entire investigation. For every handoff:
     - Cross-check the output against the original `expected_output` from your delegation. Does it ACTUALLY satisfy the spec, or does it just claim to?
     - Look for: missing edge cases, untested paths, unsupported claims, shallow research (only 1-2 sources), copy-paste without adaptation.
     - If confidence is self-reported > 0.8 but evidence is sparse, that's a red flag — challenge it.
   - **Use the strongest existing evidence first.** A passing machine-generated completion contract or specific, relevant verification record does not need to be rerun merely for duplication. If evidence is absent, weak, contradictory, or the consequence of error is high, spot-check the highest-risk claim with the cheapest decisive read/command/citation check. For read-only research with exact citations, inspect a disputed or representative citation rather than repeating the whole search. Never redo the member's full investigation or full test suite unless its evidence is insufficient for the user's risk.
   - Use `team_reject` with the same Task ID, concrete `reason`, `issues`, `suggestions`, and severity (`minor`, `major`, or `redo`) for inadequate work. Reject final deliverables sent through `team_message` instead of `team_handoff`.
   - Accept only evidence-backed work, state what you verified, and add the smallest decisive check needed before promising completion.
5. Keep useful members alive for related follow-ups and warm prompt-cache state. Dismiss only instances clearly finished for the session; their history remains restorable."""

WEBBRIDGE_SESSION_PROMPT = """\
## WebBridge session
This is a normal workspace-capable chat with the `webbridge` tool added for the user's real browser. You may read and edit files, run shell commands, use skills, delegate workspace work to team members, and otherwise operate normally. The ONLY way anyone on the team may interact with web pages is `webbridge`; browser_use, web_search, web_fetch, image_search, and browser-automation MCP tools are unavailable. If the extension is not connected, ask the user to connect it via the WebBridge icon in the sidebar."""

SIDE_CHAT_SESSION_PROMPT = """\
## Side Chat session
You are in a side chat with read-only access to the main conversation's recent context (included above, for reference only). You CANNOT modify files, execute commands, delegate to team members, or make any changes — write/edit/shell/python/team coordination tools are unavailable. Answer questions and provide information; if asked to perform an action, explain that side chat is read-only and the user should ask in the main conversation instead."""

DEFERRED_TOOL_PROTOCOL = """\
## Deferred tool activation
The tool schemas visible in this turn are the source of truth for what can be called immediately. Other granted capabilities may be deferred: their schemas stay hidden until activated. If these instructions name a tool that is not visible, search the deferred catalog before concluding that the capability is unavailable.

To use one:
1. `load_tool(query='<capability in plain words>')` — search, or call `load_tool()` with no arguments to list every deferred name available to you.
2. `load_tool(tool_names=['<exact name>', ...])` — activate. Batch everything you expect to need in one call; each activation round costs a turn.
3. Full schemas appear on your **next** turn; call the tool then.

Search matches keywords against short capability summaries, so it is literal: if the first query returns nothing useful, retry with different nouns (a synonym, the file format, the underlying technology) or list everything and pick by name. Do not give up after one miss, and do not report a capability as unavailable without having listed the catalog. Activation never overrides role, tier, or session restrictions — a tool genuinely denied to you will not appear."""

MEMBER_COMMUNICATION_RULES = """\
## Communication protocol
- **Do not use plain text output for responses/results.** Plain text is discarded — every deliverable MUST go through `team_handoff` (structured work output) or `team_message` (quick questions/clarifications).
- **Use `team_handoff` for all substantial deliverables** — research findings, analysis, proposals, completed work. It produces structured artifacts (summary, findings, evidence, confidence, next_actions) that recipients can act on without re-parsing. Use `team_message` only for short questions, clarifications, or status queries. Use `team_state` to share persistent key-value data (URLs, config, discoveries) visible to all team members.
- **Talk to peers directly for questions and unsolicited context — you are not limited to the lead.** A task-linked final `team_handoff` must go to the task's delegator so the durable task can complete; the runtime injects its artifact into dependent task briefs automatically. Do not manually relay dependency results that already use `depends_on`.
- Message the lead specifically only when you owe *them* your final deliverable, or you are blocked and need a decision; otherwise prefer peer-to-peer.
- **Idle, waiting, or done? Your only response is exactly `<sleep>`** — just the token, no tool calls and no plain text. Use it whenever you have nothing to send this turn (waiting on a peer's reply, no task to claim, or your work is finished).
- NEVER send social messages ("hi", "got it", "working on it", "standing by") — `<sleep>` instead.
- **Missing a capability?** Follow the deferred-tool activation protocol first. Only when its catalog genuinely lacks the capability, describe **what you're trying to do** in plain language to the lead via `team_message` (e.g. "I need to write files to disk", "I need shadcn component examples") rather than guessing at tool/skill/MCP names the lead would have to decode. The lead grants the capability and you'll see it on your next turn.
- **Verify before you claim.** Read each tool result before reporting. If a tool returned an error, NEVER say the operation succeeded. When you write a file or mutate state, confirm with a cheap follow-up (e.g. `ls` the directory, `read` the file) before telling anyone it's done. **Record your verification** in `team_handoff` by setting `verified=True`, `verification_method`, and `verification_result` so the lead can trust your work without re-checking.
- **Work only in the assigned workspace.** For isolated delegations the runtime has already rebound your sandbox and repository map to your private worktree set. Do not create, merge, delete, or switch Git worktrees/branches yourself. Commit/snapshot and integration are runtime/lead responsibilities.
- **Do thorough work — not minimum viable.** The lead WILL verify your claims and reject sloppy handoffs. Specifically:
  - For research: use 3+ independent sources minimum, cross-check claims, cite everything. One Google search is never enough.
  - For code: read existing code first, match style, run the relevant linter/tests yourself before handing off. "It should work" without running it = rejection.
  - For analysis: show your reasoning chain, not just conclusions. Quantify where possible. "It's better" without numbers = rejection.
  - Never hand off work you haven't verified yourself. The `verified` field in `team_handoff` is REQUIRED for final deliverables — the system will block your handoff if you skip it.
- Always format your output in **Markdown**."""

MEMBER_PROTOCOL = """\
## Member workflow
1. Receive task instructions via `[{lead_name}] ● TASK DELEGATION:` (structured — has Goal, Expected output, Constraints) or `[{lead_name}]: ...` (free-form) or from a peer.
    - **When you receive a structured delegation:** retain its delegation **Task ID** and pass it as `task_id` in every partial/final `team_handoff`. This UUID is distinct from a todo `task_id`. Your deliverable MUST satisfy the stated **Expected output** and respect all **Constraints**. Use the **Goal** as your north star and **Context** as starting knowledge. Do not deviate from the spec — if you believe the spec is wrong or unclear, ask the lead via `team_message` before proceeding.
    - **When you receive a rejection (`❌ REJECTED`):** retain the same delegation **Task ID**, read **Reason** and **Issues** carefully, and address EVERY listed issue. Follow the **Suggestions** — they are actionable fixes, not optional hints. Then re-deliver via `team_handoff(task_id='<same UUID>', ...)` with improvements. Do NOT argue with the rejection or repeat the same output — fix the problems.
2. If the instruction names a todo task, call `todo_manage(actions=[{{"action":"claim","task_id":"..."}}])` before starting. If the claim is blocked, respond `<sleep>` and wait for the dependency owner to finish instead of starting early.
3. **Use skills progressively.** Start from the visible tool schemas and this role contract. List or load a skill only when the task needs a specialized workflow that those surfaces do not already define; never load skills speculatively.
4. Do your work (research, write, calculate, etc.).
5. If you need help or input from any teammate, call `team_message(to=[teammate_name])`, then `<sleep>` — the answer arrives next wake.
6. **Deliver output via `team_handoff`** (not `team_message`) to the task's delegator, always passing the delegation `task_id` shown in the task brief. Use `status: "partial"` for incremental batches and `status: "final"` for the complete deliverable. Fill `findings` with key points, `evidence` with supporting data, and `confidence` with your self-assessed certainty (0.0–1.0). For tasks declared with `depends_on`, the runtime forwards your final artifact to downstream owners.
   - **Verify before you hand off.** If your work mutated state (wrote a file, ran a command, changed config), confirm the result with a cheap follow-up check *before* handing off. Then set `verified=True` with `verification_method` describing how you checked and `verification_result` with what you found. For pure research/analysis with no side-effects, omit verification.
7. When sending to the lead: `team_handoff(to=["{lead_name}"], task_id="<delegation UUID>")` with your **final, complete result** (`status: "final"`) unless the lead explicitly asked for incremental updates.
8. If you have nothing to do: `<sleep>` immediately.

**NEVER write plain text for responses/results; use `team_handoff` for deliverables, `team_message` for questions/clarifications, or return exactly `<sleep>` when waiting or idle.**"""


# -- Helpers -------------------------------------------------------------------


class AlreadyWorkingError(Exception):
    """Raised by :meth:`TeamMemberBase.activate_for_continuation` when the
    target agent is already running a turn.

    Carries the agent name so callers can build a useful error message.
    Caught by :meth:`AgentTeam.handle_continue` and translated to a
    ``ContinuePreconditionError`` (HTTP 409).
    """

    def __init__(self, agent_name: str) -> None:
        super().__init__(
            f"Cannot continue while {agent_name} is working — "
            "wait for the current turn to finish."
        )
        self.agent_name = agent_name


async def _mark_last_assistant_interrupted(
    db_factory: DbFactory, session_id: uuid.UUID
) -> None:
    """Stamp ``extra["interrupted"] = True`` on the most recent assistant row.

    Used by ``_run_activation`` when the active turn was cancelled (user
    pressed Stop, server shutdown, etc.).  Older revisions of this code
    appended a literal ``" [interrupted]"`` string to ``content``; that
    leaked into the next turn's LLM prompt and caused ``/continue`` to
    restart instead of resuming.  The flag now rides on ``extra`` (which is
    excluded from LLM serialisation via ``BaseMessage.extra``'s
    ``Field(exclude=True)``) so the marker is invisible to the LLM but
    still available to the frontend and audit tooling.
    """
    try:
        async with db_factory() as db:
            stmt = (
                select(SessionMessage)
                .where(col(SessionMessage.session_id) == session_id)
                .where(col(SessionMessage.role) == "assistant")
                .order_by(col(SessionMessage.created_at).desc())
                .limit(1)
            )
            result = await db.exec(stmt)
            msg = result.first()
            if msg is not None:
                existing = msg.extra or {}
                msg.extra = {**existing, "interrupted": True}
                db.add(msg)
                await db.commit()
    except Exception as exc:
        logger.warning(
            "mark_interrupted_failed session_id={} error={}", session_id, exc
        )


def _open_task_nudge_content(open_todos: list[dict], lead_name: str) -> str:
    """Build the hidden task-reminder prompt for a member."""
    lines = [
        "[system]: You still have open assigned task(s). Do not stop yet.",
        "",
    ]
    for index, todo in enumerate(open_todos, start=1):
        task_id = todo.get("task_id", "unknown")
        content = todo.get("content", "Untitled task")
        status = todo.get("status", "unknown")
        lines.append(f'{index}. "{content}" ({task_id}, status: {status})')
    lines.extend(
        [
            "",
            "If a task is complete, report the result to the lead using "
            f'`team_message(to=["{lead_name}"])`.',
            "If you are blocked, report the blocker to the lead using `team_message`.",
            "If more work is needed, continue working. If you need to wait, "
            "respond exactly `<sleep>`.",
        ]
    )
    return "\n".join(lines)


def _lead_wait_nudge_content(
    pending: list[str], task_ids: list[str] | None = None
) -> str:
    """Build the hidden wait-reminder prompt for a lead that answered early."""
    names = ", ".join(pending)
    task_line = (
        f"\nOutstanding delegation task IDs: {', '.join(task_ids)}." if task_ids else ""
    )
    return (
        "[system]: You just responded to the user, but you are still waiting "
        f"on a team_handoff from: {names}. Answering on your own before they "
        "report back is not the team's real answer — it shows the user a "
        f"conclusion the team hasn't actually produced yet.{task_line}\n\n"
        "Do not repeat, extend, or build on what you just said. Respond with "
        f"exactly `<sleep>` now and wait. Once {names} report back via "
        "`team_handoff`, synthesise your actual final response then."
    )


# =============================================================================
# TeamMemberBase — shared worker infrastructure
# =============================================================================


class TeamMemberBase(abc.ABC):
    """Base class for team agents.  Owns on-demand activation, inbox, and history.

    Agents do **not** run a persistent background loop.  When a message arrives
    in the mailbox, ``_maybe_activate()`` is called.  If the agent is already
    working the message just queues; otherwise a one-shot ``_run_activation()``
    task is spawned to drain the inbox and call ``agent.run()``.

    Subclasses implement role-specific hooks:
    - ``_on_wake``: called after draining inbox, before processing
    - ``_on_turn_success``: called after _handle_messages succeeds
    - ``_on_turn_error``: called when _handle_messages raises
    - ``_on_turn_finally``: always called in finally block
    - ``build_protocol``: assembles role-specific system prompt protocol
    - ``_skip_inbox_persistence``: whether to skip persisting certain inbox messages
    """

    def __init__(
        self,
        agent: Agent,
        *,
        session_id: str | None = None,
        db_factory: DbFactory | None = None,
    ) -> None:
        self.name = agent.name
        self.agent = agent
        self.session_id: str = session_id or str(uuid7())
        self.db_factory = db_factory

        self.state: Literal["idle", "working", "error"] = "idle"
        self._cancel_event = asyncio.Event()
        self._active_task: asyncio.Task | None = None

        # Drift flag set at end-of-turn; next turn rebuilds the agent.
        self._config_dirty: bool = False

        # Track tokens across all turns
        self.usage: dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cached_tokens": 0,
            "cache_write_tokens": 0,
        }
        # Session-level runtime selection can differ from the blueprint model.
        # Roster introspection uses these fields so routing decisions reflect
        # the model the member will actually execute with.
        self.runtime_model_id: str | None = None
        self.runtime_thinking_level: str | None = None

        # Bound at register() time
        self._team: AgentTeam | None = None
        self._mailbox: TeamMailbox | None = None

        # Rate-limit retry state
        self._rate_limit_retry_count: int = 0
        self._rate_limit_retry_task: asyncio.Task | None = None
        self._open_task_nudge_counts: dict[str, int] = {}
        self._lead_wait_nudge_counts: dict[str, int] = {}
        # id of the last SessionMessage row a nudge was already sent for —
        # guards against re-nudging the same stopping point on every idle
        # check; a fresh nudge requires the member to have taken a new turn.
        self._last_open_task_nudge_message_id: str | None = None
        # Concrete durable task currently owning this member's model turn.
        # Other delegations remain queued so unrelated contracts never share
        # one reasoning context.
        self._active_delegation_task_id: str | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def register(self, team: "AgentTeam") -> None:
        """Register this member with the team. Called by AgentTeam.start().

        Registers the mailbox inbox but does **not** spawn any background task.
        The agent becomes ``idle`` and will be activated on demand when a
        message arrives.
        """
        self._team = team
        self._mailbox = team.mailbox
        self._mailbox.register(self.name)

        self.state = "idle"
        logger.debug(
            "team_member_registered name={} session_id={}", self.name, self.session_id
        )

    async def _ensure_db_session(
        self,
        title: str | None = None,
        mode: str = "work",
        workspace: str | None = None,
        project_id: uuid.UUID | None = None,
    ) -> None:
        """Ensure a DB chat session row exists for self.session_id."""
        db_factory = resolve_db_factory(self.db_factory)
        session_uuid = uuid.UUID(self.session_id)
        try:
            async with db_factory() as db:
                existing = await db.get(ChatSession, session_uuid)
                if existing is None:
                    row = ChatSession(
                        id=session_uuid,
                        title=title or f"Team {self._role_label}: {self.name}",
                        agent_name=self.name,
                        mode=mode,
                        workspace=workspace,
                        project_id=project_id,
                        tags=sorted(self._team.session_tags) or None
                        if self._team
                        else None,
                    )
                    db.add(row)
                    await db.commit()
                    logger.info(
                        "team_member_session_created name={} session_id={}",
                        self.name,
                        self.session_id,
                    )
                elif not existing.title or (
                    self._role_label == "lead" and existing.agent_name is None
                ):
                    if not existing.title:
                        existing.title = (
                            title or f"Team {self._role_label}: {self.name}"
                        )
                        existing.mode = mode
                        existing.workspace = workspace
                        if project_id is not None:
                            existing.project_id = project_id
                    if self._role_label == "lead" and existing.agent_name is None:
                        existing.agent_name = self.name
                    db.add(existing)
                    await db.commit()
                    logger.info(
                        "team_member_session_title_set name={} session_id={} title={}",
                        self.name,
                        self.session_id,
                        existing.title,
                    )
        except Exception as e:
            logger.warning(
                "team_member_session_ensure_failed name={} error={}", self.name, e
            )

    async def stop(self) -> None:
        """Gracefully shut down: cancel any active task and deregister."""
        # Cancel any pending rate-limit retry
        if (
            self._rate_limit_retry_task is not None
            and not self._rate_limit_retry_task.done()
        ):
            self._rate_limit_retry_task.cancel()
            try:
                await asyncio.wait_for(
                    asyncio.shield(self._rate_limit_retry_task), timeout=5.0
                )
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
            self._rate_limit_retry_task = None

        if self._active_task is not None and not self._active_task.done():
            self._cancel_event.set()
            self._active_task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(self._active_task), timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
            self._active_task = None

        if self._mailbox and self.name in self._mailbox.registered_agents:
            self._mailbox.deregister(self.name)

        self.state = "idle"
        logger.debug("team_member_stopped name={}", self.name)

    def interrupt(self) -> None:
        """Request cancellation of the current activation without deregistering."""
        self._cancel_event.set()

    # ------------------------------------------------------------------
    # On-demand activation
    # ------------------------------------------------------------------

    def _maybe_activate(self) -> None:
        """Spawn an activation task if the agent is not already working.

        Called by the team's on_message callback when a message arrives.
        If the agent is already working, the message is in the queue and
        ``TeamInboxHook`` will inject it before the next LLM call.
        """
        if self.state == "working":
            return  # already active — inbox hook will drain the new message

        # Me: set state synchronously before create_task so that any
        # _try_emit_done() call that follows in the same coroutine sees
        # "working" and does not fire a premature done event.
        self.state = "working"
        self._active_task = asyncio.create_task(
            self._run_activation(), name=f"activate:{self.name}"
        )

    def _maybe_activate_for_rate_limit_retry(self) -> None:
        """Spawn an activation task that resumes after a rate-limit delay.

        Skips inbox drain/persist/SSE — the original messages are already
        in the DB from the first (failed) activation.  Used exclusively by
        :meth:`_delayed_rate_limit_retry`.
        """
        if self.state == "working":
            return
        self.state = "working"
        self._active_task = asyncio.create_task(
            self._run_activation(is_rate_limit_retry=True),
            name=f"rate-limit-retry:{self.name}",
        )

    async def _delayed_rate_limit_retry(self, delay: float) -> None:
        """Sleep for *delay* seconds, then clear the retry-task handle and re-activate.

        The handle must be cleared *before* re-activation so the ``finally``
        block in :meth:`_run_activation` does not suppress a subsequent
        late-inbox activation.
        """
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        self._rate_limit_retry_task = None
        self._maybe_activate_for_rate_limit_retry()

    def activate_for_continuation(self) -> None:
        """Spawn an activation task that resumes from existing DB history.

        Used by ``AgentTeam.handle_continue`` to run the agent without an
        inbox message — the LLM call uses the existing session history
        verbatim, which (for /continue) ends in the prior assistant turn.
        The resulting first assistant message is stamped with
        ``extra["is_continuation"] = True`` by :class:`ContinuationHook`.

        The state check + state mutation form one logical step here so two
        concurrent ``/continue`` requests cannot both observe ``idle`` and
        race into ``_run_activation``.  Callers (notably
        :meth:`AgentTeam.handle_continue`) should catch
        :class:`AlreadyWorkingError` and translate it to their own
        precondition error type.

        Raises:
            AlreadyWorkingError: if the agent is already working.
        """
        if self.state == "working":
            raise AlreadyWorkingError(self.name)
        self.state = "working"
        self._active_task = asyncio.create_task(
            self._run_activation(is_continuation=True),
            name=f"continue:{self.name}",
        )

    def activate_for_compaction(self) -> None:
        """Spawn an activation task that forces summarization before the model call."""
        if self.state == "working":
            raise AlreadyWorkingError(self.name)
        self.state = "working"
        self._active_task = asyncio.create_task(
            self._run_activation(force_compaction=True),
            name=f"compact:{self.name}",
        )

    # ── Live-config drift ──────────────────────────────────────────────

    def refresh_if_dirty(self) -> bool:
        """Detect config drift and rebuild the agent in place if dirty.

        Public wrapper used by callers that want fresh frontmatter without
        reaching into private drift internals (e.g. read-only listing
        endpoints). Safe to call on any member; the caller is responsible
        for skipping ``state == "working"`` to avoid racing ``run()``.

        Returns:
            ``True`` if a refresh was performed, ``False`` otherwise.
        """
        self._detect_config_drift()
        if self._config_dirty:
            self._refresh_agent_from_disk()
            return True
        return False

    def _detect_config_drift(self) -> None:
        """End-of-turn: flag the agent dirty if any tracked file moved."""
        if not self.agent.config_stamp:
            return  # in-memory agent with no source file
        drifted = detect_drift(self.agent.config_stamp)
        if drifted:
            self._config_dirty = True
            logger.info(
                "agent_config_dirty name={} paths={}",
                self.name,
                [Path(p).name for p in drifted],
            )

    def _refresh_agent_from_disk(self) -> None:
        """Start-of-turn: rebuild ``self.agent`` in place from its ``.md``.

        On parse/registry failure, keep the existing agent and re-stamp
        to avoid looping on the same broken edit.
        """
        # Deferred — ``app.agent.loader`` imports ``app.agent.mode.team.member``
        # to wire teams; resolving ``rebuild_agent_from_disk`` at call time
        # avoids the cycle without re-introducing one in ``app.agent.drift``.
        from app.agent.loader import rebuild_agent_from_disk

        source = self.agent.source_path
        if source is None:
            self._config_dirty = False
            return

        try:
            mode = self._team.mode if self._team is not None else "work"
            new_agent = rebuild_agent_from_disk(source, mode=mode)
        except Exception as exc:
            logger.warning(
                "agent_config_refresh_failed name={} error={}",
                self.name,
                exc,
            )
            from app.agent.mcp.config import config_path as _mcp_config_path
            from app.core.agent_settings import agent_settings_path

            self.agent.config_stamp = stamp_agent_files(
                agent_md_path=source,
                mcp_config_path=_mcp_config_path(),
                agent_settings_path=agent_settings_path(),
            )
            self._config_dirty = False
            return

        # File-backed blueprints use the base role name (e.g. ``executor``),
        # but live spawned instances must keep their concrete handle.
        new_agent.name = self.name

        old_model = self.agent.model_id
        self.agent = new_agent
        self._config_dirty = False
        logger.info(
            "agent_config_refreshed name={} model={} tools={} skills={}",
            self.name,
            new_agent.model_id,
            sorted(new_agent._tools.keys()),
            new_agent.skills,
        )
        if old_model != new_agent.model_id:
            logger.info(
                "agent_model_changed name={} old={} new={}",
                self.name,
                old_model,
                new_agent.model_id,
            )

    async def _run_activation(
        self,
        *,
        is_continuation: bool = False,
        force_compaction: bool = False,
        is_rate_limit_retry: bool = False,
    ) -> None:
        """One-shot activation: drain inbox, process, return to idle.

        When ``is_continuation`` is True the inbox drain/persist/SSE-emit
        steps are skipped — the agent runs against the current DB history
        verbatim, which (for /continue) ends in the prior assistant turn so
        the provider continues from there.  The resulting first assistant
        message is stamped via :class:`ContinuationHook`.

        When ``is_rate_limit_retry`` is True the inbox drain/persist/SSE-emit
        steps are also skipped — this activation resumes after a rate-limit
        delay and the original messages are already persisted in the DB.
        """
        assert self._mailbox is not None
        assert self._team is not None

        self._cancel_event.clear()

        if is_continuation or force_compaction or is_rate_limit_retry:
            # Control-command / retry path — no inbox messages; run on DB history.
            pending: list[Message] = []
        else:
            pending = self._drain_activation_inbox()

            if not pending:
                # Spurious activation — nothing to process. Reset state that
                # _maybe_activate pre-set to "working" and bail out.
                self.state = "idle"
                return

        self._active_delegation_task_id = self._task_id_for_batch(pending)

        # state was already set to "working" by _maybe_activate
        await self._team._emit(agent=self.name, event="agent_status", status="working")
        logger.debug(
            "team_member_activated name={} messages={} "
            "continuation={} rate_limit_retry={}",
            self.name,
            len(pending),
            is_continuation,
            is_rate_limit_retry,
        )

        # Re-check drift at turn start so edits made between turns
        # (settings UI, external editor, self-healing skill) take effect on
        # the very next turn, not two turns later.
        self._detect_config_drift()
        if self._config_dirty:
            self._refresh_agent_from_disk()

        # Let subclass reset bookkeeping
        self._on_wake(pending)

        if not is_continuation and not is_rate_limit_retry:
            # Format + persist inbox RIGHT AFTER receiving (one row per message)
            inbox_msgs = await self._persist_inbox(pending)

            # Emit one inbox SSE per message for split view
            for msg_obj, raw_msg in zip(inbox_msgs, pending):
                if self._should_emit_inbox_sse([raw_msg.from_agent]):
                    inbox_extra: dict = {
                        "content": msg_obj.content,
                        "from_agent": raw_msg.from_agent,
                    }
                    artifact = raw_msg.extra.get("_handoff_artifact") or getattr(
                        raw_msg, "_handoff_artifact", None
                    )
                    if artifact is not None:
                        inbox_extra["_handoff_artifact"] = artifact
                    await self._team._emit(
                        agent=self.name,
                        event="inbox",
                        extra=inbox_extra,
                    )

        try:
            await self._handle_messages(
                is_continuation=is_continuation,
                force_compaction=force_compaction,
            )
            self._rate_limit_retry_count = 0  # Reset on success
            await self._on_turn_success()

        except Exception as exc:
            from app.agent.errors import (
                ProviderAuthenticationError,
                ProviderRateLimitError,
            )

            if isinstance(exc, ProviderRateLimitError):
                logger.warning(
                    "team_member_provider_rate_limit name={} attempt={}/{} error={}",
                    self.name,
                    self._rate_limit_retry_count + 1,
                    _MAX_RATE_LIMIT_RETRIES,
                    exc,
                )
                if self._rate_limit_retry_count < _MAX_RATE_LIMIT_RETRIES:
                    # Schedule delayed re-activation with exponential backoff
                    self._rate_limit_retry_count += 1
                    delay = _RATE_LIMIT_BASE_DELAY * (
                        2 ** (self._rate_limit_retry_count - 1)
                    )
                    logger.info(
                        "team_member_rate_limit_retry name={} attempt={}/{} delay={}s",
                        self.name,
                        self._rate_limit_retry_count,
                        _MAX_RATE_LIMIT_RETRIES,
                        delay,
                    )
                    # Cancel any previously scheduled retry
                    if (
                        self._rate_limit_retry_task is not None
                        and not self._rate_limit_retry_task.done()
                    ):
                        self._rate_limit_retry_task.cancel()
                    self._rate_limit_retry_task = asyncio.create_task(
                        self._delayed_rate_limit_retry(delay)
                    )
                else:
                    # Exhausted retries
                    logger.warning(
                        "team_member_rate_limit_exhausted name={} attempts={}",
                        self.name,
                        _MAX_RATE_LIMIT_RETRIES,
                    )
                    await self._on_turn_error(exc)
                    self.state = "error"
                    await self._team._emit(
                        agent=self.name,
                        event="agent_status",
                        status="error",
                        extra={
                            "message": (
                                f"Rate limit exceeded after "
                                f"{_MAX_RATE_LIMIT_RETRIES} retries: {exc}"
                            )
                        },
                    )
            elif isinstance(exc, ProviderAuthenticationError):
                logger.warning(
                    "team_member_provider_auth_failed name={} error={}", self.name, exc
                )
                await self._on_turn_error(exc)
                self.state = "error"
                await self._team._emit(
                    agent=self.name,
                    event="agent_status",
                    status="error",
                    extra={"message": str(exc)},
                )
            else:
                logger.exception("team_member_error name={} error={}", self.name, exc)
                await self._on_turn_error(exc)
                self.state = "error"
                await self._team._emit(
                    agent=self.name,
                    event="agent_status",
                    status="error",
                    extra={"message": str(exc)},
                )

        finally:
            self._on_turn_finally()
            self._active_delegation_task_id = None
            if self.state != "error":
                self.state = "idle"
                await self._team._emit(
                    agent=self.name,
                    event="agent_status",
                    status="idle",
                )
                logger.debug("team_member_idle name={}", self.name)

            # Did mcp.json / agent.md / SKILL.md change during this turn?
            # Drift → rebuild the agent at the start of the next turn.
            self._detect_config_drift()

            # Me: re-activate if messages arrived while agent.run() was executing.
            # agent.run() breaks on <sleep>/final-response without running
            # TeamInboxHook again, so any message queued during that last LLM call
            # sits in the inbox.  Calling _maybe_activate here is safe: state is
            # already "idle", so it spawns a fresh activation task that loads
            # history from DB and wakes the agent — exactly like a normal wakeup.
            #
            # Skip this when a rate-limit retry is already scheduled — the
            # delayed task will re-activate us when the backoff expires.
            if (
                not self._mailbox.inbox_empty(self.name)
                and self._rate_limit_retry_task is None
            ):
                logger.info(
                    "team_member_late_inbox_reactivate name={}",
                    self.name,
                )
                self._maybe_activate()

            if self is self._team.lead:
                await self._team._try_activate_queued_after_lead_turn()

            await self._team._try_emit_done()

    @staticmethod
    def _message_task_id(message: Message) -> str | None:
        """Return the durable task identity for task-bearing coordination."""
        if message.extra.get("kind") not in {"delegation", "rejection"}:
            return None
        task_id = message.extra.get("task_id")
        return task_id if isinstance(task_id, str) and task_id else None

    @classmethod
    def _task_id_for_batch(cls, messages: list[Message]) -> str | None:
        return next(
            (
                task_id
                for message in messages
                if (task_id := cls._message_task_id(message)) is not None
            ),
            None,
        )

    def _drain_activation_inbox(self) -> list[Message]:
        """Drain one focused member task, deferring later task contracts."""
        assert self._mailbox is not None
        messages = self._mailbox.drain_nowait(self.name)
        if self._role_label == "lead":
            return messages

        active_task_id: str | None = None
        split_at: int | None = None
        for index, message in enumerate(messages):
            task_id = self._message_task_id(message)
            if task_id is None:
                continue
            if active_task_id is None:
                active_task_id = task_id
            elif task_id != active_task_id:
                split_at = index
                break
        if split_at is None:
            return messages
        self._mailbox.requeue(self.name, messages[split_at:])
        logger.info(
            "team_member_delegation_deferred name={} active_task={} deferred={}",
            self.name,
            active_task_id,
            len(messages) - split_at,
        )
        return messages[:split_at]

    def _drain_midturn_inbox(self) -> list[Message]:
        """Inject quick coordination but defer unrelated task assignments."""
        assert self._mailbox is not None
        messages = self._mailbox.drain_nowait(self.name)
        if self._role_label == "lead":
            return messages

        accepted: list[Message] = []
        deferred: list[Message] = []
        for message in messages:
            task_id = self._message_task_id(message)
            if task_id is not None and task_id != self._active_delegation_task_id:
                deferred.append(message)
            else:
                accepted.append(message)
        self._mailbox.requeue(self.name, deferred)
        return accepted

    # ------------------------------------------------------------------
    # Abstract / override points
    # ------------------------------------------------------------------

    @property
    @abc.abstractmethod
    def _role_label(self) -> str:
        """Short role label for logs and DB titles (e.g. 'lead', 'member')."""

    @abc.abstractmethod
    def build_protocol(self, base_prompt: str, team: "AgentTeam") -> str:
        """Assemble role-specific protocol-injected system prompt."""

    def _on_wake(self, pending: list[Message]) -> None:
        """Called after draining inbox, before processing.
        Override to reset bookkeeping.
        """

    def _skip_inbox_persistence(self, senders: list[str]) -> bool:
        """Return True to skip DB persistence for this inbox batch."""
        return False

    def _should_emit_inbox_sse(self, senders: list[str]) -> bool:
        """Return True to emit an inbox SSE event for this batch."""
        return True

    async def _on_turn_success(self) -> None:
        """Called after _handle_messages completes successfully."""

    async def _on_turn_error(self, exc: Exception) -> None:
        """Called when _handle_messages raises. Override for error recovery.

        Subclasses should call ``await super()._on_turn_error(exc)`` first
        so the base can emit the typed
        :class:`~app.agent.schemas.events.AgentNotConfiguredEvent` for
        :class:`~app.agent.providers.unconfigured.UnconfiguredProviderError`
        before any role-specific handling runs.
        """
        from app.agent.errors import ProviderAuthenticationError
        from app.agent.providers.unconfigured import UnconfiguredProviderError

        if isinstance(exc, UnconfiguredProviderError | ProviderAuthenticationError):
            from app.agent.schemas.events import AgentNotConfiguredEvent
            from app.services import memory_stream_store as stream_store
            from app.services.stream_envelope import StreamEnvelope

            try:
                await stream_store.push_event(
                    self._team.lead.session_id
                    if self._team is not None
                    else self.session_id,
                    StreamEnvelope.from_event(
                        AgentNotConfiguredEvent(
                            agent=self.name,
                            message=str(exc),
                        )
                    ),
                )
            except Exception as push_exc:
                logger.warning("agent_not_configured_emit_failed error={}", push_exc)

    def _on_turn_finally(self) -> None:
        """Called in the finally block of every turn. Override for cleanup."""

    # ------------------------------------------------------------------
    # Inbox persistence
    # ------------------------------------------------------------------

    async def _persist_inbox(self, messages: list[Message]) -> list[HumanMessage]:
        """Format inbox messages, persist each as its own HumanMessage row.

        Called in _run_activation right after draining the mailbox — before
        any processing — so the user turn is in DB even if _handle_messages
        crashes.  Returns the list of HumanMessages (may be empty).
        """
        result: list[HumanMessage] = []

        for msg in messages:
            # tool always delivers "[agent]: content" — user/broadcast pass through as-is
            content = msg.content

            human_msg = HumanMessage(content=content)
            extra = {
                **msg.extra,
                "message_id": msg.id,
                "from_agent": msg.from_agent,
                "is_broadcast": msg.is_broadcast,
            }

            # Backward-compatible bridge for in-flight Message objects created
            # by older tool factories before structured metadata became a
            # first-class field. New messages populate ``extra`` directly.
            for attr, key in (
                ("_task_spec", "_task_spec"),
                ("_handoff_artifact", "_handoff_artifact"),
                ("_rejection_feedback", "_rejection_feedback"),
            ):
                value = getattr(msg, attr, None)
                if value is not None and key not in extra:
                    extra[key] = value

            # Let subclass decide whether to skip persistence
            saved_row = None
            if not self._skip_inbox_persistence([msg.from_agent]):
                db_factory = resolve_db_factory(self.db_factory)
                session_uuid = uuid.UUID(self.session_id)
                async with db_factory() as db:
                    async with db.begin():
                        existing_row = None
                        if extra.get("kind") in {
                            "delegation",
                            "handoff",
                            "rejection",
                        }:
                            existing_row = (
                                await db.exec(
                                    select(SessionMessage)
                                    .where(
                                        col(SessionMessage.session_id) == session_uuid,
                                        col(SessionMessage.extra)[
                                            "message_id"
                                        ].as_string()
                                        == msg.id,
                                    )
                                    .limit(1)
                                )
                            ).first()
                        if existing_row is not None:
                            saved_row = existing_row
                        else:
                            saved_row = await save_message(
                                db, session_uuid, human_msg, extra=extra
                            )
                        human_msg.db_id = saved_row.id  # stash db_id for sync()

            task_id = extra.get("task_id")
            if saved_row is not None and isinstance(task_id, str) and self._team:
                try:
                    kind = extra.get("kind")
                    if kind in {"delegation", "rejection"}:
                        await self._team.mark_delegation_dispatched(task_id)
                    artifact = extra.get("_handoff_artifact")
                    if (
                        kind == "handoff"
                        and isinstance(artifact, dict)
                        and artifact.get("status") == "final"
                    ):
                        await self._team.attach_delegation_handoff_message(
                            task_id, saved_row.id
                        )
                except Exception as exc:
                    # The inbox row and task ID are already durable. Leaving
                    # dispatched_at/linkage unset makes recovery replayable;
                    # failing the member turn here would only lose useful work.
                    logger.warning(
                        "delegation_message_link_failed task_id={} kind={} error={}",
                        task_id,
                        extra.get("kind"),
                        exc,
                    )

            result.append(human_msg)

        return result

    # ------------------------------------------------------------------
    # Message handling
    # ------------------------------------------------------------------

    async def _handle_messages(
        self, *, is_continuation: bool = False, force_compaction: bool = False
    ) -> None:
        """Load full history from DB and call agent.run().

        When ``is_continuation`` is True a one-shot
        :class:`ContinuationHook` is appended to the hooks list so the
        very first assistant message produced by this run gets
        ``extra["is_continuation"] = True``.
        """
        assert self._team is not None

        db_factory = resolve_db_factory(self.db_factory)
        session_uuid = uuid.UUID(self.session_id)

        async with db_factory() as db:
            try:
                history = await get_messages_for_llm(db, session_uuid)
            except Exception:
                history = []
            session_row = await db.get(ChatSession, session_uuid)
            active_task_specs: list[dict] = []
            if self._role_label == "member":
                try:
                    lead_session_uuid = uuid.UUID(self._team.lead.session_id)
                    task_query = select(DelegationTask).where(
                        DelegationTask.lead_session_id == lead_session_uuid,
                        DelegationTask.recipient == self.name,
                        DelegationTask.status == "pending",
                    )
                    if self._active_delegation_task_id is not None:
                        task_query = task_query.where(
                            DelegationTask.id
                            == uuid.UUID(self._active_delegation_task_id)
                        )
                    active_tasks = (await db.exec(task_query)).all()
                    active_task_specs = [dict(task.spec) for task in active_tasks]
                except (TypeError, ValueError):
                    active_task_specs = []

        run_messages = (
            _task_scoped_history(history, self._active_delegation_task_id)
            if self._role_label == "member"
            else history
        )
        runtime_provider: LLMProviderBase | None = None
        runtime_model = None
        session_model = session_row.model if session_row is not None else None
        session_thinking_level = (
            session_row.thinking_level if session_row is not None else None
        )
        last_service_tier: str | None = None
        last_user_model: str | None = None
        for msg in reversed(run_messages):
            extra = msg.extra or {} if msg.extra else {}
            if msg.role == "user":
                if last_service_tier is None:
                    value = extra.get("service_tier")
                    if isinstance(value, str) and value:
                        last_service_tier = value
                # The most recent user message may have a per-message model override.
                if last_user_model is None:
                    value = extra.get("model")
                    if isinstance(value, str) and value:
                        last_user_model = value
                if last_service_tier is not None and last_user_model is not None:
                    break
            elif last_service_tier is None:
                value = extra.get("service_tier")
                if isinstance(value, str) and value:
                    last_service_tier = value

        claimed_paths = sorted(
            {
                str(path)
                for spec in active_task_specs
                for path in spec.get("target_paths", [])
                if isinstance(path, str) and path
            }
        )
        active_priority = next(
            (
                str(spec["priority"])
                for spec in reversed(active_task_specs)
                if spec.get("priority")
            ),
            None,
        )
        active_complexity = next(
            (
                str(spec["complexity"])
                for spec in reversed(active_task_specs)
                if spec.get("complexity")
            ),
            None,
        )

        # Prefer the per-message requested model when available; fall back to the
        # session model stored on ChatSession, then the lead agent default.
        effective_model = last_user_model or session_model or self.agent.model_id
        self.runtime_model_id = effective_model
        self.runtime_thinking_level = session_thinking_level
        # Provider-owned catalogs are authoritative for context
        # limits, modalities, tool support, and configurable thinking controls.
        # Hydrate them before provider routing, execution policy, and
        # summarization are built. Discovery is best-effort and falls back to
        # the registry when a provider is temporarily unavailable.
        provider_id = (
            effective_model.split(":", 1)[0].lower()
            if effective_model and ":" in effective_model
            else ""
        )
        if provider_id in {"fci", "copilot", "codex"}:
            await ensure_runtime_model_metadata(effective_model)
        thinking_profile = get_effective_model_thinking(effective_model)
        execution_policy = resolve_execution_policy(
            complexity=active_complexity,
            priority=active_priority,
            target_paths=claimed_paths,
            explicit_thinking_level=session_thinking_level,
            provider_default_thinking_level=thinking_profile.default_level,
            # What the request builder will honour, not the raw catalog list.
            # The catalog says MiMo has a bare toggle; it takes a token
            # budget, so clamping against the catalog turned a request for
            # ``high`` into ``none`` — thinking switched off precisely when
            # the most was asked for, and silently.
            supported_thinking_levels=honoured_levels_for(effective_model),
        )
        from app.services.delegation_worktree_service import sandbox_binding

        task_workspace = sandbox_binding(
            primary_workspace=str(
                session_workspace_dir(self._team.lead.session_id, self._team.workspace)
            ),
            extra_workspace_paths=self._team.extra_workspace_paths,
            read_only_paths=self._team.read_only_paths,
            active_specs=active_task_specs,
        )
        if effective_model and self._team._provider_factory is not None:
            model_kwargs: dict[str, object] = {}
            if execution_policy.thinking_level:
                model_kwargs["thinking_level"] = execution_policy.thinking_level
            # Whether a model has this tier is catalog/registry data, not a
            # provider prefix — see ``get_model_modes``. A tier that reaches
            # a model without one would be forwarded as an unknown field.
            if last_service_tier and get_model_mode(effective_model, last_service_tier):
                model_kwargs["service_tier"] = last_service_tier
            runtime_provider = self._team._provider_factory(
                effective_model,
                model_kwargs=model_kwargs,
            )
            runtime_model = effective_model

        # Build hooks — StreamPublisherHook writes to shared team stream
        lead_session_id = self._team.lead.session_id
        publisher_hook = StreamPublisherHook(
            session_id=lead_session_id,
            agent_name=self.name,
            publish_reasoning=not is_continuation,
        )

        # Inject team protocol via hook
        team_prompt_hook = AgentTeamProtocolHook(
            team=self._team,
            agent_name=self.name,
        )
        team_inbox_hook = TeamInboxHook(member=self)

        # OTel hook — child span under lead's trace
        otel_hook = OpenTelemetryHook(
            agent_name=self.name,
            model_id=runtime_model or self.agent.model_id,
            lead_session_id=lead_session_id,
        )

        pipeline = HookPipeline()
        pipeline.add(HookStage.BASE_CONTEXT, "clock", inject_current_date)
        pipeline.add(
            HookStage.BASE_CONTEXT, "wiki-context", default_wiki_injection_hook
        )
        pipeline.add(HookStage.BASE_CONTEXT, "team-protocol", team_prompt_hook)
        # Query-dependent context is registered later, at PROMPT_FINALIZATION,
        # alongside the skill-catalog finalizer — see the cache-boundary hook
        # registration below for why.
        memory_context_hook = (
            MemoryContextHook(
                db_factory=self.db_factory,
                session_id=self.session_id,
            )
            if self.db_factory
            else default_memory_context_hook
        )
        pipeline.add(HookStage.BASE_CONTEXT, "team-inbox", team_inbox_hook)
        pipeline.add(HookStage.BASE_CONTEXT, "stream-publisher", publisher_hook)
        pipeline.add(HookStage.BASE_CONTEXT, "telemetry", otel_hook)
        pipeline.add(
            HookStage.BASE_CONTEXT,
            CONDUCTOR_TELEMETRY_HOOK_NAME,
            ConductorTelemetryHook(
                agent_name=self.name,
                model_id=runtime_model or self.agent.model_id,
            ),
        )
        if self.db_factory:
            pipeline.add(
                HookStage.SESSION_CONTEXT,
                "goal-usage",
                GoalUsageHook(
                    db_factory=self.db_factory,
                    session_id=lead_session_id,
                ),
            )
            if self._role_label == "lead":
                pipeline.add(
                    HookStage.SESSION_CONTEXT,
                    "goal-context",
                    GoalContextHook(
                        db_factory=self.db_factory,
                        session_id=lead_session_id,
                    ),
                )
                # Sidebar-folder siblings are shared with the lead only:
                # members work from the lead's delegation brief, so adding
                # the digest to every member run would repeat the same
                # tokens without adding information.
                pipeline.add(
                    HookStage.SESSION_CONTEXT,
                    "folder-context",
                    FolderContextHook(
                        db_factory=self.db_factory,
                        session_id=lead_session_id,
                    ),
                )
        if any(
            "code_context_navigation" in tool.capabilities
            for tool in self.agent._tools.values()
        ):
            pipeline.add(
                HookStage.CAPABILITY,
                "code-navigation-telemetry",
                CodeNavigationTelemetryHook(),
            )
        # Splice user-queued messages into the running turn — lead only, since
        # the user-facing queue lives on the lead's session.  Must precede
        # summarization so a freshly-injected message participates in window
        # accounting on the same iteration. Suppressed while a workflow
        # drives the session (plan v5 §6.1): queued messages then land at
        # node boundaries only, never mid-node.
        if self._role_label == "lead" and self.db_factory:
            workflow_driving = False
            try:
                from app.workflow.runner import runner as workflow_runner

                workflow_driving = workflow_runner.is_driving(self.session_id)
            except Exception:  # noqa: BLE001 — hook attach must never fail
                workflow_driving = False
            if not workflow_driving:
                pipeline.add(
                    HookStage.INGRESS,
                    "queued-user-messages",
                    QueuedMessageInjectionHook(
                        session_id=self.session_id,
                        agent_name=self.name,
                        db_factory=self.db_factory,
                    ),
                )
        if self._team.mode == "coding":
            if self.db_factory:
                pipeline.add(
                    HookStage.SESSION_CONTEXT,
                    "trace-context",
                    EasdContextHook(
                        db_factory=self.db_factory,
                        lead_session_id=lead_session_id,
                        agent_name=self.name,
                        role=self._role_label,
                    ),
                )
            pipeline.add(
                HookStage.WORKSPACE,
                "workspace-context",
                WorkspaceInstructionsHook(
                    task_workspace.workspace,
                    task_workspace.extra_workspace_paths or None,
                ),
            )
            # Surface ruff issues introduced by an edit in the same tool
            # round — the prompt-only "run lsp_diagnostics after edits"
            # guidance has no enforcement otherwise.
            pipeline.add(
                HookStage.WORKSPACE,
                "post-edit-diagnostics",
                PostEditDiagnosticsHook(),
            )
            pipeline.add(
                HookStage.WORKSPACE,
                "problem-capture",
                ProblemCaptureHook(),
            )
            pipeline.add(
                HookStage.WORKSPACE,
                "completion-verification",
                CompletionVerificationHook(),
            )

        # Title generation — lead only (members don't need session titles).
        # Always enabled; uses the same runtime provider as the chat turn so
        # title generation does not require a separate model configuration.
        if self._role_label == "lead" and self.db_factory:
            title_hook = build_title_generation_hook(
                provider=runtime_provider or self.agent.llm_provider,
                db_factory=self.db_factory,
            )
            if title_hook is not None:
                pipeline.add(HookStage.LIFECYCLE, "title-generation", title_hook)

        # Auto-extract memory facts at session end (lead only, fire-and-forget).
        if self._role_label == "lead":
            mem_hook = build_memory_extraction_hook(
                provider=runtime_provider or self.agent.llm_provider,
                db_factory=self.db_factory,
            )
            if mem_hook is not None:
                pipeline.add(HookStage.LIFECYCLE, "memory-extraction", mem_hook)

        # Continuation stamp — one-shot, flags the first assistant message
        # of this run as a continuation of the prior assistant turn so the
        # frontend can render it tight against that prior bubble.
        if is_continuation:
            pipeline.add(HookStage.LIFECYCLE, "continuation", ContinuationHook())

        # Assemble query-dependent prompt sections after all context producers.
        # Summarization then receives the exact same finalized system prompt as
        # the main provider call instead of snapshotting an incomplete prefix.
        # cache-boundary must run first: it stamps everything built so far
        # (role prompt, team protocol, goal/folder/EASD context, workspace
        # instructions) as the stable prefix before memory-context and the
        # skill catalog append content that changes on essentially every turn.
        pipeline.add(
            HookStage.PROMPT_FINALIZATION,
            "cache-boundary",
            CacheBoundaryHook(),
        )
        pipeline.add(
            HookStage.PROMPT_FINALIZATION,
            "memory-context",
            memory_context_hook,
        )
        pipeline.add(
            HookStage.PROMPT_FINALIZATION,
            "skill-catalog-finalizer",
            SkillCatalogFinalizerHook(),
        )

        # Build checkpointer — stream_session_id + agent_name let it clear
        # this agent's stream buffer after each persist, preventing
        # duplicate blocks on mid-turn refresh.
        checkpointer = None
        if self.db_factory:
            from app.core import db as db_module

            checkpointer = SQLiteCheckpointer(
                self.db_factory,
                read_session_factory=db_module.read_session_factory,
                stream_session_id=lead_session_id,
                agent_name=self.name,
            )
            checkpointer.mark_loaded(self.session_id, history)
            # Tool result offload uses the hook's module-level defaults
            # (see app.agent.hooks.tool_result_offload.DEFAULT_CHAR_THRESHOLD).
            pipeline.add(
                HookStage.CONTEXT_CONTROL,
                "tool-result-offload",
                ToolResultOffloadHook(),
            )
            summarization_provider = runtime_provider or self.agent.llm_provider
            summarization_model = runtime_model or self.agent.model_id
            # Build team-aware summarization hook so compacted context
            # preserves role, peers, assigned tasks, and handoff history.
            peer_names = [m.name for m in self._team.all_members if m.name != self.name]
            snapshot = format_state_snapshot()
            summ_hook = build_team_summarization_hook(
                summarization_provider,
                mode=self._team.mode,
                model_id=summarization_model,
                agent_name=self.name,
                role=self._role_label,
                lead_name=self._team.lead.name,
                peer_names=peer_names,
                state_snapshot=snapshot,
            )
            if summ_hook:
                # Flush memory before the summariser compresses the window —
                # same threshold so both fire on the same turn, flush first.
                flush_hook = build_memory_flush_hook(
                    llm_provider=summarization_provider,
                    prompt_token_threshold=summ_hook.prompt_token_threshold,
                )
                if flush_hook is not None:
                    pipeline.add(HookStage.CONTEXT_CONTROL, "memory-flush", flush_hook)
                pipeline.add(HookStage.CONTEXT_CONTROL, "summarization", summ_hook)
        # Projection is a provider-boundary concern, not a persistence feature:
        # apply it to ephemeral/test runs as well as database-backed sessions.
        pipeline.add(
            HookStage.CONTEXT_CONTROL,
            "tool-context-projection",
            build_tool_context_projection_hook(self._team.mode),
        )
        hooks = pipeline.build()

        # Inject team tools
        injected = self._team.get_injected_tools(self.name)

        # Resolve tier-based tool restrictions for non-lead members.
        # The lead keeps full workspace access in a WebBridge-tagged session;
        # only competing web/browser backends are excluded so web pages are
        # always driven through the user's real browser.
        tier_excluded: frozenset[str] | None = None
        granted_tools = (*self.agent._tools.values(), *injected)
        is_webbridge_session = WEBBRIDGE_SESSION_TAG in self._team.session_tags
        deferred = deferred_tools_for_run(
            granted_tools,
            reveal_webbridge=is_webbridge_session,
        )
        if self._role_label == "member":
            member_tier = resolve_member_tier(self.name)
            tier_excluded = (
                denied_tools_for_tier(member_tier, self.agent._tools.values()) or None
            )
        if is_webbridge_session:
            webbridge_excluded = webbridge_session_excluded_tools(granted_tools)
            tier_excluded = frozenset(tier_excluded or ()) | webbridge_excluded
        else:
            # WebBridge is opt-in. In an ordinary session browser_use drives
            # the user-visible EvoFlux browser and WebBridge must not be
            # discoverable through load_tool merely because it is registered.
            tier_excluded = (
                frozenset(tier_excluded or ()) | NON_WEBBRIDGE_SESSION_DENIED_TOOLS
            )
            if SIDE_CHAT_SESSION_TAG in self._team.session_tags:
                tier_excluded |= side_chat_session_excluded_tools(
                    (*self.agent._tools.values(), *injected)
                )

        # Surface team routing context to tools via state.metadata.  The
        # schedule tool reads these as injected args so the LLM never has
        # to specify (or could lie about) the routing target.
        run_metadata: dict[str, object] = {
            "team_mode": self._team.mode,
            "webbridge_session": is_webbridge_session,
            "side_chat_session": SIDE_CHAT_SESSION_TAG in self._team.session_tags,
            # Browser ownership belongs to the top-level conversation. Team
            # members keep their own session IDs for history/checkpointing,
            # but WebBridge commands must reuse the lead's tab binding/group.
            "webbridge_session_id": lead_session_id,
            # Lead stream id — file-change tracking + SSE publish to one place.
            "stream_session_id": lead_session_id,
            "session_id": self.session_id,
            "execution_complexity": execution_policy.complexity,
            "verification_rigor": execution_policy.verification_rigor,
        }
        if force_compaction:
            run_metadata["force_summarization"] = True
            run_metadata["stop_after_before_model"] = True
        if task_workspace.workspace:
            run_metadata["team_workspace"] = task_workspace.workspace
        config = RunConfig(session_id=self.session_id, metadata=run_metadata)

        # Coding mode uses the exact project workspace for every team member.
        session_sandbox = SandboxConfig(
            workspace=task_workspace.workspace,
            session_id=lead_session_id,
            extra_workspace_paths=task_workspace.extra_workspace_paths or None,
            read_only_paths=task_workspace.read_only_paths or None,
            write_allowed_paths=(
                task_workspace.write_allowed_paths
                if self._role_label == "member"
                else None
            ),
        )
        token = set_sandbox(session_sandbox)

        # Scope permission service — mode comes from the session's persisted
        # permission_mode (ask | accept-edits | plan | auto | bypass).  Events
        # publish to the lead's stream; the service registers globally so the
        # reply endpoint can resolve requests from its own request context.
        permission_service = PermissionService(
            session_id=self.session_id,
            mode=cast(Mode, self._team.permission_mode),
            stream_session_id=lead_session_id,
        )
        perm_token = set_permission_service(permission_service)

        # Scope plan mode service — tracks active plan and pending approvals.
        plan_service = PlanModeService(
            session_id=self.session_id,
            stream_session_id=lead_session_id,
        )
        plan_token = set_plan_mode_service(plan_service)

        # Composer "Plan mode" unifies permission auto-allow with agent plan
        # mode: lead starts recording destructive tools until exit_plan_mode.
        # Pre-activate deferred plan tools so the model can exit without
        # load_tool (otherwise recorded steps can vanish with no approval UI).
        if self._team.permission_mode == "plan" and self._role_label == "lead":
            plan_service.enter()
            run_metadata["_plan_mode"] = True
            run_metadata["activated_deferred_tools"] = {
                "enter_plan_mode",
                "exit_plan_mode",
            }

        # Scope ask-user service — blocks the ask_user tool until the user
        # answers, publishing to the same lead stream as plan approvals.
        ask_user_service = AskUserService(
            session_id=self.session_id,
            stream_session_id=lead_session_id,
        )
        ask_user_token = set_ask_user_service(ask_user_service)

        # Scope agent role for plugin applies_to filtering ("lead"/"member").
        role_token = set_role(self._role_label)
        usage_token = begin_turn_usage(lead_session_id, self.name)

        # Signal that the LLM call is about to start — this breaks the long
        # "Preparing" gap into distinct ingress vs model-calling phases.
        await self._team._emit(
            agent=self.name,
            event="agent_status",
            status="working",
            extra={"phase": "model_calling"},
        )

        try:
            await self.agent.run(
                run_messages,
                config=config,
                hooks=hooks,
                injected_tools=injected,
                excluded_tools=tier_excluded,
                deferred_tools=deferred,
                interrupt_event=self._cancel_event,
                checkpointer=checkpointer,
                llm_provider=runtime_provider,
                model_id=runtime_model,
            )

            await self._maybe_inject_open_task_nudge()
            await self._maybe_inject_delegation_wait_nudge()
        finally:
            end_turn_usage(usage_token)
            reset_role(role_token)
            _sandbox_ctx.reset(token)
            reset_permission_service(perm_token, self.session_id)
            reset_plan_mode_service(plan_token, self.session_id)
            reset_ask_user_service(ask_user_token, self.session_id)

        # If interrupted, mark last assistant message
        if self._cancel_event.is_set() and self.db_factory:
            await _mark_last_assistant_interrupted(
                self.db_factory, uuid.UUID(self.session_id)
            )

    async def _maybe_inject_open_task_nudge(self) -> None:
        """Wake members that ended normally while assigned todos remain open."""
        if self._role_label != "member" or self.db_factory is None:
            return
        assert self._team is not None
        assert self._mailbox is not None

        try:
            from app.agent.tools.builtin.todo import open_assigned_todos_for_actor

            open_todos = open_assigned_todos_for_actor(
                self._team.lead.session_id,
                self.name,
            )
        except Exception as exc:
            logger.warning(
                "team_member_open_task_lookup_failed name={} error={}", self.name, exc
            )
            return
        if not open_todos:
            return

        try:
            async with resolve_db_factory(self.db_factory)() as db:
                rows = (
                    await db.exec(
                        select(SessionMessage)
                        .where(
                            col(SessionMessage.session_id) == uuid.UUID(self.session_id)
                        )
                        .order_by(col(SessionMessage.created_at).desc())
                        .limit(10)
                    )
                ).all()
        except Exception as exc:
            logger.warning(
                "team_member_open_task_history_failed name={} error={}", self.name, exc
            )
            return
        if not rows:
            return

        last = rows[0]
        if last.role != "assistant" or last.tool_calls:
            return
        if is_sleep_message(last):
            return
        if str(last.id) == self._last_open_task_nudge_message_id:
            # Already nudged for this exact stopping point — re-checking on
            # every idle tick without a new turn from the member would spam
            # the mailbox instead of bounding the nudge.
            return

        for row in rows:
            tool_calls = row.tool_calls or []
            if any(
                call.get("function", {}).get("name") == "team_message"
                for call in tool_calls
            ):
                return
            if row.id == last.id:
                break

        task_ids = [
            todo.get("task_id")
            for todo in open_todos
            if isinstance(todo.get("task_id"), str)
        ]
        nudge_keys = [f"{self._team.lead.session_id}:{task_id}" for task_id in task_ids]
        if nudge_keys and all(
            self._open_task_nudge_counts.get(key, 0) >= MAX_OPEN_TASK_NUDGES
            for key in nudge_keys
        ):
            logger.info(
                "team_member_open_task_nudge_suppressed name={} tasks={}",
                self.name,
                task_ids,
            )
            return
        for key in nudge_keys:
            self._open_task_nudge_counts[key] = (
                self._open_task_nudge_counts.get(key, 0) + 1
            )
        self._last_open_task_nudge_message_id = str(last.id)

        content = _open_task_nudge_content(open_todos, self._team.lead.name)
        logger.info("team_member_open_task_nudge name={} tasks={}", self.name, task_ids)
        await self._mailbox.send(
            to=self.name,
            message=Message(
                from_agent="system",
                to_agent=self.name,
                content=content,
            ),
        )

    async def _maybe_inject_delegation_wait_nudge(self) -> None:
        """Wake the lead if it answered while a delegated handoff is still pending.

        System-level backstop for the ``LEAD_COMMUNICATION_RULES`` rule that
        the lead must ``<sleep>`` instead of answering while team_delegate /
        team_reject recipients haven't sent their final team_handoff yet.
        Prompt compliance alone can't be guaranteed — this catches the
        violation and forces a correction on the next wake, the same way
        ``_maybe_inject_open_task_nudge`` catches members that stop with open
        todos. Only the lead ever has entries in ``pending_delegations``
        (team_delegate/team_reject are lead-only tools), so this is a no-op
        for regular members.
        """
        if self._role_label != "lead" or self.db_factory is None:
            return
        assert self._team is not None
        assert self._mailbox is not None

        await self._team.refresh_delegations(dispatch=False)
        pending = self._team.pending_delegation_recipients(self.name)
        if not pending:
            return
        pending_task_ids = sorted(self._team.pending_delegation_task_ids(self.name))

        try:
            async with resolve_db_factory(self.db_factory)() as db:
                rows = (
                    await db.exec(
                        select(SessionMessage)
                        .where(
                            col(SessionMessage.session_id) == uuid.UUID(self.session_id)
                        )
                        .order_by(col(SessionMessage.created_at).desc())
                        .limit(1)
                    )
                ).all()
        except Exception as exc:
            logger.warning(
                "team_lead_wait_nudge_history_failed name={} error={}", self.name, exc
            )
            return
        if not rows:
            return

        last = rows[0]
        if last.role != "assistant" or last.tool_calls:
            return
        if is_sleep_message(last):
            return  # already complied

        pending_sorted = sorted(pending)
        nudge_key = f"{self.session_id}:{'|'.join(pending_task_ids)}"
        if self._lead_wait_nudge_counts.get(nudge_key, 0) >= MAX_LEAD_WAIT_NUDGES:
            logger.info(
                "team_lead_wait_nudge_suppressed name={} pending={}",
                self.name,
                pending_sorted,
            )
            return
        self._lead_wait_nudge_counts[nudge_key] = (
            self._lead_wait_nudge_counts.get(nudge_key, 0) + 1
        )

        logger.warning(
            "team_lead_answered_with_pending_delegations name={} pending={}",
            self.name,
            pending_sorted,
        )
        content = _lead_wait_nudge_content(pending_sorted, pending_task_ids)
        await self._mailbox.send(
            to=self.name,
            message=Message(
                from_agent="system",
                to_agent=self.name,
                content=content,
            ),
        )


# =============================================================================
# TeamLead — the team coordinator
# =============================================================================


class TeamLead(TeamMemberBase):
    """Team lead agent. Coordinates members, does not do work itself.

    No safety-net, no _replied flag, no task requeue.
    Skips inbox persistence when only "user" senders (already saved by route handler).
    """

    @property
    def _role_label(self) -> str:
        return "lead"

    def _skip_inbox_persistence(self, senders: list[str]) -> bool:
        """Skip for lead when only "user" messages — already saved by route handler."""
        return all(s == "user" for s in senders)

    def _should_emit_inbox_sse(self, senders: list[str]) -> bool:
        """Skip SSE for lead when only user messages — already shown as UserBubble."""
        return any(s != "user" for s in senders)

    async def _on_turn_error(self, exc: Exception) -> None:
        """Emit a user-visible ``error`` event when the lead itself fails.

        Members notify the lead via the mailbox on error, but the lead has no
        one to notify — the failure would otherwise be silent (only an
        ``agent_status=error`` blip in the SSE stream, which the frontend
        treats as a status indicator, not a fatal turn failure).  Emitting a
        typed :class:`ErrorEvent` lets the UI show *why* the turn stopped.

        Unconfigured-provider errors are routed to the typed
        :class:`AgentNotConfiguredEvent` by the base class; we skip the
        generic ``ErrorEvent`` here so the UI doesn't show two banners.
        """
        from app.agent.errors import ProviderAuthenticationError
        from app.agent.providers.unconfigured import UnconfiguredProviderError

        await super()._on_turn_error(exc)
        if isinstance(exc, UnconfiguredProviderError | ProviderAuthenticationError):
            return

        from app.agent.schemas.events import ErrorEvent
        from app.services import memory_stream_store as stream_store
        from app.services.stream_envelope import StreamEnvelope

        try:
            await stream_store.push_event(
                self.session_id,
                StreamEnvelope.from_event(
                    ErrorEvent(
                        message=f"Lead agent '{self.name}' failed: {exc}",
                        metadata={"agent": self.name, "exception": type(exc).__name__},
                    )
                ),
            )
        except Exception as push_exc:
            # Defensive: never let an emit failure escape the finally block.
            logger.warning("team_lead_error_emit_failed error={}", push_exc)

    def build_protocol(self, base_prompt: str, team: "AgentTeam") -> str:
        """Assemble lead protocol into the system prompt."""
        # Runtime roster metadata is the routing source of truth. Custom names
        # and changed descriptions work without adding another heuristic.
        roster_lines = ["- **Available specialists** (when you do delegate):"]
        for name, blueprint in sorted(team.blueprints.items()):
            description = " ".join((blueprint.description or name).split())
            roster_lines.append(f"  - **{name}** — {description}")
        if not team.blueprints:
            roster_lines.append("  - No member blueprints are configured.")
        roster_lines.append(
            "  - For multiple independent concerns, use multiple suitable "
            "specialists in parallel."
        )
        rules = LEAD_COMMUNICATION_RULES.replace(
            "{{ROUTING_GUIDE}}", "\n".join(roster_lines)
        )
        sections: list[str] = [rules, LEAD_MESSAGE_FORMAT]
        # Keep the activation contract ahead of instructions that may name
        # deferred capabilities. This applies equally to ordinary and
        # WebBridge sessions: WebBridge is revealed eagerly, but other granted
        # tools can still remain deferred.
        sections.append(DEFERRED_TOOL_PROTOCOL)
        sections.append(LEAD_PROTOCOL)
        if WEBBRIDGE_SESSION_TAG in team.session_tags:
            # Tagged sessions retain workspace tools but route all browser/web
            # interaction through the user's real browser via WebBridge.
            sections.append(WEBBRIDGE_SESSION_PROMPT)
        if SIDE_CHAT_SESSION_TAG in team.session_tags:
            # Tagged session (a Side Chat panel): tools are already scoped
            # read-only via excluded_tools — tell it why, and that the
            # context above is read-only reference from the main session.
            sections.append(SIDE_CHAT_SESSION_PROMPT)
        protocol = "\n\n".join(sections)
        return f"{base_prompt}\n\n---\n\n{protocol}"


# =============================================================================
# TeamMember — a worker agent
# =============================================================================


class TeamMember(TeamMemberBase):
    """Worker agent. Does tasks, reports to lead, stops.

    Has safety-net auto-reply, task requeue on error.
    """

    def __init__(
        self,
        agent: Agent,
        *,
        session_id: str | None = None,
        db_factory: DbFactory | None = None,
    ) -> None:
        super().__init__(agent, session_id=session_id, db_factory=db_factory)

    @property
    def _role_label(self) -> str:
        return "member"

    async def _on_turn_error(self, exc: Exception) -> None:
        """Notify lead on error.

        Unconfigured-provider errors are surfaced to the UI directly by the
        base class via :class:`AgentNotConfiguredEvent`; we also notify the
        lead so it can pick a different member instead of retrying us.
        """
        from app.agent.errors import (
            ProviderAuthenticationError,
            ProviderConnectionError,
            ProviderRequestError,
        )
        from app.agent.providers.unconfigured import UnconfiguredProviderError

        assert self._team is not None
        assert self._mailbox is not None

        # A successful final handoff may have completed durably immediately
        # before a later hook/provider failure. Never turn that into a false
        # "reassign me" message. For an actually pending task, transition the
        # ledger to failed first so lead wait gates and dependent tasks cannot
        # remain stranded forever.
        active_task = None
        if self._active_delegation_task_id is not None:
            try:
                active_task = await self._team.get_delegation_task(
                    self._active_delegation_task_id
                )
            except (TypeError, ValueError) as task_exc:
                logger.warning(
                    "team_member_error_task_lookup_failed member={} task={} error={}",
                    self.name,
                    self._active_delegation_task_id,
                    task_exc,
                )
        if active_task is not None and active_task.status in {"review", "completed"}:
            logger.info(
                "team_member_post_handoff_error_suppressed member={} task={} error={}",
                self.name,
                active_task.id,
                exc,
            )
            return
        if active_task is not None and active_task.status == "pending":
            try:
                await self._team.fail_delegation_task(active_task, str(exc))
            except Exception as task_exc:  # noqa: BLE001 - preserve error reporting
                logger.warning(
                    "team_member_task_fail_transition_failed member={} task={} error={}",
                    self.name,
                    active_task.id,
                    task_exc,
                )

        await super()._on_turn_error(exc)

        from app.agent.tools.builtin.todo import release_in_progress_for_actor
        from app.core.paths import session_workspace_dir

        released = release_in_progress_for_actor(
            session_workspace_dir(self._team.lead.session_id, self._team.workspace),
            self.name,
            self._team.lead.session_id,
        )
        suffix = (
            f" In-progress todos reset to pending: {', '.join(released)}."
            if released
            else ""
        )

        # Member with no model: tell the lead exactly that so it doesn't
        # retry. Generic errors keep the existing "temporarily unavailable"
        # framing.
        if isinstance(exc, UnconfiguredProviderError):
            reason = (
                f"[{self.name}]: I have no model configured. "
                f"Ask the user to add a provider in Settings, then re-spawn me.{suffix}"
            )
        elif isinstance(exc, ProviderAuthenticationError):
            reason = (
                f"[{self.name}]: My provider credentials are not authenticated. "
                f"Ask the user to reconnect the provider in Settings, then re-spawn me.{suffix}"
            )
        elif isinstance(exc, ProviderRequestError):
            reason = (
                f"[{self.name}]: My provider rejected the request — {exc}. "
                f"This will not fix itself on retry; tell the user.{suffix}"
            )
        elif isinstance(exc, ProviderConnectionError):
            reason = (
                f"[{self.name}]: I could not reach my provider — {exc} "
                f"Reassign my work to another member or ask the user to check "
                f"connectivity.{suffix}"
            )
        else:
            reason = (
                f"[{self.name}]: System error — temporarily unavailable. "
                f"Please reassign my work to another member.{suffix}"
            )

        await self._mailbox.send(
            to=self._team.lead.name,
            message=Message(
                from_agent=self.name,
                to_agent=self._team.lead.name,
                content=reason,
            ),
        )

    def build_protocol(self, base_prompt: str, team: "AgentTeam") -> str:
        """Assemble member protocol + roster into system prompt."""
        lead_name = team.lead.name
        sections: list[str] = [
            (
                "## Runtime identity\n"
                f"You are `{self.name}`. Use this exact handle when identifying "
                "yourself or reporting back; do not use the blueprint name."
            ),
            MEMBER_COMMUNICATION_RULES,
            MEMBER_MESSAGE_FORMAT.format(lead_name=lead_name),
            DEFERRED_TOOL_PROTOCOL,
            MEMBER_PROTOCOL.format(lead_name=lead_name),
        ]

        protocol = "\n\n".join(sections)
        return f"{base_prompt}\n\n---\n\n{protocol}"
