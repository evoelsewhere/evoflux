"""The run response schema must not silently drop persisted run fields.

`serialize_run` is the single source of the run payload and `EasdRunOut` is the
response model. Pydantic drops any key the model does not declare, so a field
added to one and not the other disappears from the API without an error — which
is how saved run options read back as `false` in the panel.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.api.schemas.easd import EasdRunOut
from app.models.trace import TraceRun
from app.services.trace_service import serialize_run


def _run() -> TraceRun:
    now = datetime.now(UTC)
    return TraceRun(
        id=uuid4(),
        project_id=None,
        workspace="C:/Users/dev/project",
        session_id=None,
        title="Implement per-client rate limiting",
        intent=None,
        status="accepted",
        risk_tier="standard",
        active_spec_revision_id=None,
        active_plan_revision_id=None,
        convergence_report=None,
        converged_at=None,
        created_at=now,
        updated_at=now,
        compact_before_run=True,
        auto_pilot=True,
    )


def test_response_model_declares_every_serialized_field():
    """Guards the whole class of bug, not just the two options fields."""

    serialized = set(serialize_run(_run()))
    declared = set(EasdRunOut.model_fields)
    dropped = serialized - declared
    assert not dropped, (
        "EasdRunOut would silently drop these serialized run fields: "
        + ", ".join(sorted(dropped))
    )


def test_run_options_survive_the_response_model():
    payload = serialize_run(_run())
    assert payload["compact_before_run"] is True
    assert payload["auto_pilot"] is True

    out = EasdRunOut.model_validate(payload)
    assert out.compact_before_run is True
    assert out.auto_pilot is True

    dumped = out.model_dump()
    assert dumped["compact_before_run"] is True
    assert dumped["auto_pilot"] is True


def test_disabled_run_options_round_trip_as_false():
    run = _run()
    run.compact_before_run = False
    run.auto_pilot = False
    out = EasdRunOut.model_validate(serialize_run(run))
    assert out.compact_before_run is False
    assert out.auto_pilot is False
