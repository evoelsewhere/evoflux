"""Public value objects for the ported code-context service."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

GraphOperation = Literal[
    "definition",
    "callers",
    "callees",
    "references",
    "impact",
    "neighborhood",
]
CodeContextAction = Literal[
    "search",
    "grep",
    "definition",
    "callers",
    "callees",
    "references",
    "impact",
    "neighborhood",
]


@dataclass(frozen=True, slots=True)
class RepositoryScope:
    """One repository the current sandbox authorizes for retrieval."""

    root: Path
    label: str


@dataclass(frozen=True, slots=True)
class IndexStats:
    files: int = 0
    chunks: int = 0
    symbols: int = 0
    relations: int = 0
    languages: tuple[str, ...] = ()
    graph_languages: tuple[str, ...] = ()
    errors: tuple[tuple[str, str], ...] = ()
    version: str | None = None


@dataclass(frozen=True, slots=True)
class CodeSymbol:
    id: str
    repository: str
    file_path: str
    language: str
    kind: str
    name: str
    qualified_name: str
    line_start: int
    line_end: int
    signature: str | None = None
    docstring: str | None = None
    source: str | None = None

    @property
    def identity(self) -> tuple[str, str]:
        return self.repository, self.id


@dataclass(frozen=True, slots=True)
class SearchHit:
    repository: str
    file_path: str
    language: str
    line_start: int
    line_end: int
    content: str
    score: float
    symbol: str | None = None
    repository_path: str | None = None


@dataclass(frozen=True, slots=True)
class GraphRelation:
    kind: str
    depth: int
    cross_repo: bool
    source: CodeSymbol
    target: CodeSymbol
    callsite_file: str
    callsite_line: int
    callsite_source: str | None = None


@dataclass(frozen=True, slots=True)
class GraphSnapshot:
    symbols: tuple[CodeSymbol, ...]
    relations: tuple[GraphRelation, ...]
    total_symbols: int
    total_relations: int


@dataclass(slots=True)
class CodeContextResult:
    action: CodeContextAction
    query: str
    strategy: str
    index_version: str | None
    repositories: tuple[str, ...]
    hits: list[SearchHit] = field(default_factory=list)
    matches: list[CodeSymbol] = field(default_factory=list)
    relations: list[GraphRelation] = field(default_factory=list)
    suggestions: list[CodeSymbol] = field(default_factory=list)
    stats: dict[str, IndexStats] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)
    truncated: bool = False


__all__ = [
    "CodeContextAction",
    "CodeContextResult",
    "CodeSymbol",
    "GraphOperation",
    "GraphRelation",
    "GraphSnapshot",
    "IndexStats",
    "RepositoryScope",
    "SearchHit",
]
