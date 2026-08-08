"""Data types for native, symbol-first code-graph navigation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from uuid import UUID

from app.models.code_graph import CodeNode

GraphOperation = Literal[
    "definition",
    "callers",
    "callees",
    "references",
    "impact",
    "neighborhood",
]
FreshnessPolicy = Literal["fast", "balanced", "strict"]


@dataclass(frozen=True, slots=True)
class WorkspaceScope:
    """One authorized repository participating in graph navigation."""

    root: Path
    workspace_id: UUID
    label: str


@dataclass(frozen=True, slots=True)
class LanguageCapability:
    language: str
    extensions: tuple[str, ...]
    graph: bool
    lsp: bool
    indexed_files: int = 0
    workspace_files: int = 0

    @property
    def coverage(self) -> float:
        if self.workspace_files <= 0:
            return 0.0
        return min(1.0, self.indexed_files / self.workspace_files)


@dataclass(frozen=True, slots=True)
class SymbolMatch:
    """An exact graph node selected as a navigation root."""

    node: CodeNode
    scope: WorkspaceScope
    resolution: Literal["qualified", "name", "suffix", "casefold", "suggestion"]
    source: str | None = None

    @property
    def identity(self) -> tuple[UUID, UUID]:
        return self.scope.workspace_id, self.node.id


@dataclass(frozen=True, slots=True)
class GraphRelation:
    """One resolved relationship, including the source call/reference site."""

    source: SymbolMatch
    target: SymbolMatch
    kind: str
    depth: int
    cross_repo: bool
    callsite_file: str
    callsite_line: int
    callsite_source: str | None = None

    @property
    def direction_key(self) -> tuple[tuple[UUID, UUID], tuple[UUID, UUID], str]:
        return self.source.identity, self.target.identity, self.kind


@dataclass(slots=True)
class CodeGraphResult:
    symbol: str
    operation: GraphOperation
    strategy: str
    graph_version: str | None
    working_tree_revision: str
    freshness: Literal["fresh", "partial", "unavailable"]
    matches: list[SymbolMatch]
    relations: list[GraphRelation]
    suggestions: list[SymbolMatch]
    capabilities: list[LanguageCapability]
    dirty_files: int = 0
    pending_edges: int = 0
    limitations: list[str] = field(default_factory=list)
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class RetrievalFreshness:
    graph_version: str | None
    working_tree_revision: str
    freshness: Literal["fresh", "partial", "unavailable"]
    indexed_files: int
    dirty_files: int
    change_source: str
