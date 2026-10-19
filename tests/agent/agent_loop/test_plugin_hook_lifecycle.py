"""Smoke the canonical adapter through the real Agent.run() hook chain."""

import asyncio
from typing import Any, AsyncIterator

import pytest

from app.agent.agent_loop import Agent
from app.agent.plugins.hook_contract import (
    HookDefinition,
    HookEvent,
    HookFailurePolicy,
    HookRegistration,
    HookSettingsPolicy,
    HookSource,
)
from app.agent.plugins.hook_dispatcher import HookDispatchResult
from app.agent.plugins.hook_lifecycle import DeclarativeAgentLifecycleHook
from app.agent.plugins.hook_resolution import EventDecision
from app.agent.providers.base import LLMProviderBase
from app.agent.schemas.chat import (
    AssistantMessage,
    ChatCompletionChunk,
    ChatCompletionChunkChoice,
    ChatCompletionDelta,
    ChatMessage,
    HumanMessage,
)
from pathlib import Path


class _OneResponseProvider(LLMProviderBase):
    model = "hook-smoke-model"

    async def chat(
        self, messages: list[ChatMessage], **kwargs: Any
    ) -> AssistantMessage:
        return AssistantMessage(content="smoke complete")

    def stream(
        self,
        messages: list[ChatMessage],
        tools: list[dict] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatCompletionChunk]:
        async def chunks():
            yield ChatCompletionChunk(
                id="hook-smoke",
                created=1,
                model=self.model,
                choices=[
                    ChatCompletionChunkChoice(
                        index=0,
                        delta=ChatCompletionDelta(content="smoke complete"),
                        finish_reason="stop",
                    )
                ],
            )

        return chunks()


@pytest.mark.asyncio
async def test_agent_run_dispatches_hooks_at_lifecycle_boundaries(monkeypatch):
    events: list[HookEvent] = []
    payloads: list[dict[str, Any]] = []

    async def dispatch(event, payload, **kwargs):
        events.append(event)
        payloads.append(payload)
        if event is HookEvent.AGENT_STOP:
            raise RuntimeError("terminal hook failure must not mask result")
        return HookDispatchResult(
            decision=EventDecision(event=event, denied=False, reason=None, values={}),
            statuses={},
        )

    monkeypatch.setattr("app.agent.plugins.hook_lifecycle.dispatch_hooks", dispatch)
    lifecycle = DeclarativeAgentLifecycleHook(
        policy=HookSettingsPolicy(),
        settings_registrations=(),
        plugin_registrations=(),
        plugin_roots={},
    )

    async def no_legacy_hooks(_self, _role):
        return []

    monkeypatch.setattr(Agent, "_load_plugin_hooks", no_legacy_hooks)
    monkeypatch.setattr(
        "app.agent.plugins.hook_lifecycle.build_agent_lifecycle_hook",
        lambda **kwargs: lifecycle,
    )

    agent = Agent(name="hook-smoke", llm_provider=_OneResponseProvider())
    result = await agent.run([HumanMessage(content="run lifecycle smoke")])

    assert result
    assert events == [
        HookEvent.PROMPT_SUBMIT,
        HookEvent.AGENT_START,
        HookEvent.MODEL_BEFORE,
        HookEvent.MODEL_AFTER,
        HookEvent.COMPLETION_BEFORE,
        HookEvent.AGENT_STOP,
    ]
    assert all(isinstance(event, HookEvent) for event in events)
    stop_payload = payloads[events.index(HookEvent.AGENT_STOP)]
    assert stop_payload["outcome"] == "completed"


