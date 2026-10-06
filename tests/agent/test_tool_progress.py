from __future__ import annotations

from app.agent.agent_loop.progress import ToolProgressTracker
from app.agent.tools.registry import Tool


def test_progress_tracker_warns_then_blocks_repeated_read_results_across_changed_args():
    tool = Tool(
        lambda query: query,
        name="search",
        read_only=True,
        progress_scope=lambda args: str(args["source"]),
    )
    tracker = ToolProgressTracker()
    metadata: dict = {}

    first = {"source": "policy", "query": "policy"}
    second = {"source": "policy", "query": "policy rules"}
    third = {"source": "policy", "query": "policy details"}

    assert tracker.should_block(tool, first, metadata) is None
    tracker.record(tool, first, "same result", metadata)
    assert tracker.should_block(tool, second, metadata) is None
    tracker.record(tool, second, "same result", metadata)

    reason = tracker.should_block(tool, third, metadata)
    assert reason is not None
    assert "no progress" in reason.casefold()
    assert tracker.snapshot(metadata)["blocked"] == 1


def test_progress_tracker_blocks_repeated_identical_safe_read_arguments():
    tool = Tool(
        lambda query: query,
        name="search",
        read_only=True,
        progress_scope=lambda args: str(args["source"]),
    )
    tracker = ToolProgressTracker()
    metadata: dict = {}
    args = {"source": "policy", "query": "policy"}

    tracker.record(tool, args, "same result", metadata)
    assert tracker.should_block(tool, args, metadata) is None
    tracker.record(tool, args, "same result", metadata)

    reason = tracker.should_block(tool, args, metadata)
    assert reason is not None
    assert "no progress" in reason.casefold()


def test_progress_tracker_resets_when_result_changes_and_fails_open_without_scope():
    tool = Tool(
        lambda query: query,
        name="search",
        read_only=True,
        progress_scope=lambda args: str(args["source"]),
    )
    unscoped = Tool(lambda query: query, name="unscoped", read_only=True)
    tracker = ToolProgressTracker()
    metadata: dict = {}

    tracker.record(tool, {"source": "policy", "query": "a"}, "first", metadata)
    tracker.record(tool, {"source": "policy", "query": "b"}, "second", metadata)
    tracker.record(tool, {"source": "policy", "query": "c"}, "third", metadata)

    assert (
        tracker.should_block(tool, {"source": "policy", "query": "d"}, metadata) is None
    )
    assert tracker.should_block(unscoped, {"query": "x"}, metadata) is None


def test_progress_tracker_never_blocks_side_effecting_tools():
    tool = Tool(
        lambda value: value,
        name="write",
        progress_scope=lambda args: str(args["value"]),
    )
    tracker = ToolProgressTracker()
    metadata: dict = {}
    args = {"value": "same-target"}

    tracker.record(tool, args, "same result", metadata)
    tracker.record(
        tool, {"value": "same-target", "retry": True}, "same result", metadata
    )

    assert tracker.should_block(tool, {"value": "same-target"}, metadata) is None


def test_unclassified_read_errors_fail_open():
    tool = Tool(
        lambda path: path,
        name="read",
        read_only=True,
        progress_scope=lambda args: str(args["path"]),
    )
    tracker = ToolProgressTracker()
    metadata: dict = {}
    args = {"path": "src/module.py"}

    tracker.record(tool, args, "Error: invalid range", metadata)
    assert tracker.should_block(tool, args, metadata) is None
    tracker.record(tool, args, "Error: invalid range", metadata)
    assert tracker.should_block(tool, args, metadata) is None


def test_unclassified_error_resets_success_evidence_for_its_scope():
    tool = Tool(
        lambda query: query,
        name="search",
        read_only=True,
        progress_scope=lambda args: str(args["source"]),
    )
    tracker = ToolProgressTracker()
    metadata: dict = {}
    first = {"source": "policy", "query": "one"}
    second = {"source": "policy", "query": "two"}

    tracker.record(tool, first, "same result", metadata)
    tracker.record(tool, second, "Error: unclassified", metadata)
    tracker.record(tool, {**second, "query": "three"}, "same result", metadata)

    assert tracker.should_block(tool, {**second, "query": "four"}, metadata) is None


def test_terminal_read_error_blocks_repetition_without_retry():
    tool = Tool(
        lambda path: path,
        name="read",
        read_only=True,
        progress_scope=lambda args: str(args["path"]),
        progress_error_policy=lambda result: (
            "terminal" if "permission denied" in result.casefold() else None
        ),
    )
    tracker = ToolProgressTracker()
    metadata: dict = {}
    args = {"path": "src/module.py"}

    tracker.record(tool, args, "Error: permission denied", metadata)

    reason = tracker.should_block(tool, {**args, "line": 2}, metadata)
    assert reason is not None
    assert "terminal" in reason.casefold()


def test_transient_read_error_allows_one_retry_then_blocks():
    tool = Tool(
        lambda path: path,
        name="read",
        read_only=True,
        progress_scope=lambda args: str(args["path"]),
        progress_error_policy=lambda result: (
            "retry_once" if "temporarily unavailable" in result.casefold() else None
        ),
    )
    tracker = ToolProgressTracker()
    metadata: dict = {}
    args = {"path": "src/module.py"}

    tracker.record(tool, args, "Error: temporarily unavailable", metadata)
    assert tracker.should_block(tool, args, metadata) is None
    tracker.record(tool, args, "Error: temporarily unavailable", metadata)

    reason = tracker.should_block(tool, args, metadata)
    assert reason is not None
    assert "after one retry" in reason.casefold()
