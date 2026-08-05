"""Task-oriented code retrieval with graph, overlay, LSP, and text fallback.

The graph accelerates navigation, but the working tree remains authoritative.
One request may merge a ready graph snapshot with freshly parsed dirty files,
language-server locations, and bounded lexical matches.  This keeps callers
from manually chaining graph/search/read tools and makes degraded behaviour
explicit through provenance, freshness, coverage, and limitations.
"""

from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import os
import shutil
import subprocess
import time
from collections import OrderedDict, Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal
from urllib.parse import unquote, urlparse
from uuid import UUID

from loguru import logger
from sqlmodel import col, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.agent.tools.builtin.filesystem._ignore import (
    is_ignored_workspace_path,
    load_gitignore_rules,
)
from app.models.code_graph import CodeIndexState, CodeNode, CrossRepoEdge
from app.services import code_graph_service as graph_svc
from app.services.code_graph.query import QueryMatch, match_query, query_terms
from app.services.code_graph.parsers.registry import ParserRegistry, default_registry
from app.services.code_graph.watcher import get_dirty_code_paths, is_graph_metadata_path

CodeQueryIntent = Literal["locate", "explain", "impact", "trace", "change"]
FreshnessPolicy = Literal["fast", "balanced", "strict"]

_MAX_SCAN_BYTES = 1_500_000
_MAX_LINE_CHARS = 500
_SOURCEISH_EXTENSIONS = frozenset(
    {
        ".asm",
        ".bash",
        ".clj",
        ".cljs",
        ".coffee",
        ".ex",
        ".exs",
        ".fs",
        ".fsx",
        ".graphql",
        ".groovy",
        ".hcl",
        ".jl",
        ".json",
        ".m",
        ".ml",
        ".mli",
        ".nim",
        ".pl",
        ".pm",
        ".proto",
        ".ps1",
        ".sh",
        ".sql",
        ".sol",
        ".toml",
        ".vim",
        ".xml",
        ".yaml",
        ".yml",
        ".zig",
    }
)
_MIN_WEIGHTED_QUERY_COVERAGE = 0.5


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


@dataclass(slots=True)
class CodeQueryCandidate:
    handle: str
    file_path: str
    line_start: int
    line_end: int
    symbol: str | None = None
    kind: str | None = None
    language: str | None = None
    signature: str | None = None
    snippet: str | None = None
    score: float = 0.0
    confidence: float = 0.5
    provenance: str = "lexical"
    match_reasons: list[str] = field(default_factory=list)
    callers: list[str] = field(default_factory=list)
    callees: list[str] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)
    node_id: UUID | None = None
    workspace_id: UUID | None = None
    repository: str | None = None


@dataclass(slots=True)
class CodeQueryResult:
    query: str
    intent: CodeQueryIntent
    strategy: str
    graph_version: str | None
    working_tree_revision: str
    freshness: Literal["fresh", "partial", "stale", "unavailable"]
    coverage: float
    confidence: float
    results: list[CodeQueryCandidate]
    capabilities: list[LanguageCapability]
    dirty_files: int = 0
    pending_edges: int = 0
    limitations: list[str] = field(default_factory=list)
    next_read_ranges: list[str] = field(default_factory=list)
    truncated: bool = False
    cache_hit: bool = False


@dataclass(frozen=True, slots=True)
class RetrievalFreshness:
    graph_version: str | None
    working_tree_revision: str
    freshness: Literal["fresh", "partial", "unavailable"]
    indexed_files: int
    dirty_files: int
    change_source: str


@dataclass(frozen=True, slots=True)
class _LexicalHit:
    file_path: str
    line: int
    column: int
    text: str
    score: float
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _WorkingTreeState:
    revision: str
    changed: frozenset[str]
    deleted: frozenset[str]
    source: str
    reliable: bool = True


_CACHE_MAX = 128
_query_cache: OrderedDict[tuple[object, ...], tuple[float, CodeQueryResult]] = (
    OrderedDict()
)
_freshness_cache: OrderedDict[
    tuple[str, str | None, str], tuple[float, frozenset[str]]
] = OrderedDict()


def _relevant_match(match: QueryMatch) -> bool:
    return match.exact or match.weighted_coverage >= _MIN_WEIGHTED_QUERY_COVERAGE


def _hash_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _is_retrieval_path(path: str) -> bool:
    suffix = Path(path.replace("\\", "/")).suffix.casefold()
    return suffix in (
        default_registry().supported_extensions() | _SOURCEISH_EXTENSIONS
    ) or is_graph_metadata_path(path)


def _path_in_scope(path: str, prefixes: Sequence[str]) -> bool:
    normalized = path.replace("\\", "/").strip("/")
    scopes = [
        prefix.replace("\\", "/").strip("/")
        for prefix in prefixes
        if prefix.replace("\\", "/").strip("/") not in {"", "."}
    ]
    if not scopes:
        return True
    return any(
        normalized == prefix or normalized.startswith(prefix + "/") for prefix in scopes
    )


def _content_fingerprint(root: Path, paths: Iterable[str]) -> str:
    digest = hashlib.sha256()
    for rel_path in sorted(set(paths)):
        digest.update(rel_path.encode("utf-8", "replace"))
        digest.update(b"\0")
        path = _safe_file(root, rel_path)
        if path is None or not path.is_file():
            digest.update(b"missing")
            continue
        try:
            stat = path.stat()
            if stat.st_size <= _MAX_SCAN_BYTES:
                digest.update(path.read_bytes())
            else:
                digest.update(f"{stat.st_size}:{stat.st_mtime_ns}".encode())
        except OSError:
            digest.update(b"unreadable")
    return digest.hexdigest()[:16]


def _safe_file(root: Path, rel_path: str) -> Path | None:
    try:
        candidate = (root / rel_path).resolve()
    except OSError:
        return None
    if root != candidate and root not in candidate.parents:
        return None
    return candidate


def _graph_version(states: Sequence[CodeIndexState]) -> str | None:
    if not states:
        return None
    latest = max(state.indexed_at for state in states)
    payload = f"{latest.isoformat()}:{len(states)}"
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


