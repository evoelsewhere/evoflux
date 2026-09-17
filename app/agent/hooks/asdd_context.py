"""Tell a Coding agent which ASDD changes are open in its repository.

The old hook injected one run's accepted contract, resolved through the chat
session that owned it. Nothing owns a chat now, so this hook cannot — and should
not — guess which change a turn is about: the phase prompt names it, and the
agent reads the folder.

What it does instead is orientation. Without it an agent rediscovers the
catalogue layout by probing, and a repository with three open changes gets work
attached to whichever one it happened to find first. A short index of what is
open, what phase each change is in, and where the catalogue lives costs a few
hundred tokens and removes both failures.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from loguru import logger

from app.agent.hooks.base import BaseAgentHook
from app.services.asdd_lifecycle import action_rail
from app.services.asdd_service import catalogue_for
from app.services.asdd_setup_service import ASDD_MANIFEST

if TYPE_CHECKING:
    from app.agent.state import AgentState, ModelRequest, RunContext

_MAX_LISTED_CHANGES = 12


class AsddContextHook(BaseAgentHook):
    def __init__(self, *, workspace: str, agent_name: str, role: str) -> None:
        self._workspace = workspace
        self._agent_name = agent_name
        self._role = role
        self._block: str | None = None

    async def before_agent(self, ctx: RunContext, state: AgentState) -> None:
        self._block = None
        for key in (
            "_asdd_change_ids",
            "_asdd_repository_roots",
            "_asdd_verification_commands",
        ):
            state.metadata.pop(key, None)
        if not self._workspace:
            return
        try:
            summary = await asyncio.to_thread(self._read_catalogue)
        except Exception as exc:  # noqa: BLE001 - context must not break a turn
            logger.warning(
                "asdd_context_load_failed workspace={} agent={} error={}",
                self._workspace,
                self._agent_name,
                exc,
            )
            return
        if summary is None:
            return
        block, change_ids = summary
        self._block = block
        state.metadata["_asdd_change_ids"] = change_ids
        state.metadata["_asdd_repository_roots"] = [self._workspace]
        state.metadata.setdefault("_asdd_verification_commands", [])

    def _read_catalogue(self) -> tuple[str, list[str]] | None:
        from pathlib import Path

        if not (Path(self._workspace) / ASDD_MANIFEST).is_file():
            return None
        catalogue = catalogue_for(self._workspace)
        change_ids = catalogue.list_change_ids()
        lines = [
            "## ASDD catalogue",
            "",
            f"This repository runs Agent Specification-Driven Development. Its "
            f"catalogue is `{catalogue.relative(catalogue.base_path)}`: "
            f"`specs/<capability>/spec.md` is the current contract for a behavior, "
            f"`changes/<change-id>/` is one proposed change. Read "
            f"`{catalogue.relative(catalogue.project_path)}` and "
            f"`{ASDD_MANIFEST.as_posix()}` before phase work.",
            "",
        ]
        if not change_ids:
            lines += ["No change is open."]
            return "\n".join(lines), []

        lines += ["Open changes:", ""]
        for change_id in change_ids[:_MAX_LISTED_CHANGES]:
            try:
                record = catalogue.read_change(change_id)
            except Exception:  # noqa: BLE001 - one bad folder is not the index
                lines.append(f"- `{change_id}` — unreadable; open it to see why")
                continue
            rail = action_rail(record.artifacts)
            next_action = rail["primary_action"] or "nothing"
            lines.append(
                f"- `{change_id}` — {record.artifacts.title} "
                f"[{record.artifacts.status}, risk {record.artifacts.risk}] "
                f"→ next: {next_action}"
            )
        if len(change_ids) > _MAX_LISTED_CHANGES:
            lines.append(f"- +{len(change_ids) - _MAX_LISTED_CHANGES} more")
        lines += [
            "",
            "Work on the change you were asked about, by reading its folder. Never "
            "infer a change from conversation memory, and never approve one: "
            "approvals belong to the user.",
        ]
        return "\n".join(lines), change_ids

    async def before_model(
        self, ctx: RunContext, state: AgentState, request: ModelRequest
    ) -> ModelRequest | None:
        if not self._block:
            return None
        prompt = (
            f"{request.system_prompt}\n\n{self._block}"
            if request.system_prompt
            else self._block
        )
        return request.override(system_prompt=prompt)


__all__ = ["AsddContextHook"]
