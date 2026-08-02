"""Task-risk based reasoning and verification policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

TaskComplexity = Literal["trivial", "simple", "multi_step", "complex"]
VerificationRigor = Literal["basic", "standard", "strict"]


@dataclass(frozen=True)
class ExecutionPolicy:
    complexity: TaskComplexity
    thinking_level: str
    verification_rigor: VerificationRigor


def resolve_execution_policy(
    *,
    complexity: str | None,
    priority: str | None,
    target_paths: list[str] | None = None,
    explicit_thinking_level: str | None = None,
    provider_default_thinking_level: str | None = None,
    supported_thinking_levels: tuple[str, ...] = (),
) -> ExecutionPolicy:
    normalized = _resolve_complexity(complexity, priority, target_paths or [])
    desired = {
        "trivial": "low",
        "simple": "low",
        "multi_step": "medium",
        "complex": "high",
    }[normalized]
    if priority == "critical":
        desired = "high"
    elif priority == "high" and desired == "low":
        desired = "medium"
    if provider_default_thinking_level:
        desired = provider_default_thinking_level
    if explicit_thinking_level:
        desired = explicit_thinking_level
    thinking = _supported_level(desired, supported_thinking_levels)
    rigor_by_complexity: dict[TaskComplexity, VerificationRigor] = {
        "trivial": "basic",
        "simple": "standard",
        "multi_step": "strict",
        "complex": "strict",
    }
    rigor = rigor_by_complexity[normalized]
    return ExecutionPolicy(normalized, thinking, rigor)


def _resolve_complexity(
    complexity: str | None,
    priority: str | None,
    target_paths: list[str],
) -> TaskComplexity:
    if complexity == "trivial":
        return "trivial"
    if complexity == "simple":
        return "simple"
    if complexity == "multi_step":
        return "multi_step"
    if complexity == "complex":
        return "complex"
    if priority == "critical" or len(target_paths) >= 4:
        return "complex"
    if len(target_paths) >= 2:
        return "multi_step"
    return "simple"


def _supported_level(desired: str, supported: tuple[str, ...]) -> str:
    if not supported:
        return ""
    if desired in supported:
        return desired
    order = ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")
    desired_index = order.index(desired) if desired in order else 3
    ranked = [level for level in supported if level in order]
    if not ranked:
        return supported[0]
    return min(ranked, key=lambda level: abs(order.index(level) - desired_index))
