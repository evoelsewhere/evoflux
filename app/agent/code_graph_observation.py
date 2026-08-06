"""Structured telemetry emitted by the model-facing code_graph tool."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CodeGraphObservation:
    strategy: str
    freshness: str
    result_tokens: int


_current_observation: ContextVar[CodeGraphObservation | None] = ContextVar(
    "code_graph_observation", default=None
)


def publish_code_graph_observation(observation: CodeGraphObservation) -> None:
    _current_observation.set(observation)


def consume_code_graph_observation() -> CodeGraphObservation | None:
    observation = _current_observation.get()
    _current_observation.set(None)
    return observation
