"""Run one parity case through the Python provider stack.

Drives ``build_provider`` → ``stream_with_retry`` → ``stream_and_assemble``,
the path an agent turn takes, and reports what the Rust provider must
reproduce as a flat event list: text/reasoning deltas and usage in arrival
order (``on_model_delta``), retry notices (the retry hooks), restarts, retry
sleeps (recorded, not slept), then the assembled tool calls and ``done``, or
the error the call ended with.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from typing import Any
from unittest import mock

from pydantic import TypeAdapter

#: A tool-call id the assembler made up for a call the provider sent without one.
SYNTHESIZED_ID = re.compile(r"^call_[0-9a-f]{24}$")


def _tool_call_event(tc: Any) -> dict[str, Any]:
    arguments = tc.function.arguments
    return {
        "type": "tool_call",
        "id": "<synthesized>" if SYNTHESIZED_ID.match(tc.id) else tc.id,
        "name": tc.function.name,
        "arguments": json.loads(arguments) if arguments else {},
    }


def _error_event(exc: BaseException) -> dict[str, Any]:
    import httpx

    from app.agent.errors import (
        ContextOverflowError,
        ProviderAuthenticationError,
        ProviderRateLimitError,
        ProviderRequestError,
    )

    event: dict[str, Any] = {"type": "error", "kind": type(exc).__name__}
    if isinstance(
        exc,
        ContextOverflowError
        | ProviderAuthenticationError
        | ProviderRequestError
        | ProviderRateLimitError,
    ):
        event["message"] = str(exc)
        status = getattr(exc, "status_code", None)
        if status is not None:
            event["status_code"] = status
    elif isinstance(exc, httpx.HTTPStatusError):
        event["status_code"] = exc.response.status_code
    return event


async def run_case(case: dict[str, Any], base_url: str) -> list[dict[str, Any]]:
    from app.agent.agent_loop import retry as retry_mod
    from app.agent.agent_loop import streaming as streaming_mod
    from app.agent.hooks.base import BaseAgentHook
    from app.agent.providers.factory import build_provider
    from app.agent.schemas.chat import ChatMessage
    from app.agent.state import AgentState, ModelRequest, RunContext

    from cases import PROVIDER_ENV

    provider_id = case["model"].split(":", 1)[0]
    key_var, url_var = PROVIDER_ENV[provider_id]
    os.environ[key_var] = "mock-key"
    os.environ[url_var] = base_url

    events: list[dict[str, Any]] = []
    finish: dict[str, str | None] = {"reason": None}

    class Recorder(BaseAgentHook):
        async def on_model_delta(self, ctx, state, chunk) -> None:
            if chunk.choices:
                choice = chunk.choices[0]
                if choice.delta.reasoning_content:
                    events.append(
                        {"type": "reasoning", "text": choice.delta.reasoning_content}
                    )
                if choice.delta.content:
                    events.append({"type": "text", "text": choice.delta.content})
                if choice.finish_reason:
                    finish["reason"] = choice.finish_reason
            if chunk.usage:
                events.append({"type": "usage", **chunk.usage.model_dump()})

        async def on_rate_limit(self, ctx, state, retry_after, attempt, max_attempts):
            events.append(
                {
                    "type": "rate_limit",
                    "retry_after": retry_after,
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                }
            )

        async def on_provider_retry(
            self,
            ctx,
            state,
            model,
            attempt,
            max_attempts,
            delay_seconds,
            error_type,
            status_code=None,
            retry_after=None,
        ):
            events.append(
                {
                    "type": "retry",
                    "model": model,
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                    "delay_seconds": delay_seconds,
                    "error_type": error_type,
                    "status_code": status_code,
                    "retry_after": retry_after,
                }
            )

        async def on_provider_exhausted(
            self, ctx, state, model, max_attempts, error_type, status_code=None
        ):
            events.append(
                {
                    "type": "exhausted",
                    "model": model,
                    "max_attempts": max_attempts,
                    "error_type": error_type,
                    "status_code": status_code,
                }
            )

    async def fake_sleep(delay: float, interrupt_event: Any) -> bool:
        events.append({"type": "sleep", "seconds": delay})
        return False

    real_stream_with_retry = retry_mod.stream_with_retry

    async def recording_stream_with_retry(**kwargs: Any):
        async for item in real_stream_with_retry(**kwargs):
            if isinstance(item, retry_mod.StreamRestart):
                events.append({"type": "restart"})
            yield item

    messages = TypeAdapter(list[ChatMessage]).validate_python(case["messages"])
    system, history = messages[0], messages[1:]
    provider = build_provider(case["model"], model_kwargs=dict(case["options"]))
    ctx = RunContext(session_id=None, run_id="run", agent_name="parity")
    state = AgentState(messages=[])
    with (
        mock.patch.object(retry_mod, "_sleep_or_interrupted", fake_sleep),
        mock.patch.object(
            streaming_mod, "stream_with_retry", recording_stream_with_retry
        ),
    ):
        try:
            message, _usage = await streaming_mod.stream_and_assemble(
                req=ModelRequest(messages=tuple(history), system_prompt=system.content),
                ctx=ctx,
                state=state,
                hooks=[Recorder()],
                interrupt_event=None,
                tool_defs=case["tools"],
                primary_provider=provider,
                primary_label=case["model"],
                fallback_provider=None,
                fallback_label="",
                agent_name="parity",
                agent_id="parity",
            )
        except Exception as exc:  # noqa: BLE001 - the error is the result
            events.append(_error_event(exc))
            return events
    for tc in message.tool_calls or []:
        events.append(_tool_call_event(tc))
    events.append({"type": "done", "finish_reason": finish["reason"] or ""})
    return events


def main() -> None:
    from pathlib import Path

    here = Path(__file__).resolve().parent
    sys.path[:0] = [str(here.parent.parent), str(here)]
    case = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    from loguru import logger

    logger.remove()
    events = asyncio.run(run_case(case, sys.argv[2]))
    print(json.dumps(events))


if __name__ == "__main__":
    main()
