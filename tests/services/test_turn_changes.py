"""Unit tests for the turn_changes tracker."""

from __future__ import annotations

from uuid import uuid7  # ty: ignore[unresolved-import] - backported in app.__init__

import pytest

from app.services.turn_changes import (
    MESSAGE_EXTRA_KEY,
    begin_turn,
    clear_session,
    flush_turn,
    get_latest,
    persist_snapshot,
    record_tool_change,
    take_anchor,
)


def test_record_and_flush_turn_changes() -> None:
    sid = "sess-test-1"
    clear_session(sid)
    begin_turn(sid)
    record_tool_change(
        sid, "write", {"file_path": "web/src/a.tsx", "content": "a\nb\n"}
    )
    record_tool_change(
        sid, "edit", {"path": "web/src/b.tsx", "old_string": "x", "new_string": "x\ny"}
    )
    record_tool_change(sid, "rm", {"file_path": "old.txt"})
    snap = flush_turn(sid)
    assert snap is not None
    assert snap.session_id == sid
    paths = {f.path for f in snap.files}
    assert paths == {"web/src/a.tsx", "web/src/b.tsx", "old.txt"}
    by_path = {f.path: f.status for f in snap.files}
    assert by_path["web/src/a.tsx"] == "added"
    assert by_path["web/src/b.tsx"] == "modified"
    assert by_path["old.txt"] == "removed"
    assert snap.additions >= 1
    assert get_latest(sid) is snap
    assert flush_turn(sid) is None


def test_patch_records_paths_and_stats() -> None:
    sid = "sess-patch"
    clear_session(sid)
    begin_turn(sid)
    patch = "\n".join(
        [
            "*** Begin Patch",
            "*** Add File: new.py",
            "+print(1)",
            "+print(2)",
            "*** Update File: old.py",
            "@@",
            "-a",
            "+b",
            "*** End Patch",
        ]
    )
    record_tool_change(sid, "patch", {"patch_text": patch})
    snap = flush_turn(sid)
    assert snap is not None
    by_path = {f.path: f for f in snap.files}
    assert set(by_path) == {"new.py", "old.py"}
    assert by_path["new.py"].status == "added"
    assert by_path["new.py"].additions == 2
    assert by_path["old.py"].status == "modified"
    assert (by_path["old.py"].additions or 0) >= 1
    assert (by_path["old.py"].deletions or 0) >= 1


def test_rm_then_write_becomes_added() -> None:
    sid = "sess-recreate"
    clear_session(sid)
    begin_turn(sid)
    record_tool_change(sid, "rm", {"file_path": "x.txt"})
    record_tool_change(sid, "write", {"file_path": "x.txt", "content": "hi"})
    snap = flush_turn(sid)
    assert snap is not None
    assert len(snap.files) == 1
    assert snap.files[0].status == "added"


def test_anchor_is_taken_once() -> None:
    sid = "sess-anchor"
    clear_session(sid)
    begin_turn(sid, "msg-1")
    assert take_anchor(sid) == "msg-1"
    assert take_anchor(sid) is None
    begin_turn(sid)
    assert take_anchor(sid) is None


@pytest.mark.asyncio
@pytest.mark.usefixtures("setup_db")
async def test_snapshot_is_saved_on_the_turns_user_message() -> None:
    """The "Edited N files" summary outlives the live stream."""
    import app.core.db as _db
    from app.models.chat import ChatSession, SessionMessage

    async with _db.async_session_factory() as db:
        session = ChatSession(mode="coding")
        db.add(session)
        await db.flush()
        message = SessionMessage(
            session_id=session.id, role="user", content="edit", extra={"model": "m"}
        )
        db.add(message)
        await db.commit()
        sid, message_id = str(session.id), message.id

    clear_session(sid)
    begin_turn(sid, str(message_id))
    record_tool_change(sid, "write", {"path": "src/util.ts", "content": "x\n"})
    snap = flush_turn(sid)
    anchor = take_anchor(sid)
    assert snap is not None and anchor == str(message_id)

    async with _db.async_session_factory() as db:
        assert await persist_snapshot(db, anchor, snap) is True
    async with _db.async_session_factory() as db:
        row = await db.get(SessionMessage, message_id)
    assert row is not None and row.extra is not None
    assert row.extra["model"] == "m"
    assert row.extra[MESSAGE_EXTRA_KEY]["files"] == [
        {"path": "src/util.ts", "status": "added", "additions": 2, "deletions": 0}
    ]

    async with _db.async_session_factory() as db:
        assert await persist_snapshot(db, str(uuid7()), snap) is False
