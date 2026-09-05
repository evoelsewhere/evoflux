"""ToolResultOffloadHook — saves large tool results to session artifacts.

Replaces oversized tool output with a compact summary so the LLM context window stays lean.

How it works
------------
``wrap_tool_call`` fires after every tool execution. If the result exceeds
``char_threshold``, the full content is written to::

    {EVOFLUX_DATA_DIR}/sessions/{session_id}/.tool_results/{agent_name}/{tool_call_id}.txt

The content returned to the LLM (and stored in the ``ToolMessage``) is replaced
with a compact, token-efficient summary::

    [Tool result offloaded — too large for context]
    File: {absolute_artifact_path}
    Size: {lines} lines · {chars} chars
    Preview (first):
    {first N chars}
    …
    Preview (last):
    {last N chars}
    (use read to load full output)

The full content is preserved on disk so the agent can call ``read_file`` on the
offload path at any time to re-read the complete output.

``ToolMessage.extra`` is populated with offload metadata so the UI can show a
verbose view without re-reading the file::

    {
        "offloaded": True,
        "artifact": "{absolute_artifact_path}",
        "lines": N,
        "chars": N,
    }

This is persisted to the DB via the checkpointer since ``extra`` is included in
``model_dump_full()``.

Usage::

    from app.agent.hooks.tool_result_offload import ToolResultOffloadHook

    hook = ToolResultOffloadHook(
        char_threshold=40000,  # offload results longer than this (~10k tokens)
        preview_chars=1000,    # chars to keep from head & tail as preview
    )
    agent = Agent(llm_provider=provider, hooks=[hook])
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from app.agent.artifacts import tool_results_dir
from app.agent.hooks.base import BaseAgentHook

if TYPE_CHECKING:
    from app.agent.state import AgentState, RunContext
    from app.agent.schemas.chat import ToolCall

# Me default threshold — ~10k tokens at 4 chars/token
DEFAULT_CHAR_THRESHOLD = 40000
# Me preview chars: first N + last N shown inline so agent sees head & tail
DEFAULT_PREVIEW_CHARS = 1000
# Never offload read — agent uses it to access prior offloads, offloading
# its result would create a circular dependency.
# Never offload skill — skill content must reach the agent intact; truncating
# it would silently deliver incomplete instructions.
# shell is NOT excluded: it self-truncates large output (persists full content
# to the XDG session artifact directory) so this hook normally never sees
# oversized shell results.
_NEVER_OFFLOAD = frozenset({"read", "skill"})


class ToolResultOffloadHook(BaseAgentHook):
    """Offload large tool results to workspace files to protect context window.

    Parameters
    ----------
    char_threshold:
        Results longer than this many characters are offloaded.
        Set to 0 to disable.
    preview_chars:
        Number of characters to include from the head and tail as preview.
        The agent sees first N + last N chars; full content is in the file.
    """

    def __init__(
        self,
        char_threshold: int = DEFAULT_CHAR_THRESHOLD,
        preview_chars: int = DEFAULT_PREVIEW_CHARS,
    ) -> None:
        self._char_threshold = char_threshold
        self._preview_chars = preview_chars

    async def wrap_tool_call(
        self,
        ctx: "RunContext",
        state: "AgentState",
        tool_call: "ToolCall",
        handler,
    ) -> str:
        result: str = await handler(ctx, state, tool_call)

        tool_name = tool_call.function.name
        if (
            self._char_threshold <= 0
            or len(result) <= self._char_threshold
            or tool_name in _NEVER_OFFLOAD
        ):
            return result

        tool_call_id = tool_call.id or f"tc_{tool_call.function.name}"
        try:
            path = await asyncio.to_thread(
                self._write_offload,
                ctx.agent_name,
                tool_call_id,
                result,
                ctx.session_id,
            )
        except Exception as exc:
            # Me keep original result if write fails — never break tool execution
            logger.warning(
                "tool_result_offload_write_failed agent={} tool={} tool_call_id={} error={}",
                ctx.agent_name,
                tool_call.function.name,
                tool_call_id,
                exc,
            )
            return result

        lines = result.count("\n") + 1
        chars = len(result)
        head = result[: self._preview_chars].rstrip()
        tail = (
            result[-self._preview_chars :].lstrip()
            if chars > self._preview_chars * 2
            else ""
        )
        omitted = (
            chars - self._preview_chars * 2 if tail else chars - self._preview_chars
        )

        # Absolute app-managed path — session artifacts live outside coding
        # workspaces, so a workspace-relative path would point at the wrong repo.
        artifact_path = str(path)

        compact = (
            f"[Tool result offloaded — content saved to session artifacts]\n"
            f"File: {artifact_path}\n"
            f"Size: {lines:,} lines · {chars:,} chars\n"
            f"\nPreview (first):\n{head}"
        )
        if tail:
            compact += f"\n… ({omitted:,} chars omitted)\n\nPreview (last):\n{tail}"
        elif chars > self._preview_chars:
            compact += f"\n… ({omitted:,} more chars — use read to load full output)"

        logger.debug(
            "tool_result_offloaded agent={} tool={} tool_call_id={} chars={} path={}",
            ctx.agent_name,
            tool_call.function.name,
            tool_call_id,
            chars,
            path,
        )

        # The loop and stream publisher consume this per-call metadata and attach it
        # to the durable ToolMessage plus the live tool_end event.
        state.metadata.setdefault("_tool_result_metadata", {})[tool_call_id] = {
            "offloaded": True,
            "artifact": artifact_path,
            "lines": lines,
            "chars": chars,
            "shown_chars": len(compact),
            "omitted_chars": max(0, chars - len(head) - len(tail)),
        }

        return compact

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _write_offload(
        self,
        agent_name: str,
        tool_call_id: str,
        content: str,
        session_id: str | None = None,
    ) -> Path:
        """Write full tool result to session metadata below ``.evoflux``."""
        offload_dir = tool_results_dir(agent_name, session_id)
        offload_dir.mkdir(parents=True, exist_ok=True)
        dest = offload_dir / f"{tool_call_id}.txt"
        dest.write_text(content, encoding="utf-8")
        return dest


def build_tool_result_offload_hook() -> "ToolResultOffloadHook":
    """Construct the hook with the operator's threshold, if one is set."""
    from app.agent.hooks.context_settings import resolve

    return ToolResultOffloadHook(
        char_threshold=resolve("tool_result_offload_chars", DEFAULT_CHAR_THRESHOLD)
    )
