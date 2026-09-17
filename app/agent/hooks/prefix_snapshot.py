"""Freeze the assembled system/tool prefix per session runtime profile."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from loguru import logger
from sqlalchemy.exc import IntegrityError

from app.agent.hooks.base import BaseAgentHook
from app.agent.hooks.cache_boundary import CACHE_VOLATILE_MARKER
from app.agent.model_context import (
    PREFIX_SNAPSHOT_DIRTY_KEY,
    PREFIX_SNAPSHOT_FROZEN_KEY,
    PREFIX_SNAPSHOT_PROFILE_KEY,
)
from app.agent.state import ModelRequest
from app.core.db import DbFactory, resolve_db_factory
from app.services.prompt_prefix import (
    get_prefix_snapshot,
    pin_prefix_snapshot,
    prefix_profile_key,
    tool_contract_hash,
)

if TYPE_CHECKING:
    from app.agent.schemas.chat import AssistantMessage
    from app.agent.state import AgentState, ModelCallHandler, RunContext


class SessionPrefixSnapshotHook(BaseAgentHook):
    """Pin the final assembled prefix and reuse it on later session turns.

    The hook is intentionally registered as the final model wrapper. Earlier
    prompt hooks may still perform their normal side effects on a frozen run,
    but this hook is the last authority before provider serialization. The
    first request captures the assembled system prompt; subsequent requests
    with the same profile/tool contract receive those bytes verbatim.
    """

    def __init__(
        self,
        *,
        db_factory: DbFactory,
        session_id: str,
        profile: dict[str, Any],
    ) -> None:
        self._db_factory = resolve_db_factory(db_factory)
        self._session_id = session_id
        self._session_uuid = self._parse_uuid(session_id)
        self._profile_key = prefix_profile_key(profile)
        self._snapshot = None

    @staticmethod
    def _parse_uuid(value: str) -> UUID | None:
        try:
            return UUID(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _clean_system_prompt(value: str) -> str:
        return value.replace(CACHE_VOLATILE_MARKER, "")

    def _current_tools_hash(self, state: "AgentState") -> str:
        return tool_contract_hash(state.tool_defs)

    async def before_agent(self, ctx: "RunContext", state: "AgentState") -> None:
        self._snapshot = None
        state.metadata[PREFIX_SNAPSHOT_PROFILE_KEY] = self._profile_key
        state.metadata[PREFIX_SNAPSHOT_FROZEN_KEY] = False
        if self._session_uuid is None:
            return
        try:
            async with self._db_factory() as db:
                self._snapshot = await get_prefix_snapshot(
                    db,
                    self._session_uuid,
                    self._profile_key,
                )
            state.metadata[PREFIX_SNAPSHOT_FROZEN_KEY] = self._snapshot is not None
        except Exception as exc:  # noqa: BLE001 — cache optimization is optional
            logger.warning(
                "prefix_snapshot_load_failed session_id={} error={}",
                self._session_id,
                exc,
            )

    async def preflight_before_model(
        self,
        ctx: "RunContext",
        state: "AgentState",
        request: ModelRequest,
    ) -> None:
        """Decide whether ordinary prompt hooks should rebuild this request."""
        if state.metadata.pop(PREFIX_SNAPSHOT_DIRTY_KEY, False):
            self._snapshot = None
        elif self._snapshot is not None and (
            self._snapshot.tools_hash != self._current_tools_hash(state)
        ):
            self._snapshot = None
        state.metadata[PREFIX_SNAPSHOT_FROZEN_KEY] = self._snapshot is not None

    async def before_model(
        self,
        ctx: "RunContext",
        state: "AgentState",
        request: ModelRequest,
    ) -> ModelRequest | None:
        if self._snapshot is None:
            state.metadata[PREFIX_SNAPSHOT_FROZEN_KEY] = False
            return None
        if self._snapshot.tools_hash != self._current_tools_hash(state):
            # A tool-schema change is the official rotation boundary. Let the
            # normal prompt hooks rebuild this request; wrap_model_call pins
            # the new final system prompt below.
            self._snapshot = None
            state.metadata[PREFIX_SNAPSHOT_FROZEN_KEY] = False
            return None
        state.metadata[PREFIX_SNAPSHOT_FROZEN_KEY] = True
        return request.override(system_prompt=self._snapshot.system_prompt)

    async def wrap_model_call(
        self,
        ctx: "RunContext",
        state: "AgentState",
        request: ModelRequest,
        handler: "ModelCallHandler",
    ) -> "AssistantMessage":
        if self._session_uuid is None:
            state.metadata[PREFIX_SNAPSHOT_FROZEN_KEY] = False
            return await handler(request)

        tools_hash = self._current_tools_hash(state)
        if self._snapshot is not None and self._snapshot.tools_hash == tools_hash:
            state.metadata[PREFIX_SNAPSHOT_FROZEN_KEY] = True
            return await handler(
                request.override(system_prompt=self._snapshot.system_prompt)
            )

        system_prompt = self._clean_system_prompt(request.system_prompt)
        tools = [dict(tool) for tool in state.tool_defs]
        try:
            async with self._db_factory() as db:
                async with db.begin():
                    snapshot = await pin_prefix_snapshot(
                        db,
                        session_id=self._session_uuid,
                        profile_key=self._profile_key,
                        system_prompt=system_prompt,
                        tools_hash=tools_hash,
                        tools=tools,
                    )
            self._snapshot = snapshot
        except IntegrityError:
            # Two workers may pin the same (session, profile) concurrently.
            # The unique constraint is the cross-process idempotency guard;
            # reuse the winner when its tool contract matches this request.
            try:
                async with self._db_factory() as db:
                    raced = await get_prefix_snapshot(
                        db,
                        self._session_uuid,
                        self._profile_key,
                    )
                if raced is not None and raced.tools_hash == tools_hash:
                    self._snapshot = raced
                    system_prompt = raced.system_prompt
            except Exception as race_exc:  # noqa: BLE001 — keep model available
                logger.warning(
                    "prefix_snapshot_race_recovery_failed session_id={} error={}",
                    self._session_id,
                    race_exc,
                )
        except Exception as exc:  # noqa: BLE001 — never block the model call
            logger.warning(
                "prefix_snapshot_pin_failed session_id={} error={}",
                self._session_id,
                exc,
            )

        state.metadata[PREFIX_SNAPSHOT_FROZEN_KEY] = self._snapshot is not None
        return await handler(request.override(system_prompt=system_prompt))


__all__ = ["SessionPrefixSnapshotHook"]
