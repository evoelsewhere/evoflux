"""Model-only projection for old, high-volume tool observations.

The durable transcript remains untouched for UI, audit, and resumability.  At
the provider boundary, results outside a small recent tool-batch window are
replaced by deterministic receipts.  Assistant/tool pairs stay intact, so
OpenAI-compatible providers continue to receive a valid function-call history.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from app.agent.hooks.base import BaseAgentHook
from app.agent.schemas.chat import AssistantMessage, ToolMessage

if TYPE_CHECKING:
    from app.agent.state import (
        AgentState,
        ModelCallHandler,
        ModelRequest,
        RunContext,
    )


# Skill bodies are executable instructions and have their own exact-preservation
# contract. Every other old text-only result is safe to project once it leaves
# the recent working set; this also protects the harness when new tools appear.
_NON_PROJECTABLE_TOOLS = frozenset({"skill"})
_MIN_RESULT_CHARS = 1_200
_RECEIPT_STATUS_CHARS = 160
_RECEIPT_HEAD_CHARS = 180
_RECEIPT_TAIL_CHARS = 420


def _receipt(message: ToolMessage) -> str:
    content = message.content or ""
    first_line = (
        content.splitlines()[0].strip()[:_RECEIPT_STATUS_CHARS]
        if content
        else "(empty result)"
    )
    head = content[:_RECEIPT_HEAD_CHARS].strip()
    tail = content[-_RECEIPT_TAIL_CHARS:].strip()
    extra = message.extra or {}
    artifact = extra.get("artifact") or extra.get("path")
    lines = [
        f"[Earlier {message.name or 'tool'} result compacted]",
        f"Original size: {len(content):,} chars",
        f"Status: {first_line}",
    ]
    if artifact:
        lines.append(f"Full output: {artifact}")
    if head:
        lines.extend(["", head])
    if tail and tail != head:
        lines.extend(["", "...", tail])
    if not artifact:
        lines.append("Re-run the tool if exact omitted details are needed.")
    return "\n".join(lines)


def _projected_batch_count(total_batches: int, keep_recent: int) -> int:
    """How many leading tool batches to compact, advancing in whole steps.

    Compacting "everything but the last N batches" recomputed per call means
    the boundary slides forward by one on every batch, and each slide rewrites
    a message the provider had already cached — discarding the cache for the
    entire tail from that point on. Measured on MiMo in a long investigation
    turn, two consecutive calls that differed only by such a slide were served
    at 34% and 25% cache hit on 59k- and 82k-token prompts.

    Advancing the boundary in steps of ``keep_recent`` instead makes it a pure
    function of how many batches exist, so it is unchanged between calls *and*
    between turns, and moves only once every ``keep_recent`` batches. The cost
    is that the verbatim window breathes between ``keep_recent`` and
    ``2 * keep_recent - 1`` batches; those extra carried tokens are billed at
    the cache-read rate, which is where they belong, rather than being re-read
    at full price after every slide.
    """
    step = max(1, keep_recent)
    if total_batches <= keep_recent:
        return 0
    return ((total_batches - keep_recent) // step) * step


class ToolContextProjectionHook(BaseAgentHook):
    """Bound replay cost while preserving the recent working set verbatim."""

    def __init__(self, *, keep_recent_batches: int) -> None:
        self._keep_recent_batches = max(1, keep_recent_batches)

    async def wrap_model_call(
        self,
        ctx: "RunContext",
        state: "AgentState",
        request: "ModelRequest",
        handler: "ModelCallHandler",
    ) -> AssistantMessage:
        batches = [
            message
            for message in request.messages
            if isinstance(message, AssistantMessage) and message.tool_calls
        ]
        compacted_batches = _projected_batch_count(
            len(batches), self._keep_recent_batches
        )
        if compacted_batches <= 0:
            return await handler(request)

        keep_call_ids = {
            call.id
            for message in batches[compacted_batches:]
            for call in message.tool_calls or []
        }
        projected = []
        original_chars = 0
        projected_chars = 0
        projected_count = 0
        for message in request.messages:
            if (
                isinstance(message, ToolMessage)
                and message.tool_call_id not in keep_call_ids
                and message.name not in _NON_PROJECTABLE_TOOLS
                and not message.parts
                and len(message.content or "") > _MIN_RESULT_CHARS
            ):
                replacement = _receipt(message)
                projected.append(message.model_copy(update={"content": replacement}))
                original_chars += len(message.content or "")
                projected_chars += len(replacement)
                projected_count += 1
            else:
                projected.append(message)

        if projected_count:
            saved = original_chars - projected_chars
            state.metadata["tool_context_projection"] = {
                "results": projected_count,
                "original_chars": original_chars,
                "projected_chars": projected_chars,
                "saved_chars": saved,
            }
            logger.debug(
                "tool_context_projected agent={} results={} original_chars={} projected_chars={} saved_chars={}",
                ctx.agent_name,
                projected_count,
                original_chars,
                projected_chars,
                saved,
            )
            request = request.override(messages=tuple(projected))
        return await handler(request)


#: Tool-call batches kept verbatim at the provider boundary. Coding keeps one
#: fewer: its results are far larger, so the same window costs much more.
#: Named rather than inline because the Settings API reports them as the
#: built-in default this hook actually falls back to.
DEFAULT_KEEP_RECENT_BATCHES = 4
CODING_KEEP_RECENT_BATCHES = 3


def keep_recent_batches_for_mode(mode: str | None) -> int:
    """Batches kept for *mode*, with the operator override taking precedence."""
    from app.agent.hooks.context_settings import resolve

    return resolve(
        "keep_recent_tool_batches",
        CODING_KEEP_RECENT_BATCHES if mode == "coding" else DEFAULT_KEEP_RECENT_BATCHES,
    )


def build_tool_context_projection_hook(mode: str) -> ToolContextProjectionHook:
    return ToolContextProjectionHook(
        keep_recent_batches=keep_recent_batches_for_mode(mode),
    )
