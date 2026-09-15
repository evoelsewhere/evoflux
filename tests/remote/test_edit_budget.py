"""Tests for app/remote/edit_budget.py — the shared per-connection live-mode
edit throttle (AC-57)."""

from __future__ import annotations

from app.remote.edit_budget import LIVE_EDIT_INTERVAL, EditBudget


def test_first_edit_for_a_key_is_always_allowed() -> None:
    budget = EditBudget()

    assert budget.should_edit(connection_id="conn-1", key="turn-1", text="a", now=0.0)


def test_unchanged_text_is_skipped_even_when_budget_allows_it() -> None:
    budget = EditBudget()
    budget.record_edit(connection_id="conn-1", key="turn-1", text="a", now=0.0)

    assert not budget.should_edit(
        connection_id="conn-1", key="turn-1", text="a", now=10.0
    )


def test_changed_text_is_throttled_within_the_interval() -> None:
    budget = EditBudget()
    budget.record_edit(connection_id="conn-1", key="turn-1", text="a", now=0.0)

    allowed = budget.should_edit(
        connection_id="conn-1", key="turn-1", text="b", now=LIVE_EDIT_INTERVAL - 0.1
    )

    assert not allowed


def test_changed_text_is_allowed_once_the_interval_elapses() -> None:
    budget = EditBudget()
    budget.record_edit(connection_id="conn-1", key="turn-1", text="a", now=0.0)

    allowed = budget.should_edit(
        connection_id="conn-1", key="turn-1", text="b", now=LIVE_EDIT_INTERVAL + 0.1
    )

    assert allowed


def test_budget_is_shared_across_concurrent_turns_on_one_connection() -> None:
    budget = EditBudget()
    budget.record_edit(connection_id="conn-1", key="turn-1", text="a", now=0.0)

    # A second, distinct turn on the SAME connection is still throttled by
    # the first turn's recent edit — the budget is per-connection, not
    # per-turn (AC-57: "one shared per-connection edit budget across all
    # concurrently live turns").
    allowed = budget.should_edit(connection_id="conn-1", key="turn-2", text="x", now=0.5)

    assert not allowed


def test_a_different_connection_has_its_own_independent_budget() -> None:
    budget = EditBudget()
    budget.record_edit(connection_id="conn-1", key="turn-1", text="a", now=0.0)

    allowed = budget.should_edit(connection_id="conn-2", key="turn-2", text="x", now=0.5)

    assert allowed


def test_rate_limit_pushes_the_next_allowed_edit_out_by_retry_after() -> None:
    budget = EditBudget()
    budget.record_edit(connection_id="conn-1", key="turn-1", text="a", now=0.0)
    budget.note_rate_limited(connection_id="conn-1", retry_after=30.0, now=1.0)

    still_blocked = budget.should_edit(
        connection_id="conn-1", key="turn-1", text="b", now=LIVE_EDIT_INTERVAL + 0.1
    )
    allowed_after_backoff = budget.should_edit(
        connection_id="conn-1", key="turn-1", text="b", now=31.5
    )

    assert not still_blocked
    assert allowed_after_backoff


def test_rate_limit_never_shortens_an_already_longer_cooldown() -> None:
    budget = EditBudget()
    budget.record_edit(connection_id="conn-1", key="turn-1", text="a", now=0.0)
    # A tiny retry_after must not undercut the normal LIVE_EDIT_INTERVAL cooldown.
    budget.note_rate_limited(connection_id="conn-1", retry_after=0.01, now=0.5)

    allowed = budget.should_edit(
        connection_id="conn-1", key="turn-1", text="b", now=LIVE_EDIT_INTERVAL - 0.1
    )

    assert not allowed


def test_discard_forgets_a_finished_turns_last_text() -> None:
    budget = EditBudget()
    budget.record_edit(connection_id="conn-1", key="turn-1", text="a", now=0.0)
    budget.discard("turn-1")

    # The connection-level cooldown still applies (discard only forgets the
    # per-key last-text bookkeeping, not the shared connection throttle),
    # but a differently-keyed re-observation of the same text is no longer
    # considered "unchanged".
    allowed = budget.should_edit(
        connection_id="conn-1", key="turn-1", text="a", now=LIVE_EDIT_INTERVAL + 1
    )

    assert allowed
