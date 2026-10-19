"""Canonical, bounded contracts for declarative plugin lifecycle hooks.

These models describe the data boundary. They do not grant execution trust or
permissions; trust and OS isolation are enforced by the plugin platform and
hook runner before a registration can execute.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class HookEvent(StrEnum):
    SESSION_START = "session.start"
    SESSION_END = "session.end"
    PROMPT_SUBMIT = "prompt.submit"
    AGENT_START = "agent.start"
    AGENT_STOP = "agent.stop"
    MODEL_BEFORE = "model.before"
    MODEL_AFTER = "model.after"
    TOOL_BEFORE = "tool.before"
    TOOL_AFTER = "tool.after"
    COMPLETION_BEFORE = "completion.before"
    COMPACT_BEFORE = "compact.before"
    COMPACT_AFTER = "compact.after"
    SUBAGENT_START = "subagent.start"
    SUBAGENT_STOP = "subagent.stop"


class HookSource(StrEnum):
    SETTINGS = "settings"
    MANAGED_PLUGIN = "managed_plugin"
    LEGACY_PYTHON = "legacy_python"


class HookMode(StrEnum):
    AUGMENT = "augment"
    REPLACE = "replace"


class HookFailurePolicy(StrEnum):
    FAIL_OPEN = "fail_open"
    FAIL_CLOSED = "fail_closed"


_EVENT_INPUT_FIELDS: dict[HookEvent, frozenset[str]] = {
    HookEvent.SESSION_START: frozenset({"session_id", "source"}),
    HookEvent.SESSION_END: frozenset({"session_id", "source"}),
    HookEvent.PROMPT_SUBMIT: frozenset({"session_id", "source", "prompt_text"}),
    HookEvent.AGENT_START: frozenset({"session_id", "run_id", "agent_name", "role"}),
    HookEvent.AGENT_STOP: frozenset(
        {"session_id", "run_id", "agent_name", "role", "outcome"}
    ),
    HookEvent.MODEL_BEFORE: frozenset(
        {"session_id", "run_id", "agent_name", "model", "attempt"}
    ),
    HookEvent.MODEL_AFTER: frozenset(
        {"session_id", "run_id", "agent_name", "model", "attempt"}
    ),
    HookEvent.TOOL_BEFORE: frozenset(
        {"session_id", "run_id", "agent_name", "tool_name", "call_id", "arguments"}
    ),
    HookEvent.TOOL_AFTER: frozenset(
        {
            "session_id",
            "run_id",
            "agent_name",
            "tool_name",
            "call_id",
            "arguments",
            "result",
        }
    ),
    HookEvent.COMPLETION_BEFORE: frozenset(
        {"session_id", "run_id", "agent_name", "response_text"}
    ),
    HookEvent.COMPACT_BEFORE: frozenset(
        {"session_id", "run_id", "agent_name", "source"}
    ),
    HookEvent.COMPACT_AFTER: frozenset(
        {"session_id", "run_id", "agent_name", "source"}
    ),
    HookEvent.SUBAGENT_START: frozenset(
        {"session_id", "run_id", "agent_name", "parent_agent_name", "role"}
    ),
    HookEvent.SUBAGENT_STOP: frozenset(
        {
            "session_id",
            "run_id",
            "agent_name",
            "parent_agent_name",
            "role",
            "outcome",
        }
    ),
}

_EVENT_OUTPUT_FIELDS: dict[HookEvent, frozenset[str]] = {
    HookEvent.SESSION_START: frozenset({"context", "deny", "reason"}),
    HookEvent.SESSION_END: frozenset(),
    HookEvent.PROMPT_SUBMIT: frozenset({"context", "deny", "reason"}),
    HookEvent.AGENT_START: frozenset(),
    HookEvent.AGENT_STOP: frozenset(),
    HookEvent.MODEL_BEFORE: frozenset({"context"}),
    HookEvent.MODEL_AFTER: frozenset(),
    HookEvent.TOOL_BEFORE: frozenset({"arguments", "deny", "reason"}),
    HookEvent.TOOL_AFTER: frozenset({"result"}),
    HookEvent.COMPLETION_BEFORE: frozenset({"feedback", "deny", "reason"}),
    HookEvent.COMPACT_BEFORE: frozenset(),
    HookEvent.COMPACT_AFTER: frozenset(),
    HookEvent.SUBAGENT_START: frozenset(),
    HookEvent.SUBAGENT_STOP: frozenset(),
}

_EVENT_MATCH_FIELDS: dict[HookEvent, frozenset[str]] = {
    HookEvent.SESSION_START: frozenset({"source"}),
    HookEvent.SESSION_END: frozenset({"source"}),
    HookEvent.PROMPT_SUBMIT: frozenset({"source"}),
    HookEvent.AGENT_START: frozenset({"agent_name", "role"}),
    HookEvent.AGENT_STOP: frozenset({"agent_name", "role", "outcome"}),
    HookEvent.MODEL_BEFORE: frozenset({"agent_name", "model"}),
    HookEvent.MODEL_AFTER: frozenset({"agent_name", "model"}),
    HookEvent.TOOL_BEFORE: frozenset({"agent_name", "role", "tool_name"}),
    HookEvent.TOOL_AFTER: frozenset({"agent_name", "role", "tool_name"}),
    HookEvent.COMPLETION_BEFORE: frozenset({"agent_name", "role"}),
    HookEvent.COMPACT_BEFORE: frozenset({"agent_name", "source"}),
    HookEvent.COMPACT_AFTER: frozenset({"agent_name", "source"}),
    HookEvent.SUBAGENT_START: frozenset({"agent_name", "role"}),
    HookEvent.SUBAGENT_STOP: frozenset({"agent_name", "role", "outcome"}),
}


class _HookEventInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _SessionEventInput(_HookEventInput):
    session_id: str | None = Field(default=None, max_length=128)
    source: str = Field(min_length=1, max_length=64)


class _PromptSubmitInput(_HookEventInput):
    session_id: str | None = Field(default=None, max_length=128)
    source: str = Field(min_length=1, max_length=64)
    prompt_text: str | None = Field(default=None, max_length=32_000)


class _AgentLifecycleInput(_HookEventInput):
    session_id: str | None = Field(default=None, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)
    agent_name: str = Field(min_length=1, max_length=128)
    role: str = Field(min_length=1, max_length=32)


class _AgentStopInput(_AgentLifecycleInput):
    outcome: Literal["completed", "cancelled", "failed"] | None = None


class _ModelLifecycleInput(_HookEventInput):
    session_id: str | None = Field(default=None, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)
    agent_name: str = Field(min_length=1, max_length=128)
    model: str = Field(min_length=1, max_length=128)
    attempt: int = Field(ge=0, le=100)


class _ToolBeforeInput(_HookEventInput):
    session_id: str | None = Field(default=None, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)
    agent_name: str = Field(min_length=1, max_length=128)
    tool_name: str = Field(min_length=1, max_length=128)
    call_id: str = Field(min_length=1, max_length=128)
    arguments: dict[str, Any]


class _ToolAfterInput(_ToolBeforeInput):
    result: str = Field(max_length=32_000)


class _CompletionBeforeInput(_HookEventInput):
    session_id: str | None = Field(default=None, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)
    agent_name: str = Field(min_length=1, max_length=128)
    response_text: str = Field(max_length=32_000)


class _CompactLifecycleInput(_HookEventInput):
    session_id: str | None = Field(default=None, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)
    agent_name: str = Field(min_length=1, max_length=128)
    source: str = Field(min_length=1, max_length=64)


class _SubagentLifecycleInput(_HookEventInput):
    session_id: str | None = Field(default=None, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)
    agent_name: str = Field(min_length=1, max_length=128)
    parent_agent_name: str = Field(min_length=1, max_length=128)
    role: str = Field(min_length=1, max_length=32)


class _SubagentStopInput(_SubagentLifecycleInput):
    outcome: Literal["completed", "cancelled", "failed"] | None = None


_EVENT_INPUT_MODELS: dict[HookEvent, type[_HookEventInput]] = {
    HookEvent.SESSION_START: _SessionEventInput,
    HookEvent.SESSION_END: _SessionEventInput,
    HookEvent.PROMPT_SUBMIT: _PromptSubmitInput,
    HookEvent.AGENT_START: _AgentLifecycleInput,
    HookEvent.AGENT_STOP: _AgentStopInput,
    HookEvent.MODEL_BEFORE: _ModelLifecycleInput,
    HookEvent.MODEL_AFTER: _ModelLifecycleInput,
    HookEvent.TOOL_BEFORE: _ToolBeforeInput,
    HookEvent.TOOL_AFTER: _ToolAfterInput,
    HookEvent.COMPLETION_BEFORE: _CompletionBeforeInput,
    HookEvent.COMPACT_BEFORE: _CompactLifecycleInput,
    HookEvent.COMPACT_AFTER: _CompactLifecycleInput,
    HookEvent.SUBAGENT_START: _SubagentLifecycleInput,
    HookEvent.SUBAGENT_STOP: _SubagentStopInput,
}


class HookMatcher(BaseModel):
    """Small event matcher; arbitrary expression languages are not accepted."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str | None = Field(default=None, min_length=1, max_length=64)
    agent_name: str | None = Field(default=None, min_length=1, max_length=128)
    role: str | None = Field(default=None, min_length=1, max_length=32)
    model: str | None = Field(default=None, min_length=1, max_length=128)
    tool_name: str | None = Field(default=None, min_length=1, max_length=128)
    outcome: Literal["completed", "cancelled", "failed"] | None = None

    @model_validator(mode="after")
    def require_match_field(self) -> HookMatcher:
        if not any(getattr(self, name) is not None for name in self.model_fields):
            raise ValueError("matcher must declare at least one field")
        return self

    def declared_fields(self) -> frozenset[str]:
        return frozenset(
            name for name in self.model_fields if getattr(self, name) is not None
        )


