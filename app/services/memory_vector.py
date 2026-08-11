"""Optional vector backend interface for unified EvoFlux Memory.

The default EvoFlux memory path remains deterministic markdown + lexical
retrieval. This module defines the narrow seam for future semantic backends
such as Turbovec without adding a required vector database dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from app.core.runtime_settings import load_runtime_settings


@dataclass(frozen=True)
class MemoryVectorChunk:
    """A chunk eligible for optional semantic indexing."""

    id: str
    source_ref: str
    path: str | None
    text: str
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryVectorHit:
    """A semantic retrieval result from an optional vector backend."""

    chunk_id: str
    source_ref: str
    score: float
    text: str
    path: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


class MemoryVectorBackend(Protocol):
    """Narrow interface implemented by optional semantic backends."""

    @property
    def name(self) -> str: ...

    @property
    def enabled(self) -> bool: ...

    async def upsert(self, chunks: list[MemoryVectorChunk]) -> None: ...

    async def search(
        self,
        query: str,
        *,
        top_k: int,
        allow_sources: list[str] | None = None,
    ) -> list[MemoryVectorHit]: ...


class DisabledMemoryVectorBackend:
    """Default backend: explicit disabled state with deterministic behavior."""

    name = "disabled"
    enabled = False

    async def upsert(self, chunks: list[MemoryVectorChunk]) -> None:
        return None

    async def search(
        self,
        query: str,
        *,
        top_k: int,
        allow_sources: list[str] | None = None,
    ) -> list[MemoryVectorHit]:
        return []


class UnavailableMemoryVectorBackend:
    """Placeholder for configured-but-unavailable optional backends."""

    enabled = False

    def __init__(self, name: str, reason: str) -> None:
        self.name = name
        self.reason = reason

    async def upsert(self, chunks: list[MemoryVectorChunk]) -> None:
        return None

    async def search(
        self,
        query: str,
        *,
        top_k: int,
        allow_sources: list[str] | None = None,
    ) -> list[MemoryVectorHit]:
        return []


def get_memory_vector_backend() -> MemoryVectorBackend:
    """Return the configured optional vector backend.

    Today only the disabled default is functional. The `turbovec` name is
    accepted as an explicit experimental selection so config/docs/manual tooling
    can detect intent without importing a native dependency or changing default
    retrieval behavior.
    """
    cfg = load_runtime_settings().memory_vector
    if not cfg.enabled or cfg.backend == "disabled":
        return DisabledMemoryVectorBackend()
    if cfg.backend == "turbovec":
        return UnavailableMemoryVectorBackend(
            "turbovec",
            "Turbovec backend is planned but not implemented in this build.",
        )
    return UnavailableMemoryVectorBackend(
        cfg.backend,
        f"Unknown memory vector backend: {cfg.backend}",
    )


async def semantic_memory_search(
    query: str,
    *,
    top_k: int = 8,
    allow_sources: list[str] | None = None,
) -> list[MemoryVectorHit]:
    """Search the optional semantic backend when enabled, otherwise return []."""
    backend = get_memory_vector_backend()
    if not backend.enabled:
        return []
    return await backend.search(query, top_k=max(1, top_k), allow_sources=allow_sources)


__all__ = [
    "DisabledMemoryVectorBackend",
    "MemoryVectorBackend",
    "MemoryVectorChunk",
    "MemoryVectorHit",
    "UnavailableMemoryVectorBackend",
    "get_memory_vector_backend",
    "semantic_memory_search",
]
