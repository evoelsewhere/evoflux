"""Admissibility rules for delivery-flow reasoning and verification proof.

Delivery flow must be decided by properties of the change. An agent that reasons
from the permissions of the current phase ("authoring forbids editing product
files") produces a justification that is true of every run, which routes every
run to `planned` and defeats the lightest-safe-flow rule.

Verification commands are frozen into an immutable accepted Spec, so a command
that never ran can make every machine-required criterion unsatisfiable and cost a
whole new revision to repair.
"""

from __future__ import annotations

import pytest

from app.services.trace_contracts import (
    PLANNED_FLOW_TRIGGERS,
    TraceDeliveryFlow,
    TraceSpecification,
    TraceVerificationProbe,
    normalize_flow_trigger,
    validate_delivery_flow_reasoning,
    validate_verification_probes,
)


def _specification(**overrides) -> TraceSpecification:
    payload = {
        "title": "Implement per-client rate limiting",
        "problem": "RateLimiter.allow() raises NotImplementedError.",
        "outcome": "The limiter rejects requests past the quota.",
        "risk_tier": "standard",
        "verification_commands": ["python -m pytest tests/test_rate.py"],
        "criteria": [
            {
                "id": "AC-1",
                "statement": "The eleventh request in the window is rejected.",
                "required": True,
                "evidence_policy": {
                    "allowed_kinds": ["machine", "review"],
                    "machine_required": True,
                    "minimum_passes": 1,
                },
            }
        ],
    }
    payload.update(overrides)
    return TraceSpecification.model_validate(payload)


class TestDeliveryFlowReasoning:
    def test_phase_permission_rationale_is_rejected(self):
        """The exact reasoning observed in a real run must not be admissible."""

        flow = TraceDeliveryFlow(
            mode="planned",
            rationale=(
                "The repository runtime blocks implementation during authoring, "
                "so a Plan mission is required before code changes or direct "
                "test execution; direct delivery is not permitted in this phase "
                "even for low-risk work."
            ),
            confidence=1.0,
            required_by=["EASD lifecycle", "repo runtime guard"],
        )
        problems = validate_delivery_flow_reasoning(flow)
        assert problems, "phase-permission reasoning must be rejected"
        assert any("permissions of the current phase" in item for item in problems)

    def test_unrecognized_required_by_entries_are_named(self):
        flow = TraceDeliveryFlow(
            mode="planned",
            rationale="Touches two repositories.",
            required_by=["multi_repository", "AGENTS.md project constraints"],
        )
        problems = validate_delivery_flow_reasoning(flow)
        assert len(problems) == 1
        assert "AGENTS.md project constraints" in problems[0]
        assert "multi_repository" not in problems[0].split("Recognized")[0]

    def test_planned_without_a_matched_condition_is_rejected(self):
        flow = TraceDeliveryFlow(
            mode="planned",
            rationale="A single function in one file.",
            required_by=[],
        )
        problems = validate_delivery_flow_reasoning(flow)
        assert any("at least one matched condition" in item for item in problems)

    def test_direct_with_a_matched_condition_is_rejected(self):
        flow = TraceDeliveryFlow(
            mode="direct",
            rationale="Small change.",
            required_by=["migration"],
        )
        problems = validate_delivery_flow_reasoning(flow)
        assert any("force planned" in item for item in problems)

    def test_admissible_planned_and_direct_flows_pass(self):
        planned = TraceDeliveryFlow(
            mode="planned",
            rationale="Adds an Alembic revision and rewrites the read path.",
            confidence=0.9,
            required_by=["migration", "cross_layer"],
        )
        assert validate_delivery_flow_reasoning(planned) == []

        direct = TraceDeliveryFlow(
            mode="direct",
            rationale="One pure function in one module, no public surface.",
            confidence=0.8,
            required_by=[],
        )
        assert validate_delivery_flow_reasoning(direct) == []

    @pytest.mark.parametrize(
        ("written", "expected"),
        [
            ("multi_repository", "multi_repository"),
            ("Cross-layer change", "cross_layer"),
            ("authentication", "security"),
            ("schema migration", "migration"),
            ("public API compatibility", "public_compatibility"),
            ("critical", "critical_risk"),
        ],
    )
    def test_trigger_wording_is_tolerant(self, written, expected):
        assert normalize_flow_trigger(written) == expected

    @pytest.mark.parametrize(
        "written",
        ["EASD lifecycle", "repo runtime guard", "phase restrictions", ""],
    )
    def test_non_driver_wording_matches_no_trigger(self, written):
        assert normalize_flow_trigger(written) is None

    def test_every_trigger_normalizes_to_itself(self):
        for trigger in PLANNED_FLOW_TRIGGERS:
            assert normalize_flow_trigger(trigger) == trigger

    def test_default_flow_stays_constructible(self):
        """Loading persisted contracts must not depend on the new rules."""

        assert TraceDeliveryFlow().mode == "planned"
        legacy = TraceDeliveryFlow(
            mode="planned",
            rationale="The repository runtime blocks implementation.",
            required_by=["EASD lifecycle"],
        )
        assert legacy.required_by == ["EASD lifecycle"]


