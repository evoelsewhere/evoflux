from __future__ import annotations

import pytest

from app.services.asdd_lifecycle import (
    ChangeArtifacts,
    action_rail,
    archive_blockers,
    artifact_blockers,
    declared_status_problems,
    required_approvals,
    status_after_approval,
)


def artifacts(**overrides: object) -> ChangeArtifacts:
    values: dict[str, object] = {
        "change_id": "add-user-auth",
        "title": "Add user authentication",
        "status": "drafting",
        "risk": "standard",
        "capabilities": ["user-auth"],
        "approvals": {
            "proposal": None,
            "specs": None,
            "design": None,
            "tasks": None,
        },
        "has_proposal": True,
        "has_design": False,
        "has_tasks": False,
        "delta_capabilities": [],
        "spec_problems": [],
        "tasks_total": 0,
        "tasks_done": 0,
        "evidence_ids": [],
        "review_recorded": False,
    }
    values.update(overrides)
    return ChangeArtifacts(**values)  # type: ignore[arg-type]


def approved(*names: str) -> dict[str, str | None]:
    stamp = "2026-09-16T08:00:00Z"
    return {
        artifact: (stamp if artifact in names else None)
        for artifact in ("proposal", "specs", "design", "tasks")
    }


@pytest.mark.parametrize(
    ("status", "primary"),
    [
        ("drafting", "draft_proposal"),
        ("proposed", "approve_proposal"),
        ("specifying", "draft_specs"),
        ("specified", "approve_specs"),
        ("designing", "draft_design"),
        ("designed", "approve_design"),
        ("tasking", "draft_tasks"),
        ("tasked", "approve_tasks"),
        ("implementing", "start_verification"),
        ("verifying", "mark_ready"),
        ("ready", "archive"),
    ],
)
def test_every_status_offers_one_primary_action(status: str, primary: str) -> None:
    rail = action_rail(artifacts(status=status, risk="critical"))

    assert rail["primary_action"] == primary


def test_an_archived_change_offers_nothing() -> None:
    rail = action_rail(artifacts(status="archived"))

    assert rail["primary_action"] is None
    assert rail["actions"] == []


def test_design_is_only_gated_for_boundary_crossing_risk() -> None:
    assert required_approvals(artifacts(risk="standard")) == (
        "proposal",
        "specs",
        "tasks",
    )
    assert required_approvals(artifacts(risk="cross_layer")) == (
        "proposal",
        "specs",
        "design",
        "tasks",
    )
    assert status_after_approval(artifacts(risk="standard"), "specs") == "tasking"
    assert status_after_approval(artifacts(risk="critical"), "specs") == "designing"


def test_approving_specs_is_blocked_while_a_named_capability_has_no_delta() -> None:
    blockers = artifact_blockers(
        artifacts(
            status="specified",
            capabilities=["user-auth", "audit-log"],
            delta_capabilities=["user-auth"],
        ),
        "specs",
    )

    assert [blocker["code"] for blocker in blockers] == ["capability_without_delta"]
    assert blockers[0]["capabilities"] == ["audit-log"]


def test_approving_specs_surfaces_every_format_problem() -> None:
    blockers = artifact_blockers(
        artifacts(
            status="specified",
            delta_capabilities=["user-auth"],
            spec_problems=["spec.md: requirement 'X' has no scenario"],
        ),
        "specs",
    )

    assert [blocker["code"] for blocker in blockers] == ["spec_format"]


def test_verification_is_blocked_by_unchecked_tasks() -> None:
    rail = action_rail(
        artifacts(status="implementing", tasks_total=4, tasks_done=1, has_tasks=True)
    )
    primary = next(
        item for item in rail["actions"] if item["id"] == "start_verification"
    )

    assert primary["state"] == "blocked"
    assert primary["blockers"][0]["remaining"] == 3


def test_archive_is_blocked_until_evidence_and_approvals_exist() -> None:
    codes = {
        blocker["code"]
        for blocker in archive_blockers(
            artifacts(status="ready", tasks_total=2, tasks_done=2, has_tasks=True)
        )
    }

    assert codes == {"no_evidence", "approval_missing", "missing_artifact"}


def test_archive_clears_once_the_change_is_complete() -> None:
    assert (
        archive_blockers(
            artifacts(
                status="ready",
                approvals=approved("proposal", "specs", "tasks"),
                has_tasks=True,
                tasks_total=2,
                tasks_done=2,
                delta_capabilities=["user-auth"],
                evidence_ids=["check-1"],
            )
        )
        == []
    )


