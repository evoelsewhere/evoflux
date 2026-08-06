"""Structured observations emitted by the model-facing code query tool.

The telemetry hook consumes this side channel after tool execution. Keeping
metrics out of the rendered text means output wording can evolve without a
regex parser silently changing behavior.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass


CODE_QUERY_DEFAULT_MAX_FILES = 6


@dataclass(frozen=True, slots=True)
class CodeQueryObservation:
    strategy: str
    freshness: str
    cache_hit: bool
    result_tokens: int


_current_observation: ContextVar[CodeQueryObservation | None] = ContextVar(
    "code_query_observation", default=None
)


def publish_code_query_observation(observation: CodeQueryObservation) -> None:
    _current_observation.set(observation)


def consume_code_query_observation() -> CodeQueryObservation | None:
    observation = _current_observation.get()
    _current_observation.set(None)
    return observation