def _git_working_tree(root: Path) -> _WorkingTreeState:
    """Return a cheap change journal derived from Git, when available."""
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
            cwd=root,
            capture_output=True,
            check=False,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        proc = None
    if proc is None or proc.returncode != 0:
        stamp = str(root.stat().st_mtime_ns) if root.exists() else "missing"
        return _WorkingTreeState(
            stamp, frozenset(), frozenset(), "filesystem", reliable=False
        )

    changed: set[str] = set()
    deleted: set[str] = set()
    records = proc.stdout.decode("utf-8", "replace").split("\0")
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record or len(record) < 4:
            continue
        status = record[:2]
        path = record[3:].replace("\\", "/")
        # With ``-z``, porcelain v1 emits destination first and source second.
        if "R" in status or "C" in status:
            if _is_retrieval_path(path):
                changed.add(path)
            if index < len(records) and records[index]:
                source_path = records[index].replace("\\", "/")
                index += 1
                if "R" in status and _is_retrieval_path(source_path):
                    deleted.add(source_path)
            continue
        if _is_retrieval_path(path):
            changed.add(path)
        if "D" in status and _is_retrieval_path(path):
            deleted.add(path)
    try:
        head = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"],
            cwd=root,
            capture_output=True,
            check=False,
            timeout=2,
        )
        head_reliable = head.returncode == 0
        head_value = head.stdout.strip() if head_reliable else b"unborn"
    except (OSError, subprocess.TimeoutExpired):
        head_value = b"unknown"
        head_reliable = False
    fingerprint = _content_fingerprint(root, [*changed, *deleted])
    digest = hashlib.sha256(
        b"\0".join((head_value, proc.stdout, fingerprint.encode()))
    ).hexdigest()[:16]
    return _WorkingTreeState(
        revision=digest,
        changed=frozenset(changed),
        deleted=frozenset(deleted),
        source="git",
        reliable=head_reliable,
    )


async def _working_tree(root: Path) -> _WorkingTreeState:
    state = await asyncio.to_thread(_git_working_tree, root)
    gitignore_rules = await asyncio.to_thread(load_gitignore_rules, root)
    state = replace(
        state,
        changed=frozenset(
            path
            for path in state.changed
            if not is_ignored_workspace_path(path, is_dir=False, rules=gitignore_rules)
        ),
        deleted=frozenset(
            path
            for path in state.deleted
            if not is_ignored_workspace_path(path, is_dir=False, rules=gitignore_rules)
        ),
    )
    watched = frozenset(
        path
        for path in get_dirty_code_paths(str(root))
        if _is_retrieval_path(path)
        and not is_ignored_workspace_path(path, is_dir=False, rules=gitignore_rules)
    )
    if not watched:
        return state
    changed = state.changed | watched
    fingerprint = await asyncio.to_thread(_content_fingerprint, root, watched)
    digest = hashlib.sha256(f"{state.revision}\0{fingerprint}".encode()).hexdigest()[
        :16
    ]
    return _WorkingTreeState(
        revision=digest,
        changed=frozenset(changed),
        deleted=state.deleted,
        source=f"{state.source}+watcher",
        reliable=state.reliable,
    )


def _reconcile_working_tree(
    root: Path, state: _WorkingTreeState, states: Sequence[CodeIndexState]
) -> _WorkingTreeState:
    """Drop journal entries whose live content already matches the index."""
    indexed = {item.file_path: item.content_hash for item in states}
    changed: set[str] = set()
    for rel_path in state.changed:
        path = _safe_file(root, rel_path)
        expected = indexed.get(rel_path)
        if path is None or not path.is_file() or expected is None:
            changed.add(rel_path)
            continue
        try:
            if _hash_bytes(path.read_bytes()) != expected:
                changed.add(rel_path)
        except OSError:
            changed.add(rel_path)
    deleted = {
        rel_path
        for rel_path in state.deleted
        if rel_path in indexed
        and (path := _safe_file(root, rel_path)) is not None
        and not path.is_file()
    }
    return replace(state, changed=frozenset(changed), deleted=frozenset(deleted))


def _iter_sourceish_files(root: Path, paths: Sequence[str]) -> list[Path]:
    from app.core.runtime_settings import load_runtime_settings

    max_scan_files = load_runtime_settings().code_graph.query_max_scan_files
    roots: list[Path] = []
    for value in paths or (".",):
        candidate = _safe_file(root, value)
        if candidate is not None and candidate.exists():
            roots.append(candidate)
    registry_extensions = default_registry().supported_extensions()
    allowed = registry_extensions | _SOURCEISH_EXTENSIONS
    gitignore_rules = load_gitignore_rules(root)
    files: list[Path] = []
    for scan_root in roots:
        scan_rel = scan_root.relative_to(root).as_posix()
        if scan_rel != "." and is_ignored_workspace_path(
            scan_rel,
            is_dir=scan_root.is_dir(),
            rules=gitignore_rules,
        ):
            continue
        if scan_root.is_file():
            if scan_root.suffix.casefold() in allowed:
                files.append(scan_root)
            continue
        for current, dirnames, filenames in os.walk(scan_root):
            current_path = Path(current)
            dirnames[:] = [
                name
                for name in dirnames
                if not is_ignored_workspace_path(
                    (current_path / name).relative_to(root).as_posix(),
                    is_dir=True,
                    rules=gitignore_rules,
                )
            ]
            for filename in filenames:
                path = current_path / filename
                if path.suffix.casefold() not in allowed:
                    continue
                if is_ignored_workspace_path(
                    path.relative_to(root).as_posix(),
                    is_dir=False,
                    rules=gitignore_rules,
                ):
                    continue
                try:
                    if path.stat().st_size > _MAX_SCAN_BYTES:
                        continue
                except OSError:
                    continue
                files.append(path)
                if len(files) >= max_scan_files:
                    return files
    return files


