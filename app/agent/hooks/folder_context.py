"""FolderContextHook — share context between sessions filed in one folder."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from loguru import logger

from app.agent.hooks.base import BaseAgentHook
from app.core.db import DbFactory, resolve_db_factory
from app.services.session_folder_service import build_folder_context_block

if TYPE_CHECKING:
    from app.agent.state import AgentState, ModelRequest, RunContext


class FolderContextHook(BaseAgentHook):
    """Inject a digest of the session's folder-mates into the system prompt.

    Sessions grouped in a sidebar folder are usually facets of one piece of
    work, so each of them should know what the others established. The digest
    is built from the siblings' own summaries (see
    :func:`build_folder_context_block`) and stays out of ``session_messages``:
    nothing is copied into this session's history, so un-filing the session
    removes the shared context again.

    Built once per run and reused for the remaining model calls of that turn —
    a turn can issue many tool rounds and the siblings cannot change
    mid-turn, so re-querying per call would only add DB round-trips.
    """

    def __init__(self, *, db_factory: DbFactory, session_id: str) -> None:
        self._db_factory = resolve_db_factory(db_factory)
        self._session_id = session_id
        self._block: str | None = None
        self._loaded = False

    async def before_agent(self, ctx: RunContext, state: AgentState) -> None:
        self._block = None
        self._loaded = False

    async def before_model(
        self,
        ctx: RunContext,
        state: AgentState,
        request: ModelRequest,
    ) -> ModelRequest | None:
        if not self._loaded:
            self._loaded = True
            self._block = await self._load_block()
        if not self._block:
            return None
        prompt = (
            f"{request.system_prompt}\n\n{self._block}"
            if request.system_prompt
            else self._block
        )
        return request.override(system_prompt=prompt)

    async def _load_block(self) -> str | None:
        try:
            session_uuid = UUID(self._session_id)
        except ValueError:
            return None
        try:
            async with self._db_factory() as db:
                return await build_folder_context_block(db, session_uuid)
        except Exception as exc:  # noqa: BLE001 - context must not break a turn
            logger.warning(
                "folder_context_load_failed session_id={} error={}",
                self._session_id,
                exc,
            )
            return None


__all__ = ["FolderContextHook"]
