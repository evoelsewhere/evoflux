from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

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
from app.conductor.managed_state import ManagedResourceStore
from app.conductor.models import ManagedResourceRecord
from app.conductor.telemetry import (
    TelemetryOutbox,
    flush_usage,
    record_skill_usage,
)
from app.core.config import settings
from app.plugin_platform.models import PluginInstallation
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
                    "cost": {"estimated_usd": 0.00125},
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
    assert events[0][TelemetryField.RESPONSE_MODEL] == "openai:gpt-5.1"
    assert events[0][TelemetryField.ESTIMATED_COST_USD_MICROS] == 1250
    assert events[0][TelemetryField.COST_SOURCE] == "evoflux_catalog"
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


@pytest.mark.asyncio
async def test_hook_attributes_managed_agent_and_skill_and_closes_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installation_id = str(uuid.uuid4())
    _configure(tmp_path, monkeypatch, installation_id)
    project_id = str(uuid.uuid4())
    agent_resource_id = str(uuid.uuid4())
    agent_version_id = str(uuid.uuid4())
    skill_resource_id = str(uuid.uuid4())
    skill_version_id = str(uuid.uuid4())
    store = ManagedResourceStore()
    for kind, slug, resource_id, version_id in (
        ("agent", "reviewer", agent_resource_id, agent_version_id),
        ("skill", "release-check", skill_resource_id, skill_version_id),
    ):
        store.upsert(
            ManagedResourceRecord(
                project_id=project_id,
                resource_id=resource_id,
                version_id=version_id,
                version="1.0.0",
                release_channel="published",
                kind=kind,
                slug=slug,
                observed_state="applied",
                observed_at=datetime.now(UTC),
            )
        )

    outbox = TelemetryOutbox(tmp_path / "outbox.json")
    hook = ConductorTelemetryHook(
        agent_name="reviewer", model_id="openai:gpt-5", outbox=outbox
    )
    ctx = RunContext(session_id="session-1", run_id="request-1", agent_name="reviewer")
    state = AgentState(messages=[])
    await hook.before_agent(ctx, state)

    async def model_handler(_request: ModelRequest) -> AssistantMessage:
        return AssistantMessage(extra={"usage": {"input": 10, "output": 5}})

    await hook.wrap_model_call(
        ctx,
        state,
        ModelRequest(messages=(), system_prompt="private"),
        model_handler,
    )
    tool_call = ToolCall(
        id="skill-1",
        function=FunctionCall(
            name="skill",
            arguments='{"action":"load","skill_name":"release-check"}',
        ),
    )

    async def tool_handler(_ctx, _state, _call) -> str:
        return "private skill instructions"

    await hook.wrap_tool_call(ctx, state, tool_call, tool_handler)
    await hook.after_agent(ctx, state, AssistantMessage(content="private response"))

    events = outbox.peek(installation_id)
    assert [event[TelemetryField.EVENT_TYPE] for event in events] == [
        TelemetryEventType.MODEL_CALL,
        TelemetryEventType.TOOL_CALL,
        TelemetryEventType.REQUEST,
    ]
    assert events[0][TelemetryField.RESOURCES] == [
        {
            "resource_id": agent_resource_id,
            "version_id": agent_version_id,
            "relation": "executing_agent",
        }
    ]
    assert {item["relation"] for item in events[1][TelemetryField.RESOURCES]} == {
        "executing_agent",
        "activated_skill",
    }
    assert {item["relation"] for item in events[2][TelemetryField.RESOURCES]} == {
        "executing_agent",
        "activated_skill",
    }
    serialized = json.dumps(events)
    assert "release-check" not in serialized
    assert "private" not in serialized