def test_the_rail_never_offers_a_mark_ready_the_service_would_refuse() -> None:
    """The rail and the endpoint must apply one gate, not two."""

    incomplete = artifacts(
        status="verifying",
        has_tasks=True,
        tasks_total=1,
        tasks_done=1,
        evidence_ids=["check-1"],
        delta_capabilities=[],
    )
    rail = action_rail(incomplete)
    offered = next(item for item in rail["actions"] if item["id"] == "mark_ready")

    assert offered["state"] == "blocked"
    assert [blocker["code"] for blocker in offered["blockers"]] == [
        blocker["code"] for blocker in archive_blockers(incomplete)
    ]


def test_archiving_needs_a_capability_delta_to_fold() -> None:
    codes = {
        blocker["code"]
        for blocker in archive_blockers(
            artifacts(
                status="ready",
                approvals=approved("proposal", "specs", "tasks"),
                has_tasks=True,
                tasks_total=1,
                tasks_done=1,
                evidence_ids=["check-1"],
                delta_capabilities=[],
            )
        )
    }

    assert codes == {"missing_artifact"}


def test_a_critical_change_needs_a_recorded_review_before_it_is_ready() -> None:
    codes = {
        blocker["code"]
        for blocker in archive_blockers(
            artifacts(
                status="ready",
                risk="critical",
                approvals=approved("proposal", "specs", "design", "tasks"),
                has_tasks=True,
                has_design=True,
                tasks_total=1,
                tasks_done=1,
                delta_capabilities=["user-auth"],
                evidence_ids=["check-1"],
            )
        )
    }

    assert codes == {"review_required"}


def test_a_hand_edited_status_reports_the_contradiction_it_creates() -> None:
    problems = declared_status_problems(
        artifacts(status="implementing", has_tasks=False, delta_capabilities=[])
    )
    codes = {problem["code"] for problem in problems}

    assert codes == {"approval_missing", "missing_artifact"}


def test_an_unknown_status_is_reported_rather_than_corrected() -> None:
    problems = declared_status_problems(artifacts(status="shipping"))

    assert [problem["code"] for problem in problems] == ["unknown_status"]


def test_a_consistent_change_reports_no_problem() -> None:
    assert (
        declared_status_problems(
            artifacts(
                status="implementing",
                approvals=approved("proposal", "specs", "tasks"),
                has_tasks=True,
                delta_capabilities=["user-auth"],
            )
        )
        == []
    )


def test_approving_an_artifact_the_change_has_not_reached_is_blocked() -> None:
    # `create_change` writes a proposal template, so "the file exists" was true
    # from the moment the change existed and the proposal gate let an untouched
    # template through. Reaching the gate is something the author declares.
    blockers = artifact_blockers(artifacts(status="drafting"), "proposal")

    assert [blocker["code"] for blocker in blockers] == ["gate_not_reached"]
    assert "status: proposed" in blockers[0]["message"]


def test_approving_an_artifact_the_change_has_passed_is_blocked() -> None:
    # Re-approving would run `status_after_approval` again and rewind a change
    # that has already moved on.
    blockers = artifact_blockers(
        artifacts(status="implementing", approvals=approved("proposal")), "proposal"
    )

    assert [blocker["code"] for blocker in blockers] == ["gate_passed"]
    assert "back to `specifying`" in blockers[0]["message"]


@pytest.mark.parametrize(
    ("artifact", "gate"),
    [
        ("proposal", "proposed"),
        ("specs", "specified"),
        ("design", "designed"),
        ("tasks", "tasked"),
    ],
)
def test_every_artifact_is_approvable_at_its_own_gate(artifact: str, gate: str) -> None:
    blockers = artifact_blockers(
        artifacts(
            status=gate,
            risk="critical",
            delta_capabilities=["user-auth"],
            has_design=True,
            has_tasks=True,
            tasks_total=3,
        ),
        artifact,
    )

    assert blockers == []


def test_autopilot_leads_with_continue_and_keeps_approve_available() -> None:
    rail = action_rail(artifacts(status="proposed", autopilot=True))

    assert rail["primary_action"] == "autopilot_continue"
    assert "approve_proposal" in {action["id"] for action in rail["actions"]}
    assert rail["autopilot"] is True


def test_without_autopilot_the_gate_still_waits_for_a_person() -> None:
    rail = action_rail(artifacts(status="proposed"))

    assert rail["primary_action"] == "approve_proposal"
    assert rail["autopilot"] is False


def test_a_hold_hands_the_change_back_to_the_reader() -> None:
    # The agent decided this one needs a person, so the rail must stop leading
    # with the action that would carry it further.
    rail = action_rail(
        artifacts(
            status="proposed",
            autopilot=True,
            hold={"gate": "proposal", "reason": "Scope is wider than the title"},
        )
    )

    assert rail["primary_action"] == "approve_proposal"
    assert rail["hold"]["reason"] == "Scope is wider than the title"