class TestVerificationProbes:
    def test_unexecuted_command_is_rejected(self):
        problems = validate_verification_probes(_specification(), [])
        assert any("was never executed" in item for item in problems)

    def test_a_command_that_cannot_run_blocks_machine_required_criteria(self):
        problems = validate_verification_probes(
            _specification(),
            [
                TraceVerificationProbe(
                    command="python -m pytest tests/test_rate.py",
                    exit_code=127,
                    detail="No module named pytest",
                )
            ],
        )
        assert any(
            "could not be executed" in item and "AC-1" in item for item in problems
        )

    def test_failing_tests_are_admissible_before_implementation(self):
        """Specification-first means the suite is red at authoring time.

        Demanding exit 0 here pushes the author toward a command that passes
        today — a discovery-only or no-op check — which then cannot prove the
        accepted criteria at convergence.
        """

        problems = validate_verification_probes(
            _specification(),
            [
                TraceVerificationProbe(
                    command="python -m pytest tests/test_rate.py",
                    exit_code=1,
                    detail="4 failed",
                )
            ],
        )
        assert problems == []

    @pytest.mark.parametrize("exit_code", [124, 126, 127])
    def test_unrunnable_exit_codes_are_rejected(self, exit_code):
        problems = validate_verification_probes(
            _specification(),
            [
                TraceVerificationProbe(
                    command="python -m pytest tests/test_rate.py",
                    exit_code=exit_code,
                )
            ],
        )
        assert any("could not be executed" in item for item in problems)

    @pytest.mark.parametrize("exit_code", [0, 1, 2, 5])
    def test_codes_that_prove_the_toolchain_works_are_accepted(self, exit_code):
        problems = validate_verification_probes(
            _specification(),
            [
                TraceVerificationProbe(
                    command="python -m pytest tests/test_rate.py",
                    exit_code=exit_code,
                )
            ],
        )
        assert problems == []

    def test_unrunnable_command_is_allowed_without_machine_required_criteria(self):
        specification = _specification(
            criteria=[
                {
                    "id": "AC-1",
                    "statement": "Docs describe the limiter.",
                    "required": True,
                    "evidence_policy": {
                        "allowed_kinds": ["review"],
                        "machine_required": False,
                        "minimum_passes": 1,
                    },
                }
            ]
        )
        problems = validate_verification_probes(
            specification,
            [
                TraceVerificationProbe(
                    command="python -m pytest tests/test_rate.py", exit_code=127
                )
            ],
        )
        assert problems == []

    def test_machine_required_criteria_need_a_command(self):
        problems = validate_verification_probes(
            _specification(verification_commands=[]), []
        )
        assert any(
            "at least one executable verification command" in i for i in problems
        )

    def test_probe_for_an_unpersisted_command_is_reported(self):
        problems = validate_verification_probes(
            _specification(),
            [
                TraceVerificationProbe(
                    command="python -m pytest tests/test_rate.py", exit_code=0
                ),
                TraceVerificationProbe(command="ruff check .", exit_code=0),
            ],
        )
        assert any("does not persist" in item for item in problems)

    def test_executed_passing_command_is_admissible(self):
        problems = validate_verification_probes(
            _specification(),
            [
                TraceVerificationProbe(
                    command="python -m pytest tests/test_rate.py",
                    exit_code=0,
                    detail="4 passed",
                )
            ],
        )
        assert problems == []