@pytest.mark.asyncio
async def test_smoke_trusted_hook_stays_blocked_without_native_isolation(
    monkeypatch, tmp_path: Path
):
    class Backend:
        launched = False

        def supports(self, profile):
            return False

        async def launch(self, *args, **kwargs):
            self.launched = True
            raise AssertionError("unsupported backend must not launch a process")

    backend = Backend()
    definition = HookDefinition(
        hook_id="smoke-before-model",
        event=HookEvent.MODEL_BEFORE,
        command=("./hook.py",),
        timeout_seconds=5,
        input_fields=("session_id", "run_id", "agent_name", "model", "attempt"),
        output_fields=(),
        failure_policy=HookFailurePolicy.FAIL_OPEN,
    )
    registration = HookRegistration(
        hook_id=definition.hook_id,
        event=definition.event,
        source=HookSource.SETTINGS,
        definition=definition,
        digest="a" * 64,
        trusted=True,
    )
    lifecycle = DeclarativeAgentLifecycleHook(
        policy=HookSettingsPolicy(),
        settings_registrations=(registration,),
        plugin_registrations=(),
        plugin_roots={(HookSource.SETTINGS.value, None, definition.hook_id): tmp_path},
        backend=backend,
    )

    async def no_legacy_hooks(_self, _role):
        return []

    monkeypatch.setattr(Agent, "_load_plugin_hooks", no_legacy_hooks)
    monkeypatch.setattr(
        "app.agent.plugins.hook_lifecycle.build_agent_lifecycle_hook",
        lambda **kwargs: lifecycle,
    )
    agent = Agent(name="hook-isolation-smoke", llm_provider=_OneResponseProvider())

    with pytest.raises(PermissionError, match="hook isolation is unavailable"):
        await agent.run([HumanMessage(content="verify fail closed")])
    assert backend.launched is False


@pytest.mark.asyncio
async def test_agent_stop_fires_after_lifecycle_failure(monkeypatch):
    events: list[HookEvent] = []
    payloads: list[dict[str, Any]] = []

    async def dispatch(event, payload, **kwargs):
        events.append(event)
        payloads.append(payload)
        if event is HookEvent.MODEL_BEFORE:
            raise RuntimeError("simulated lifecycle failure")
        return HookDispatchResult(
            decision=EventDecision(event=event, denied=False, reason=None, values={}),
            statuses={},
        )

    monkeypatch.setattr("app.agent.plugins.hook_lifecycle.dispatch_hooks", dispatch)
    lifecycle = DeclarativeAgentLifecycleHook(
        policy=HookSettingsPolicy(),
        settings_registrations=(),
        plugin_registrations=(),
        plugin_roots={},
    )

    async def no_legacy_hooks(_self, _role):
        return []

    monkeypatch.setattr(Agent, "_load_plugin_hooks", no_legacy_hooks)
    monkeypatch.setattr(
        "app.agent.plugins.hook_lifecycle.build_agent_lifecycle_hook",
        lambda **kwargs: lifecycle,
    )
    agent = Agent(name="hook-stop-on-error", llm_provider=_OneResponseProvider())

    with pytest.raises(RuntimeError, match="simulated lifecycle failure"):
        await agent.run([HumanMessage(content="run lifecycle error smoke")])

    assert events == [
        HookEvent.PROMPT_SUBMIT,
        HookEvent.AGENT_START,
        HookEvent.MODEL_BEFORE,
        HookEvent.AGENT_STOP,
    ]
    assert payloads[-1]["outcome"] == "failed"


@pytest.mark.asyncio
async def test_agent_stop_reports_cancelled_terminal_outcome(monkeypatch):
    events: list[HookEvent] = []
    payloads: list[dict[str, Any]] = []

    async def dispatch(event, payload, **kwargs):
        events.append(event)
        payloads.append(payload)
        return HookDispatchResult(
            decision=EventDecision(event=event, denied=False, reason=None, values={}),
            statuses={},
        )

    monkeypatch.setattr("app.agent.plugins.hook_lifecycle.dispatch_hooks", dispatch)
    lifecycle = DeclarativeAgentLifecycleHook(
        policy=HookSettingsPolicy(),
        settings_registrations=(),
        plugin_registrations=(),
        plugin_roots={},
    )

    async def no_legacy_hooks(_self, _role):
        return []

    monkeypatch.setattr(Agent, "_load_plugin_hooks", no_legacy_hooks)
    monkeypatch.setattr(
        "app.agent.plugins.hook_lifecycle.build_agent_lifecycle_hook",
        lambda **kwargs: lifecycle,
    )
    interrupt_event = asyncio.Event()
    interrupt_event.set()
    agent = Agent(name="hook-stop-on-cancel", llm_provider=_OneResponseProvider())

    await agent.run(
        [HumanMessage(content="run lifecycle cancellation smoke")],
        interrupt_event=interrupt_event,
    )

    assert events == [
        HookEvent.PROMPT_SUBMIT,
        HookEvent.AGENT_START,
        HookEvent.AGENT_STOP,
    ]
    assert payloads[-1]["outcome"] == "cancelled"
