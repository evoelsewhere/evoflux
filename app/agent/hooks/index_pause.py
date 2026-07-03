"""Hook that pauses code-graph reindexing while the agent loop is active.

Prevents the file-watcher from triggering expensive incremental reindexing
(tree-sitter parsing + ONNX embedding) while an agent is rapidly writing
files, which would otherwise spike CPU/RAM and crash the backend.

The watcher accumulates dirty workspaces while paused and performs a single
batched reindex on resume.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from app.agent.hooks.base import BaseAgentHook

if TYPE_CHECKING:
    from app.agent.schemas.chat import AssistantMessage
    from app.agent.state import AgentState, RunContext


class IndexPauseHook(BaseAgentHook):
    """Pauses the code-graph watcher during agent runs."""

    async def before_agent(self, ctx: "RunContext", state: "AgentState") -> None:
        watcher = _get_watcher()
        if watcher is None:
            return
        await watcher.pause()
        logger.debug("index_pause_hook paused agent={}", ctx.agent_name)

    async def after_agent(
        self, ctx: "RunContext", state: "AgentState", response: "AssistantMessage"
    ) -> None:
        watcher = _get_watcher()
        if watcher is None:
            return
        await watcher.resume()
        logger.debug("index_pause_hook resumed agent={}", ctx.agent_name)


def _get_watcher():
    """Retrieve the global CodeGraphWatcher from app state, if available."""
    try:
        from app.services.code_graph.watcher import _global_watcher

        return _global_watcher
    except (ImportError, AttributeError):
        return None


# Singleton instance — reuse across agent runs (stateless hook).
index_pause_hook = IndexPauseHook()
