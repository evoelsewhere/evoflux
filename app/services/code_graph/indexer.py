"""Workspace indexer — walks a coding workspace and builds an in-memory graph.

This module is pure (no database, no async): it produces a :class:`WorkspaceIndex`
that the service layer persists. Cross-file edges (``calls``, ``inherits``, …) are
resolved by name with a high-precision heuristic: a name target is linked only
when it resolves to a *single* definition in the workspace. Ambiguous or external
targets are dropped, keeping the P1 graph clean. Scope-aware resolution is future
work.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from app.agent.tools.builtin.filesystem._ignore import (
    _SKIPPED_DIR_NAMES,
    is_gitignored,
    load_gitignore_rules,
)
from app.services.code_graph.parsers.registry import ParserRegistry, default_registry
from app.services.code_graph.types import (
    EDGE_IMPLEMENTS,
    EDGE_INHERITS,
    NODE_CLASS,
    NODE_FUNCTION,
    NODE_INTERFACE,
    NODE_METHOD,
)

# Skip files larger than this — generated bundles/minified blobs aren't worth
# parsing and can be huge.
_MAX_FILE_BYTES = 1_500_000

# Definition kinds a name-based call/reference may resolve to.
_CALLABLE_KINDS = frozenset({NODE_FUNCTION, NODE_METHOD, NODE_CLASS})
# Definition kinds an inherits/implements edge may resolve to.
_TYPE_KINDS = frozenset({NODE_CLASS, NODE_INTERFACE})


@dataclass(frozen=True, slots=True)
class IndexedNode:
    key: str
    kind: str
    name: str
    qualified_name: str
    file_path: str
    language: str
    line_start: int
    line_end: int
    signature: str | None
    docstring: str | None


@dataclass(frozen=True, slots=True)
class IndexedEdge:
    src_key: str
    dst_key: str
    kind: str
    file_path: str
    line: int | None


@dataclass(frozen=True, slots=True)
class FileIndex:
    file_path: str
    language: str
    content_hash: str
    node_count: int
    edge_count: int


@dataclass(slots=True)
class WorkspaceIndex:
    nodes: list[IndexedNode] = field(default_factory=list)
    edges: list[IndexedEdge] = field(default_factory=list)
    files: list[FileIndex] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ExistingDef:
    """A definition already stored in the graph, used as a resolution target.

    During an incremental re-index only the changed files are re-parsed; the
    nodes of *unchanged* files are passed in as ``ExistingDef`` so cross-file
    edges (e.g. a re-parsed file calling a function defined elsewhere) still
    resolve. ``key`` is the ``str(uuid)`` of the stored :class:`CodeNode`.
    """

    key: str
    name: str
    kind: str


def index_workspace(
    root: str | Path, *, registry: ParserRegistry | None = None
) -> WorkspaceIndex:
    """Parse every supported file under ``root`` into a resolved graph."""
    registry = registry or default_registry()
    root_path = Path(root).expanduser().resolve()
    return _build_index(
        _iter_source_files(root_path, registry), registry, existing_defs=()
    )


def index_files(
    root: str | Path,
    rel_paths: Iterable[str],
    *,
    registry: ParserRegistry | None = None,
    existing_defs: Sequence[ExistingDef] = (),
) -> WorkspaceIndex:
    """Parse only ``rel_paths`` (relative POSIX paths) into a resolved graph.

    Cross-file edges resolve against the parsed nodes *plus* ``existing_defs``
    (nodes of unchanged files already in the graph). The returned nodes/files
    cover only the parsed files; edges may target an ``ExistingDef.key`` (a
    stored node's ``str(uuid)``).
    """
    registry = registry or default_registry()
    root_path = Path(root).expanduser().resolve()
    return _build_index(
        _iter_named_files(root_path, rel_paths, registry),
        registry,
        existing_defs=existing_defs,
    )


def hash_workspace_files(
    root: str | Path, *, registry: ParserRegistry | None = None
) -> dict[str, str]:
    """Return ``{relative_path: sha256}`` for every indexable file under ``root``.

    Cheap relative to parsing — used by incremental re-index to detect which
    files actually changed before deciding what to re-parse.
    """
    registry = registry or default_registry()
    root_path = Path(root).expanduser().resolve()
    return {
        rel: _hash_bytes(source)
        for rel, source in _iter_source_files(root_path, registry)
    }


def _build_index(
    files_iter: Iterator[tuple[str, bytes]],
    registry: ParserRegistry,
    *,
    existing_defs: Sequence[ExistingDef],
) -> WorkspaceIndex:
    """Shared core: turn a stream of ``(rel_path, bytes)`` into a resolved graph."""
    index = WorkspaceIndex()

    # Per-file raw extraction keyed by workspace-unique node key. Seed the name
    # map and kind map with pre-existing definitions so cross-file edges from a
    # re-parsed file can resolve to unchanged symbols.
    name_to_keys: dict[str, list[str]] = {}
    extra_kinds: dict[str, str] = {}
    for definition in existing_defs:
        name_to_keys.setdefault(definition.name, []).append(definition.key)
        extra_kinds[definition.key] = definition.kind

    raw_edges: list[tuple[str, str | None, str | None, str, int | None]] = []
    # (src_key, dst_local_id, dst_name, kind, line)
    local_to_key: dict[tuple[str, str], str] = {}

    for file_path, source in files_iter:
        parser = registry.for_path(file_path)
        if parser is None:
            continue
        try:
            result = parser.parse(file_path=file_path, source=source)
        except Exception as exc:  # noqa: BLE001 — never let one file break indexing
            index.errors.append(f"{file_path}: {exc}")
            continue

        node_count = 0
        for node in result.nodes:
            key = f"{file_path}::{node.local_id}"
            local_to_key[(file_path, node.local_id)] = key
            index.nodes.append(
                IndexedNode(
                    key=key,
                    kind=node.kind,
                    name=node.name,
                    qualified_name=node.qualified_name,
                    file_path=file_path,
                    language=result.language,
                    line_start=node.line_start,
                    line_end=node.line_end,
                    signature=node.signature,
                    docstring=node.docstring,
                )
            )
            name_to_keys.setdefault(node.name, []).append(key)
            node_count += 1

        for edge in result.edges:
            src_key = local_to_key.get((file_path, edge.src_local_id))
            if src_key is None:
                continue
            raw_edges.append(
                (src_key, edge.dst_local_id, edge.dst_name, edge.kind, edge.line)
            )

        index.files.append(
            FileIndex(
                file_path=file_path,
                language=result.language,
                content_hash=_hash_bytes(source),
                node_count=node_count,
                edge_count=0,  # filled in after resolution
            )
        )

    _resolve_edges(index, raw_edges, local_to_key, name_to_keys, extra_kinds)
    _backfill_edge_counts(index)
    return index


def _resolve_edges(
    index: WorkspaceIndex,
    raw_edges: list[tuple[str, str | None, str | None, str, int | None]],
    local_to_key: dict[tuple[str, str], str],
    name_to_keys: dict[str, list[str]],
    extra_kinds: dict[str, str] | None = None,
) -> None:
    kind_by_key = {n.key: n.kind for n in index.nodes}
    if extra_kinds:
        kind_by_key.update(extra_kinds)
    file_by_key = {n.key: n.file_path for n in index.nodes}
    seen: set[tuple[str, str, str]] = set()

    for src_key, dst_local_id, dst_name, kind, line in raw_edges:
        dst_key: str | None = None
        if dst_local_id is not None:
            src_file = file_by_key.get(src_key, "")
            dst_key = local_to_key.get((src_file, dst_local_id))
        elif dst_name is not None:
            allowed = (
                _TYPE_KINDS
                if kind in {EDGE_INHERITS, EDGE_IMPLEMENTS}
                else _CALLABLE_KINDS
            )
            dst_key = _resolve_name(dst_name, name_to_keys, kind_by_key, allowed)

        if dst_key is None or dst_key == src_key:
            continue
        dedupe = (src_key, dst_key, kind)
        if dedupe in seen:
            continue
        seen.add(dedupe)
        index.edges.append(
            IndexedEdge(
                src_key=src_key,
                dst_key=dst_key,
                kind=kind,
                file_path=file_by_key.get(src_key, ""),
                line=line,
            )
        )


def _resolve_name(
    name: str,
    name_to_keys: dict[str, list[str]],
    kind_by_key: dict[str, str],
    allowed_kinds: frozenset[str],
) -> str | None:
    """Resolve a name to a single matching definition key, else ``None``."""
    candidates = [
        key
        for key in name_to_keys.get(name, [])
        if kind_by_key.get(key) in allowed_kinds
    ]
    if len(candidates) == 1:
        return candidates[0]
    return None


def _backfill_edge_counts(index: WorkspaceIndex) -> None:
    counts: dict[str, int] = {}
    for edge in index.edges:
        counts[edge.file_path] = counts.get(edge.file_path, 0) + 1
    index.files = [
        FileIndex(
            file_path=f.file_path,
            language=f.language,
            content_hash=f.content_hash,
            node_count=f.node_count,
            edge_count=counts.get(f.file_path, 0),
        )
        for f in index.files
    ]


def _iter_named_files(
    root: Path, rel_paths: Iterable[str], registry: ParserRegistry
) -> Iterator[tuple[str, bytes]]:
    """Yield ``(rel_path, bytes)`` for the given paths that are still readable."""
    extensions = registry.supported_extensions()
    for rel in rel_paths:
        if Path(rel).suffix.lower() not in extensions:
            continue
        fpath = root / rel
        try:
            if not fpath.is_file() or fpath.stat().st_size > _MAX_FILE_BYTES:
                continue
            source = fpath.read_bytes()
        except OSError:
            continue
        yield rel, source


def _iter_source_files(
    root: Path, registry: ParserRegistry
) -> Iterator[tuple[str, bytes]]:
    """Yield ``(relative_posix_path, bytes)`` for supported, non-ignored files."""
    extensions = registry.supported_extensions()
    gitignore_rules = load_gitignore_rules(root)
    for current_root, dirs, files in os.walk(root):
        current = Path(current_root)
        dirs[:] = [
            d
            for d in dirs
            if not d.startswith(".")
            and d not in _SKIPPED_DIR_NAMES
            and not is_gitignored(
                (current / d).relative_to(root).as_posix(),
                is_dir=True,
                rules=gitignore_rules,
            )
        ]
        for fname in files:
            if fname.startswith("."):
                continue
            if Path(fname).suffix.lower() not in extensions:
                continue
            fpath = current / fname
            rel = fpath.relative_to(root).as_posix()
            if is_gitignored(rel, is_dir=False, rules=gitignore_rules):
                continue
            try:
                if fpath.stat().st_size > _MAX_FILE_BYTES:
                    continue
                source = fpath.read_bytes()
            except OSError:
                continue
            yield rel, source


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
