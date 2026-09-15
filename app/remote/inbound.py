"""Provider-neutral remote text ingress and current-task selection."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from uuid import UUID

from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.chat import ChatSession
from app.models.remote import RemotePairing
from app.remote.contracts import RemoteInboundAction, RemoteInboundActionKind
from app.remote.pairing import PairingService
from app.services import agent_service
from app.services.chat_service import create_chat_session
from app.services.interactive_message_service import (
    NoTeamConfigured,
    resolve_team_for_session,
    submit_persisted_interactive_message,
)


@dataclass(frozen=True)
class RemoteInboundResult:
    """A bounded, adapter-neutral outcome for one remote action."""

    status: str
    session_id: UUID | None = None
    message_id: UUID | None = None
    response_mode: str = "summary"


class RemoteInboundService:
    """Admits paired remote actions through the existing service layer."""

    def __init__(self, *, pairing_service: PairingService | None = None) -> None:
        self._pairing_service = pairing_service or PairingService()
        self._locks: dict[UUID, asyncio.Lock] = {}
        self._locks_lock = asyncio.Lock()

    async def handle_text(
        self, db: AsyncSession, action: RemoteInboundAction
    ) -> RemoteInboundResult:
        """Submit paired plain text to its current task or create one."""
        if action.kind is not RemoteInboundActionKind.TEXT:
            return RemoteInboundResult(status="ignored")
        content = (action.text or "").strip()
        if not content:
            return RemoteInboundResult(status="ignored")

        pairing = await self._authorize(db, action)
        if pairing is None:
            return RemoteInboundResult(status="unauthorized")

        async with await self._lock_for(pairing.id):
            pairing = await db.get(RemotePairing, pairing.id)
            if pairing is None:
                return RemoteInboundResult(status="unauthorized")
            # Captured now, before the rollback below expires every ORM
            # instance in this session — accessing pairing.response_mode
            # after that would need a lazy reload, which the async ORM
            # cannot do implicitly.
            response_mode = pairing.response_mode
            session = await self._current_session(db, pairing)
            if session is None:
                session = await self._create_work_session(db, pairing, action)

            session_id = session.id
            if db.in_transaction():
                await db.rollback()
            session, team = await resolve_team_for_session(
                db, str(session_id), require_existing=True
            )
            if session is None:
                return RemoteInboundResult(status="session_not_addressable")

            request_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            result = await submit_persisted_interactive_message(
                db,
                session=session,
                team=team,
                content=content,
                message_extra={
                    "interactive_source": {
                        "channel": "remote",
                        "adapter": "telegram",
                        "connection_id": str(action.connection_id),
                        "key": action.source_key,
                        "request_hash": request_hash,
                        "state": "persisted",
                    }
                },
                source_key=action.source_key,
                source_request_hash=request_hash,
            )
        return RemoteInboundResult(
            status=result.status,
            session_id=UUID(result.session_id),
            message_id=result.message_id,
            response_mode=response_mode,
        )

    async def new_task(
        self, db: AsyncSession, action: RemoteInboundAction
    ) -> RemoteInboundResult:
        """Clear only this pairing's current-task pointer."""
        pairing = await self._authorize(db, action)
        if pairing is None:
            return RemoteInboundResult(status="unauthorized")

        async with await self._lock_for(pairing.id):
            pairing = await db.get(RemotePairing, pairing.id)
            if pairing is None:
                return RemoteInboundResult(status="unauthorized")
            pairing.active_session_id = None
            db.add(pairing)
            await db.commit()
        return RemoteInboundResult(status="current_task_cleared")

    async def continue_task(
        self, db: AsyncSession, action: RemoteInboundAction, session_id: UUID
    ) -> RemoteInboundResult:
        """Make an existing task current for the pairing."""
        pairing = await self._authorize(db, action)
        if pairing is None:
            return RemoteInboundResult(status="unauthorized")

        async with await self._lock_for(pairing.id):
            pairing = await db.get(RemotePairing, pairing.id)
            if pairing is None:
                return RemoteInboundResult(status="unauthorized")
            session = await db.get(ChatSession, session_id)
            if not _is_addressable_session(session):
                return RemoteInboundResult(status="session_not_addressable")
            assert session is not None
            pairing.active_session_id = session.id
            db.add(pairing)
            await db.commit()
        return RemoteInboundResult(
            status="current_task_selected", session_id=session_id
        )

    async def stop_current(
        self, db: AsyncSession, action: RemoteInboundAction
    ) -> RemoteInboundResult:
        """Interrupt a live current turn without deleting or changing its task."""
        pairing = await self._authorize(db, action)
        if pairing is None:
            return RemoteInboundResult(status="unauthorized")

        async with await self._lock_for(pairing.id):
            pairing = await db.get(RemotePairing, pairing.id)
            if pairing is None:
                return RemoteInboundResult(status="unauthorized")
            session = await self._current_session(db, pairing)
            if session is None:
                return RemoteInboundResult(status="no_active_turn")
            session_id = session.id
            if db.in_transaction():
                await db.rollback()
            try:
                _, team = await resolve_team_for_session(
                    db, str(session_id), require_existing=True
                )
            except NoTeamConfigured:
                return RemoteInboundResult(
                    status="no_active_turn", session_id=session_id
                )
            if not team.has_active_user_turn():
                return RemoteInboundResult(
                    status="no_active_turn", session_id=session_id
                )
            await agent_service.interrupt_team(team, str(session_id))
        return RemoteInboundResult(status="interrupted", session_id=session_id)

    async def _authorize(
        self, db: AsyncSession, action: RemoteInboundAction
    ) -> RemotePairing | None:
        if action.principal.connection_id != action.connection_id:
            return None
        return await self._pairing_service.authorize(
            db,
            connection_id=action.connection_id,
            principal_id=action.principal.principal_id,
        )

    async def _lock_for(self, pairing_id: UUID) -> asyncio.Lock:
        async with self._locks_lock:
            return self._locks.setdefault(pairing_id, asyncio.Lock())

    async def _current_session(
        self, db: AsyncSession, pairing: RemotePairing
    ) -> ChatSession | None:
        if pairing.active_session_id is None:
            return None
        session = await db.get(ChatSession, pairing.active_session_id)
        if _is_addressable_session(session):
            return session
        pairing.active_session_id = None
        db.add(pairing)
        await db.commit()
        return None

    async def _create_work_session(
        self,
        db: AsyncSession,
        pairing: RemotePairing,
        action: RemoteInboundAction,
    ) -> ChatSession:
        session = await create_chat_session(db)
        session.mode = "work"
        session.parent_session_id = None
        session.session_type = "main"
        session.tags = [
            "remote_origin",
            f"remote_connection:{action.connection_id}",
        ]
        pairing.active_session_id = session.id
        db.add(session)
        db.add(pairing)
        await db.commit()
        return session


def _is_addressable_session(session: ChatSession | None) -> bool:
    return (
        session is not None
        and session.parent_session_id is None
        and session.session_type == "main"
        and session.mode in {"work", "coding"}
    )


__all__ = ["RemoteInboundResult", "RemoteInboundService"]