def _scan_lexical(
    root: Path,
    query: str,
    paths: Sequence[str],
    limit: int,
) -> tuple[list[_LexicalHit], Counter[str]]:
    terms = query_terms(query)
    if not terms:
        return [], Counter()
    query_folded = query.casefold().strip()
    hits: list[_LexicalHit] = []
    extension_counts: Counter[str] = Counter()
    for file_path in _iter_sourceish_files(root, paths):
        extension_counts[file_path.suffix.casefold()] += 1
        try:
            raw = file_path.read_bytes()
        except OSError:
            continue
        if b"\0" in raw[:4096]:
            continue
        rel = file_path.relative_to(root).as_posix()
        path_match = match_query(query, terms, (rel,))
        if _relevant_match(path_match):
            hits.append(
                _LexicalHit(
                    file_path=rel,
                    line=1,
                    column=1,
                    text=f"source path: {rel}",
                    score=10.0 + path_match.score * 0.3,
                    reasons=("query overlap in source path",),
                )
            )
        for line_number, text in enumerate(
            raw.decode("utf-8", "replace").splitlines(), start=1
        ):
            folded = text.casefold()
            line_match = match_query(query, terms, (text,))
            if not _relevant_match(line_match):
                continue
            matched = [term for term in terms if term in folded]
            score = 20.0 + line_match.score * 0.4
            reasons = [f"{line_match.hits} query term(s) in current source"]
            if query_folded and query_folded in folded:
                reasons.append("exact query text")
            column = min(
                (folded.find(term) for term in matched if term in folded), default=0
            )
            hits.append(
                _LexicalHit(
                    file_path=rel,
                    line=line_number,
                    column=column + 1,
                    text=text[:_MAX_LINE_CHARS],
                    score=score,
                    reasons=tuple(reasons),
                )
            )
    hits.sort(key=lambda item: (-item.score, item.file_path, item.line))
    # Preserve file diversity before allowing multiple hits from one file.
    diverse: list[_LexicalHit] = []
    seen_files: set[str] = set()
    for hit in hits:
        if hit.file_path not in seen_files:
            diverse.append(hit)
            seen_files.add(hit.file_path)
        if len(diverse) >= limit:
            return diverse, extension_counts
    for hit in hits:
        if hit not in diverse:
            diverse.append(hit)
        if len(diverse) >= limit:
            break
    return diverse, extension_counts


def _count_workspace_extensions(root: Path, paths: Sequence[str] = ()) -> Counter[str]:
    """Count source-like files without opening their contents."""
    return Counter(
        path.suffix.casefold() for path in _iter_sourceish_files(root, paths)
    )


async def _lexical_search(
    root: Path, query: str, paths: Sequence[str], limit: int
) -> tuple[list[_LexicalHit], Counter[str]]:
    return await asyncio.to_thread(_scan_lexical, root, query, paths, limit)


def _read_snippet(root: Path, file_path: str, start: int, end: int) -> str | None:
    path = _safe_file(root, file_path)
    if path is None or not path.is_file():
        return None
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    first = max(1, start)
    last = min(len(lines), max(first, end))
    return "\n".join(
        f"{number:>5} | {lines[number - 1]}" for number in range(first, last + 1)
    )


def _node_handle(workspace_id: UUID, node_id: UUID, qualified_name: str) -> str:
    fallback = base64.urlsafe_b64encode(qualified_name.encode()).decode().rstrip("=")
    return f"cg:{workspace_id}:{node_id}:{fallback}"


def _source_handle(file_path: str, line: int) -> str:
    digest = hashlib.sha256(f"{file_path}:{line}".encode()).hexdigest()[:12]
    return f"src:{digest}"


def _parse_overlay(
    root: Path,
    dirty_paths: Sequence[str],
    query: str,
    registry: ParserRegistry,
    limit: int,
    languages: Sequence[str] = (),
    kinds: Sequence[str] = (),
) -> list[CodeQueryCandidate]:
    terms = query_terms(query)
    candidates: list[CodeQueryCandidate] = []
    for rel_path in dirty_paths:
        parser = registry.for_path(rel_path)
        path = _safe_file(root, rel_path)
        if parser is None or path is None or not path.is_file():
            continue
        try:
            result = parser.parse(file_path=rel_path, source=path.read_bytes())
        except (OSError, RuntimeError, ValueError) as exc:
            logger.debug(
                "code_query_overlay_parse_failed path={} err={}", rel_path, exc
            )
            continue
        if languages and result.language not in languages:
            continue
        nodes_by_id = {node.local_id: node for node in result.nodes}
        candidates_by_id: dict[str, CodeQueryCandidate] = {}
        for node in result.nodes:
            node_match = match_query(
                query,
                terms,
                (
                    node.name,
                    node.qualified_name,
                    node.signature,
                    node.docstring,
                    rel_path,
                ),
            )
            if not _relevant_match(node_match):
                continue
            if kinds and node.kind not in kinds:
                continue
            candidate = CodeQueryCandidate(
                handle=_source_handle(rel_path, node.line_start),
                file_path=rel_path,
                line_start=node.line_start,
                line_end=node.line_end,
                symbol=node.qualified_name,
                kind=node.kind,
                language=result.language,
                signature=node.signature,
                score=70.0 + node_match.score,
                confidence=min(0.95, 0.5 + node_match.weighted_coverage * 0.45),
                provenance="overlay",
                match_reasons=[
                    f"{node_match.hits} query term(s) in parsed source",
                    "fresh dirty-file parse",
                ],
            )
            candidates.append(candidate)
            candidates_by_id[node.local_id] = candidate

        # Preserve relationship evidence from the live parse. This matters for
        # newly-added callers/imports that do not exist in the stored graph yet.
        for edge in result.edges:
            source = nodes_by_id.get(edge.src_local_id)
            target = nodes_by_id.get(edge.dst_local_id or "")
            target_name = edge.dst_name or (target.qualified_name if target else None)
            source_candidate = candidates_by_id.get(edge.src_local_id)
            target_candidate = (
                candidates_by_id.get(edge.dst_local_id or "") if target else None
            )
            relation_line = edge.line or (source.line_start if source else 1)
            if source_candidate and target_name:
                source_candidate.callees.append(
                    f"{edge.kind} {target_name} — {rel_path}:{relation_line} [live]"
                )
            if target_candidate and source:
                target_candidate.callers.append(
                    f"{edge.kind} {source.qualified_name} — {rel_path}:{relation_line} [live]"
                )
            target_match = match_query(
                query,
                terms,
                (target_name, edge.module_path, edge.local_name),
            )
            if (
                source is not None
                and _relevant_match(target_match)
                and edge.src_local_id not in candidates_by_id
                and (not kinds or source.kind in kinds)
            ):
                relationship_candidate = CodeQueryCandidate(
                    handle=_source_handle(rel_path, source.line_start),
                    file_path=rel_path,
                    line_start=source.line_start,
                    line_end=source.line_end,
                    symbol=source.qualified_name,
                    kind=source.kind,
                    language=result.language,
                    signature=source.signature,
                    score=102.0,
                    confidence=0.86,
                    provenance="overlay",
                    match_reasons=[f"fresh {edge.kind} relationship to query target"],
                    callees=[
                        f"{edge.kind} {target_name} — {rel_path}:{relation_line} [live]"
                    ],
                )
                candidates.append(relationship_candidate)
                candidates_by_id[edge.src_local_id] = relationship_candidate
    candidates.sort(key=lambda item: (-item.score, item.file_path, item.line_start))
    return candidates[:limit]


