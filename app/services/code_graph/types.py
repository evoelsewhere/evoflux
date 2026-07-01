"""Language-agnostic value objects produced by code parsers.

Parsers emit ``ParseResult`` objects whose nodes/edges reference each other by
*local* string ids (unique within a single file parse). The indexer assigns real
database UUIDs and resolves cross-file edges by name afterwards, so parsers stay
pure and free of any database concerns.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# --- Node kinds -------------------------------------------------------------
NODE_FILE = "file"
NODE_MODULE = "module"
NODE_CLASS = "class"
NODE_FUNCTION = "function"
NODE_METHOD = "method"
NODE_INTERFACE = "interface"
NODE_VARIABLE = "variable"

# --- Edge kinds -------------------------------------------------------------
EDGE_CONTAINS = "contains"
EDGE_CALLS = "calls"
EDGE_INHERITS = "inherits"
EDGE_IMPLEMENTS = "implements"
EDGE_REFERENCES = "references"
EDGE_IMPORTS = "imports"
EDGE_DECORATED_BY = "decorated_by"


@dataclass(frozen=True, slots=True)
class ExtractedNode:
    """A symbol discovered while parsing a file."""

    local_id: str
    kind: str
    name: str
    qualified_name: str
    line_start: int
    line_end: int
    signature: str | None = None
    docstring: str | None = None


@dataclass(frozen=True, slots=True)
class ExtractedEdge:
    """A relationship between two symbols.

    Exactly one of ``dst_local_id`` (same-file structural target) or
    ``dst_name`` (cross-file target resolved later by name) is set.
    """

    src_local_id: str
    kind: str
    dst_local_id: str | None = None
    dst_name: str | None = None
    line: int | None = None
    # Raw import source string (EDGE_IMPORTS only), e.g. "./utils",
    # "app.services", "com.example.bar.Baz". Survives into the indexer's
    # unresolved-import bookkeeping even when dst_name can't be resolved
    # within this workspace — see ImportRef.module_path.
    module_path: str | None = None


@dataclass(frozen=True, slots=True)
class ParseResult:
    """Everything a parser extracted from one file."""

    language: str
    file_path: str
    nodes: list[ExtractedNode] = field(default_factory=list)
    edges: list[ExtractedEdge] = field(default_factory=list)