class HookTarget(BaseModel):
    """Exact target for Settings shadowing or disabling a plugin hook."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    plugin_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    hook_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class HookDefinition(BaseModel):
    """Version-neutral hook definition after package/vendor normalization."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    hook_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    event: HookEvent
    matcher: HookMatcher | None = None
    runtime: Literal["native", "python"] = "native"
    command: tuple[str, ...] = Field(min_length=1, max_length=64)
    files: tuple[str, ...] = Field(default=(), max_length=128)
    execution_kind: Literal["command", "static_context"] = "command"
    context_prefix: str = Field(default="", max_length=2048)
    context_suffix: str = Field(default="", max_length=2048)
    timeout_seconds: int = Field(ge=1, le=120)
    input_fields: tuple[str, ...] = ()
    output_fields: tuple[str, ...] = ()
    failure_policy: HookFailurePolicy
    overrides: tuple[HookTarget, ...] = ()

    @field_validator("command")
    @classmethod
    def validate_command_argv(cls, argv: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value or "\x00" in value or len(value) > 4096 for value in argv):
            raise ValueError("command argv entries must be non-empty bounded strings")
        return argv

    @field_validator("input_fields", "output_fields")
    @classmethod
    def validate_unique_fields(cls, fields: tuple[str, ...]) -> tuple[str, ...]:
        if len(fields) != len(set(fields)):
            raise ValueError("field declarations must not contain duplicates")
        if any(not field or len(field) > 64 for field in fields):
            raise ValueError("field declarations must be non-empty bounded strings")
        return fields

    @field_validator("files")
    @classmethod
    def validate_declared_files(cls, files: tuple[str, ...]) -> tuple[str, ...]:
        if len(files) != len(set(files)):
            raise ValueError("declared files must not contain duplicates")
        for relative in files:
            if not relative.startswith("./"):
                raise ValueError("declared files must be package-relative ./ paths")
            parts = relative[2:].replace("\\", "/").split("/")
            if any(part in {"", ".", ".."} for part in parts):
                raise ValueError("declared file path contains an invalid component")
        return files

    @model_validator(mode="after")
    def validate_event_contract(self) -> HookDefinition:
        if self.execution_kind == "static_context":
            if self.event is not HookEvent.SESSION_START:
                raise ValueError("static context is supported only for session.start")
            if self.output_fields != ("context",):
                raise ValueError("static context may output only context")
            if self.input_fields:
                raise ValueError("static context cannot receive event input")
            if len(self.command) != 1:
                raise ValueError("static context requires one package-relative file")
            if self.files:
                raise ValueError("static context cannot declare additional files")
        elif self.context_prefix or self.context_suffix:
            raise ValueError("context templates require static_context execution")

        unknown_input = set(self.input_fields) - _EVENT_INPUT_FIELDS[self.event]
        if unknown_input:
            raise ValueError(
                f"input fields are not allowed for {self.event.value}: "
                f"{', '.join(sorted(unknown_input))}"
            )

        unknown_output = set(self.output_fields) - _EVENT_OUTPUT_FIELDS[self.event]
        if unknown_output:
            raise ValueError(
                f"output fields are not allowed for {self.event.value}: "
                f"{', '.join(sorted(unknown_output))}"
            )

        if self.matcher is not None:
            unknown_match = (
                self.matcher.declared_fields() - _EVENT_MATCH_FIELDS[self.event]
            )
            if unknown_match:
                raise ValueError(
                    f"matcher fields are not allowed for {self.event.value}: "
                    f"{', '.join(sorted(unknown_match))}"
                )
        return self