def test_autopilot_never_carries_a_reserved_gate() -> None:
    rail = action_rail(
        artifacts(status="designed", risk="critical", autopilot=True, has_design=True)
    )

    assert rail["primary_action"] == "approve_design"
    assert rail["human_only_gates"] == ["archive", "design"]


def test_autopilot_does_not_lead_past_a_gate_that_is_blocked() -> None:
    # Continuing would skip the problem rather than fix it.
    rail = action_rail(
        artifacts(status="specified", autopilot=True, delta_capabilities=[])
    )

    assert rail["primary_action"] == "approve_specs"


def test_an_auto_approval_clears_a_gate_for_archiving() -> None:
    cleared = artifacts(
        status="ready",
        auto_approvals=approved("proposal", "specs", "tasks"),
        delta_capabilities=["user-auth"],
        has_tasks=True,
        tasks_total=2,
        tasks_done=2,
        evidence_ids=["pytest"],
    )

    assert [blocker["code"] for blocker in archive_blockers(cleared)] == []


def test_a_reserved_gate_cleared_by_autopilot_blocks_the_archive() -> None:
    # Autopilot must not be able to walk a critical change to the end by
    # clearing the one gate its tier exists to force.
    forged = artifacts(
        status="ready",
        risk="critical",
        approvals=approved("proposal", "specs", "tasks"),
        auto_approvals=approved("design"),
        delta_capabilities=["user-auth"],
        has_design=True,
        has_tasks=True,
        tasks_total=1,
        tasks_done=1,
        evidence_ids=["pytest"],
        review_recorded=True,
    )

    codes = [blocker["code"] for blocker in archive_blockers(forged)]

    assert "human_approval_required" in codes


def test_a_gate_autopilot_cleared_is_not_reported_as_a_contradiction() -> None:
    # The problems banner exists for a status that disagrees with the folder.
    # An autopilot run agrees with it perfectly — the signature is just in the
    # other map — and flagging it put a red alert on every autopilot change.
    problems = declared_status_problems(
        artifacts(
            status="specifying",
            autopilot=True,
            auto_approvals=approved("proposal"),
        )
    )

    assert [problem["code"] for problem in problems] == []


def test_a_status_past_a_gate_nobody_cleared_is_still_reported() -> None:
    problems = declared_status_problems(artifacts(status="specifying"))

    assert [problem["code"] for problem in problems] == ["approval_missing"]


def test_implementing_leads_with_the_work_while_tasks_remain() -> None:
    # Arriving at `implementing` used to highlight "Run verification", which is
    # blocked until every box is ticked, and draw the action you actually
    # wanted as a secondary beside it.
    rail = action_rail(
        artifacts(status="implementing", has_tasks=True, tasks_total=6, tasks_done=0)
    )

    assert rail["primary_action"] == "start_implementation"
    verification = next(
        item for item in rail["actions"] if item["id"] == "start_verification"
    )
    assert verification["state"] == "blocked"


def test_implementing_leads_with_verification_once_every_task_is_ticked() -> None:
    rail = action_rail(
        artifacts(status="implementing", has_tasks=True, tasks_total=6, tasks_done=6)
    )

    assert rail["primary_action"] == "start_verification"
    assert {item["id"] for item in rail["actions"]} >= {
        "start_verification",
        "start_implementation",
    }


def test_autopilot_carries_the_implementation_phase() -> None:
    rail = action_rail(
        artifacts(
            status="implementing",
            autopilot=True,
            has_tasks=True,
            tasks_total=6,
            tasks_done=2,
        )
    )

    assert rail["primary_action"] == "autopilot_continue"
    # The manual actions stay available: autopilot is a default, not a lock.
    assert {"start_implementation", "start_verification"} <= {
        action["id"] for action in rail["actions"]
    }


def test_autopilot_carries_the_verification_phase() -> None:
    rail = action_rail(
        artifacts(status="verifying", autopilot=True, has_tasks=True, tasks_total=1, tasks_done=1)
    )

    assert rail["primary_action"] == "autopilot_continue"
    assert "mark_ready" in {action["id"] for action in rail["actions"]}


def test_autopilot_stops_at_ready_because_archiving_is_the_users() -> None:
    # Archiving rewrites the capability catalogue and is undone only by another
    # change, so it stays a click a person makes at every risk tier.
    rail = action_rail(
        artifacts(
            status="ready",
            autopilot=True,
            approvals=approved("proposal", "specs", "tasks"),
            delta_capabilities=["user-auth"],
            has_tasks=True,
            tasks_total=1,
            tasks_done=1,
            evidence_ids=["pytest"],
        )
    )

    assert rail["primary_action"] == "archive"
    assert "autopilot_continue" not in {action["id"] for action in rail["actions"]}