async def _overlay_candidates(
    root: Path,
    dirty_paths: Sequence[str],
    query: str,
    registry: ParserRegistry,
    limit: int,
    languages: Sequence[str] = (),
    kinds: Sequence[str] = (),
) -> list[CodeQueryCandidate]:
    return await asyncio.to_thread(
        _parse_overlay, root, dirty_paths, query, registry, limit, languages, kinds
    )


def _language_capabilities(
    extension_counts: Counter[str], states: Sequence[CodeIndexState]
) -> list[LanguageCapability]:
    registry = default_registry()
    indexed_by_language = Counter(state.language or "unknown" for state in states)
    extensions_by_language: dict[str, set[str]] = {}
    workspace_by_language: Counter[str] = Counter()
    unsupported: Counter[str] = Counter()
    for extension, count in extension_counts.items():
        parser = registry.for_path(f"x{extension}")
        if parser is None:
            unsupported[extension] += count
            continue
        extensions_by_language.setdefault(parser.name, set()).add(extension)
        workspace_by_language[parser.name] += count

    lsp_commands = {
        "python": ("basedpyright-langserver", "pyright-langserver"),
        "typescript": ("typescript-language-server",),
        "javascript": ("typescript-language-server",),
        "go": ("gopls",),
        "rust": ("rust-analyzer",),
    }
    capabilities = [
        LanguageCapability(
            language=language,
            extensions=tuple(sorted(extensions)),
            graph=True,
            lsp=any(
                shutil.which(command) for command in lsp_commands.get(language, ())
            ),
            indexed_files=indexed_by_language[language],
            workspace_files=workspace_by_language[language],
        )
        for language, extensions in sorted(extensions_by_language.items())
    ]
    capabilities.extend(
        LanguageCapability(
            language=f"unsupported:{extension}",
            extensions=(extension,),
            graph=False,
            lsp=False,
            workspace_files=count,
        )
        for extension, count in sorted(unsupported.items())
    )
    return capabilities


def _scoped_capability_inputs(
    extension_counts: Counter[str],
    states: Sequence[CodeIndexState],
    paths: Sequence[str],
    languages: Sequence[str],
) -> tuple[Counter[str], list[CodeIndexState]]:
    """Align capability coverage numerator and denominator to query scope."""
    scoped_extensions = Counter(
        {
            extension: count
            for extension, count in extension_counts.items()
            if not languages or _language_for_path(f"source{extension}") in languages
        }
    )
    scoped_states = [
        state
        for state in states
        if _path_in_scope(state.file_path, paths)
        and (not languages or state.language in languages)
    ]
    return scoped_extensions, scoped_states


async def _try_lsp(
    root: Path,
    query: str,
    lexical_hits: Sequence[_LexicalHit],
    intent: CodeQueryIntent,
) -> list[CodeQueryCandidate]:
    """Best-effort live LSP enrichment after a lexical seed was found."""
    if not lexical_hits:
        return []
    seed = lexical_hits[0]
    path = _safe_file(root, seed.file_path)
    if path is None:
        return []
    terms = query_terms(query)
    if not terms:
        return []
    term = terms[0]
    folded = seed.text.casefold()
    column = folded.find(term) + 1
    if column <= 0:
        column = seed.column
    try:
        from app.agent.lsp_manager import get_language_server
    except ImportError:
        return []

    try:
        client = await asyncio.wait_for(get_language_server(root, path), timeout=4.0)
        if intent in {"impact", "trace", "change"}:
            locations = await asyncio.wait_for(
                client.references(
                    path,
                    seed.line,
                    column,
                    include_declaration=True,
                ),
                timeout=4.0,
            )
        else:
            locations = await asyncio.wait_for(
                client.definition(path, seed.line, column), timeout=4.0
            )
    except (TimeoutError, OSError, RuntimeError):
        return []

    candidates: list[CodeQueryCandidate] = []
    for location in locations[:20]:
        uri = str(location.get("uri") or location.get("targetUri") or "")
        parsed = urlparse(uri)
        if parsed.scheme != "file":
            continue
        absolute = Path(unquote(parsed.path)).resolve()
        if root not in absolute.parents and absolute != root:
            continue
        range_data = location.get("range") or location.get("targetSelectionRange") or {}
        start = range_data.get("start") or {}
        end = range_data.get("end") or start
        rel = absolute.relative_to(root).as_posix()
        line_start = int(start.get("line", 0)) + 1
        line_end = int(end.get("line", start.get("line", 0))) + 1
        candidates.append(
            CodeQueryCandidate(
                handle=_source_handle(rel, line_start),
                file_path=rel,
                line_start=line_start,
                line_end=line_end,
                score=110.0,
                confidence=0.92,
                provenance="lsp",
                match_reasons=["live language-server location"],
                language=_language_for_path(rel),
            )
        )
    return candidates


def _dedupe(candidates: Sequence[CodeQueryCandidate]) -> list[CodeQueryCandidate]:
    ranked = sorted(
        candidates,
        key=lambda item: (-item.score, item.file_path, item.line_start),
    )
    unique: list[CodeQueryCandidate] = []
    for candidate in ranked:
        duplicate = any(
            existing.file_path == candidate.file_path
            and existing.line_start <= candidate.line_end
            and candidate.line_start <= existing.line_end
            and (
                existing.symbol == candidate.symbol
                or existing.symbol is None
                or candidate.symbol is None
            )
            for existing in unique
        )
        if not duplicate:
            unique.append(candidate)

    # MMR-lite: surface one strong candidate per file before secondary hits
    # from an already represented file.
    diverse: list[CodeQueryCandidate] = []
    repeated: list[CodeQueryCandidate] = []
    seen_files: set[str] = set()
    for candidate in unique:
        if candidate.file_path in seen_files:
            repeated.append(candidate)
        else:
            diverse.append(candidate)
            seen_files.add(candidate.file_path)
    return [*diverse, *repeated]


def _apply_budget(
    root: Path,
    candidates: Sequence[CodeQueryCandidate],
    budget_tokens: int,
    limit: int,
) -> tuple[list[CodeQueryCandidate], bool]:
    remaining_chars = max(800, budget_tokens * 4)
    selected: list[CodeQueryCandidate] = []
    for original in candidates:
        if len(selected) >= limit:
            break
        candidate = copy.deepcopy(original)
        metadata_cost = _candidate_metadata_chars(candidate)
        if metadata_cost >= remaining_chars and selected:
            break
        remaining_chars -= min(metadata_cost, remaining_chars)
        span = max(1, candidate.line_end - candidate.line_start + 1)
        if span > 60:
            end = candidate.line_start + (50 if candidate.kind != "file" else 20)
        else:
            end = candidate.line_end
        snippet = _read_snippet(root, candidate.file_path, candidate.line_start, end)
        if snippet:
            allowance = min(remaining_chars, len(snippet))
            candidate.snippet = snippet[:allowance] or None
            remaining_chars -= len(candidate.snippet or "")
        selected.append(candidate)
        if remaining_chars <= 250:
            break
    return selected, len(selected) < len(candidates)


