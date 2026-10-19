from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.agent.plugins.hook_contract import (
    HookDefinition,
    HookEvent,
    validate_event_input,
)


def test_hook_contract_is_available_from_plugin_package() -> None:
    from app.agent.plugins import HookDefinition as PublicHookDefinition

    assert PublicHookDefinition is HookDefinition


def test_hook_definition_accepts_only_declared_tool_arguments() -> None:
    definition = HookDefinition(
        hook_id="rewrite-shell-args",
        event=HookEvent.TOOL_BEFORE,
        matcher={"tool_name": "shell"},
        command=["python", "./hooks/rewrite.py", "--mode", "safe"],
        timeout_seconds=5,
        input_fields=["tool_name", "arguments"],
        output_fields=["arguments", "deny", "reason"],
        failure_policy="fail_closed",
    )

    assert definition.event is HookEvent.TOOL_BEFORE
    assert definition.command == (
        "python",
        "./hooks/rewrite.py",
        "--mode",
        "safe",
    )
    assert definition.input_fields == ("tool_name", "arguments")
    assert definition.output_fields == ("arguments", "deny", "reason")


@pytest.mark.parametrize(
    "overrides",
    [
        {"event": "not-a-real-event"},
        {"input_fields": ["full_transcript"]},
        {"output_fields": ["allow"]},
        {"command": []},
        {"command": ["python", "bad\x00script.py"]},
        {"timeout_seconds": 121},
        {"matcher": {"unknown_match_key": "value"}},
    ],
)
def test_hook_definition_rejects_invalid_or_unsafe_contract_fields(
    overrides: dict[str, object],
) -> None:
    payload: dict[str, object] = {
        "hook_id": "validated-hook",
        "event": HookEvent.PROMPT_SUBMIT,
        "command": ["python", "./hooks/run.py"],
        "timeout_seconds": 10,
        "input_fields": [],
        "output_fields": ["context"],
        "failure_policy": "fail_open",
    }
    payload.update(overrides)

    with pytest.raises(ValidationError):
        HookDefinition.model_validate(payload)


@pytest.mark.parametrize(
    "overrides",
    [
        {"event": "prompt.submit"},
        {"output_fields": ["context", "deny"]},
        {"input_fields": ["source"]},
        {"command": ["./skill.md", "extra"]},
    ],
)
def test_static_context_is_limited_to_one_session_file_and_context_output(
    overrides: dict[str, object],
) -> None:
    payload: dict[str, object] = {
        "hook_id": "static-context",
        "event": "session.start",
        "command": ["./skill.md"],
        "execution_kind": "static_context",
        "timeout_seconds": 1,
        "input_fields": [],
        "output_fields": ["context"],
        "failure_policy": "fail_open",
    }
    payload.update(overrides)

    with pytest.raises(ValidationError):
        HookDefinition.model_validate(payload)


def test_hook_definition_rejects_duplicate_field_declarations() -> None:
    with pytest.raises(ValidationError):
        HookDefinition.model_validate(
            {
                "hook_id": "duplicate-input",
                "event": HookEvent.PROMPT_SUBMIT,
                "command": ["python", "./hooks/run.py"],
                "timeout_seconds": 10,
                "input_fields": ["source", "source"],
                "output_fields": ["context"],
                "failure_policy": "fail_open",
            }
        )


def test_event_input_is_typed_and_only_declared_fields_are_forwarded() -> None:
    event_input = validate_event_input(
        HookEvent.PROMPT_SUBMIT,
        {
            "session_id": "session-1",
            "source": "new",
            "prompt_text": "hello",
        },
        declared_fields=("session_id", "source"),
    )

    assert event_input == {"session_id": "session-1", "source": "new"}


def test_event_input_rejects_unmodeled_fields_and_wrong_types() -> None:
    with pytest.raises(ValidationError):
        validate_event_input(
            HookEvent.PROMPT_SUBMIT,
            {"source": "new", "password": "secret"},
            declared_fields=("source",),
        )

    with pytest.raises(ValidationError):
        validate_event_input(
            HookEvent.TOOL_BEFORE,
            {
                "session_id": "session-1",
                "run_id": "run-1",
                "agent_name": "agent",
                "tool_name": "shell",
                "call_id": "call-1",
                "arguments": ["not", "an", "object"],
            },
            declared_fields=("arguments",),
        )


def test_agent_stop_outcome_is_a_bounded_lifecycle_input() -> None:
    result = validate_event_input(
        HookEvent.AGENT_STOP,
        {
            "session_id": "session-1",
            "run_id": "run-1",
            "agent_name": "agent",
            "role": "work",
            "outcome": "cancelled",
        },
        declared_fields=("role", "outcome"),
    )

    assert result == {"role": "work", "outcome": "cancelled"}

    with pytest.raises(ValidationError):
        validate_event_input(
            HookEvent.AGENT_STOP,
            {
                "run_id": "run-1",
                "agent_name": "agent",
                "role": "work",
                "outcome": "partial",
            },
            declared_fields=("outcome",),
        )


def test_hook_contract_declares_runtime_and_explicit_file_read_set() -> None:
    definition = HookDefinition.model_validate(
        {
            "hook_id": "python-hook",
            "event": "session.start",
            "runtime": "python",
            "command": ["./hooks/main.py"],
            "files": ["./hooks/helper.py", "./data/policy.json"],
            "timeout_seconds": 5,
            "output_fields": ["context"],
            "failure_policy": "fail_closed",
        }
    )

    assert definition.runtime == "python"
    assert definition.command == ("./hooks/main.py",)
    assert definition.files == ("./hooks/helper.py", "./data/policy.json")


@pytest.mark.parametrize(
    "payload",
    [
        {"runtime": "shell"},
        {"files": ["../secret.txt"]},
        {"files": ["/absolute/secret.txt"]},
        {"files": ["./hooks/helper.py", "./hooks/helper.py"]},
        {"files": ["./hooks/helper.py\\..\\secret.txt"]},
    ],
)
def test_hook_contract_rejects_unsupported_runtime_and_unsafe_read_set(
    payload: dict[str, object],
) -> None:
    declaration: dict[str, object] = {
        "hook_id": "unsafe-read-set",
        "event": "session.start",
        "runtime": "native",
        "command": ["./hooks/main.py"],
        "timeout_seconds": 5,
        "output_fields": ["context"],
        "failure_policy": "fail_closed",
    }
    declaration.update(payload)

    with pytest.raises(ValidationError):
        HookDefinition.model_validate(declaration)
