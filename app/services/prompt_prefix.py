"""Stable hashing and persistence helpers for session prompt prefixes."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.prompt_cache import SessionPrefixSnapshot


def _stable_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def stable_hash(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def prefix_profile_key(profile: dict[str, Any]) -> str:
    """Hash only stable runtime identity, never raw session/user content."""
    return stable_hash(profile)


def tool_contract_hash(tools: Sequence[dict[str, Any]]) -> str:
    """Hash the exact ordered tool contract sent to the provider."""
    return stable_hash(list(tools))


async def get_prefix_snapshot(
    db: AsyncSession,
    session_id: UUID,
    profile_key: str,
) -> SessionPrefixSnapshot | None:
    stmt = (
        select(SessionPrefixSnapshot)
        .where(col(SessionPrefixSnapshot.session_id) == session_id)
        .where(col(SessionPrefixSnapshot.profile_key) == profile_key)
        .limit(1)
    )
    return (await db.exec(stmt)).first()


async def pin_prefix_snapshot(
    db: AsyncSession,
    *,
    session_id: UUID,
    profile_key: str,
    system_prompt: str,
    tools_hash: str,
    tools: list[dict],
) -> SessionPrefixSnapshot:
    """Insert or rotate a profile snapshot in the caller's transaction."""
    current = await get_prefix_snapshot(db, session_id, profile_key)
    system_hash = stable_hash(system_prompt)
    if current is None:
        current = SessionPrefixSnapshot(
            session_id=session_id,
            profile_key=profile_key,
            system_prompt=system_prompt,
            system_hash=system_hash,
            tools_hash=tools_hash,
            tools=tools,
            revision=1,
        )
        db.add(current)
        await db.flush()
        return current

    current.system_prompt = system_prompt
    current.system_hash = system_hash
    current.tools_hash = tools_hash
    current.tools = tools
    current.revision += 1
    db.add(current)
    await db.flush()
    return current


async def advance_prefix_snapshot(
    db: AsyncSession,
    *,
    session_id: UUID,
    profile_key: str,
    watermark_message_id: UUID,
) -> None:
    """Advance the completed-message watermark without rotating the prefix."""
    current = await get_prefix_snapshot(db, session_id, profile_key)
    if current is None:
        return
    current.watermark_message_id = watermark_message_id
    current.updated_at = datetime.now(timezone.utc)
    db.add(current)
    await db.flush()


__all__ = [
    "advance_prefix_snapshot",
    "get_prefix_snapshot",
    "pin_prefix_snapshot",
    "prefix_profile_key",
    "stable_hash",
    "tool_contract_hash",
]