def _candidate_metadata_chars(candidate: CodeQueryCandidate) -> int:
    return 120 + sum(
        len(value)
        for value in (
            candidate.file_path,
            candidate.symbol or "",
            candidate.signature or "",
            *candidate.match_reasons,
            *candidate.callers,
            *candidate.callees,
            *candidate.tests,
        )
    )


def _apply_existing_snippet_budget(
    candidates: Sequence[CodeQueryCandidate], budget_tokens: int, limit: int
) -> tuple[list[CodeQueryCandidate], bool]:
    """Apply one global budget to already-rendered multi-repository results."""
    remaining = max(800, budget_tokens * 4)
    selected: list[CodeQueryCandidate] = []
    for original in candidates:
        if len(selected) >= limit or remaining <= 180:
            break
        candidate = copy.deepcopy(original)
        metadata_cost = _candidate_metadata_chars(candidate)
        if metadata_cost >= remaining and selected:
            break
        remaining -= min(metadata_cost, remaining)
        if candidate.snippet:
            candidate.snippet = candidate.snippet[: max(0, remaining)] or None
            remaining -= len(candidate.snippet or "")
        selected.append(candidate)
    return selected, len(selected) < len(candidates)


def _language_for_path(file_path: str) -> str | None:
    parser = default_registry().for_path(file_path)
    if parser is not None:
        return parser.name
    suffix = Path(file_path).suffix.casefold()
    return f"unsupported:{suffix}" if suffix else None


async def _states(db: AsyncSession, workspace_id: UUID | None) -> list[CodeIndexState]:
    if workspace_id is None:
        return []
    return list(
        (
            await db.exec(
                select(CodeIndexState).where(
                    CodeIndexState.workspace_id == workspace_id
                )
            )
        ).all()
    )


def _cache_key_for(
    *,
    root: Path,
    graph_version: str | None,
    working_revision: str,
    query: str,
    intent: CodeQueryIntent,
    paths: Sequence[str],
    languages: Sequence[str],
    kinds: Sequence[str],
    budget: int,
    freshness_policy: FreshnessPolicy,
    limit: int,
    enable_lsp: bool,
) -> tuple[object, ...]:
    return (
        str(root),
        graph_version,
        working_revision,
        query.casefold(),
        intent,
        tuple(paths),
        tuple(languages),
        tuple(kinds),
        budget,
        freshness_policy,
        limit,
        enable_lsp,
    )


def _stale_paths(
    root: Path,
    states: Sequence[CodeIndexState],
    candidate_paths: Sequence[str],
) -> set[str]:
    hashes = {state.file_path: state.content_hash for state in states}
    stale: set[str] = set()
    for rel_path in set(candidate_paths):
        expected = hashes.get(rel_path)
        path = _safe_file(root, rel_path)
        if expected is None or path is None or not path.is_file():
            stale.add(rel_path)
            continue
        try:
            if _hash_bytes(path.read_bytes()) != expected:
                stale.add(rel_path)
        except OSError:
            stale.add(rel_path)
    return stale


async def _verified_stale_paths(
    root: Path,
    states: Sequence[CodeIndexState],
    working: _WorkingTreeState,
    ttl_seconds: float,
) -> frozenset[str]:
    key = (str(root), _graph_version(states), working.revision)
    cached = _freshness_cache.get(key) if working.reliable else None
    if cached and time.monotonic() - cached[0] <= ttl_seconds:
        _freshness_cache.move_to_end(key)
        return cached[1]
    stale = frozenset(
        await asyncio.to_thread(
            _stale_paths, root, states, [state.file_path for state in states]
        )
    )
    if working.reliable:
        _freshness_cache[key] = (time.monotonic(), stale)
        _freshness_cache.move_to_end(key)
        while len(_freshness_cache) > 64:
            _freshness_cache.popitem(last=False)
    return stale


