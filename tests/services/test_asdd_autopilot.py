"""Autopilot carries a change; it does not merely sign for one.

Before this driver, `autopilot: true` let an agent clear a gate and then the
turn ended — the rail put a Continue button up and waited for a person. These
tests pin the two halves of the replacement: which phase runs next, and when
the chain has to stop.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.asdd_autopilot import (
    MAX_CHAIN_HOPS,
    AutopilotHop,
    change_id_in,
    next_hop,
    stop_reason,
)
from app.services.asdd_service import catalogue_for, create_change, set_autopilot
from app.services.asdd_setup_service import (
    AsddRepositoryTarget,
    initialize_repositories,
)


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    initialize_repositories(
        [AsddRepositoryTarget(path=str(root), name="repo", display_name="Repo")]
    )
    return root


def open_change(root: Path, *, autopilot: bool = True) -> str:
    catalogue = catalogue_for(root)
    record = create_change(
        catalogue,
        title="Add note search",
        risk="standard",
        capabilities=["note-search"],
        problem="Nobody can find a note.",
        outcome="A note is findable by title.",
    )
    if autopilot:
        set_autopilot(catalogue, record.change_id, enabled=True)
    return record.change_id


def set_status(root: Path, change_id: str, status: str) -> None:
    catalogue = catalogue_for(root)
    catalogue.set_status(change_id, status)


def raise_hold(root: Path, change_id: str, *, gate: str, reason: str) -> None:
    """Write a hold the way an agent does — into the proposal's front matter."""
    proposal = catalogue_for(root).change_path(change_id) / "proposal.md"
    text = proposal.read_text(encoding="utf-8")
    marker = "status:"
    insert = f"hold:\n  gate: {gate}\n  reason: {reason}\n"
    proposal.write_text(text.replace(marker, insert + marker, 1), encoding="utf-8")


# ── binding a session to a change ────────────────────────────────────────


class TestChangeIdInPrompt:
    """The transcript is the binding — no second identifier (rule 2)."""

    def test_a_phase_prompt_names_its_change(self) -> None:
        prompt = (
            "$asdd-specify\n\nWork on ASDD change `add-note-search` — “Add note "
            "search”.\nIts folder is `documents/asdd/changes/add-note-search`."
        )
        assert change_id_in(prompt) == "add-note-search"

    def test_ordinary_conversation_names_none(self) -> None:
        assert change_id_in("can you look at the search code") is None
        assert change_id_in("") is None
        assert change_id_in(None) is None


# ── which phase runs next ────────────────────────────────────────────────


class TestNextHop:
    def test_a_carried_change_gets_its_next_phase(self, repository: Path) -> None:
        change_id = open_change(repository)
        set_status(repository, change_id, "proposed")

        hop = next_hop(repository, change_id)

        assert hop is not None
        assert hop.change_id == change_id
        assert hop.skill == "asdd-specify"
        assert "ASDD change `add-note-search`" in hop.prompt

    def test_a_change_without_autopilot_is_not_carried(
        self, repository: Path
    ) -> None:
        """The button stays the user's when they did not ask for autopilot."""
        change_id = open_change(repository, autopilot=False)
        set_status(repository, change_id, "proposed")

        assert next_hop(repository, change_id) is None

    def test_a_held_change_stops_the_chain(self, repository: Path) -> None:
        """A hold is the agent asking for a person; driving past it is worse
        than not driving at all."""
        change_id = open_change(repository)
        set_status(repository, change_id, "proposed")
        raise_hold(repository, change_id, gate="specs", reason="scope unclear")

        assert next_hop(repository, change_id) is None

    def test_a_ready_change_waits_for_a_person(self, repository: Path) -> None:
        """Archiving folds the catalogue, and that is nobody's but the user's."""
        change_id = open_change(repository)
        set_status(repository, change_id, "ready")

        assert next_hop(repository, change_id) is None

    def test_a_repository_without_asdd_is_not_driven(self, tmp_path: Path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()

        assert next_hop(plain, "add-note-search") is None

    def test_an_unknown_change_is_not_driven(self, repository: Path) -> None:
        assert next_hop(repository, "no-such-change") is None


# ── the chain's own bounds ───────────────────────────────────────────────


def hop_at(progress: tuple[str, int, int]) -> AutopilotHop:
    return AutopilotHop(
        change_id="add-note-search",
        action="autopilot_continue",
        skill="asdd-specify",
        prompt="…",
        progress=progress,
    )


class TestChainBounds:
    def test_a_first_hop_runs(self) -> None:
        assert stop_reason(0, None, hop_at(("proposed", 0, 0))) is None

    def test_progress_earns_another_hop(self) -> None:
        previous = ("proposed", 0, 0)
        assert stop_reason(3, previous, hop_at(("specified", 0, 0))) is None

    def test_a_turn_that_moved_nothing_ends_the_chain(self) -> None:
        """Otherwise a stuck change re-runs its phase every turn, forever —
        which is the compaction failure wearing a different hat."""
        previous = ("implementing", 2, 1)
        assert stop_reason(3, previous, hop_at(previous)) == "no_progress"

    def test_the_chain_is_capped(self) -> None:
        assert (
            stop_reason(MAX_CHAIN_HOPS, ("proposed", 0, 0), hop_at(("specified", 0, 0)))
            == "chain_capped"
        )
