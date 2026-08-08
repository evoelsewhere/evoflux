"""Pure desired-state reconciliation for stable keyed components."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True, slots=True)
class ReconcilePlan:
    """Difference between a source snapshot and the last committed generation."""

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
    def affected(self) -> frozenset[str]:
        return frozenset((*self.reprocess, *self.deletes))

    @property
    def is_noop(self) -> bool:
        return not self.adds and not self.updates and not self.deletes


def plan_reconciliation(
    current: Mapping[str, str],
    previous: Mapping[str, str],
    *,
    force: bool = False,
) -> ReconcilePlan:
    """Build a deterministic add/update/delete plan from keyed fingerprints.

    ``force`` reprocesses every current component without turning existing
    components into additions. This preserves stable target identities during
    a parser-format rebuild while still removing disappeared components.
    """
    current_copy = dict(current)
    previous_copy = dict(previous)
    current_keys = set(current_copy)
    previous_keys = set(previous_copy)
    adds = tuple(sorted(current_keys - previous_keys))
    deletes = tuple(sorted(previous_keys - current_keys))
    shared = current_keys & previous_keys
    if force:
        updates = tuple(sorted(shared))
        unchanged: tuple[str, ...] = ()
    else:
        updates = tuple(
            sorted(key for key in shared if current_copy[key] != previous_copy[key])
        )
        unchanged = tuple(
            sorted(key for key in shared if current_copy[key] == previous_copy[key])
        )
    return ReconcilePlan(
        current=MappingProxyType(current_copy),
        previous=MappingProxyType(previous_copy),
        adds=adds,
        updates=updates,
        deletes=deletes,
        unchanged=unchanged,
    )


__all__ = ["ReconcilePlan", "plan_reconciliation"]