async def query_code(
    db: AsyncSession,
    *,
    root_path: str,
    workspace_id: UUID | None,
    query: str,
    intent: CodeQueryIntent = "explain",
    paths: Sequence[str] = (),
    languages: Sequence[str] = (),
    kinds: Sequence[str] = (),
    budget_tokens: int = 2500,
    freshness_policy: FreshnessPolicy = "balanced",
    limit: int = 10,
    enable_lsp: bool = True,
) -> CodeQueryResult:
    """Retrieve a minimal, freshness-aware context pack for one code task."""
    root = Path(root_path).expanduser().resolve()
    capped_limit = max(1, min(limit, 30))
    capped_budget = max(500, min(budget_tokens, 12_000))
    states_task = asyncio.create_task(_states(db, workspace_id))
    working_task = asyncio.create_task(_working_tree(root))
    ignore_task = asyncio.create_task(asyncio.to_thread(load_gitignore_rules, root))
    states = await states_task
    working = await working_task
    gitignore_rules = await ignore_task
    states = [
        state
        for state in states
        if not is_ignored_workspace_path(
            state.file_path, is_dir=False, rules=gitignore_rules
        )
    ]
    working = await asyncio.to_thread(_reconcile_working_tree, root, working, states)
    graph_version = _graph_version(states)
    from app.core.runtime_settings import load_runtime_settings

    query_settings = load_runtime_settings().code_graph
    cache_key = _cache_key_for(
        root=root,
        graph_version=graph_version,
        working_revision=working.revision,
        query=query,
        intent=intent,
        paths=paths,
        languages=languages,
        kinds=kinds,
        budget=capped_budget,
        freshness_policy=freshness_policy,
        limit=capped_limit,
        enable_lsp=enable_lsp,
    )
    cached = _query_cache.get(cache_key)
    if (
        working.reliable
        and cached
        and time.monotonic() - cached[0] <= query_settings.query_cache_ttl_seconds
    ):
        result = copy.deepcopy(cached[1])
        result.cache_hit = True
        return result

    graph_candidates: list[CodeQueryCandidate] = []
    graph_query_terms = query_terms(query)
    best_graph_score = 0.0
    graph_kind = kinds[0] if len(kinds) == 1 else None
    graph_language = languages[0] if len(languages) == 1 else None
    if workspace_id is not None and states:
        ranked = await graph_svc.search_nodes_ranked(
            db,
            workspace_id=workspace_id,
            query=query,
            kind=graph_kind,
            language=graph_language,
            paths=paths,
            limit=max(capped_limit * 3, 20),
        )
        best_graph_score = max((item.score for item in ranked), default=0.0)
        relevance_floor = max(1.0, best_graph_score * 0.3)
        hash_stale = await asyncio.to_thread(
            _stale_paths,
            root,
            states,
            [item.node.file_path for item in ranked],
        )
        if hash_stale:
            working = replace(
                working,
                changed=working.changed | hash_stale,
                source=f"{working.source}+hash",
            )
        for item in ranked:
            node = item.node
            if is_ignored_workspace_path(
                node.file_path, is_dir=False, rules=gitignore_rules
            ):
                continue
            if node.file_path in working.changed or node.file_path in working.deleted:
                continue
            if kinds and node.kind not in kinds:
                continue
            if languages and node.language not in languages:
                continue
            graph_match = match_query(
                query,
                graph_query_terms,
                (
                    node.name,
                    node.qualified_name,
                    node.file_path,
                    node.signature,
                    node.docstring,
                ),
            )
            if not _relevant_match(graph_match):
                continue
            if item.score < relevance_floor:
                continue
            relative_score = item.score / best_graph_score if best_graph_score else 0.0
            graph_candidates.append(
                CodeQueryCandidate(
                    handle=_node_handle(workspace_id, node.id, node.qualified_name),
                    file_path=node.file_path,
                    line_start=node.line_start,
                    line_end=node.line_end,
                    symbol=node.qualified_name,
                    kind=node.kind,
                    language=node.language,
                    signature=node.signature,
                    score=item.score,
                    confidence=min(
                        0.96,
                        0.5
                        + relative_score * 0.25
                        + graph_match.weighted_coverage * 0.2,
                    ),
                    provenance="graph",
                    match_reasons=list(item.match_reasons),
                    node_id=node.id,
                    workspace_id=workspace_id,
                )
            )

    relevant_dirty = sorted(
        path for path in working.changed if _path_in_scope(path, paths)
    )
    if freshness_policy == "fast":
        needs_live_source = not graph_candidates or best_graph_score < 20.0
    elif freshness_policy == "strict":
        needs_live_source = True
    else:
        needs_live_source = (
            not graph_candidates
            or best_graph_score < 20.0
            or bool(relevant_dirty)
            or intent in {"impact", "trace", "change"}
        )
    if needs_live_source:
        lexical_hits, extension_counts = await _lexical_search(
            root, query, paths, max(capped_limit * 3, 20)
        )
    else:
        lexical_hits = []
        extension_counts = await asyncio.to_thread(
            _count_workspace_extensions, root, paths
        )
    lexical_stale = await asyncio.to_thread(
        _stale_paths,
        root,
        states,
        [hit.file_path for hit in lexical_hits],
    )
    newly_detected_stale = lexical_stale - working.changed
    if newly_detected_stale:
        working = replace(
            working,
            revision=hashlib.sha256(
                f"{working.revision}\0{_content_fingerprint(root, newly_detected_stale)}".encode()
            ).hexdigest()[:16],
            changed=working.changed | newly_detected_stale,
            source=f"{working.source}+scan",
        )
    extension_counts, capability_states = _scoped_capability_inputs(
        extension_counts, states, paths, languages
    )
    capabilities = _language_capabilities(extension_counts, capability_states)
    relevant_dirty = sorted(
        path for path in working.changed if _path_in_scope(path, paths)
    )
    # For very large changes, prioritize files that lexical retrieval proved
    # relevant; remaining files stay represented by a partial-freshness flag.
    metadata_dirty = [path for path in relevant_dirty if is_graph_metadata_path(path)]
    source_dirty = [path for path in relevant_dirty if path not in metadata_dirty]
    overlay_paths = (
        [] if freshness_policy == "fast" and bool(graph_candidates) else source_dirty
    )
    pending_edges = 0
    limitations: list[str] = []
    if metadata_dirty:
        pending_edges = len(metadata_dirty)
        limitations.append(
            f"{len(metadata_dirty)} changed graph metadata file(s) require relationship re-resolution."
        )
    if len(relevant_dirty) > query_settings.query_large_change_files:
        relevant_hit_paths = {hit.file_path for hit in lexical_hits}
        overlay_paths = [path for path in source_dirty if path in relevant_hit_paths]
        pending_edges = max(pending_edges, len(relevant_dirty) - len(overlay_paths))
        limitations.append(
            f"Large working-tree change: parsed {len(overlay_paths)} query-relevant "
            f"files first; {pending_edges} files remain for background indexing."
        )
    overlay = await _overlay_candidates(
        root,
        overlay_paths,
        query,
        default_registry(),
        max(capped_limit * 2, 20),
        languages,
        kinds,
    )

    lexical_candidates = [
        CodeQueryCandidate(
            handle=_source_handle(hit.file_path, hit.line),
            file_path=hit.file_path,
            line_start=max(1, hit.line - 2),
            line_end=hit.line + 3,
            score=hit.score,
            confidence=min(0.85, 0.5 + hit.score / 400.0),
            provenance="lexical",
            match_reasons=list(hit.reasons),
            language=_language_for_path(hit.file_path),
        )
        for hit in lexical_hits
        if hit.file_path not in working.deleted
        and (not languages or _language_for_path(hit.file_path) in languages)
        and not kinds
    ]

    lsp_candidates: list[CodeQueryCandidate] = []
    if (
        enable_lsp
        and freshness_policy != "fast"
        and (not graph_candidates or freshness_policy == "strict")
    ):
        lsp_candidates = await _try_lsp(root, query, lexical_hits, intent)
        lsp_candidates = [
            candidate
            for candidate in lsp_candidates
            if _path_in_scope(candidate.file_path, paths)
            and (not languages or candidate.language in languages)
            and not kinds
        ]

    combined = _dedupe(
        [*overlay, *lsp_candidates, *graph_candidates, *lexical_candidates]
    )
    primary = combined[: max(capped_limit * 2, 20)]

    for candidate in primary:
        if intent == "locate":
            candidate.callers.clear()
            candidate.callees.clear()
            candidate.tests.clear()

    if workspace_id is not None and intent != "locate":
        for candidate in primary[: min(5, capped_limit)]:
            if candidate.node_id is None or candidate.workspace_id is None:
                continue
            direction = "in" if intent == "impact" else "both"
            neighbors = await graph_svc.get_neighbors(
                db,
                workspace_id=candidate.workspace_id,
                node_id=candidate.node_id,
                direction=direction,
            )
            for edge_kind, neighbor in neighbors[:12]:
                location = (
                    f"{edge_kind} {neighbor.qualified_name} — "
                    f"{neighbor.file_path}:{neighbor.line_start}"
                )
                if neighbor.file_path in working.changed:
                    location += " [pending freshness]"
                    pending_edges += 1
                if direction == "in" or edge_kind in {"called by", "referenced by"}:
                    candidate.callers.append(location)
                else:
                    candidate.callees.append(location)
    if intent != "locate":
        for candidate in primary:
            candidate.callers[:] = candidate.callers[:12]
            candidate.callees[:] = candidate.callees[:12]
            candidate.tests[:] = candidate.tests[:12]

    if relevant_dirty and intent in {"impact", "trace", "change"}:
        pending_edges = max(pending_edges, len(relevant_dirty))
        limitations.append(
            "Live dirty-file relationships are locally parsed, but cross-file edge resolution remains partial until reindex."
        )

    selected, truncated = _apply_budget(root, primary, capped_budget, capped_limit)
    indexed_files = sum(cap.indexed_files for cap in capabilities if cap.graph)
    workspace_files = sum(cap.workspace_files for cap in capabilities if cap.graph)
    coverage = min(1.0, indexed_files / workspace_files) if workspace_files else 0.0
    has_graph = bool(graph_candidates)
    has_overlay = bool(overlay)
    has_lsp = bool(lsp_candidates)
    has_lexical = bool(lexical_candidates)
    strategies = [
        name
        for name, active in (
            ("overlay", has_overlay),
            ("lsp", has_lsp),
            ("graph", has_graph),
            ("lexical", has_lexical),
        )
        if active
    ]
    strategy = "+".join(strategies) or "unavailable"
    if workspace_id is None or not states:
        freshness: Literal["fresh", "partial", "stale", "unavailable"] = "unavailable"
        limitations.append(
            "No ready graph snapshot; source/LSP fallback is authoritative."
        )
    elif not working.reliable:
        freshness = "partial"
        limitations.append(
            "Working-tree journal was unavailable; source verification was used and graph freshness cannot be guaranteed."
        )
    elif working.changed:
        freshness = (
            "partial"
            if pending_edges
            or len(relevant_dirty) > len(overlay_paths)
            or (freshness_policy == "fast" and bool(relevant_dirty))
            else "fresh"
        )
    else:
        freshness = "fresh"
    if any(not capability.graph for capability in capabilities):
        limitations.append(
            "Some workspace languages have no graph parser; lexical/LSP results do not imply complete call relationships."
        )
    if pending_edges:
        limitations.append(
            f"{pending_edges} relationship(s) touch dirty or not-yet-resolved files."
        )
    confidence = max((candidate.confidence for candidate in selected), default=0.0)
    if freshness == "partial" and intent in {"impact", "trace", "change"}:
        confidence = min(confidence, 0.78)
    next_ranges = [
        f"{candidate.file_path}:{candidate.line_start}-{candidate.line_end}"
        for candidate in selected
        if candidate.snippet is None
    ]
    result = CodeQueryResult(
        query=query,
        intent=intent,
        strategy=strategy,
        graph_version=graph_version,
        working_tree_revision=working.revision,
        freshness=freshness,
        coverage=coverage,
        confidence=confidence,
        results=selected,
        capabilities=capabilities,
        dirty_files=len(working.changed),
        pending_edges=pending_edges,
        limitations=list(dict.fromkeys(limitations)),
        next_read_ranges=next_ranges,
        truncated=truncated,
    )
    final_cache_key = _cache_key_for(
        root=root,
        graph_version=graph_version,
        working_revision=working.revision,
        query=query,
        intent=intent,
        paths=paths,
        languages=languages,
        kinds=kinds,
        budget=capped_budget,
        freshness_policy=freshness_policy,
        limit=capped_limit,
        enable_lsp=enable_lsp,
    )
    _query_cache[final_cache_key] = (time.monotonic(), copy.deepcopy(result))
    _query_cache.move_to_end(final_cache_key)
    while len(_query_cache) > _CACHE_MAX:
        _query_cache.popitem(last=False)
    return result


