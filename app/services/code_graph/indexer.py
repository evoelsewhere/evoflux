"""Workspace indexer — walks a coding workspace and builds an in-memory graph.

This module is pure (no database, no async): it produces a :class:`WorkspaceIndex`
that the service layer persists. Cross-file edges (``calls``, ``inherits``, …) are
resolved with import scope and qualified/simple-name fallbacks. A target is linked
only when it resolves to a single definition; ambiguous targets and plausible
cross-repository references are retained explicitly for later resolution.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from app.services.codeindex import source as codeindex_source
from app.services.code_graph.parsers.registry import ParserRegistry, default_registry
from app.services.code_graph.types import (
    EDGE_IMPLEMENTS,
    EDGE_IMPORTS,
    EDGE_INHERITS,
    EDGE_REFERENCES,
    EDGE_USES,
    NODE_CLASS,
    NODE_ENUM,
    NODE_FIELD,
    NODE_FUNCTION,
    NODE_INTERFACE,
    NODE_METHOD,
    NODE_MODULE,
    NODE_NAMESPACE,
    NODE_PROPERTY,
    NODE_STRUCT,
    NODE_VARIABLE,
)

if TYPE_CHECKING:
    from app.services.code_graph.path_resolve import ModuleResolution

# Compatibility export for callers/tests that inspect the graph format tag.
INDEX_FORMAT_VERSION = codeindex_source.INDEX_FORMAT_VERSION

# Definition kinds a name-based call/reference may resolve to.
_CALLABLE_KINDS = frozenset(
    {NODE_FUNCTION, NODE_METHOD, NODE_CLASS, NODE_ENUM, NODE_STRUCT}
)
# Definition kinds an inherits/implements edge may resolve to.
_TYPE_KINDS = frozenset({NODE_CLASS, NODE_INTERFACE, NODE_STRUCT})
# Import targets can be any defined symbol.
_ANY_KINDS = frozenset(
    {
        NODE_FUNCTION,
        NODE_METHOD,
        NODE_CLASS,
        NODE_INTERFACE,
        NODE_MODULE,
        NODE_VARIABLE,
        NODE_FIELD,
        NODE_PROPERTY,
        NODE_ENUM,
        NODE_STRUCT,
        NODE_NAMESPACE,
    }
)
# Field/property access targets.
_FIELD_KINDS = frozenset({NODE_FIELD, NODE_PROPERTY, NODE_VARIABLE})
# Edge kinds worth keeping as cross-repo candidates when they don't resolve
# locally at all (as opposed to same-workspace EDGE_IMPORTS, which already
# gets this treatment separately). All three carry a type name — precise and
# low-volume compared to e.g. every method signature's parameter/return
# types (EDGE_REFERENCES) or a bare method-call name (EDGE_CALLS), which are
# too ambiguous to resolve across repos without receiver-type inference.
_CROSS_REPO_CANDIDATE_KINDS = frozenset({EDGE_USES, EDGE_INHERITS, EDGE_IMPLEMENTS})


def _allowed_kinds_for(kind: str) -> frozenset[str]:
    """Definition kinds a name-based edge of this ``kind`` may resolve to."""
    if kind in {EDGE_INHERITS, EDGE_IMPLEMENTS}:
        return _TYPE_KINDS
    if kind in {EDGE_IMPORTS, EDGE_REFERENCES}:
        return _ANY_KINDS
    return _CALLABLE_KINDS


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


@dataclass(frozen=True, slots=True)
class UnresolvedReference:
    """An edge that couldn't resolve within this workspace, with 0 local
    name candidates — plausibly a sibling repo's symbol rather than a typo
    or dead reference.

    Persisted by the service layer as an unresolved ``CrossRepoEdge`` row
    (only for workspaces that belong to a project) instead of being dropped
    the way any other unresolved same-workspace edge is — the whole point is
    that the target may be a sibling repo, resolvable later. Originally
    EDGE_IMPORTS-only; also covers EDGE_USES/EDGE_INHERITS/EDGE_IMPLEMENTS
    (see ``_CROSS_REPO_CANDIDATE_KINDS``).
    """

    src_key: str
    kind: str
    raw_reference: str
    dst_name_hint: str | None
    file_path: str
    line: int | None


@dataclass(frozen=True, slots=True)
class AmbiguousEdge:
    """An edge whose target name matched 2+ candidates.

    Stored so the UI and future resolution passes can surface these as
    "ambiguous" rather than silently dropping them. The agent can use
    ``code_graph`` to disambiguate manually.
    """

    src_key: str
    dst_name: str
    kind: str
    candidate_keys: tuple[str, ...]
    file_path: str
    line: int | None


@dataclass(slots=True)
class WorkspaceIndex:
    nodes: list[IndexedNode] = field(default_factory=list)
    edges: list[IndexedEdge] = field(default_factory=list)
    files: list[FileIndex] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    unresolved_references: list[UnresolvedReference] = field(default_factory=list)
    ambiguous_edges: list[AmbiguousEdge] = field(default_factory=list)


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
    file_path: str = ""
    qualified_name: str | None = None
    language: str = ""


def index_workspace(
    root: str | Path, *, registry: ParserRegistry | None = None
) -> WorkspaceIndex:
    """Parse every supported file under ``root`` into a resolved graph."""
    registry = registry or default_registry()
    root_path = Path(root).expanduser().resolve()
    return _build_index(
        _iter_source_files(root_path, registry),
        registry,
        existing_defs=(),
        known_file_paths=frozenset(),
        root_path=root_path,
    )


def index_files(
    root: str | Path,
    rel_paths: Iterable[str],
    *,
    registry: ParserRegistry | None = None,
    existing_defs: Sequence[ExistingDef] = (),
    known_file_paths: frozenset[str] = frozenset(),
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
        known_file_paths=known_file_paths,
        root_path=root_path,
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
        rel: content_hash(source)
        for rel, source in _iter_source_files(root_path, registry)
    }


def hash_named_workspace_files(
    root: str | Path,
    rel_paths: Iterable[str],
    *,
    registry: ParserRegistry | None = None,
) -> dict[str, str]:
    """Return fingerprints for explicitly named source files that still exist.

    Missing, ignored, oversized, unsupported, and unsafe paths are omitted.
    The reconciliation layer compares that omission with prior keyed state to
    turn watcher delete/rename events into precise deletes without walking the
    rest of the repository.
    """
    registry = registry or default_registry()
    root_path = Path(root).expanduser().resolve()
    return {
        rel: content_hash(source)
        for rel, source in _iter_named_files(root_path, rel_paths, registry)
    }


def _build_index(
    files_iter: Iterator[tuple[str, bytes]],
    registry: ParserRegistry,
    *,
    existing_defs: Sequence[ExistingDef],
    known_file_paths: frozenset[str] = frozenset(),
    root_path: Path | None = None,
) -> WorkspaceIndex:
    """Shared core: turn a stream of ``(rel_path, bytes)`` into a resolved graph."""
    from app.services.code_graph.path_resolve import (
        ModuleResolution,
        build_repo_context,
        resolve_module_paths,
    )

    index = WorkspaceIndex()

    # Per-file raw extraction keyed by workspace-unique node key. Seed the name
    # map and kind map with pre-existing definitions so cross-file edges from a
    # re-parsed file can resolve to unchanged symbols.
    name_to_keys: dict[str, list[str]] = {}
    qname_to_keys: dict[str, list[str]] = {}
    extra_kinds: dict[str, str] = {}
    extra_files: dict[str, str] = {}
    qualified_by_key: dict[str, str] = {}
    language_by_key: dict[str, str] = {}
    for definition in existing_defs:
        name_to_keys.setdefault(definition.name, []).append(definition.key)
        if definition.qualified_name and definition.qualified_name != definition.name:
            qname_to_keys.setdefault(definition.qualified_name, []).append(
                definition.key
            )
        extra_kinds[definition.key] = definition.kind
        extra_files[definition.key] = definition.file_path
        qualified_by_key[definition.key] = definition.qualified_name or definition.name
        language_by_key[definition.key] = definition.language

    raw_edges: list[
        tuple[str, str | None, str | None, str, int | None, str | None, str | None]
    ] = []
    # (src_key, dst_local_id, dst_name, kind, line, module_path, local_name)
    local_to_key: dict[tuple[str, str], str] = {}
    symbols_by_file: dict[str, dict[str, list[str]]] = {}

    # Seed symbols_by_file from existing defs so path-aware resolution can find
    # symbols in unchanged files during incremental reindex.
    for definition in existing_defs:
        if definition.file_path:
            file_symbols = symbols_by_file.setdefault(definition.file_path, {})
            file_symbols.setdefault(definition.name, []).append(definition.key)

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
            qualified_by_key[key] = node.qualified_name
            language_by_key[key] = result.language
            if node.qualified_name != node.name:
                qname_to_keys.setdefault(node.qualified_name, []).append(key)
            file_symbols = symbols_by_file.setdefault(file_path, {})
            file_symbols.setdefault(node.name, []).append(key)
            node_count += 1

        for edge in result.edges:
            src_key = local_to_key.get((file_path, edge.src_local_id))
            if src_key is None:
                continue
            raw_edges.append(
                (
                    src_key,
                    edge.dst_local_id,
                    edge.dst_name,
                    edge.kind,
                    edge.line,
                    edge.module_path,
                    edge.local_name,
                )
            )

        index.files.append(
            FileIndex(
                file_path=file_path,
                language=result.language,
                content_hash=content_hash(source),
                node_count=node_count,
                edge_count=0,  # filled in after resolution
            )
        )

    # Build path-aware module resolution.
    module_resolution = ModuleResolution()
    if root_path is not None:
        all_known = frozenset(symbols_by_file.keys()) | known_file_paths
        repo_ctx = build_repo_context(root_path)
        module_resolution = resolve_module_paths(
            raw_edges, symbols_by_file, all_known, repo_ctx
        )

    _resolve_edges(
        index,
        raw_edges,
        local_to_key,
        name_to_keys,
        qname_to_keys,
        extra_kinds,
        extra_files,
        qualified_by_key,
        language_by_key,
        module_resolution=module_resolution,
    )
    _backfill_edge_counts(index)
    return index


def _resolve_edges(
    index: WorkspaceIndex,
    raw_edges: list[
        tuple[
            str,
            str | None,
            str | None,
            str,
            int | None,
            str | None,
            str | None,
        ]
    ],
    local_to_key: dict[tuple[str, str], str],
    name_to_keys: dict[str, list[str]],
    qname_to_keys: dict[str, list[str]],
    extra_kinds: dict[str, str] | None = None,
    extra_files: dict[str, str] | None = None,
    qualified_by_key: dict[str, str] | None = None,
    language_by_key: dict[str, str] | None = None,
    module_resolution: ModuleResolution | None = None,
) -> None:
    kind_by_key = {n.key: n.kind for n in index.nodes}
    if extra_kinds:
        kind_by_key.update(extra_kinds)
    file_by_key = {n.key: n.file_path for n in index.nodes}
    if extra_files:
        file_by_key.update(extra_files)
    # Preserve distinct source locations. A caller can reference the same
    # symbol more than once and navigation must report each real callsite;
    # parser overlap on the same line is still de-duplicated.
    seen: set[tuple[str, str, str, int | None]] = set()

    for (
        src_key,
        dst_local_id,
        dst_name,
        kind,
        line,
        module_path,
        local_name,
    ) in raw_edges:
        dst_key: str | None = None
        local_import_target_found = False
        import_binding_found = False
        if dst_local_id is not None:
            src_file = file_by_key.get(src_key, "")
            dst_key = local_to_key.get((src_file, dst_local_id))
        elif dst_name is not None:
            allowed = _allowed_kinds_for(kind)
            if kind == EDGE_IMPORTS:
                # Try path-aware resolution first for import edges.
                if module_resolution is not None and module_path:
                    resolved = module_resolution.by_import_edge.get(
                        (src_key, module_path, dst_name, local_name)
                    )
                    import_binding_found = resolved is not None
                    if resolved is not None and resolved.dst_key is not None:
                        local_import_target_found = True
                        dst_key = resolved.dst_key
                        # Skip _resolve_qualified — we have a precise match.
                    elif resolved is not None and resolved.dst_file_path is not None:
                        local_import_target_found = True
                        # File resolved but specific symbol didn't disambiguate.
                        # Keep its scope for later edges without guessing a symbol.
                        pass
                    else:
                        dst_key = _resolve_qualified(
                            dst_name,
                            name_to_keys,
                            qname_to_keys,
                            kind_by_key,
                            allowed,
                        )
                else:
                    dst_key = _resolve_qualified(
                        dst_name,
                        name_to_keys,
                        qname_to_keys,
                        kind_by_key,
                        allowed,
                    )

            if dst_key is None and kind != EDGE_IMPORTS:
                src_file = file_by_key.get(src_key, "")
                # Calls within a type are best resolved against that lexical
                # container. This disambiguates ``self.run()``/``this.run()``
                # and bare ``run()`` when several classes in one file expose
                # the same method name.
                if qualified_by_key is not None and language_by_key is not None:
                    dst_key = _resolve_lexical_scope(
                        dst_name,
                        src_key,
                        qname_to_keys,
                        qualified_by_key,
                        language_by_key,
                        kind_by_key,
                        allowed,
                    )
                # A definition in the caller's own file is the narrowest
                # possible scope and must win over an identical private name
                # elsewhere in the repository.
                if dst_key is None:
                    dst_key = _resolve_same_file(
                        dst_name,
                        src_file,
                        name_to_keys,
                        qname_to_keys,
                        kind_by_key,
                        file_by_key,
                        allowed,
                    )
                # Then use import context to narrow the search before falling
                # back to the global name heuristic.
                if module_resolution is not None:
                    import_binding_found = _has_import_binding(
                        dst_name, src_file, module_resolution
                    )
                    if dst_key is None:
                        dst_key = _resolve_scoped(
                            dst_name,
                            src_file,
                            module_resolution,
                            name_to_keys,
                            kind_by_key,
                            file_by_key,
                            allowed,
                        )
                if dst_key is None and not import_binding_found:
                    dst_key = _resolve_qualified(
                        dst_name, name_to_keys, qname_to_keys, kind_by_key, allowed
                    )

        if dst_key is None or dst_key == src_key:
            # An import that doesn't resolve *within this workspace* may
            # still resolve to a sibling repo in the same project — keep the
            # raw reference instead of dropping it outright like every other
            # unresolved edge kind.
            if (
                dst_key is None
                and kind == EDGE_IMPORTS
                and module_path
                and not local_import_target_found
            ):
                index.unresolved_references.append(
                    UnresolvedReference(
                        src_key=src_key,
                        kind=EDGE_IMPORTS,
                        raw_reference=module_path,
                        dst_name_hint=dst_name,
                        file_path=file_by_key.get(src_key, ""),
                        line=line,
                    )
                )
            elif dst_key is None and dst_name is not None and kind != EDGE_IMPORTS:
                # Check if the name matched multiple candidates (ambiguous)
                # rather than matching nothing at all. Store these so the UI
                # can surface them as "ambiguous" instead of silently dropping.
                candidates = _collect_candidates(
                    dst_name,
                    name_to_keys,
                    qname_to_keys,
                    kind_by_key,
                    _allowed_kinds_for(kind),
                )
                if len(candidates) >= 2:
                    index.ambiguous_edges.append(
                        AmbiguousEdge(
                            src_key=src_key,
                            dst_name=dst_name,
                            kind=kind,
                            candidate_keys=tuple(candidates),
                            file_path=file_by_key.get(src_key, ""),
                            line=line,
                        )
                    )
                elif not candidates and kind in _CROSS_REPO_CANDIDATE_KINDS:
                    # Zero local matches at all (not just ambiguous) — this
                    # may be a sibling repo's symbol rather than a typo or
                    # dead reference. Keep it as a candidate for cross-repo
                    # resolution instead of dropping it, same idea as an
                    # unresolved import but for a wired dependency/supertype.
                    index.unresolved_references.append(
                        UnresolvedReference(
                            src_key=src_key,
                            kind=kind,
                            raw_reference=dst_name,
                            dst_name_hint=dst_name,
                            file_path=file_by_key.get(src_key, ""),
                            line=line,
                        )
                    )
            continue
        dedupe = (src_key, dst_key, kind, line)
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


def _resolve_qualified(
    name: str,
    name_to_keys: dict[str, list[str]],
    qname_to_keys: dict[str, list[str]],
    kind_by_key: dict[str, str],
    allowed_kinds: frozenset[str],
) -> str | None:
    """Resolve a name with qualified-name fallback.

    Resolution order:
    1. Exact match on simple ``name`` — if exactly 1 candidate, return it.
    2. Exact match on ``qualified_name`` — handles ``Class.method`` calls.
    3. A dotted call may fall back to a distinctive last segment. This retains
       useful untyped instance flows such as ``svc.get_user()`` while generic
       members such as ``append`` and ``select`` cannot bind across files.
    """
    # Step 1: direct name lookup
    candidates = [
        key
        for key in name_to_keys.get(name, [])
        if kind_by_key.get(key) in allowed_kinds
    ]
    if len(candidates) == 1:
        return candidates[0]

    # Step 2: try as qualified name (e.g. "Animal.run" → qualified_name "Animal.run")
    qcandidates = [
        key
        for key in qname_to_keys.get(name, [])
        if kind_by_key.get(key) in allowed_kinds
    ]
    if len(qcandidates) == 1:
        return qcandidates[0]

    # Step 3: untyped instance receivers cannot be scoped without data-flow
    # inference. Preserve only names distinctive enough to be credible across
    # files; common collection/query methods are worse than a missing edge.
    if "." in name:
        short = name.rsplit(".", 1)[1]
        if _is_distinctive_member(short):
            short_candidates = [
                key
                for key in name_to_keys.get(short, [])
                if kind_by_key.get(key) in allowed_kinds
            ]
            if len(short_candidates) == 1:
                return short_candidates[0]

    return None


def _is_distinctive_member(name: str) -> bool:
    """Whether an unscoped member name is safe enough for global fallback."""
    # Exported Go methods and conventional PascalCase members carry a useful
    # type/API signal even when short (for example ``a.Run()`` -> the only
    # indexed ``Animal.Run``). Lowercase collection/query verbs remain gated
    # by length so calls such as ``items.append`` cannot bind to an unrelated
    # project helper merely because it is the only same-named definition.
    return name[:1].isupper() or len(name) >= 8 or ("_" in name and len(name) >= 6)


def _resolve_lexical_scope(
    dst_name: str,
    src_key: str,
    qname_to_keys: dict[str, list[str]],
    qualified_by_key: dict[str, str],
    language_by_key: dict[str, str],
    kind_by_key: dict[str, str],
    allowed_kinds: frozenset[str],
) -> str | None:
    """Resolve a call/reference inside its nearest enclosing symbol.

    Parsers normalize qualified names to dots across languages. A source
    method such as ``pkg.Service.execute`` can therefore resolve a bare
    implicit-receiver ``validate`` or an explicit
    ``self.validate``/``this.validate`` to
    ``pkg.Service.validate`` before same-file/global heuristics are attempted.
    Arbitrary receivers (``client.validate``) are deliberately excluded: they
    require type-flow inference and guessing would create false edges.
    """
    if "." in dst_name:
        receiver, short_name = dst_name.rsplit(".", 1)
        if receiver.casefold() not in {"self", "this", "cls"}:
            return None
    else:
        # A bare call is an implicit receiver only in these language models.
        # In Python/JavaScript/PHP, ``validate()`` is a local/global function;
        # treating it as ``this.validate()`` would create a false method edge.
        if language_by_key.get(src_key) not in {
            "cpp",
            "csharp",
            "dart",
            "java",
            "kotlin",
            "objc",
            "pascal",
            "ruby",
            "scala",
            "swift",
        }:
            return None
        short_name = dst_name

    source_qualified = qualified_by_key.get(src_key)
    if not source_qualified or "." not in source_qualified:
        return None
    container = source_qualified.rsplit(".", 1)[0]
    while container:
        candidate_name = f"{container}.{short_name}"
        candidates = [
            key
            for key in qname_to_keys.get(candidate_name, [])
            if kind_by_key.get(key) in allowed_kinds and key != src_key
        ]
        if len(candidates) == 1:
            return candidates[0]
        if "." not in container:
            break
        container = container.rsplit(".", 1)[0]
    return None


def _resolve_same_file(
    dst_name: str,
    src_file: str,
    name_to_keys: dict[str, list[str]],
    qname_to_keys: dict[str, list[str]],
    kind_by_key: dict[str, str],
    file_by_key: dict[str, str],
    allowed_kinds: frozenset[str],
) -> str | None:
    """Resolve an otherwise ambiguous target inside the caller's file."""
    possible = [
        *name_to_keys.get(dst_name, []),
        *qname_to_keys.get(dst_name, []),
    ]
    if "." in dst_name:
        possible.extend(name_to_keys.get(dst_name.rsplit(".", 1)[1], []))
    candidates = list(
        dict.fromkeys(
            key
            for key in possible
            if kind_by_key.get(key) in allowed_kinds
            and file_by_key.get(key) == src_file
        )
    )
    return candidates[0] if len(candidates) == 1 else None


