from __future__ import annotations

from pathlib import Path

import pytest

from app.services.asdd_service import (
    AsddActionBlocked,
    action_prompt,
    approve,
    catalogue_for,
    create_change,
    derive_change_id,
    detail_payload,
    list_changes,
    prepare_action,
    record_handoff_evidence,
)
from app.services.asdd_setup_service import (
    AsddRepositoryTarget,
    initialize_repositories,
)
from app.services.asdd_store import AsddCatalogue
from app.services.asdd_spec_format import parse_delta

DELTA = """## ADDED Requirements

### Requirement: Slug identity

A change SHALL be identified by its directory name.

#### Scenario: Two chats open the same change

- **WHEN** two Coding chats point at the same change
- **THEN** both read and write the same change folder
"""


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    initialize_repositories([AsddRepositoryTarget(path=str(root), name="repo")])
    return root


@pytest.fixture
def catalogue(repository: Path) -> AsddCatalogue:
    return catalogue_for(repository)


def seeded(catalogue: AsddCatalogue, *, status: str | None = None) -> str:
    create_change(
        catalogue,
        title="Add user auth",
        change_id="add-user-auth",
        risk="standard",
        capabilities=["user-auth"],
    )
    if status is not None:
        catalogue.set_status("add-user-auth", status)
    return "add-user-auth"


def test_the_catalogue_location_comes_from_the_repository_manifest(
    repository: Path,
) -> None:
    catalogue = catalogue_for(repository)

    assert catalogue.base_path == repository / "documents" / "asdd"


def test_a_change_id_is_derived_from_the_title(repository: Path) -> None:
    assert derive_change_id("Add user authentication", taken=set()) == (
        "add-user-authentication"
    )
    assert derive_change_id("Add user auth", taken={"add-user-auth"}) == (
        "add-user-auth-2"
    )


def test_an_unreadable_change_is_skipped_rather_than_blanking_the_list(
    catalogue: AsddCatalogue,
) -> None:
    seeded(catalogue)
    broken = catalogue.changes_path / "broken"
    broken.mkdir()
    (broken / "proposal.md").write_text("---\nchange: [\n---\n", encoding="utf-8")

    listed = list_changes(catalogue)

    assert [item["change_id"] for item in listed["changes"]] == ["add-user-auth"]


def test_approving_an_artifact_the_files_do_not_support_is_blocked(
    catalogue: AsddCatalogue,
) -> None:
    change_id = seeded(catalogue, status="proposed")
    approve(catalogue, change_id, "proposal")
    catalogue.set_status(change_id, "specified")

    with pytest.raises(AsddActionBlocked) as raised:
        approve(catalogue, change_id, "specs")

    assert raised.value.blockers[0]["code"] == "missing_artifact"


def test_approving_a_change_that_is_not_at_the_gate_is_blocked(
    catalogue: AsddCatalogue,
) -> None:
    # The endpoint takes the artifact from the URL, so it can be asked for an
    # approval the rail never offered. A freshly created change carries a
    # proposal template, which an existence check alone accepts.
    change_id = seeded(catalogue)

    with pytest.raises(AsddActionBlocked, match="still at `drafting`"):
        approve(catalogue, change_id, "proposal")

    assert catalogue.read_change(change_id).artifacts.status == "drafting"


def test_an_action_the_phase_does_not_offer_is_blocked(
    catalogue: AsddCatalogue,
) -> None:
    change_id = seeded(catalogue)

    with pytest.raises(AsddActionBlocked, match="not offered"):
        prepare_action(catalogue, change_id, "start_implementation")


def test_a_phase_prompt_names_the_skill_the_folder_and_no_identifier(
    catalogue: AsddCatalogue,
) -> None:
    change_id = seeded(catalogue)
    record = catalogue.read_change(change_id)

    prompt = action_prompt(catalogue, record, "draft_proposal")

    assert "$asdd-propose" in prompt
    assert "documents/asdd/changes/add-user-auth" in prompt
    assert "documents/asdd/specs" in prompt
    for absent in ("hash", "revision", "session"):
        assert absent not in prompt.lower()