async def query_code_across_workspaces(
    db: AsyncSession,
    *,
    workspaces: Sequence[tuple[str, UUID | None, str]],
    query: str,
    intent: CodeQueryIntent = "explain",
    paths: Sequence[str] = (),
    languages: Sequence[str] = (),
    kinds: Sequence[str] = (),
    budget_tokens: int = 2500,
    freshness_policy: FreshnessPolicy = "balanced",
    limit: int = 10,
    enable_lsp: bool = True,
) -> CodeQueryResult:
    """Query linked repositories without flushing or extra model calls."""
    unique = list(dict.fromkeys(workspaces))
    if not unique:
        raise ValueError("At least one workspace is required.")
    if len(unique) == 1:
        root_path, workspace_id, _label = unique[0]
        return await query_code(
            db,
            root_path=root_path,
            workspace_id=workspace_id,
            query=query,
            intent=intent,
            paths=paths,
            languages=languages,
            kinds=kinds,
            budget_tokens=budget_tokens,
            freshness_policy=freshness_policy,
            limit=limit,
            enable_lsp=enable_lsp,
        )
    per_workspace_budget = max(500, min(12_000, budget_tokens))
    collected: list[tuple[str, CodeQueryResult]] = []
    for index, (root_path, workspace_id, label) in enumerate(unique):
        value = await query_code(
            db,
            root_path=root_path,
            workspace_id=workspace_id,
            query=query,
            intent=intent,
            paths=paths,
            languages=languages,
            kinds=kinds,
            budget_tokens=per_workspace_budget,
            freshness_policy=freshness_policy,
            limit=max(3, min(30, (limit + len(unique) - 1) // len(unique) * 2)),
            enable_lsp=enable_lsp and index == 0,
        )
        collected.append((label, value))

    combined_candidates = sorted(
        (
            replace(
                candidate,
                repository=label,
                score=candidate.score + (3.0 if index == 0 else 0.0),
                match_reasons=list(candidate.match_reasons),
                callers=list(candidate.callers),
                callees=list(candidate.callees),
                tests=list(candidate.tests),
            )
            for index, (label, value) in enumerate(collected)
            for candidate in value.results
        ),
        key=lambda item: (-item.score, item.repository or "", item.file_path),
    )

    node_candidates = {
        candidate.node_id: candidate
        for candidate in combined_candidates
        if candidate.node_id is not None
    }
    allowed_workspace_ids = {
        workspace_id for _root, workspace_id, _label in unique if workspace_id
    }
    if node_candidates:
        cross_edges = list(
            (
                await db.exec(
                    select(CrossRepoEdge)
                    .where(
                        CrossRepoEdge.status == "resolved",
                        or_(
                            col(CrossRepoEdge.src_node_id).in_(node_candidates),
                            col(CrossRepoEdge.dst_node_id).in_(node_candidates),
                        ),
                    )
                    .limit(50)
                )
            ).all()
        )
        labels_by_workspace = {
            workspace_id: label
            for _root, workspace_id, label in unique
            if workspace_id is not None
        }
        related_node_ids = {
            node_id
            for edge in cross_edges
            for node_id in (edge.src_node_id, edge.dst_node_id)
            if node_id is not None
        }
        related_nodes = {
            node.id: node
            for node in (
                await db.exec(
                    select(CodeNode).where(col(CodeNode.id).in_(related_node_ids))
                )
            ).all()
        }
        for edge in cross_edges:
            if edge.src_node_id in node_candidates:
                candidate = node_candidates[edge.src_node_id]
                if (
                    edge.dst_workspace_id in allowed_workspace_ids
                    and edge.dst_node_id is not None
                ):
                    target = related_nodes.get(edge.dst_node_id)
                    if target is not None:
                        label = labels_by_workspace.get(edge.dst_workspace_id, "repo")
                        candidate.callees.append(
                            f"cross-repo {edge.kind} {target.qualified_name} — "
                            f"{label}/{target.file_path}:{target.line_start}"
                        )
            if edge.dst_node_id in node_candidates:
                candidate = node_candidates[edge.dst_node_id]
                if (
                    edge.src_workspace_id in allowed_workspace_ids
                    and edge.src_node_id is not None
                ):
                    source = related_nodes.get(edge.src_node_id)
                    if source is not None:
                        label = labels_by_workspace.get(edge.src_workspace_id, "repo")
                        candidate.callers.append(
                            f"cross-repo {edge.kind} {source.qualified_name} — "
                            f"{label}/{source.file_path}:{source.line_start}"
                        )

    combined_candidates, globally_truncated = _apply_existing_snippet_budget(
        combined_candidates,
        max(500, min(budget_tokens, 12_000)),
        max(1, min(limit, 30)),
    )

    capability_map: dict[
        tuple[str, tuple[str, ...], bool, bool], LanguageCapability
    ] = {}
    for _label, value in collected:
        for capability in value.capabilities:
            key = (
                capability.language,
                capability.extensions,
                capability.graph,
                capability.lsp,
            )
            previous = capability_map.get(key)
            capability_map[key] = LanguageCapability(
                language=capability.language,
                extensions=capability.extensions,
                graph=capability.graph,
                lsp=capability.lsp,
                indexed_files=capability.indexed_files
                + (previous.indexed_files if previous else 0),
                workspace_files=capability.workspace_files
                + (previous.workspace_files if previous else 0),
            )
    total_workspace_files = sum(
        capability.workspace_files for capability in capability_map.values()
    )
    total_indexed_files = sum(
        capability.indexed_files for capability in capability_map.values()
    )
    freshness_values = {value.freshness for _label, value in collected}
    if freshness_values == {"unavailable"}:
        combined_freshness: Literal["fresh", "partial", "stale", "unavailable"] = (
            "unavailable"
        )
    elif freshness_values == {"fresh"}:
        combined_freshness = "fresh"
    else:
        combined_freshness = "partial"
    versions = ":".join(value.graph_version or "none" for _label, value in collected)
    strategies = "+".join(dict.fromkeys(value.strategy for _label, value in collected))
    limitations = [
        f"[{label}] {limitation}"
        for label, value in collected
        for limitation in value.limitations
    ]
    return CodeQueryResult(
        query=query,
        intent=intent,
        strategy=f"project:{strategies}",
        graph_version=hashlib.sha256(versions.encode()).hexdigest()[:12],
        working_tree_revision=hashlib.sha256(
            ":".join(
                value.working_tree_revision for _label, value in collected
            ).encode()
        ).hexdigest()[:16],
        freshness=combined_freshness,
        coverage=(
            min(1.0, total_indexed_files / total_workspace_files)
            if total_workspace_files
            else 0.0
        ),
        confidence=max(
            (candidate.confidence for candidate in combined_candidates), default=0.0
        ),
        results=combined_candidates,
        capabilities=list(capability_map.values()),
        dirty_files=sum(value.dirty_files for _label, value in collected),
        pending_edges=sum(value.pending_edges for _label, value in collected),
        limitations=list(dict.fromkeys(limitations)),
        next_read_ranges=[
            f"{candidate.repository}/{candidate.file_path}:"
            f"{candidate.line_start}-{candidate.line_end}"
            for candidate in combined_candidates
            if candidate.snippet is None
        ],
        truncated=globally_truncated
        or any(value.truncated for _label, value in collected),
        cache_hit=all(value.cache_hit for _label, value in collected),
    )


async def get_capabilities(
    db: AsyncSession, *, root_path: str, workspace_id: UUID | None
) -> list[LanguageCapability]:
    root = Path(root_path).expanduser().resolve()
    states, counts = await asyncio.gather(
        _states(db, workspace_id),
        asyncio.to_thread(_count_workspace_extensions, root),
    )
    return _language_capabilities(counts, states)


async def get_freshness(
    db: AsyncSession, *, root_path: str, workspace_id: UUID | None
) -> RetrievalFreshness:
    root = Path(root_path).expanduser().resolve()
    states, working = await asyncio.gather(
        _states(db, workspace_id), _working_tree(root)
    )
    working = await asyncio.to_thread(_reconcile_working_tree, root, working, states)
    from app.core.runtime_settings import load_runtime_settings

    stale = await _verified_stale_paths(
        root,
        states,
        working,
        load_runtime_settings().code_graph.query_cache_ttl_seconds,
    )
    if stale:
        working = replace(
            working,
            changed=working.changed | stale,
            source=f"{working.source}+hash",
        )
    if workspace_id is None or not states:
        freshness: Literal["fresh", "partial", "unavailable"] = "unavailable"
    elif working.changed or not working.reliable:
        freshness = "partial"
    else:
        freshness = "fresh"
    return RetrievalFreshness(
        graph_version=_graph_version(states),
        working_tree_revision=working.revision,
        freshness=freshness,
        indexed_files=len(states),
        dirty_files=len(working.changed),
        change_source=working.source,
    )
