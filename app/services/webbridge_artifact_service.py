"""Retention and path safety for browser-created WebBridge artifacts."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from loguru import logger
from sqlalchemy import update
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.paths import uploads_dir
from app.models.chat import SessionMessage

_CLEANUP_INTERVAL_SECONDS = 3600


@dataclass(frozen=True, slots=True)
class _ArtifactCleanup:
    message_id: UUID
    session_id: UUID
    extra: dict[str, Any]
    attachments: tuple[dict[str, Any], ...]


def artifact_expired(value: Any, *, now: datetime | None = None) -> bool:
    artifact = value.get("webbridge_artifact") if isinstance(value, dict) else None
    expires_at = artifact.get("expires_at") if isinstance(artifact, dict) else None
    if not isinstance(expires_at, str):
        return False
    try:
        expiry = datetime.fromisoformat(expires_at)
    except ValueError:
        return True
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    return expiry <= (now or datetime.now(timezone.utc))


def resolve_attachment_path(
    message_session_id: UUID | str,
    value: dict[str, Any],
) -> Path:
    """Resolve canonical attachment metadata inside approved app storage."""
    filename = str(value.get("filename") or "")
    if not filename or Path(filename).name != filename:
        raise ValueError("Invalid attachment filename.")
    local_root = uploads_dir(str(message_session_id)).resolve(strict=False)
    storage_root = Path(settings.EVOFLUX_WORKSPACE_DIR).resolve(strict=False)
    canonical = value.get("path") or value.get("workspace_path")
    if isinstance(canonical, str) and canonical:
        resolved = Path(canonical).resolve(strict=False)
        if resolved.name != filename:
            raise ValueError("Attachment path does not match its filename.")
        try:
            resolved.relative_to(storage_root)
        except ValueError:
            try:
                resolved.relative_to(local_root)
            except ValueError as exc:
                raise ValueError(
                    "Attachment path escapes application storage."
                ) from exc
        if resolved.exists():
            return resolved
    fallback = (local_root / filename).resolve(strict=False)
    fallback.relative_to(local_root)
    return fallback


async def delete_artifact_bytes(
    message_session_id: UUID | str,
    value: dict[str, Any],
) -> None:
    try:
        path = resolve_attachment_path(message_session_id, value)
    except ValueError:
        return
    if path.exists() and path.is_file():
        await asyncio.to_thread(path.unlink)


async def cleanup_expired_artifacts(
    db: AsyncSession,
    *,
    now: datetime | None = None,
) -> int:
    """Delete expired bytes and tombstone metadata across all message history."""
    plan = await _plan_expired_artifact_cleanup(db, now=now)
    return await _apply_artifact_cleanup(db, plan)


async def _plan_expired_artifact_cleanup(
    db: AsyncSession,
    *,
    now: datetime | None = None,
) -> list[_ArtifactCleanup]:
    """Project only metadata columns; message bodies can occupy hundreds of MB."""

    rows = (
        await db.exec(
            select(
                SessionMessage.id, SessionMessage.session_id, SessionMessage.extra
            ).where(col(SessionMessage.extra).is_not(None))
        )
    ).all()
    plan: list[_ArtifactCleanup] = []
    for message_id, session_id, raw_extra in rows:
        extra = dict(raw_extra or {})
        attachments = extra.get("attachments")
        if not isinstance(attachments, list):
            continue
        updated_attachments = list(attachments)
        expired: list[dict[str, Any]] = []
        changed = False
        for index, value in enumerate(attachments):
            if not isinstance(value, dict):
                continue
            attachment = cast(dict[str, Any], value)
            if attachment.get("deleted_at") or not artifact_expired(
                attachment, now=now
            ):
                continue
            updated = dict(attachment)
            updated["deleted_at"] = (now or datetime.now(timezone.utc)).isoformat()
            updated_attachments[index] = updated
            expired.append(attachment)
            changed = True
        if changed:
            extra["attachments"] = updated_attachments
            plan.append(
                _ArtifactCleanup(
                    message_id=message_id,
                    session_id=session_id,
                    extra=extra,
                    attachments=tuple(expired),
                )
            )
    return plan


async def _apply_artifact_cleanup(
    db: AsyncSession,
    plan: list[_ArtifactCleanup],
) -> int:
    cleaned = 0
    for item in plan:
        for attachment in item.attachments:
            await delete_artifact_bytes(item.session_id, attachment)
            cleaned += 1
        await db.exec(
            update(SessionMessage)
            .where(col(SessionMessage.id) == item.message_id)
            .values(extra=item.extra)
        )
    if plan:
        await db.commit()
    return cleaned


async def run_artifact_cleanup_loop() -> None:
    """Sweep once at startup and hourly until cancelled."""
    while True:
        try:
            from app.core import db as db_module

            async with db_module.read_session_factory() as db:
                plan = await _plan_expired_artifact_cleanup(db)
            if plan:
                async with db_module.async_session_factory() as db:
                    cleaned = await _apply_artifact_cleanup(db, plan)
            else:
                cleaned = 0
            if cleaned:
                logger.info("webbridge_artifacts_expired count={}", cleaned)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - maintenance must stay best-effort
            logger.warning("webbridge_artifact_cleanup_failed error={}", exc)
        await asyncio.sleep(_CLEANUP_INTERVAL_SECONDS)
