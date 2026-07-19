"""Inject workspace-local AGENTS.md instructions for coding mode."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from app.agent.hooks.base import BaseAgentHook

if TYPE_CHECKING:
    from app.agent.schemas.chat import AssistantMessage
    from app.agent.state import AgentState, ModelCallHandler, ModelRequest, RunContext


MAX_AGENTS_MD_BYTES = 128 * 1024


class WorkspaceInstructionsHook(BaseAgentHook):
    def __init__(self, workspace: str | None) -> None:
        self._workspace = Path(workspace).resolve() if workspace else None

    async def wrap_model_call(
        self,
        ctx: "RunContext",
        state: "AgentState",
        request: "ModelRequest",
        handler: "ModelCallHandler",
    ) -> "AssistantMessage":
        instructions = self._read_agents_md()
        if not instructions:
            return await handler(request)
        block = f"## Workspace Instructions\n\n{instructions}"
        prompt = (
            f"{request.system_prompt}\n\n{block}" if request.system_prompt else block
        )
        return await handler(request.override(system_prompt=prompt))

    def _read_agents_md(self) -> str:
        if self._workspace is None:
            return ""
        path = self._workspace / "AGENTS.md"
        if not path.is_file():
            return ""
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.warning(
                "workspace_agents_md_read_failed path={} error={}", path, exc
            )
            return ""
        if len(content.encode("utf-8")) > MAX_AGENTS_MD_BYTES:
            # Truncate rather than drop — partial instructions beat none.
            logger.warning(
                "workspace_agents_md_truncated path={} limit={}",
                path,
                MAX_AGENTS_MD_BYTES,
            )
            content = content[:MAX_AGENTS_MD_BYTES]
            content += (
                "\n\n[AGENTS.md truncated — file exceeds the injected-size limit]"
            )
        return content.strip()