def test_a_hold_stops_autopilot_in_the_build_phases_too() -> None:
    rail = action_rail(
        artifacts(
            status="implementing",
            autopilot=True,
            hold={"gate": "implementing", "reason": "Task 3 contradicts the delta"},
            has_tasks=True,
            tasks_total=6,
            tasks_done=2,
        )
    )

    assert rail["primary_action"] == "start_implementation"
    assert "autopilot_continue" not in {action["id"] for action in rail["actions"]}


def test_a_design_that_still_lists_open_questions_cannot_be_approved() -> None:
    # The design gate is the one review a `cross_layer` or `critical` tier
    # exists to force. Approving a document that says, in writing, that it has
    # not decided yet turns that review into a formality.
    blockers = artifact_blockers(
        artifacts(
            status="designed",
            risk="critical",
            has_design=True,
            design_open_questions=[
                "**Page size**: A4 or US Letter?",
                "**PDF metadata**: should it carry an author?",
            ],
        ),
        "design",
    )

    assert [blocker["code"] for blocker in blockers] == ["open_questions"]
    assert "2 open questions" in blockers[0]["message"]
    assert "ask_user" in blockers[0]["message"]


def test_a_design_that_answered_its_questions_is_approvable() -> None:
    blockers = artifact_blockers(
        artifacts(status="designed", risk="critical", has_design=True), "design"
    )

    assert blockers == []


def test_a_delta_the_proposal_never_named_blocks_the_specs_gate() -> None:
    # Archiving folds every delta it finds, so an undeclared one would contract
    # behaviour nobody proposed and nobody approved.
    blockers = artifact_blockers(
        artifacts(
            status="specified",
            capabilities=["user-auth"],
            delta_capabilities=["user-auth", "audit-log"],
        ),
        "specs",
    )

    assert [blocker["code"] for blocker in blockers] == ["delta_without_capability"]
    assert blockers[0]["capabilities"] == ["audit-log"]


def test_archiving_needs_evidence_for_every_approved_requirement() -> None:
    # "Evidence before ready" used to mean one page of any kind: a change
    # contracting five requirements archived on a single unrelated page.
    blockers = archive_blockers(
        artifacts(
            status="ready",
            approvals=approved("proposal", "specs", "tasks"),
            delta_capabilities=["user-auth"],
            delta_requirements=["Slug identity", "Soft chat pointer"],
            has_tasks=True,
            tasks_total=1,
            tasks_done=1,
            evidence_ids=["something-else"],
            evidence_results={"Slug identity": ["passed"]},
        )
    )

    assert [blocker["code"] for blocker in blockers] == ["requirement_without_evidence"]
    assert blockers[0]["requirements"] == ["Soft chat pointer"]


def test_a_failing_requirement_blocks_the_archive() -> None:
    blockers = archive_blockers(
        artifacts(
            status="ready",
            approvals=approved("proposal", "specs", "tasks"),
            delta_capabilities=["user-auth"],
            delta_requirements=["Slug identity"],
            has_tasks=True,
            tasks_total=1,
            tasks_done=1,
            evidence_ids=["pytest"],
            evidence_results={"Slug identity": ["passed", "failed"]},
        )
    )

    assert "requirement_failed" in [blocker["code"] for blocker in blockers]


def test_an_inconclusive_verdict_does_not_block_the_archive() -> None:
    # The verify Skill calls `inconclusive` a real answer and the archive report
    # names them; refusing outright would push agents to record a guess instead.
    blockers = archive_blockers(
        artifacts(
            status="ready",
            approvals=approved("proposal", "specs", "tasks"),
            delta_capabilities=["user-auth"],
            delta_requirements=["Slug identity"],
            has_tasks=True,
            tasks_total=1,
            tasks_done=1,
            evidence_ids=["pytest"],
            evidence_results={"Slug identity": ["inconclusive"]},
        )
    )

    assert blockers == []


def test_a_removed_requirement_needs_no_evidence() -> None:
    # There is nothing left to exercise once the fold takes it out of the spec.
    blockers = archive_blockers(
        artifacts(
            status="ready",
            approvals=approved("proposal", "specs", "tasks"),
            delta_capabilities=["user-auth"],
            delta_requirements=[],
            has_tasks=True,
            tasks_total=1,
            tasks_done=1,
            evidence_ids=["pytest"],
        )
    )

    assert blockers == []