def _collect_candidates(
    dst_name: str,
    name_to_keys: dict[str, list[str]],
    qname_to_keys: dict[str, list[str]],
    kind_by_key: dict[str, str],
    allowed_kinds: frozenset[str],
) -> list[str]:
    """Collect all candidate keys that could match ``dst_name``.

    Unlike ``_resolve_qualified`` which only returns when exactly 1 match,
    this returns ALL matches across name, qualified-name, and last-segment
    lookups so ambiguous edges can be stored rather than silently dropped.
    """
    candidates = [
        key
        for key in name_to_keys.get(dst_name, [])
        if kind_by_key.get(key) in allowed_kinds
    ]
    if candidates:
        return candidates

    qcandidates = [
        key
        for key in qname_to_keys.get(dst_name, [])
        if kind_by_key.get(key) in allowed_kinds
    ]
    if qcandidates:
        return qcandidates

    if "." in dst_name:
        short = dst_name.rsplit(".", 1)[1]
        short_candidates = [
            key
            for key in name_to_keys.get(short, [])
            if kind_by_key.get(key) in allowed_kinds
        ]
        if short_candidates:
            return short_candidates

    return []


def _resolve_scoped(
    dst_name: str,
    src_file: str,
    module_resolution: ModuleResolution,
    name_to_keys: dict[str, list[str]],
    kind_by_key: dict[str, str],
    file_by_key: dict[str, str],
    allowed_kinds: frozenset[str],
) -> str | None:
    """Scope-aware resolution using import context.

    For a ``dst_name``-based edge in originating file ``src_file``:
    1. Split ``dst_name`` into ``head`` + optional ``rest`` (after first ``.``).
    2. Look up ``head`` in ``module_resolution.imports_by_file[src_file]``.
    3. If found and ``rest`` is empty: resolve to the import's ``dst_key`` if
       set; else search only that import's target file for ``name == head``.
    4. If found and ``rest`` is non-empty: search only that import's target
       file for ``name == rest[-1]``.
    5. Return ``None`` if no scope-aware match — caller falls through to
       ``_resolve_qualified``.
    """
    file_imports = module_resolution.imports_by_file.get(src_file)
    if not file_imports:
        return None

    if "." in dst_name:
        head, rest = dst_name.split(".", 1)
        rest_name = rest.rsplit(".", 1)[-1]
    else:
        head = dst_name
        rest_name = None

    resolved_import = file_imports.get(head)
    if resolved_import is None:
        return None

    target_file = resolved_import.dst_file_path
    if target_file is None:
        return None

    # Search only within the import's target file.
    search_name = rest_name if rest_name else resolved_import.imported_name
    candidates = [
        key
        for key in name_to_keys.get(search_name, [])
        if kind_by_key.get(key) in allowed_kinds
        and _file_matches_scope(file_by_key.get(key, ""), target_file)
    ]
    if len(candidates) == 1:
        return candidates[0]

    # If the import itself resolved to a specific key, use that.
    if resolved_import.dst_key and not rest_name:
        if kind_by_key.get(resolved_import.dst_key) in allowed_kinds:
            return resolved_import.dst_key

    return None


