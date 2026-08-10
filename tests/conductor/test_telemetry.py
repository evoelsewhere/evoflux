from __future__ import annotations

import json
import uuid
from pathlib import Path

import httpx
import pytest

from app.agent.hooks.conductor_telemetry import ConductorTelemetryHook
from app.agent.schemas.chat import AssistantMessage, FunctionCall, ToolCall
from app.agent.state import AgentState, ModelRequest, RunContext
from app.conductor.client import ConductorClient
from app.conductor.constants.api import V1_TELEMETRY_PATH
from app.conductor.constants.telemetry import (
    TelemetryBatchField,
    TelemetryCollectionLevel,
    TelemetryEventStatus,
    TelemetryEventType,
    TelemetryField,
    TelemetryToolCategory,
)
from app.conductor.telemetry import TelemetryOutbox
from app.core.config import settings
from app.core.runtime_settings import (
    ConductorSettings,
    RuntimeSettings,
    save_runtime_settings,
)


class MemoryCredentialStore:
    def __init__(self, value: str | None = None) -> None:
        self.value = value

    def load(self) -> str | None:
        return self.value

    def save(self, credential: str) -> None:
        self.value = credential

    def delete(self) -> None:
        self.value = None


def _configure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, installation_id: str
) -> None:
    monkeypatch.setattr(settings, "EVOFLUX_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr(settings, "EVOFLUX_STATE_DIR", str(tmp_path / "state"))
    save_runtime_settings(
        RuntimeSettings(
            conductor=ConductorSettings(
                enabled=True,
                url="https://conductor.example",
                installation_id=installation_id,
                collection_level=TelemetryCollectionLevel.COUNTERS,
            )
        )
    )


@pytest.mark.asyncio
async def test_hook_queues_only_safe_model_and_tool_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installation_id = str(uuid.uuid4())
    _configure(tmp_path, monkeypatch, installation_id)
    outbox = TelemetryOutbox(tmp_path / "outbox.json")
    hook = ConductorTelemetryHook(
        agent_name="lead", model_id="openai:gpt-5", outbox=outbox
    )
    ctx = RunContext(session_id="session-1", run_id="request-1", agent_name="lead")
    state = AgentState(messages=[])
    request = ModelRequest(messages=(), system_prompt="private system prompt")
    await hook.before_agent(ctx, state)

    async def model_handler(_request: ModelRequest) -> AssistantMessage:
        return AssistantMessage(
            content="private response",
            reasoning_content="private reasoning",
            extra={
                "model": "openai:gpt-5.1",
                "usage": {
                    "input": 120,
                    "output": 40,
                    "cache": 20,
                    "thoughts": 10,
                },
            },
        )

    await hook.wrap_model_call(ctx, state, request, model_handler)

    tool_call = ToolCall(
        id="tool-1",
        function=FunctionCall(
            name="read_file", arguments='{"path":"/private/project"}'
        ),
    )

    async def tool_handler(_ctx, _state, _call) -> str:
        return "private file contents"

    await hook.wrap_tool_call(ctx, state, tool_call, tool_handler)

    events = outbox.peek(installation_id)
    assert len(events) == 2
    assert events[0][TelemetryField.EVENT_TYPE] == TelemetryEventType.MODEL_CALL
    assert events[0][TelemetryField.MODEL] == "gpt-5.1"
    assert events[0][TelemetryField.TOKENS_IN] == 120
    assert events[0][TelemetryField.TOKENS_OUT] == 40
    assert events[1][TelemetryField.EVENT_TYPE] == TelemetryEventType.TOOL_CALL
    assert events[1][TelemetryField.TOOL_NAME] == "read_file"
    assert events[1][TelemetryField.TOOL_CATEGORY] == TelemetryToolCategory.FILESYSTEM
    serialized = json.dumps(events)
    for secret in (
        "private system prompt",
        "private response",
        "private reasoning",
        "/private/project",
        "private file contents",
        "arguments",
        "result",
    ):
        assert secret not in serialized


def test_outbox_is_bounded_and_acknowledges_by_event_id(tmp_path: Path) -> None:
    path = tmp_path / "outbox.json"
    outbox = TelemetryOutbox(path, max_events=2)
    installation_id = str(uuid.uuid4())
    for index in range(3):
        assert outbox.enqueue(
            {
                TelemetryField.EVENT_ID: f"event-{index}",
                TelemetryField.INSTALLATION_ID: installation_id,
                TelemetryField.REQUEST_ID: "request-1",
                TelemetryField.EVENT_TYPE: TelemetryEventType.MODEL_CALL,
                TelemetryField.STATUS: TelemetryEventStatus.SUCCESS,
                TelemetryField.REPORTED_AT: "2026-08-10T00:00:00+00:00",
                TelemetryField.TOKENS_IN: index,
                "prompt": "never persisted",
            }
        )
    assert [
        event[TelemetryField.EVENT_ID] for event in outbox.peek(installation_id)
    ] == [
        "event-1",
        "event-2",
    ]
    outbox.acknowledge({"event-1"})
    assert [
        event[TelemetryField.EVENT_ID] for event in outbox.peek(installation_id)
    ] == ["event-2"]
    assert "never persisted" not in path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_client_posts_sanitized_batch() -> None:
    installation_id = str(uuid.uuid4())
    store = MemoryCredentialStore("evc_telemetry")

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == V1_TELEMETRY_PATH
        assert request.headers["authorization"] == "Bearer evc_telemetry"
        body = json.loads(request.content)
        assert body[TelemetryBatchField.INSTALLATION_ID] == installation_id
        assert body[TelemetryBatchField.EVENTS][0][TelemetryField.TOKENS_IN] == 12
        assert TelemetryField.INSTALLATION_ID not in body[TelemetryBatchField.EVENTS][0]
        assert "prompt" not in body[TelemetryBatchField.EVENTS][0]
        return httpx.Response(200, json={"accepted": 1, "duplicates": 0})

    client = ConductorClient(
        "https://conductor.example",
        store,
        transport=httpx.MockTransport(handler),
    )
    try:
        await client.report_telemetry(
            installation_id,
            [
                {
                    TelemetryField.EVENT_ID: str(uuid.uuid4()),
                    TelemetryField.INSTALLATION_ID: installation_id,
                    TelemetryField.REQUEST_ID: "request-1",
                    TelemetryField.EVENT_TYPE: TelemetryEventType.MODEL_CALL,
                    TelemetryField.STATUS: TelemetryEventStatus.SUCCESS,
                    TelemetryField.REPORTED_AT: "2026-08-10T00:00:00+00:00",
                    TelemetryField.TOKENS_IN: 12,
                    "prompt": "secret",
                }
            ],
        )
    finally:
        await client.close()
