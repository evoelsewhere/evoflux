"""Request and response schemas for the repository-local code-context API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

CodeAction = Literal[
    "search",
    "grep",
    "definition",
    "callers",
    "callees",
    "references",
    "impact",
    "neighborhood",
]


class IndexStatsOut(BaseModel):
    files: int = 0
    chunks: int = 0
    symbols: int = 0
    relations: int = 0
    languages: list[str] = []
    graph_languages: list[str] = []
    errors: list[tuple[str, str]] = []
    version: str | None = None


class CodeContextStatusResponse(IndexStatsOut):
    indexed: bool = False
    indexing: bool = False
    index_error: str | None = None


class CodeContextIndexRequest(BaseModel):
    full: bool = False


class ProjectCodeContextIndexResponse(BaseModel):
    indexing: bool
    repo_count: int
    already_running: int
    full: bool


class CodeContextQueryRequest(BaseModel):
    action: CodeAction = "search"
    query: str = Field(min_length=1, max_length=2_000)
    repository: str | None = None
    repositories: list[str] = Field(default_factory=list)
    paths: list[str] | None = None
    languages: list[str] | None = None
    depth: int = Field(default=1, ge=1, le=3)
    limit: int = Field(default=20, ge=1, le=100)
    refresh: bool = True


class CodeContextHitOut(BaseModel):
    repository: str
    file_path: str
    language: str
    line_start: int
    line_end: int
    content: str
    score: float
    symbol: str | None = None
    repository_path: str | None = None


class CodeContextSymbolOut(BaseModel):
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


class CodeContextRelationOut(BaseModel):
    kind: str
    depth: int
    cross_repo: bool
    source: CodeContextSymbolOut
    target: CodeContextSymbolOut
    callsite_file: str
    callsite_line: int
    callsite_source: str | None = None


class CodeContextQueryResponse(BaseModel):
    action: CodeAction
    query: str
    strategy: str
    index_version: str | None
    repositories: list[str]
    hits: list[CodeContextHitOut]
    matches: list[CodeContextSymbolOut]
    relations: list[CodeContextRelationOut]
    suggestions: list[CodeContextSymbolOut]
    stats: dict[str, IndexStatsOut]
    limitations: list[str]
    truncated: bool


__all__ = [
    "CodeAction",
    "CodeContextHitOut",
    "CodeContextIndexRequest",
    "CodeContextQueryRequest",
    "CodeContextQueryResponse",
    "CodeContextRelationOut",
    "CodeContextStatusResponse",
    "CodeContextSymbolOut",
    "IndexStatsOut",
    "ProjectCodeContextIndexResponse",
]
