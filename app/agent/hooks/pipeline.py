"""Ordered, ownership-checked runtime hook composition."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

from app.agent.hooks.base import BaseAgentHook


class HookStage(IntEnum):
    BASE_CONTEXT = 10
    SESSION_CONTEXT = 20
    CAPABILITY = 30
    INGRESS = 40
    WORKSPACE = 50
    LIFECYCLE = 60
    CONTEXT_CONTROL = 70


@dataclass(slots=True)
class HookPipeline:
    """Collect hooks with a single named owner and deterministic order."""

    _entries: list[tuple[HookStage, int, str, BaseAgentHook]] = field(
        default_factory=list
    )
    _owners: set[str] = field(default_factory=set)

    def add(
        self,
        stage: HookStage,
        owner: str,
        hook: BaseAgentHook | None,
    ) -> None:
        if hook is None:
            return
        if owner in self._owners:
            raise RuntimeError(f"Runtime hook owner registered twice: {owner}")
        self._owners.add(owner)
        self._entries.append((stage, len(self._entries), owner, hook))

    def build(self) -> list[BaseAgentHook]:
        return [
            hook
            for _stage, _index, _owner, hook in sorted(
                self._entries, key=lambda entry: (entry[0], entry[1])
            )
        ]
