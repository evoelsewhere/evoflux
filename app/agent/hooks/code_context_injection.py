"""Inject a small task-specific code context pack before the first model call."""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from app.agent.hooks.base import BaseAgentHook
from app.agent.schemas.chat import (
    AssistantMessage,
    FunctionCall,
    HumanMessage,
    ToolCall,
    ToolMessage,
)

if TYPE_CHECKING:
    from app.agent.state import AgentState, RunContext

_CODE_TOOL_NAMES = frozenset(
    {"code_query", "code_search", "code_graph", "code_overview", "code_path"}
)
_CODE_INTENT_RE = re.compile(
    r"(?:\b(?:bug|code|class|function|method|api|route|component|hook|service|"
    r"refactor|implement|fix|trace|test|build|compile|lint|typecheck|caller|"
    r"dependency|import|module|file|repo|repository)\b|"
    r"[A-Za-z0-9_./-]+\.(?:py|ts|tsx|js|jsx|go|rs|java|cs|cpp|c|h|rb|php)\b)",
    re.IGNORECASE,
)


class CodeContextHook(BaseAgentHook):
    """Prefetch only evidence related to the latest coding request."""

    async def before_agent(self, ctx: "RunContext", state: "AgentState") -> None:
        from app.core.runtime_settings import load_runtime_settings

        if not load_runtime_settings().code_graph.task_prefetch_enabled:
            return
        found = self._latest_human(state)
        if found is None:
            return
        insert_index, query = found
        if self._has_code_tool_history(state, since=insert_index):
            return
        if not query or not _CODE_INTENT_RE.search(query):
            return
        result = await self._fetch(query)
        if not result:
            return

        call_id = f"code_context_{uuid.uuid4().hex[:12]}"
        arguments = {
            "query": query,
            "intent": "locate",
            "budget_tokens": 800,
            "limit": 4,
        }
        state.messages[insert_index:insert_index] = [
            AssistantMessage(
                content=None,
                tool_calls=[
                    ToolCall(
                        id=call_id,
                        function=FunctionCall(
                            name="code_query", arguments=json.dumps(arguments)
                        ),
                    )
                ],
            ),
            ToolMessage(tool_call_id=call_id, name="code_query", content=result),
        ]
        logger.info(
            "code_context_injected agent={} at_index={}", ctx.agent_name, insert_index
        )

    @staticmethod
    def _has_code_tool_history(state: "AgentState", *, since: int = 0) -> bool:
        return any(
            call.function.name in _CODE_TOOL_NAMES
            for message in state.messages[since:]
            if isinstance(message, AssistantMessage)
            for call in (message.tool_calls or [])
        )

    @staticmethod
    def _latest_human(state: "AgentState") -> tuple[int, str] | None:
        for index in range(len(state.messages) - 1, -1, -1):
            message = state.messages[index]
            if isinstance(message, HumanMessage):
                return index + 1, message.text_content() or ""
        return None

    @staticmethod
    async def _fetch(query: str) -> str | None:
        from app.agent.sandbox import get_sandbox
        from app.agent.tools.builtin.code_graph import _render_code_query
        from app.core.db import async_session_factory
        from app.services import code_graph_service as graph_svc
        from app.services.code_query_service import query_code_across_workspaces

        try:
            sandbox = get_sandbox()
        except Exception:
            return None
        async with async_session_factory() as db:
            raw_roots = [
                str(sandbox.workspace_root),
                *getattr(sandbox, "extra_workspace_paths", []),
            ]
            workspaces = []
            roots = dict.fromkeys(
                str(Path(value).expanduser().resolve()) for value in raw_roots
            )
            for root in roots:
                if not Path(root).is_dir():
                    continue
                workspaces.append(
                    (
                        root,
                        await graph_svc.resolve_workspace_id(db, path=root),
                        Path(root).name or root,
                    )
                )
            result = await query_code_across_workspaces(
                db,
                workspaces=workspaces,
                query=query,
                intent="locate",
                budget_tokens=800,
                limit=4,
                enable_lsp=False,
            )
        if not result.results:
            return None
        return _render_code_query(result)
