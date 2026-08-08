"""Structured telemetry emitted by the model-facing code_context tool."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CodeContextObservation:
    strategy: str
    freshness: str
    result_tokens: int


_current_observation: ContextVar[CodeContextObservation | None] = ContextVar(
    "code_context_observation", default=None
)


def publish_code_context_observation(observation: CodeContextObservation) -> None:
    _current_observation.set(observation)


def consume_code_context_observation() -> CodeContextObservation | None:
    observation = _current_observation.get()
    _current_observation.set(None)
    return observation


__all__ = [
    "CodeContextObservation",
    "consume_code_context_observation",
    "publish_code_context_observation",
]