def _has_import_binding(
    dst_name: str, src_file: str, module_resolution: ModuleResolution
) -> bool:
    """Whether the reference head is a known local or external import binding."""
    head = dst_name.split(".", 1)[0]
    return head in module_resolution.imports_by_file.get(src_file, {})


def _file_matches_scope(file_path: str, target: str) -> bool:
    if target.endswith("/"):
        return file_path.startswith(target)
    return file_path == target


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
    for record in codeindex_source.read_source_records(
        root,
        rel_paths,
        extensions=registry.supported_extensions(),
    ):
        yield record.key, record.content


def _iter_source_files(
    root: Path, registry: ParserRegistry
) -> Iterator[tuple[str, bytes]]:
    """Yield ``(relative_posix_path, bytes)`` for supported, non-ignored files."""
    for record in codeindex_source.walk_source_records(
        root,
        extensions=registry.supported_extensions(),
    ):
        yield record.key, record.content


def content_hash(data: bytes) -> str:
    # Keep the 64-character database representation while reserving a visible
    # prefix for the parser/index format. A query can then detect an upgrade
    # from one stored row without rescanning the repository on every request.
    return codeindex_source.fingerprint_source(data, INDEX_FORMAT_VERSION)


def index_format_tag() -> str:
    return codeindex_source.index_format_tag(INDEX_FORMAT_VERSION)