def test_the_detail_payload_carries_the_rail_and_the_artifacts(
    catalogue: AsddCatalogue,
) -> None:
    change_id = seeded(catalogue)
    catalogue.write_delta(change_id, "user-auth", parse_delta(DELTA))

    payload = detail_payload(catalogue, catalogue.read_change(change_id))

    assert payload["rail"]["primary_action"] == "draft_proposal"
    assert payload["deltas"][0]["added"] == ["Slug identity"]
    assert payload["change"]["change_id"] == change_id


def test_a_handoff_with_every_requirement_passing_records_machine_evidence(
    repository: Path, catalogue: AsddCatalogue
) -> None:
    change_id = seeded(catalogue)

    record = record_handoff_evidence(
        repository,
        change_id=change_id,
        task_id="task-1",
        recipient="coder#1",
        artifact={
            "criteria_results": [{"criterion_id": "Slug identity", "status": "passed"}],
            "completion_contract": {"passed": True},
        },
        owned_requirements=["Slug identity"],
    )

    assert record is not None
    evidence = detail_payload(catalogue, record)["evidence"][0]
    assert evidence["kind"] == "machine"
    assert evidence["result"] == "passed"
    assert evidence["requirement"] == "Slug identity"


def test_a_handoff_without_a_completion_contract_is_review_evidence_only(
    repository: Path, catalogue: AsddCatalogue
) -> None:
    """Self-reported checks never become machine proof."""

    change_id = seeded(catalogue)

    record = record_handoff_evidence(
        repository,
        change_id=change_id,
        task_id="task-1",
        recipient="coder#1",
        artifact={
            "criteria_results": [{"criterion_id": "Slug identity", "status": "passed"}]
        },
        owned_requirements=["Slug identity"],
    )

    assert record is not None
    assert detail_payload(catalogue, record)["evidence"][0]["kind"] == "review"


def test_a_handoff_missing_a_requirement_result_fails(
    repository: Path, catalogue: AsddCatalogue
) -> None:
    change_id = seeded(catalogue)

    record = record_handoff_evidence(
        repository,
        change_id=change_id,
        task_id="task-1",
        recipient="coder#1",
        artifact={"criteria_results": []},
        owned_requirements=["Slug identity"],
    )

    assert record is not None
    assert detail_payload(catalogue, record)["evidence"][0]["result"] == "failed"


def test_a_handoff_for_a_change_that_is_gone_is_dropped_not_raised(
    repository: Path, catalogue: AsddCatalogue
) -> None:
    assert (
        record_handoff_evidence(
            repository,
            change_id="never-existed",
            task_id="task-1",
            recipient="coder#1",
            artifact={},
            owned_requirements=["Slug identity"],
        )
        is None
    )


def test_hand_written_evidence_with_an_unquoted_timestamp_is_serializable(
    catalogue: AsddCatalogue,
) -> None:
    # An agent writes evidence pages with Write, following the template in the
    # asdd-verify skill — which spells `recorded:` unquoted. YAML hands that back
    # as a datetime, and letting it reach the API contract returned a 500 for the
    # whole change rather than one unreadable page.
    change_id = seeded(catalogue)
    page = catalogue.change_path(change_id) / "evidence" / "web-filter-tests.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(
        "---\n"
        "id: web-filter-tests\n"
        "kind: machine\n"
        "result: passed\n"
        "requirement: Narrow the catalogue by query\n"
        "recorded: 2026-09-17T07:35:00Z\n"
        "---\n"
        "\n"
        "`bun run test` — 4 passed.\n",
        encoding="utf-8",
    )

    payload = detail_payload(catalogue, catalogue.read_change(change_id))

    assert payload["evidence"] == [
        {
            "id": "web-filter-tests",
            "kind": "machine",
            "result": "passed",
            "requirement": "Narrow the catalogue by query",
            "recorded": "2026-09-17T07:35:00Z",
            "summary": "`bun run test` — 4 passed.",
        }
    ]
    assert payload["change"]["evidence_count"] == 1
