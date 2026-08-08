"""Deterministic desired-state reconciliation for keyed source components."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True, slots=True)
class ReconcilePlan:
    current: Mapping[str, str]
    previous: Mapping[str, str]
    adds: tuple[str, ...]
    updates: tuple[str, ...]
    deletes: tuple[str, ...]
    unchanged: tuple[str, ...]

    @property
    def reprocess(self) -> tuple[str, ...]:
        return self.adds + self.updates

    @property
    def is_noop(self) -> bool:
        return not self.adds and not self.updates and not self.deletes


def plan_reconciliation(
    current: Mapping[str, str],
    previous: Mapping[str, str],
    *,
    force: bool = False,
) -> ReconcilePlan:
    """Diff snapshots exactly like a keyed source-to-target dataflow."""
    current_copy = dict(current)
    previous_copy = dict(previous)
    current_keys = set(current_copy)
    previous_keys = set(previous_copy)
    adds = tuple(sorted(current_keys - previous_keys))
    deletes = tuple(sorted(previous_keys - current_keys))
    shared = current_keys & previous_keys
    updates = tuple(
        sorted(
            key for key in shared if force or current_copy[key] != previous_copy[key]
        )
    )
    unchanged = tuple(sorted(shared - set(updates)))
    return ReconcilePlan(
        current=MappingProxyType(current_copy),
        previous=MappingProxyType(previous_copy),
        adds=adds,
        updates=updates,
        deletes=deletes,
        unchanged=unchanged,
    )


__all__ = ["ReconcilePlan", "plan_reconciliation"]
