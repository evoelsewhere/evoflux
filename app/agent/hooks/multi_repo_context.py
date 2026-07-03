"""Inject multi-repository context for project-scoped coding sessions."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from app.agent.hooks.base import BaseAgentHook

if TYPE_CHECKING:
    from app.agent.schemas.chat import AssistantMessage
    from app.agent.state import AgentState, ModelCallHandler, ModelRequest, RunContext

MAX_AGENTS_MD_BYTES = 64 * 1024


def _read_agents_md(workspace: Path) -> str:
    path = workspace / "AGENTS.md"
    if not path.is_file():
        return ""
    try:
        size = path.stat().st_size
        if size > MAX_AGENTS_MD_BYTES:
            return ""
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("multi_repo_agents_md_read_failed path={} error={}", path, exc)
        return ""


class MultiRepoContextHook(BaseAgentHook):
    """Injects a map of all project repositories into the agent's system prompt.

    For project sessions with multiple repos, tells the agent:
    - All available repository paths (so it knows where to cd)
    - Per-repo AGENTS.md instructions if present
    """

    def __init__(self, primary_workspace: str, extra_workspace_paths: list[str]) -> None:
        self._primary = Path(primary_workspace).resolve() if primary_workspace else None
        self._extras = [Path(p).resolve() for p in extra_workspace_paths]

    async def wrap_model_call(
        self,
        ctx: "RunContext",
        state: "AgentState",
        request: "ModelRequest",
        handler: "ModelCallHandler",
    ) -> "AssistantMessage":
        block = self._build_block()
        if not block:
            return await handler(request)
        prompt = (
            f"{request.system_prompt}\n\n{block}" if request.system_prompt else block
        )
        return await handler(request.override(system_prompt=prompt))

    def _build_block(self) -> str:
        all_workspaces = []
        if self._primary:
            all_workspaces.append(("primary", self._primary))
        for ws in self._extras:
            if ws != self._primary:
                all_workspaces.append(("", ws))

        if not all_workspaces:
            return ""

        lines = ["## Available Repositories\n"]
        lines.append(
            "You have filesystem and shell access to these repositories. "
            "Use `cd <path>` before shell commands targeting a non-primary repo.\n"
        )
        for label, ws in all_workspaces:
            marker = " **(primary)**" if label == "primary" else ""
            lines.append(f"- **{ws.name}**: `{ws}`{marker}")

        instructions_sections = []
        for _, ws in all_workspaces:
            content = _read_agents_md(ws)
            if content:
                instructions_sections.append(f"### {ws.name}\n{content}")

        block = "\n".join(lines)
        if instructions_sections:
            block += "\n\n## Workspace Instructions\n\n" + "\n\n".join(
                instructions_sections
            )
        return block
