"""Validation tests for locally captured skill-recording payloads."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.schemas.skill_recordings import (
    SkillRecordingEvent,
    SkillRecordingEventBatch,
    SkillRecordingDraftRequest,
    SkillRecordingPreviewRequest,
)


def test_focus_and_text_control_names_are_redacted_at_schema_boundary():
    focus = SkillRecordingEvent(
        sequence=1,
        elapsed_ms=2,
        kind="focus",
        target={"automation_id": "field", "control_type": "button", "name": "private"},
    )
    text = SkillRecordingEvent(
        sequence=2,
        elapsed_ms=3,
        kind="invoked",
        target={"automation_id": "input", "control_type": "EDIT", "name": "private"},
    )

    assert focus.target.name is None
    assert text.target.name is None


@pytest.mark.parametrize(
    "payload",
    [
        {
            "sequence": 1,
            "elapsed_ms": 0,
            "kind": "value_changed",
            "value": "secret",
            "value_state": "omitted_secure",
        },
        {
            "sequence": 1,
            "elapsed_ms": 0,
            "kind": "focus",
            "value": "secret",
            "value_state": "captured",
        },
        {"sequence": 1, "elapsed_ms": 0, "kind": "screenshot"},
        {"sequence": 1, "elapsed_ms": 0, "kind": "focus", "unexpected": "field"},
    ],
)
def test_invalid_or_sensitive_event_shapes_are_rejected(payload):
    with pytest.raises(ValidationError):
        SkillRecordingEvent.model_validate(payload)


def test_event_batch_is_bounded():
    with pytest.raises(ValidationError):
        SkillRecordingEventBatch(
            events=[
                {"sequence": index + 1, "elapsed_ms": 0, "kind": "focus"}
                for index in range(65)
            ]
        )


@pytest.mark.parametrize(
    "event",
    [
        {
            "sequence": 1,
            "elapsed_ms": 10,
            "kind": "click",
            "point": {"x": 12, "y": 34},
            "button": "left",
        },
        {
            "sequence": 1,
            "elapsed_ms": 10,
            "kind": "double_click",
            "point": {"x": -12, "y": 34},
            "button": "right",
        },
        {
            "sequence": 1,
            "elapsed_ms": 10,
            "kind": "scroll",
            "point": {"x": 12, "y": 34},
            "scroll_delta": {"x": 0, "y": -120},
        },
        {"sequence": 1, "elapsed_ms": 10, "kind": "window_change"},
    ],
)
def test_desktop_pointer_and_window_events_are_accepted(event):
    assert SkillRecordingEvent.model_validate(event).kind == event["kind"]


@pytest.mark.parametrize(
    "event",
    [
        {"sequence": 1, "elapsed_ms": 0, "kind": "click"},
        {"sequence": 1, "elapsed_ms": 0, "kind": "click", "point": {"x": 1, "y": 2}},
        {"sequence": 1, "elapsed_ms": 0, "kind": "scroll", "point": {"x": 1, "y": 2}},
        {"sequence": 1, "elapsed_ms": 0, "kind": "focus", "point": {"x": 1, "y": 2}},
        {
            "sequence": 1,
            "elapsed_ms": 0,
            "kind": "click",
            "point": {"x": 40000, "y": 0},
            "button": "left",
        },
        {
            "sequence": 1,
            "elapsed_ms": 0,
            "kind": "click",
            "point": {"x": 1, "y": 2},
            "button": "keyboard",
        },
    ],
)
def test_desktop_pointer_events_reject_incomplete_or_invalid_shapes(event):
    with pytest.raises(ValidationError):
        SkillRecordingEvent.model_validate(event)


def test_preview_request_does_not_require_a_manually_written_goal():
    request = SkillRecordingPreviewRequest(selected_event_ids=[1])

    assert request.goal == ""
    assert request.model is None


def test_chat_draft_request_still_requires_a_provider_model():
    with pytest.raises(ValidationError):
        SkillRecordingDraftRequest(
            selected_event_ids=[1], confirm_processing=True, preview_sha256="a" * 64
        )
