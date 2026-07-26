"""Code knowledge graph: tree-sitter parsing and workspace indexing."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_INDEXER_EXPORTS = {
    "FileIndex",
    "IndexedEdge",
    "IndexedNode",
    "WorkspaceIndex",
    "index_workspace",
}


def __getattr__(name: str) -> Any:  # noqa: ANN401 - public lazy re-export
    if name not in _INDEXER_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module("app.services.code_graph.indexer"), name)
    globals()[name] = value
    return value

__all__ = [
    "FileIndex",
    "IndexedEdge",
    "IndexedNode",
    "WorkspaceIndex",
    "index_workspace",
]
