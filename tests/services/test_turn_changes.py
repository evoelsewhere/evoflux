"""Unit tests for turn_changes tracker + plan step enrichment."""

from __future__ import annotations

from app.services.turn_changes import (
    begin_turn,
    clear_session,
    enrich_plan_step,
    flush_turn,
    get_latest,
    record_tool_change,
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


def test_enrich_plan_step_includes_path() -> None:
    step = enrich_plan_step("edit", {"file_path": "app/x.py"}, "Edit app/x.py")
    assert step["tool"] == "edit"
    assert step["path"] == "app/x.py"
    assert step["summary"] == "Edit app/x.py"


def test_enrich_plan_step_patch_path() -> None:
    patch = "\n".join(
        [
            "*** Begin Patch",
            "*** Update File: app/y.py",
            "@@",
            "-a",
            "+b",
            "*** End Patch",
        ]
    )
    step = enrich_plan_step("patch", {"patch_text": patch}, "Patch app/y.py")
    assert step["path"] == "app/y.py"
    assert step.get("diff_stat")