class HookRegistration(BaseModel):
    """A discovered hook plus trust/enable state used by the resolver."""

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    hook_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    event: HookEvent
    source: HookSource
    plugin_id: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
    )
    definition: HookDefinition | None = None
    digest: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")
    trusted: bool = False
    enabled: bool = True
    handler: Any = Field(default=None, exclude=True, repr=False, compare=False)

    @model_validator(mode="after")
    def validate_registration_identity(self) -> HookRegistration:
        if self.source is HookSource.SETTINGS:
            if self.plugin_id is not None or self.definition is None:
                raise ValueError(
                    "Settings registrations require a definition and no plugin_id"
                )
        elif self.plugin_id is None:
            raise ValueError("plugin registrations require a plugin_id")

        if self.source is not HookSource.LEGACY_PYTHON and self.definition is None:
            raise ValueError("declarative registrations require a hook definition")
        if self.definition is not None:
            if (
                self.definition.hook_id != self.hook_id
                or self.definition.event is not self.event
            ):
                raise ValueError("registration identity must match its hook definition")
            if self.source is not HookSource.SETTINGS and self.definition.overrides:
                raise ValueError("only Settings hooks may target plugin overrides")
        return self


class HookSettingsPolicy(BaseModel):
    """Global Settings policy that affects configurable plugin hooks only."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: HookMode = HookMode.AUGMENT
    replace_plugin_events: tuple[HookEvent, ...] = ()
    disabled_plugin_hooks: tuple[HookTarget, ...] = ()

    @field_validator("replace_plugin_events", "disabled_plugin_hooks")
    @classmethod
    def validate_unique_targets(cls, values: tuple[Any, ...]) -> tuple[Any, ...]:
        if len(values) != len(set(values)):
            raise ValueError("Settings policy entries must not contain duplicates")
        return values


def validate_hook_output(
    event: HookEvent,
    declared_fields: tuple[str, ...],
    output: dict[str, Any],
) -> dict[str, Any]:
    """Validate a JSON output against its event and declared field allowlists."""

    permitted = _EVENT_OUTPUT_FIELDS[event]
    declared = set(declared_fields)
    if not declared <= permitted:
        raise ValueError("declared output fields are invalid for this event")
    unexpected = set(output) - declared
    if unexpected:
        raise ValueError(
            f"output contains undeclared fields: {', '.join(sorted(unexpected))}"
        )

    validated: dict[str, Any] = {}
    for name, value in output.items():
        if name == "deny":
            if not isinstance(value, bool):
                raise ValueError("deny must be a boolean")
            validated[name] = value
        elif name in {"context", "reason", "feedback", "result"}:
            maximum = 4000 if name in {"context", "feedback"} else 2000
            if not isinstance(value, str) or len(value) > maximum:
                raise ValueError(
                    f"{name} must be a string no longer than {maximum} characters"
                )
            validated[name] = value
        elif name == "arguments":
            if not isinstance(value, dict):
                raise ValueError("arguments must be a JSON object")
            validated[name] = value
    return validated


def validate_event_input(
    event: HookEvent,
    payload: dict[str, Any],
    *,
    declared_fields: tuple[str, ...],
) -> dict[str, Any]:
    """Validate the complete event input, then project declared fields only."""

    allowed = _EVENT_INPUT_FIELDS[event]
    declared = set(declared_fields)
    if not declared <= allowed:
        unknown = ", ".join(sorted(declared - allowed))
        raise ValueError(
            f"declared input fields are invalid for {event.value}: {unknown}"
        )

    validated = _EVENT_INPUT_MODELS[event].model_validate(payload)
    return validated.model_dump(
        mode="json",
        include=declared,
        exclude_unset=True,
    )


def event_allowed_input_fields(event: HookEvent) -> frozenset[str]:
    """Return the input field allowlist for *event*."""

    return _EVENT_INPUT_FIELDS[event]


def event_allowed_output_fields(event: HookEvent) -> frozenset[str]:
    """Return the output field allowlist for *event*."""

    return _EVENT_OUTPUT_FIELDS[event]