@pytest.mark.asyncio
async def test_hook_attributes_plugin_tools_by_runtime_installation_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installation_id = str(uuid.uuid4())
    _configure(tmp_path, monkeypatch, installation_id)
    plugin_installation_id = "a" * 32
    resource_id = str(uuid.uuid4())
    version_id = str(uuid.uuid4())
    installation = PluginInstallation(
        id=plugin_installation_id,
        name="managed-search",
        version="2.0.0",
        root=str(tmp_path / "plugin"),
        source_type="installed",
        source_ref="conductor://project/resource/version",
        content_sha256="b" * 64,
        enabled=True,
        managed_by="conductor",
        managed_project_id=str(uuid.uuid4()),
        managed_resource_id=resource_id,
        managed_version_id=version_id,
        installed_at=datetime.now(UTC).isoformat(),
        updated_at=datetime.now(UTC).isoformat(),
    )
    from app.plugin_platform import registry
    from app.plugin_platform.runtime import plugin_mcp_runtime

    monkeypatch.setattr(
        registry,
        "get_installation",
        lambda value: installation if value == plugin_installation_id else None,
    )
    monkeypatch.setattr(
        plugin_mcp_runtime,
        "get_tools_for_installation",
        lambda value: (
            [SimpleNamespace(name="mcp_managed_search")]
            if value == plugin_installation_id
            else []
        ),
    )

    outbox = TelemetryOutbox(tmp_path / "plugin-outbox.json")
    hook = ConductorTelemetryHook(
        agent_name="lead", model_id="openai:gpt-5", outbox=outbox
    )
    ctx = RunContext(session_id="session-1", run_id="request-1", agent_name="lead")
    state = AgentState(messages=[])
    await hook.before_agent(ctx, state)
    state.metadata["plugin_mcp_grants"] = {plugin_installation_id}
    tool_call = ToolCall(
        id="plugin-tool-1",
        function=FunctionCall(
            name="mcp_managed_search", arguments='{"query":"private"}'
        ),
    )

    async def tool_handler(_ctx, _state, _call) -> str:
        return "private result"

    await hook.wrap_tool_call(ctx, state, tool_call, tool_handler)
    await hook.after_agent(ctx, state, AssistantMessage(content="done"))

    events = outbox.peek(installation_id)
    expected = {
        "resource_id": resource_id,
        "version_id": version_id,
        "relation": "plugin_contributed_tool",
        "plugin_installation_id": plugin_installation_id,
    }
    assert expected in events[0][TelemetryField.RESOURCES]
    assert expected in events[1][TelemetryField.RESOURCES]
    assert "private" not in json.dumps(events)


@pytest.mark.asyncio
async def test_hook_closes_failed_request_once_with_resource_attribution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installation_id = str(uuid.uuid4())
    _configure(tmp_path, monkeypatch, installation_id)
    resource_id = str(uuid.uuid4())
    version_id = str(uuid.uuid4())
    ManagedResourceStore().upsert(
        ManagedResourceRecord(
            project_id=str(uuid.uuid4()),
            resource_id=resource_id,
            version_id=version_id,
            version="1.0.0",
            release_channel="published",
            kind="skill",
            slug="failing-skill",
            observed_state="applied",
            observed_at=datetime.now(UTC),
        )
    )
    outbox = TelemetryOutbox(tmp_path / "failure-outbox.json")
    hook = ConductorTelemetryHook(
        agent_name="lead", model_id="openai:gpt-5", outbox=outbox
    )
    ctx = RunContext(session_id="session-1", run_id="request-1", agent_name="lead")
    state = AgentState(messages=[])
    await hook.before_agent(ctx, state)
    tool_call = ToolCall(
        id="skill-1",
        function=FunctionCall(
            name="skill",
            arguments='{"action":"load","skill_name":"failing-skill"}',
        ),
    )

    async def failing_tool_handler(_ctx, _state, _call) -> str:
        raise RuntimeError("private failure")

    with pytest.raises(RuntimeError):
        await hook.wrap_tool_call(ctx, state, tool_call, failing_tool_handler)
    await hook.after_agent(ctx, state, AssistantMessage(content="private response"))

    events = outbox.peek(installation_id)
    request_events = [
        event
        for event in events
        if event[TelemetryField.EVENT_TYPE] == TelemetryEventType.REQUEST
    ]
    assert len(request_events) == 1
    assert request_events[0][TelemetryField.STATUS] == TelemetryEventStatus.ERROR
    assert request_events[0][TelemetryField.RESOURCES] == [
        {
            "resource_id": resource_id,
            "version_id": version_id,
            "relation": "activated_skill",
        }
    ]
    assert "private failure" not in json.dumps(events)


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


@pytest.mark.asyncio
async def test_managed_skill_usage_is_durable_and_content_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    skills = tmp_path / "skills"
    state = tmp_path / "state"
    managed = skills / "research"
    managed.mkdir(parents=True)
    (managed / ".evoflux.json").write_text(
        json.dumps(
            {
                "managed_by": "conductor",
                "resource_id": "11111111-1111-1111-1111-111111111111",
                "resource_version": "1.2.3",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "SKILLS_DIR", str(skills))
    monkeypatch.setattr(settings, "EVOFLUX_STATE_DIR", str(state))

    record_skill_usage("local-only", source="manual", mode="work")
    record_skill_usage("research", source="implicit", mode="coding", duration_ms=12)

    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/usage/resources"
        assert request.headers["authorization"] == "Bearer evc_secret"
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"accepted": 1, "duplicates": 0, "rejected": 0})

    client = ConductorClient(
        "https://conductor.example",
        MemoryCredentialStore("evc_secret"),
        transport=httpx.MockTransport(handler),
    )
    try:
        assert await flush_usage(client) == 1
    finally:
        await client.close()

    events = captured["events"]
    assert isinstance(events, list) and len(events) == 1
    assert events[0]["resource_version"] == "1.2.3"
    assert events[0]["invocation_source"] == "implicit"
    assert "prompt" not in events[0]
    assert not (state / "conductor" / "usage-queue.jsonl").read_text()
