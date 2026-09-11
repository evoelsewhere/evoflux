"""`direct` must stay reachable for genuinely single-boundary work.

Two deterministic server rules made it unreachable in practice:

- boundaries were counted from raw top-level path segments, so a change that
  also updated its own tests read as two architectural layers — that is every
  well-tested change;
- any architecture, compatibility or operational *constraint* blocked `direct`,
  which penalised precise specifications and rewarded under-specifying.

Together they forced `planned` on almost everything, and because the rejection
named conditions ("multi_boundary", "constraint:compatibility") that are absent
from the documented trigger list, the author had to guess at a plausible-looking
`required_by` entry instead of citing the real reason.
"""

from __future__ import annotations

import pytest

from app.services.trace_contracts import (
    PLANNED_FLOW_TRIGGERS,
    TraceSpecification,
    normalize_flow_trigger,
)
from app.services.trace_service import (
    TraceValidationError,
    _direct_flow_blockers,
    _validate_delivery_flow,
)


def _spec(**overrides) -> TraceSpecification:
    payload = {
        "title": "Implement per-client rate limiting",
        "problem": "RateLimiter.allow() raises NotImplementedError.",
        "outcome": "The limiter rejects requests past the quota.",
        "risk_tier": "standard",
        "delivery_flow": {
            "mode": "direct",
            "rationale": "One class in one module, no published interface change.",
            "confidence": 0.9,
            "required_by": [],
        },
        "impact_targets": [
            {
                "repository": "easd-lab",
                "path": "tasklib/rate.py",
                "reason": "Implementation target",
            },
            {
                "repository": "easd-lab",
                "path": "tests/test_rate.py",
                "reason": "Existing contract tests",
            },
        ],
        "criteria": [
            {
                "id": "AC-1",
                "statement": "The eleventh request in the window is rejected.",
            }
        ],
    }
    payload.update(overrides)
    return TraceSpecification.model_validate(payload)


class TestTestSurfaceIsNotALayer:
    def test_source_plus_its_tests_stays_direct(self):
        assert _direct_flow_blockers(_spec()) == []
        _validate_delivery_flow(_spec())

    @pytest.mark.parametrize(
        "test_path",
        [
            "tests/test_rate.py",
            "test/rate_test.py",
            "spec/rate.spec.ts",
            "src/__tests__/rate.test.ts",
            "testing/test_rate.py",
        ],
    )
    def test_common_test_layouts_are_recognized(self, test_path):
        spec = _spec(
            impact_targets=[
                {
                    "repository": "easd-lab",
                    "path": "tasklib/rate.py",
                    "reason": "Implementation",
                },
                {
                    "repository": "easd-lab",
                    "path": test_path,
                    "reason": "Coverage",
                },
            ]
        )
        assert _direct_flow_blockers(spec) == []

    def test_two_real_product_layers_still_block(self):
        spec = _spec(
            impact_targets=[
                {
                    "repository": "easd-lab",
                    "path": "tasklib/rate.py",
                    "reason": "Backend",
                },
                {
                    "repository": "easd-lab",
                    "path": "web/RateBanner.tsx",
                    "reason": "Frontend",
                },
            ]
        )
        assert "cross_layer" in _direct_flow_blockers(spec)


class TestConstraintsDoNotPenalizePrecision:
    @pytest.mark.parametrize(
        "kind", ["architecture", "compatibility", "operational", "product"]
    )
    def test_documenting_care_does_not_force_plan(self, kind):
        spec = _spec(
            constraints=[
                {
                    "kind": kind,
                    "statement": "Preserve the existing method signatures.",
                    "source_refs": ["easd-lab:tasklib/rate.py"],
                }
            ]
        )
        assert _direct_flow_blockers(spec) == []

    def test_a_security_constraint_still_earns_a_plan(self):
        spec = _spec(
            constraints=[
                {
                    "kind": "security",
                    "statement": "The limiter must not leak client identifiers.",
                    "source_refs": ["easd-lab:tasklib/rate.py"],
                }
            ]
        )
        assert _direct_flow_blockers(spec) == ["security"]


class TestBlockersSpeakTheDocumentedVocabulary:
    def test_every_blocker_maps_onto_a_documented_trigger(self):
        cases = [
            _spec(risk_tier="cross_layer"),
            _spec(risk_tier="critical"),
            _spec(
                impact_targets=[
                    {
                        "repository": "one",
                        "path": "a/x.py",
                        "reason": "r",
                    },
                    {
                        "repository": "two",
                        "path": "b/y.py",
                        "reason": "r",
                    },
                ]
            ),
            _spec(
                constraints=[
                    {
                        "kind": "security",
                        "statement": "Auth boundary.",
                        "source_refs": [],
                    }
                ]
            ),
        ]
        for spec in cases:
            blockers = _direct_flow_blockers(spec)
            assert blockers, "expected this specification to block direct"
            for blocker in blockers:
                assert blocker in PLANNED_FLOW_TRIGGERS, blocker
                assert normalize_flow_trigger(blocker) == blocker

    def test_the_rejection_tells_the_author_what_to_cite(self):
        with pytest.raises(TraceValidationError) as excinfo:
            _validate_delivery_flow(_spec(risk_tier="critical"))
        message = str(excinfo.value)
        assert "critical_risk" in message
        assert "required_by" in message

    def test_blockers_are_deduplicated(self):
        spec = _spec(
            risk_tier="cross_layer",
            impact_targets=[
                {"repository": "easd-lab", "path": "a/x.py", "reason": "r"},
                {"repository": "easd-lab", "path": "b/y.py", "reason": "r"},
            ],
        )
        blockers = _direct_flow_blockers(spec)
        assert len(blockers) == len(set(blockers))

    def test_planned_specifications_are_never_blocked_here(self):
        spec = _spec(
            risk_tier="critical",
            delivery_flow={
                "mode": "planned",
                "rationale": "Touches authentication and a schema migration.",
                "confidence": 0.9,
                "required_by": ["critical_risk", "security"],
            },
        )
        assert _direct_flow_blockers(spec) == []
