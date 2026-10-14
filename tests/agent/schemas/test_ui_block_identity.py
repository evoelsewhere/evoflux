"""UiBlockEvent block identity fields (spec §1.1 / §6.1 Stream 1).

``block_id`` / ``replace_id`` are optional: ``None`` must keep old events
valid, the pattern must reject malformed identities, and serialization must
round-trip both fields for the SSE and WebBridge projections.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.agent.schemas.events import UiBlockEvent

_VALID_NODE: dict[str, Any] = {"type": "key_value", "pairs": [{"k": "v"}]}


def _payload(**fields: Any) -> dict[str, Any]:
    return {
        "agent": "lead",
        "tool_call_id": "call-1",
        "blocks": [_VALID_NODE],
        **fields,
    }


def test_identity_fields_default_to_none() -> None:
    event = UiBlockEvent.model_validate(_payload())

    assert event.block_id is None
    assert event.replace_id is None


def test_none_still_passes_the_regex_validator() -> None:
    # Explicit None (old wire shape) stays valid — the pattern only applies
    # when a value is set.
    event = UiBlockEvent.model_validate(_payload(block_id=None, replace_id=None))

    assert event.block_id is None
    assert event.replace_id is None


def test_block_id_and_replace_id_accept_valid_values() -> None:
    event = UiBlockEvent.model_validate(
        _payload(block_id="metrics", replace_id="old.metrics_1")
    )

    assert event.block_id == "metrics"
    assert event.replace_id == "old.metrics_1"


def test_block_id_accepts_max_length() -> None:
    identity = "a" + "b" * 127  # 128 chars — first must be alnum

    event = UiBlockEvent.model_validate(_payload(block_id=identity))

    assert event.block_id == identity


@pytest.mark.parametrize(
    "bad",
    [
        "-leading",  # first char must be alnum
        "_leading",
        "has space",
        "up/slash",
        "b" * 129,  # over 128 chars
        "",
    ],
)
def test_block_id_rejects_invalid_values(bad: str) -> None:
    with pytest.raises(ValidationError):
        UiBlockEvent.model_validate(_payload(block_id=bad))


def test_serialization_round_trip_keeps_both_fields() -> None:
    event = UiBlockEvent.model_validate(_payload(block_id="metrics", replace_id="old"))

    dumped = event.model_dump(mode="json")
    restored = UiBlockEvent.model_validate(dumped)

    assert dumped["block_id"] == "metrics"
    assert dumped["replace_id"] == "old"
    assert restored.block_id == "metrics"
    assert restored.replace_id == "old"


def test_legacy_event_serialization_shape_unchanged() -> None:
    # No-identity events keep None on the wire; every consumer guards with a
    # string check, so the null keys are inert.
    event = UiBlockEvent.model_validate(_payload())

    dumped = event.model_dump(mode="json")

    assert dumped["block_id"] is None
    assert dumped["replace_id"] is None
    assert dumped["type"] == "ui_block"
    assert dumped["tool_call_id"] == "call-1"
