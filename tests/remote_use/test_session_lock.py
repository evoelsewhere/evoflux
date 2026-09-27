"""Single-device session lock semantics: conflict, heartbeat, idle, release."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services import remote_use_service as service

UTC = timezone.utc
T0 = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


async def test_second_claim_from_another_session_conflicts() -> None:
    await service.claim("alice@example.com", "phone", now=T0)
    with pytest.raises(service.RemoteUseConflict) as excinfo:
        await service.claim("bob@example.com", "tablet", now=T0 + timedelta(minutes=1))
    body = excinfo.value.body()
    assert set(body) == {"detail", "current", "live_window_minutes"}
    assert body["current"]["user_login"] == "alice@example.com"
    assert body["current"]["device_label"] == "phone"
    assert body["live_window_minutes"] == 30
    assert "alice@example.com" in body["detail"]
    # The live window is reported as absolute timestamps the UI can render.
    assert datetime.fromisoformat(body["current"]["claimed_at"]) == T0


async def test_reclaim_same_identity_is_a_heartbeat_not_a_conflict() -> None:
    first = await service.claim("alice@example.com", "phone", now=T0)
    again = await service.claim(
        "alice@example.com", "phone", now=T0 + timedelta(minutes=2)
    )
    assert again.id == first.id
    assert again.last_seen_at == T0 + timedelta(minutes=2)
    assert again.idle_expires_at == T0 + timedelta(minutes=2) + service.IDLE_WINDOW
    assert again.released_at is None


async def test_heartbeat_updates_last_seen_only_for_own_session() -> None:
    await service.claim("alice@example.com", "phone", now=T0)
    later = T0 + timedelta(minutes=5)
    beat = await service.heartbeat("alice@example.com", "phone", now=later)
    assert beat is not None
    assert beat.last_seen_at == later
    assert beat.idle_expires_at == later + service.IDLE_WINDOW
    # A different pair's heartbeat never touches (or resurrects) the holder.
    assert await service.heartbeat("bob@example.com", "tablet", now=later) is None


async def test_idle_sweep_releases_sessions_older_than_30_minutes() -> None:
    stale = await service.claim("alice@example.com", "phone", now=T0)
    assert stale.released_at is None
    expired = T0 + timedelta(minutes=31)
    assert await service.sweep_idle(now=expired) == 1
    assert await service.get_lock_holder(now=expired) is None
    # The holder is gone for good: releasing again finds nothing.
    assert await service.heartbeat("alice@example.com", "phone", now=expired) is None


async def test_idle_expired_session_never_blocks_the_next_claim() -> None:
    await service.claim("alice@example.com", "phone", now=T0)
    bob = await service.claim(
        "bob@example.com", "tablet", now=T0 + timedelta(minutes=31)
    )
    assert bob.user_login == "bob@example.com"
    assert await service.get_lock_holder(now=T0 + timedelta(minutes=31)) == bob


async def test_release_frees_the_lock_and_is_pair_scoped() -> None:
    held = await service.claim("alice@example.com", "phone", now=T0)
    released_at = T0 + timedelta(minutes=1)
    released = await service.release("alice@example.com", "phone", now=released_at)
    assert released is not None
    assert released.id == held.id
    assert released.released_at == released_at
    assert await service.get_lock_holder(now=released_at) is None
    # Releasing a pair that holds nothing is a no-op.
    assert await service.release("bob@example.com", "tablet", now=released_at) is None


async def test_force_release_retires_every_live_session() -> None:
    await service.claim("alice@example.com", "phone", now=T0)
    later = T0 + timedelta(minutes=2)
    assert await service.force_release(now=later) == 1
    assert await service.get_lock_holder(now=later) is None
    assert await service.force_release(now=later) == 0
    # The lock is free for a different device immediately afterwards.
    bob = await service.claim(
        "bob@example.com", "tablet", now=later + timedelta(minutes=1)
    )
    assert bob.user_login == "bob@example.com"


async def test_claim_requires_a_login() -> None:
    with pytest.raises(ValueError):
        await service.claim("   ", "phone", now=T0)
