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

from app.core.runtime_settings import (
    CodeGraphSettings,
    CodeQueryPolicySettings,
    load_runtime_settings,
)
from app.agent.tools.builtin.filesystem._ignore import (
    is_ignored_workspace_path,
    load_gitignore_rules,
)
from app.models.code_graph import CodeIndexState, CodeNode, CrossRepoEdge
from app.services import code_graph_service as graph_svc
from app.services.code_graph.query import QueryMatch, match_query, query_terms
from app.services.code_graph.indexer import content_hash as graph_content_hash
from app.services.code_graph.parsers.registry import ParserRegistry, default_registry
from app.services.code_graph.types import EDGE_CALLS, EDGE_CONTAINS, EDGE_REFERENCES
from app.services.code_graph.watcher import get_dirty_code_paths, is_graph_metadata_path

CodeQueryIntent = Literal["locate", "explain", "impact", "trace", "change"]
FreshnessPolicy = Literal["fast", "balanced", "strict"]

_MAX_SCAN_BYTES = 1_500_000
_MAX_LINE_CHARS = 500


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
    context_role: Literal["match", "root", "spine", "neighbor"] = "match"


@dataclass(frozen=True, slots=True)
class CodeQueryFlowHop:
    source: str
    relation: str
    target: str
    source_location: str
    target_location: str


@dataclass(frozen=True, slots=True)
class CodeQueryImpact:
    root: str
    references: tuple[str, ...]
    truncated: bool = False


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
    flow: list[CodeQueryFlowHop] = field(default_factory=list)
    blast_radius: list[CodeQueryImpact] = field(default_factory=list)
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


def _relevant_match(match: QueryMatch, policy: CodeQueryPolicySettings) -> bool:
    # Long natural-language questions dilute exact symbol/path evidence. Keep
    # the strict coverage rule for sparse prose, while accepting corroborated
    # source evidence (three independently matched terms) and concise named
    # lookups. This is evidence scoring, not message-intent routing.
    return bool(
        match.exact
        or match.weighted_coverage >= policy.min_weighted_coverage
        or (
            match.total <= policy.sparse_query_max_terms
            and match.hits >= policy.sparse_query_min_hits
        )
        or (
            match.hits >= policy.corroborating_min_hits
            and match.weighted_coverage >= policy.corroborating_min_coverage
        )
    )


def _is_retrieval_path(root: Path, path: str) -> bool:
    """Accept parser-backed files and any other live text file.

    Unsupported languages must remain searchable without maintaining an
    extension allowlist. Binary detection is content-based and bounded; ripgrep
    applies its own binary guard during the lexical scan as a second layer.
    """
    if default_registry().for_path(path) is not None or is_graph_metadata_path(path):
        return True
    candidate = _safe_file(root, path)
    if candidate is None or not candidate.is_file():
        return False
    try:
        with candidate.open("rb") as stream:
            sample = stream.read(8192)
    except OSError:
        return False
    return b"\0" not in sample


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
            if _is_retrieval_path(root, path):
                changed.add(path)
            if index < len(records) and records[index]:
                source_path = records[index].replace("\\", "/")
                index += 1
                if "R" in status and _is_retrieval_path(root, source_path):
                    deleted.add(source_path)
            continue
        if _is_retrieval_path(root, path):
            changed.add(path)
        if "D" in status and _is_retrieval_path(root, path):
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
        if _is_retrieval_path(root, path)
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
            if graph_content_hash(path.read_bytes()) != expected:
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


def _rg_lexical(
    root: Path,
    query: str,
    paths: Sequence[str],
    limit: int,
    policy: CodeQueryPolicySettings | None = None,
) -> tuple[list[_LexicalHit], Counter[str]]:
    """Run one bounded, gitignore-aware text fallback without walking files."""
    policy = policy or load_runtime_settings().code_graph.query_policy
    terms = query_terms(query)
    rg = shutil.which("rg")
    if not terms or rg is None:
        return [], Counter()
    scopes = [value for value in paths if _safe_file(root, value) is not None] or ["."]
    command = [
        rg,
        "--fixed-strings",
        "--ignore-case",
        "--line-number",
        "--column",
        "--no-heading",
        "--color=never",
        "--max-count=3",
    ]
    gitignore = root / ".gitignore"
    if gitignore.is_file():
        command.extend(("--ignore-file", str(gitignore)))
    # Longer evidence is more selective, but every term remains eligible. rg
    # evaluates the alternatives in one process and is capped again below.
    for term in sorted(terms, key=lambda value: (-len(value), value)):
        command.extend(("-e", term))
    command.extend(("--", *scopes))
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=2.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return [], Counter()

    hits: list[_LexicalHit] = []
    extension_counts: Counter[str] = Counter()
    for raw_line in completed.stdout.splitlines()[
        : max(
            policy.lexical_output_min_lines,
            limit * policy.lexical_output_multiplier,
        )
    ]:
        try:
            file_path, line_text, column_text, text = raw_line.split(":", 3)
            line = int(line_text)
            column = int(column_text)
        except (ValueError, TypeError):
            continue
        rel = Path(file_path).as_posix().removeprefix("./")
        if not _is_retrieval_path(root, rel):
            continue
        suffix = Path(rel).suffix.casefold()
        extension_counts[suffix] += 1
        line_match = match_query(query, terms, (rel, text))
        if not _relevant_match(line_match, policy):
            continue
        hits.append(
            _LexicalHit(
                file_path=rel,
                line=line,
                column=column,
                text=text[:_MAX_LINE_CHARS],
                score=(
                    policy.lexical_score_base
                    + line_match.score * policy.lexical_score_scale
                ),
                reasons=(f"{line_match.hits} query term(s) in current source",),
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


def _indexed_extension_counts(states: Sequence[CodeIndexState]) -> Counter[str]:
    """Use index metadata for coverage; never enumerate a clean workspace."""
    return Counter(Path(state.file_path).suffix.casefold() for state in states)


async def _lexical_search(
    root: Path,
    query: str,
    paths: Sequence[str],
    limit: int,
    policy: CodeQueryPolicySettings,
) -> tuple[list[_LexicalHit], Counter[str]]:
    return await asyncio.to_thread(_rg_lexical, root, query, paths, limit, policy)


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


def _read_relevant_snippet(
    root: Path,
    file_path: str,
    start: int,
    end: int,
    *,
    query: str,
    max_lines: int,
) -> str | None:
    """Read a whole short symbol or merged evidence windows from a large one."""
    if end - start + 1 <= max_lines:
        return _read_snippet(root, file_path, start, end)
    path = _safe_file(root, file_path)
    if path is None or not path.is_file():
        return None
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    first = max(1, start)
    last = min(len(lines), max(first, end))
    terms = query_terms(query)
    folded_by_number = {
        number: lines[number - 1].casefold() for number in range(first, last + 1)
    }
    term_frequency = Counter(
        term for folded in folded_by_number.values() for term in terms if term in folded
    )
    scored: list[tuple[float, int, tuple[str, ...]]] = []
    for number in range(first, last + 1):
        folded = folded_by_number[number]
        matched_terms = tuple(term for term in terms if term in folded)
        score = sum(len(term) / term_frequency[term] for term in matched_terms)
        if score:
            scored.append((score, number, matched_terms))
    if not scored:
        return _read_snippet(root, file_path, first, first + max_lines - 1)

    radius = 6
    windows: list[tuple[int, int]] = []
    covered = 0
    covered_terms: set[str] = set()
    remaining_hits = list(scored)
    while remaining_hits and covered < max_lines:
        _score, number, matched_terms = max(
            remaining_hits,
            key=lambda item: (
                sum(
                    len(term) / term_frequency[term]
                    for term in item[2]
                    if term not in covered_terms
                ),
                item[0],
                -item[1],
            ),
        )
        remaining_hits.remove((_score, number, matched_terms))
        window = (max(first, number - radius), min(last, number + radius))
        if any(left <= number <= right for left, right in windows):
            continue
        windows.append(window)
        covered_terms.update(matched_terms)
        covered += window[1] - window[0] + 1
    windows.sort()
    merged: list[tuple[int, int]] = []
    for left, right in windows:
        if merged and left <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], right))
        else:
            merged.append((left, right))
    rendered: list[str] = []
    emitted = 0
    for left, right in merged:
        if rendered:
            rendered.append("      | …")
        for number in range(left, right + 1):
            if emitted >= max_lines:
                break
            rendered.append(f"{number:>5} | {lines[number - 1]}")
            emitted += 1
        if emitted >= max_lines:
            break
    return "\n".join(rendered) or None


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
    policy: CodeQueryPolicySettings | None = None,
) -> list[CodeQueryCandidate]:
    policy = policy or load_runtime_settings().code_graph.query_policy
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
            if not _relevant_match(node_match, policy):
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
                score=policy.overlay_score_base + node_match.score,
                confidence=min(
                    policy.overlay_confidence_cap,
                    policy.overlay_confidence_base
                    + node_match.weighted_coverage
                    * policy.overlay_confidence_coverage_weight,
                ),
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
                and _relevant_match(target_match, policy)
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
                    score=policy.overlay_relationship_score,
                    confidence=policy.overlay_relationship_confidence,
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
    policy: CodeQueryPolicySettings | None = None,
) -> list[CodeQueryCandidate]:
    return await asyncio.to_thread(
        _parse_overlay,
        root,
        dirty_paths,
        query,
        registry,
        limit,
        languages,
        kinds,
        policy,
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
    policy: CodeQueryPolicySettings,
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
    for location in locations[: policy.lsp_max_locations]:
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
                score=policy.lsp_score,
                confidence=policy.lsp_confidence,
                provenance="lsp",
                match_reasons=["live language-server location"],
                language=_language_for_path(rel),
            )
        )
    return candidates


def _dedupe(candidates: Sequence[CodeQueryCandidate]) -> list[CodeQueryCandidate]:
    ranked = sorted(
        candidates,
        key=lambda item: (
            -item.score,
            item.kind == "file",
            item.file_path,
            item.line_start,
        ),
    )
    unique: list[CodeQueryCandidate] = []
    for candidate in ranked:
        duplicate = any(
            existing.file_path == candidate.file_path
            and existing.line_start <= candidate.line_end
            and candidate.line_start <= existing.line_end
            and existing.provenance == candidate.provenance
            and {existing.context_role, candidate.context_role} != {"root", "spine"}
            for existing in unique
        )
        if not duplicate:
            unique.append(candidate)

    # Structural flow evidence must survive a repository-wide diversity pass.
    # Then MMR-lite surfaces one ordinary match per remaining file before
    # secondary hits from a file that is already represented.
    structural = [
        candidate for candidate in unique if candidate.context_role in {"root", "spine"}
    ]
    ordinary = [
        candidate
        for candidate in unique
        if candidate.context_role not in {"root", "spine"}
    ]
    diverse: list[CodeQueryCandidate] = []
    repeated: list[CodeQueryCandidate] = []
    seen_files = {candidate.file_path for candidate in structural}
    for candidate in ordinary:
        if candidate.file_path in seen_files:
            repeated.append(candidate)
        else:
            diverse.append(candidate)
            seen_files.add(candidate.file_path)
    return [*structural, *diverse, *repeated]


def _required_evidence_candidates(
    candidates: Sequence[CodeQueryCandidate],
    policy: CodeQueryPolicySettings | None = None,
) -> list[CodeQueryCandidate]:
    policy = policy or load_runtime_settings().code_graph.query_policy
    roots = [candidate for candidate in candidates if candidate.context_role == "root"]
    spines = [
        candidate for candidate in candidates if candidate.context_role == "spine"
    ]
    if not roots and not spines:
        return list(
            candidates[: min(policy.fallback_required_matches, len(candidates))]
        )

    required = roots[: policy.max_required_structural]
    root_files = {candidate.file_path for candidate in required}
    spines_per_file: Counter[str] = Counter()
    for candidate in spines:
        if len(required) >= policy.max_required_structural:
            break
        if candidate.file_path in root_files:
            continue
        if spines_per_file[candidate.file_path] >= policy.max_required_spines_per_file:
            continue
        required.append(candidate)
        spines_per_file[candidate.file_path] += 1
    return required


def _candidate_identity(candidate: CodeQueryCandidate) -> tuple[str | None, str]:
    return candidate.repository, candidate.handle


def _missing_evidence_candidates(
    candidates: Sequence[CodeQueryCandidate],
    selected: Sequence[CodeQueryCandidate],
    policy: CodeQueryPolicySettings | None = None,
) -> list[CodeQueryCandidate]:
    """Return only source omissions that can materially limit the answer.

    Secondary matches and neighbors provide ranking diversity; omitting them
    must not tell the model to keep exploring. Structural roots/spines are
    required when available, while source-only fallback requires its leading
    matches.
    """
    policy = policy or load_runtime_settings().code_graph.query_policy
    required = _required_evidence_candidates(candidates, policy)
    satisfied = {
        _candidate_identity(candidate)
        for candidate in selected
        if candidate.snippet is not None
    }
    missing: list[CodeQueryCandidate] = []
    seen: set[tuple[str | None, str]] = set()
    for candidate in required:
        identity = _candidate_identity(candidate)
        if identity in satisfied or identity in seen:
            continue
        seen.add(identity)
        missing.append(candidate)
    return missing


def _apply_budget(
    root: Path,
    candidates: Sequence[CodeQueryCandidate],
    budget_tokens: int,
    limit: int,
    query: str,
    policy: CodeQueryPolicySettings | None = None,
) -> tuple[list[CodeQueryCandidate], bool]:
    """Allocate source by file relevance before rendering any snippets."""
    policy = policy or load_runtime_settings().code_graph.query_policy
    remaining_chars = max(
        policy.min_output_chars,
        budget_tokens * policy.estimated_chars_per_token,
    )
    grouped: dict[str, list[CodeQueryCandidate]] = {}
    for candidate in candidates:
        grouped.setdefault(candidate.file_path, []).append(candidate)
    role_order = {"root": 0, "spine": 1, "match": 2, "neighbor": 3}
    bounded_groups: dict[str, list[CodeQueryCandidate]] = {}
    for path, items in grouped.items():
        ordered = sorted(
            items, key=lambda item: (role_order[item.context_role], -item.score)
        )
        structural = [
            item for item in ordered if item.context_role in {"root", "spine"}
        ][: policy.max_structural_per_file]
        ordinary = [
            item for item in ordered if item.context_role not in {"root", "spine"}
        ]
        bounded_groups[path] = [
            *structural,
            *ordinary[
                : (
                    policy.max_ordinary_per_structural_file
                    if structural
                    else policy.max_ordinary_without_structural
                )
            ],
        ]
    grouped = bounded_groups
    role_weight = {
        "root": policy.root_role_weight,
        "spine": policy.spine_role_weight,
        "neighbor": policy.neighbor_role_weight,
        "match": policy.match_role_weight,
    }
    file_scores = {
        path: sum(
            item.score * role_weight[item.context_role] / (index + 1)
            for index, item in enumerate(items)
        )
        for path, items in grouped.items()
    }
    best_file_score = max(file_scores.values(), default=0.0)
    admitted = [
        path
        for path, _score in sorted(
            file_scores.items(), key=lambda item: (-item[1], item[0])
        )
        if not best_file_score
        or file_scores[path] >= best_file_score * policy.file_relevance_ratio
    ][
        : max(
            1,
            min(
                policy.max_candidate_files,
                (limit + policy.candidates_per_file - 1)
                // policy.candidates_per_file,
            ),
        )
    ]
    ranked = [candidate for path in admitted for candidate in grouped[path]]
    selected: list[CodeQueryCandidate] = []
    has_structural_evidence = any(
        candidate.context_role in {"root", "spine"} for candidate in candidates
    )
    required_identities = {
        _candidate_identity(candidate)
        for candidate in _required_evidence_candidates(candidates, policy)
    }
    clipped_fallback_source = False
    total_score = sum(file_scores[path] for path in admitted) or 1.0
    source_chars = max(
        0,
        remaining_chars
        - sum(_candidate_metadata_chars(candidate, policy) for candidate in ranked),
    )
    minimum_file_chars = min(
        policy.min_file_allocation_cap_chars,
        source_chars // max(1, len(admitted)),
    )
    distributable_chars = max(0, source_chars - minimum_file_chars * len(admitted))
    file_allowance = {
        path: minimum_file_chars
        + int(distributable_chars * file_scores[path] / total_score)
        for path in admitted
    }
    file_used: Counter[str] = Counter()
    for original in ranked:
        if len(selected) >= limit:
            break
        candidate = copy.deepcopy(original)
        metadata_cost = _candidate_metadata_chars(candidate, policy)
        if metadata_cost >= remaining_chars and selected:
            break
        remaining_chars -= min(metadata_cost, remaining_chars)
        # A complete admitted method is more useful than several disconnected
        # fragments. Large file nodes remain a compact skeleton.
        max_lines = (
            policy.max_symbol_lines
            if candidate.kind != "file"
            else policy.max_file_lines
        )
        source_allowance = max(
            0,
            file_allowance[candidate.file_path] - file_used[candidate.file_path],
        )
        max_lines = min(
            max_lines,
            max(
                policy.min_snippet_lines,
                source_allowance // policy.estimated_chars_per_line,
            ),
        )
        snippet = _read_relevant_snippet(
            root,
            candidate.file_path,
            candidate.line_start,
            candidate.line_end,
            query=query,
            max_lines=max_lines,
        )
        if snippet:
            allowance = min(
                remaining_chars,
                source_allowance,
                len(snippet),
            )
            if (
                not has_structural_evidence
                and allowance < len(snippet)
                and _candidate_identity(candidate) in required_identities
            ):
                clipped_fallback_source = True
            candidate.snippet = snippet[:allowance] or None
            remaining_chars -= len(candidate.snippet or "")
            file_used[candidate.file_path] += len(candidate.snippet or "")
        selected.append(candidate)
        if remaining_chars <= policy.output_stop_reserve_chars:
            break
    return selected, clipped_fallback_source or bool(
        _missing_evidence_candidates(candidates, selected, policy)
    )


def _candidate_metadata_chars(
    candidate: CodeQueryCandidate, policy: CodeQueryPolicySettings
) -> int:
    return policy.candidate_metadata_base_chars + sum(
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


def _candidate_from_node(
    workspace_id: UUID,
    node: CodeNode,
    *,
    score: float,
    reason: str,
    confidence: float,
    context_role: Literal["spine", "neighbor"] = "neighbor",
) -> CodeQueryCandidate:
    return CodeQueryCandidate(
        handle=_node_handle(workspace_id, node.id, node.qualified_name),
        file_path=node.file_path,
        line_start=node.line_start,
        line_end=node.line_end,
        symbol=node.qualified_name,
        kind=node.kind,
        language=node.language,
        signature=node.signature,
        score=score,
        confidence=confidence,
        provenance="graph",
        match_reasons=[reason],
        node_id=node.id,
        workspace_id=workspace_id,
        context_role=context_role,
    )


def _shared_path_prefix(left: str, right: str) -> int:
    count = 0
    for left_part, right_part in zip(Path(left).parts, Path(right).parts, strict=False):
        if left_part != right_part:
            break
        count += 1
    return count


async def _expand_graph_context(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    query: str,
    roots: Sequence[CodeQueryCandidate],
    policy: CodeQueryPolicySettings | None = None,
) -> tuple[list[CodeQueryCandidate], list[CodeQueryFlowHop], list[CodeQueryImpact]]:
    """Build compact evidence every exploration needs: impact and named flow."""
    policy = policy or load_runtime_settings().code_graph.query_policy
    query_folded = query.casefold()
    query_evidence = set(query_terms(query))
    exact_qualified = {
        item.symbol.casefold()
        for item in roots
        if item.symbol and "." in item.symbol and item.symbol.casefold() in query_folded
    }
    named_roots = [
        item
        for item in roots
        if item.node_id is not None
        and item.symbol
        and len(item.symbol.rsplit(".", 1)[-1]) >= policy.weak_identifier_chars
        and (
            (
                item.context_role == "spine"
                and Path(item.file_path).stem.casefold() in query_evidence
            )
            or item.symbol.rsplit(".", 1)[-1].casefold() in query_folded
        )
        and (
            item.symbol.casefold() in exact_qualified
            or not any(
                exact.endswith("." + item.symbol.rsplit(".", 1)[-1].casefold())
                or exact.startswith(item.symbol.casefold() + ".")
                for exact in exact_qualified
            )
        )
    ]
    anchored_root_paths = {
        item.file_path
        for item in named_roots
        if item.context_role == "spine"
        and Path(item.file_path).stem.casefold() in query_evidence
    }
    exact_named_root_ids = {
        item.node_id
        for item in named_roots
        if item.node_id is not None
        and item.symbol
        and len(item.symbol.rsplit(".", 1)[-1]) >= policy.strong_identifier_chars
        and (
            item.symbol.casefold() in query_evidence
            or item.symbol.rsplit(".", 1)[-1].casefold() in query_evidence
        )
    }
    if anchored_root_paths or exact_named_root_ids:
        named_roots = [
            item
            for item in named_roots
            if item.node_id in exact_named_root_ids
            or item.file_path in anchored_root_paths
            or (item.symbol and item.symbol.casefold() in exact_qualified)
        ]
    named_roots.sort(
        key=lambda item: (
            item.node_id not in exact_named_root_ids,
            item.context_role != "spine",
            Path(item.file_path).stem.casefold() not in query_evidence,
            item.symbol.casefold() not in exact_qualified if item.symbol else True,
            query_folded.find(
                (item.symbol or item.file_path).rsplit(".", 1)[-1].casefold()
            ),
            -len((item.symbol or "").rsplit(".", 1)[-1]),
            -item.score,
        )
    )
    named_roots = named_roots[: policy.max_named_roots]
    if not named_roots:
        named_roots = sorted(
            (item for item in roots if item.node_id is not None),
            key=lambda item: (-item.score, item.file_path, item.line_start),
        )[: policy.fallback_root_count]
    named_root_ids: list[UUID] = list(
        dict.fromkeys(item.node_id for item in named_roots if item.node_id is not None)
    )
    roots_by_id = {
        item.node_id: item for item in roots if item.node_id in named_root_ids
    }
    for candidate in roots_by_id.values():
        candidate.context_role = "root"

    impact: list[CodeQueryImpact] = []
    neighborhood: list[CodeQueryCandidate] = []
    for node_id in named_root_ids[: policy.max_named_roots]:
        candidate = roots_by_id[node_id]
        references = await graph_svc.find_references(
            db,
            workspace_id=workspace_id,
            node_id=node_id,
            limit=policy.max_trace_callees + 1,
        )
        rendered = tuple(
            f"{kind} {source.qualified_name} — {source.file_path}:{line or source.line_start}"
            for kind, source, line in references[: policy.max_trace_callees]
        )
        impact.append(
            CodeQueryImpact(
                root=candidate.symbol or candidate.file_path,
                references=rendered,
                truncated=len(references) > policy.max_trace_callees,
            )
        )
        ranked_references = sorted(
            references,
            key=lambda item: (
                -_shared_path_prefix(candidate.file_path, item[1].file_path),
                len(Path(item[1].file_path).parts),
                item[1].file_path,
            ),
        )
        admitted_references = 0
        for _kind, source, _line in ranked_references:
            if (
                source.kind != "file"
                and source.qualified_name != source.file_path
                and _shared_path_prefix(candidate.file_path, source.file_path)
                >= policy.min_shared_path_segments
            ):
                neighborhood.append(
                    _candidate_from_node(
                        workspace_id,
                        source,
                        score=min(
                            policy.inbound_score_cap,
                            max(
                                policy.inbound_score_floor,
                                candidate.score * policy.inbound_score_factor,
                            ),
                        ),
                        reason=f"inbound reference to {candidate.symbol}",
                        confidence=policy.graph_neighbor_confidence,
                    )
                )
                admitted_references += 1
                if admitted_references >= policy.max_neighbors_per_root:
                    break
        neighbors = await graph_svc.get_neighbors(
            db,
            workspace_id=workspace_id,
            node_id=node_id,
            direction="out",
        )
        ranked_neighbors = sorted(
            neighbors,
            key=lambda item: (
                -sum(
                    len(term)
                    for term in query_evidence.intersection(query_terms(item[1].name))
                )
                if item[0] == EDGE_CONTAINS
                else 0,
                -_shared_path_prefix(candidate.file_path, item[1].file_path),
                0 if item[0] == EDGE_REFERENCES else 1,
                item[1].file_path,
            ),
        )
        admitted_neighbors = 0
        for relation, neighbor in ranked_neighbors:
            same_file = neighbor.file_path == candidate.file_path
            neighbor_leaf = neighbor.name.strip("_").casefold()
            source_leaf = (
                (candidate.symbol or "").rsplit(".", 1)[-1].strip("_").casefold()
            )
            relationship_terms = query_evidence.intersection(query_terms(neighbor.name))
            contained_terms = {
                term
                for term in relationship_terms
                if len(term) >= policy.strong_identifier_chars
                or term == neighbor_leaf
                or (term == source_leaf and neighbor_leaf.startswith(f"{source_leaf}_"))
            }
            contained_evidence = bool(
                relation == EDGE_CONTAINS
                and contained_terms
                and not (
                    neighbor.line_start <= candidate.line_start
                    and neighbor.line_end >= candidate.line_end
                )
            )
            direct_evidence = bool(
                (
                    not same_file
                    and relation == EDGE_CALLS
                    and any(
                        len(term) >= policy.strong_identifier_chars
                        or term == neighbor_leaf
                        for term in relationship_terms
                    )
                )
                or (same_file and contained_terms and relation == EDGE_CALLS)
                or (same_file and contained_terms and relation == EDGE_REFERENCES)
            )
            if (
                neighbor.kind == "file"
                or neighbor.qualified_name == neighbor.file_path
                or (relation == EDGE_CONTAINS and not contained_evidence)
                or (not same_file and relation not in {EDGE_CALLS, EDGE_REFERENCES})
                or (not same_file and not direct_evidence)
            ):
                continue
            neighborhood.append(
                _candidate_from_node(
                    workspace_id,
                    neighbor,
                    score=(
                        min(
                            policy.direct_score_cap,
                            max(
                                policy.direct_score_floor,
                                candidate.score * policy.direct_score_factor,
                            ),
                        )
                        + sum(
                            len(term)
                            for term in (
                                relationship_terms
                                if relation == EDGE_CALLS
                                else contained_terms
                            )
                        )
                        if contained_evidence or direct_evidence
                        else min(
                            policy.neighbor_score_cap,
                            max(
                                policy.neighbor_score_floor,
                                candidate.score * policy.neighbor_score_factor,
                            ),
                        )
                    ),
                    reason=f"direct {relation} relationship to {candidate.symbol}",
                    confidence=policy.graph_neighbor_confidence,
                    context_role=(
                        "spine" if contained_evidence or direct_evidence else "neighbor"
                    ),
                )
            )
            admitted_neighbors += 1
            if admitted_neighbors >= policy.max_neighbors_per_root:
                break

    flow: list[CodeQueryFlowHop] = []
    spine: list[CodeQueryCandidate] = []
    trace_frontier = [
        (node_id, roots_by_id[node_id], 0)
        for node_id in named_root_ids
        if node_id in roots_by_id
    ]
    traced_ids = set(named_root_ids)
    traced_count = 0
    while trace_frontier and traced_count < policy.max_trace_callees:
        source_id, source_candidate, depth = trace_frontier.pop(0)
        if depth >= policy.max_trace_hops:
            continue
        callees = await graph_svc.get_neighbors(
            db,
            workspace_id=workspace_id,
            node_id=source_id,
            direction="out",
            edge_kind=EDGE_CALLS,
        )
        for relation, target in callees:
            if target.id in traced_ids or target.kind == "file":
                continue
            target_leaf = target.name.strip("_").casefold()
            source_leaf = (
                (source_candidate.symbol or "").rsplit(".", 1)[-1].strip("_").casefold()
            )
            matched_terms = {
                term
                for term in query_evidence.intersection(query_terms(target.name))
                if len(term) >= policy.strong_identifier_chars
                or term == target_leaf
                or (
                    target.file_path == source_candidate.file_path
                    and term == source_leaf
                    and target_leaf.startswith(f"{source_leaf}_")
                )
            }
            if not matched_terms:
                continue
            traced_ids.add(target.id)
            traced_count += 1
            traced_candidate = _candidate_from_node(
                workspace_id,
                target,
                score=max(
                    policy.trace_score_floor,
                    source_candidate.score * policy.trace_score_factor,
                )
                + sum(len(term) for term in matched_terms),
                reason=f"query-relevant call from {source_candidate.symbol}",
                confidence=policy.graph_neighbor_confidence,
                context_role="spine",
            )
            spine.append(traced_candidate)
            flow.append(
                CodeQueryFlowHop(
                    source=source_candidate.symbol or source_candidate.file_path,
                    relation=relation,
                    target=target.qualified_name,
                    source_location=(
                        f"{source_candidate.file_path}:{source_candidate.line_start}"
                    ),
                    target_location=f"{target.file_path}:{target.line_start}",
                )
            )
            trace_frontier.append((target.id, traced_candidate, depth + 1))
            if traced_count >= policy.max_trace_callees:
                break

    if len(named_root_ids) >= 2:
        for src_id, dst_id in zip(named_root_ids, named_root_ids[1:], strict=False):
            path = await graph_svc.find_shortest_path(
                db,
                src_workspace_id=workspace_id,
                src_id=src_id,
                dst_id=dst_id,
                max_hops=policy.max_shortest_path_hops,
            )
            if path is None:
                continue
            current_id = src_id
            forward_path = []
            for source, relation, target in path:
                if source.id != current_id:
                    forward_path = []
                    break
                forward_path.append((source, relation, target))
                current_id = target.id
            if current_id != dst_id:
                forward_path = []
            source_root = roots_by_id[src_id]
            target_root = roots_by_id[dst_id]
            shared_scope = min(
                policy.min_shared_path_segments,
                _shared_path_prefix(
                    source_root.file_path,
                    target_root.file_path,
                ),
            )
            if shared_scope and any(
                _shared_path_prefix(node.file_path, source_root.file_path)
                < shared_scope
                and _shared_path_prefix(node.file_path, target_root.file_path)
                < shared_scope
                for hop in forward_path
                for node in (hop[0], hop[2])
            ):
                forward_path = []
            for source, relation, target in forward_path:
                flow.append(
                    CodeQueryFlowHop(
                        source=source.qualified_name,
                        relation=relation,
                        target=target.qualified_name,
                        source_location=f"{source.file_path}:{source.line_start}",
                        target_location=f"{target.file_path}:{target.line_start}",
                    )
                )
                for node in (source, target):
                    if node.id not in roots_by_id:
                        spine.append(
                            _candidate_from_node(
                                workspace_id,
                                node,
                                score=policy.shortest_path_score,
                                reason="shortest-path flow spine",
                                confidence=policy.graph_neighbor_confidence,
                                context_role="spine",
                            )
                        )
    return _dedupe([*spine, *neighborhood]), flow, impact


def _apply_existing_snippet_budget(
    candidates: Sequence[CodeQueryCandidate],
    budget_tokens: int,
    limit: int,
    policy: CodeQueryPolicySettings | None = None,
) -> tuple[list[CodeQueryCandidate], bool]:
    """Apply one global budget to already-rendered multi-repository results."""
    policy = policy or load_runtime_settings().code_graph.query_policy
    remaining = max(
        policy.min_output_chars,
        budget_tokens * policy.estimated_chars_per_token,
    )
    selected: list[CodeQueryCandidate] = []
    required_identities = {
        _candidate_identity(candidate)
        for candidate in _required_evidence_candidates(candidates, policy)
    }
    clipped_required_source = False
    for original in candidates:
        if (
            len(selected) >= limit
            or remaining <= policy.merged_output_stop_reserve_chars
        ):
            break
        candidate = copy.deepcopy(original)
        metadata_cost = _candidate_metadata_chars(candidate, policy)
        if metadata_cost >= remaining and selected:
            break
        remaining -= min(metadata_cost, remaining)
        if candidate.snippet:
            if (
                len(candidate.snippet) > remaining
                and _candidate_identity(candidate) in required_identities
            ):
                clipped_required_source = True
            candidate.snippet = candidate.snippet[: max(0, remaining)] or None
            remaining -= len(candidate.snippet or "")
        selected.append(candidate)
    return selected, clipped_required_source or bool(
        _missing_evidence_candidates(candidates, selected, policy)
    )


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
    settings: CodeGraphSettings,
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
        settings.model_dump_json(),
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
            if graph_content_hash(path.read_bytes()) != expected:
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
    settings: CodeGraphSettings | None = None,
) -> CodeQueryResult:
    """Retrieve a minimal, freshness-aware context pack for one code task."""
    root = Path(root_path).expanduser().resolve()
    query_settings = settings or load_runtime_settings().code_graph
    policy = query_settings.query_policy
    capped_limit = max(1, min(limit, policy.max_candidates))
    capped_budget = max(
        policy.min_budget_tokens,
        min(budget_tokens, policy.max_budget_tokens),
    )
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
        settings=query_settings,
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
            limit=max(
                capped_limit * policy.candidates_per_file,
                policy.min_candidates,
            ),
        )
        best_graph_score = max((item.score for item in ranked), default=0.0)
        relevance_floor = max(
            1.0, best_graph_score * policy.graph_relevance_ratio
        )
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
            if not _relevant_match(graph_match, policy):
                continue
            if item.score < relevance_floor:
                continue
            relative_score = item.score / best_graph_score if best_graph_score else 0.0
            evidence_bonus = 0.0
            file_stem = Path(node.file_path).stem.casefold()
            symbol_leaf = node.name.casefold()
            qualified_symbol = node.qualified_name.casefold()
            if file_stem in graph_query_terms:
                evidence_bonus += policy.file_match_bonus
            if symbol_leaf in graph_query_terms:
                evidence_bonus += policy.symbol_match_bonus
            if "." in qualified_symbol and qualified_symbol in graph_query_terms:
                evidence_bonus += policy.qualified_match_bonus
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
                    score=item.score + evidence_bonus,
                    confidence=min(
                        policy.graph_confidence_cap,
                        policy.graph_confidence_base
                        + relative_score * policy.graph_confidence_rank_weight
                        + graph_match.weighted_coverage
                        * policy.graph_confidence_coverage_weight,
                    ),
                    provenance="graph",
                    match_reasons=list(item.match_reasons),
                    node_id=node.id,
                    workspace_id=workspace_id,
                )
            )

        # A broad flow question often names one file/domain and several stages,
        # while each function in that file matches only one stage. Expand the
        # exact file anchor structurally instead of weakening global relevance
        # and admitting one-term matches from the whole repository.
        anchored_paths = sorted(
            {
                item.node.file_path
                for item in ranked
                if len(Path(item.node.file_path).stem)
                >= policy.strong_identifier_chars
                and Path(item.node.file_path).stem.casefold() in graph_query_terms
                and item.node.file_path not in working.changed
                and item.node.file_path not in working.deleted
            }
        )
        if anchored_paths:
            existing_node_ids = {
                candidate.node_id
                for candidate in graph_candidates
                if candidate.node_id is not None
            }
            anchored_candidates: dict[
                str, list[tuple[CodeQueryCandidate, frozenset[str]]]
            ] = {path: [] for path in anchored_paths}
            anchor_nodes = list(
                (
                    await db.exec(
                        select(CodeNode)
                        .where(
                            CodeNode.workspace_id == workspace_id,
                            col(CodeNode.file_path).in_(anchored_paths),
                        )
                        .order_by(col(CodeNode.file_path), col(CodeNode.line_start))
                        .limit(
                            max(
                                policy.anchor_scan_min,
                                capped_limit * policy.anchor_scan_multiplier,
                            )
                        )
                    )
                ).all()
            )
            for node in anchor_nodes:
                if node.id in existing_node_ids or node.kind == "file":
                    continue
                if kinds and node.kind not in kinds:
                    continue
                if languages and node.language not in languages:
                    continue
                anchor_stem = Path(node.file_path).stem.casefold()
                stage_values = tuple(
                    value.casefold()
                    for value in (node.name, node.signature, node.docstring)
                    if value
                )
                stage_terms = frozenset(
                    term
                    for term in graph_query_terms
                    if term != anchor_stem
                    and any(term in value for value in stage_values)
                )
                if not stage_terms:
                    continue
                anchored_match = match_query(
                    query,
                    graph_query_terms,
                    (node.name, node.signature, node.docstring),
                )
                candidate = CodeQueryCandidate(
                    handle=_node_handle(workspace_id, node.id, node.qualified_name),
                    file_path=node.file_path,
                    line_start=node.line_start,
                    line_end=node.line_end,
                    symbol=node.qualified_name,
                    kind=node.kind,
                    language=node.language,
                    signature=node.signature,
                    score=policy.anchor_score_base + anchored_match.score,
                    confidence=min(
                        policy.anchor_confidence_cap,
                        policy.anchor_confidence_base
                        + anchored_match.weighted_coverage
                        * policy.anchor_confidence_coverage_weight,
                    ),
                    provenance="graph",
                    match_reasons=[
                        "query-named file anchor",
                        f"{len(stage_terms)} distinct stage term(s) in symbol",
                    ],
                    node_id=node.id,
                    workspace_id=workspace_id,
                )
                graph_candidates.append(candidate)
                anchored_candidates[node.file_path].append((candidate, stage_terms))
                existing_node_ids.add(node.id)

            # Promote a compact set that covers distinct named stages. This
            # keeps lifecycle evidence structural without making every match
            # in a large anchor file mandatory source evidence.
            executable_kinds = {"function", "method", "class"}
            for records in anchored_candidates.values():
                uncovered = set().union(*(terms for _, terms in records))
                records.sort(
                    key=lambda record: (
                        -len(record[1]),
                        record[0].kind not in executable_kinds,
                        record[0].line_end - record[0].line_start,
                        -record[0].score,
                    )
                )
                promoted = 0
                for candidate, stage_terms in records:
                    newly_covered = stage_terms & uncovered
                    if not newly_covered:
                        continue
                    candidate.context_role = "spine"
                    uncovered.difference_update(newly_covered)
                    promoted += 1
                    if promoted >= policy.max_promoted_stages or not uncovered:
                        break

    relevant_dirty = sorted(
        path for path in working.changed if _path_in_scope(path, paths)
    )
    needs_lexical = (
        not graph_candidates or best_graph_score < policy.lexical_fallback_score
    )
    if freshness_policy == "strict":
        needs_lexical = True
    if needs_lexical:
        lexical_hits, extension_counts = await _lexical_search(
            root,
            query,
            paths,
            max(
                capped_limit * policy.candidates_per_file,
                policy.min_candidates,
            ),
            policy,
        )
    elif len(relevant_dirty) > query_settings.query_large_change_files:
        lexical_hits, _dirty_counts = await _lexical_search(
            root,
            query,
            relevant_dirty,
            max(
                capped_limit * policy.candidates_per_file,
                policy.min_candidates,
            ),
            policy,
        )
        extension_counts = _indexed_extension_counts(
            [state for state in states if _path_in_scope(state.file_path, paths)]
        )
    else:
        lexical_hits = []
        extension_counts = _indexed_extension_counts(
            [state for state in states if _path_in_scope(state.file_path, paths)]
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
        max(capped_limit * 2, policy.min_candidates),
        languages,
        kinds,
        policy,
    )

    lexical_candidates = [
        CodeQueryCandidate(
            handle=_source_handle(hit.file_path, hit.line),
            file_path=hit.file_path,
            line_start=max(1, hit.line - policy.lexical_context_before_lines),
            line_end=hit.line + policy.lexical_context_after_lines,
            score=hit.score,
            confidence=min(
                policy.lexical_confidence_cap,
                policy.lexical_confidence_base
                + hit.score / policy.lexical_confidence_divisor,
            ),
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
        lsp_candidates = await _try_lsp(root, query, lexical_hits, intent, policy)
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
    flow: list[CodeQueryFlowHop] = []
    blast_radius: list[CodeQueryImpact] = []
    if workspace_id is not None and graph_candidates and intent != "locate":
        spine, flow, blast_radius = await _expand_graph_context(
            db,
            workspace_id=workspace_id,
            query=query,
            roots=graph_candidates,
            policy=policy,
        )
        combined = _dedupe([*spine, *combined])
    primary = combined[: max(capped_limit * 2, policy.min_candidates)]

    for candidate in primary:
        if intent == "locate":
            candidate.callers.clear()
            candidate.callees.clear()
            candidate.tests.clear()

    if workspace_id is not None and intent != "locate":
        for candidate in primary[
            : min(policy.max_enriched_candidates, capped_limit)
        ]:
            if candidate.node_id is None or candidate.workspace_id is None:
                continue
            directed_neighbors: list[tuple[Literal["in", "out"], str, CodeNode]] = []
            if intent != "impact":
                outgoing = await graph_svc.get_neighbors(
                    db,
                    workspace_id=candidate.workspace_id,
                    node_id=candidate.node_id,
                    direction="out",
                )
                directed_neighbors.extend(
                    ("out", edge_kind, neighbor)
                    for edge_kind, neighbor in outgoing
                )
            incoming = await graph_svc.get_neighbors(
                db,
                workspace_id=candidate.workspace_id,
                node_id=candidate.node_id,
                direction="in",
            )
            directed_neighbors.extend(
                ("in", edge_kind, neighbor) for edge_kind, neighbor in incoming
            )
            for edge_direction, edge_kind, neighbor in directed_neighbors[
                : policy.max_relationships_per_candidate
            ]:
                location = (
                    f"{edge_kind} {neighbor.qualified_name} — "
                    f"{neighbor.file_path}:{neighbor.line_start}"
                )
                if neighbor.file_path in working.changed:
                    location += " [pending freshness]"
                    pending_edges += 1
                relationships = (
                    candidate.callers if edge_direction == "in" else candidate.callees
                )
                relationships.append(location)
    if intent != "locate":
        for candidate in primary:
            candidate.callers[:] = candidate.callers[
                : policy.max_relationships_per_kind
            ]
            candidate.callees[:] = candidate.callees[
                : policy.max_relationships_per_kind
            ]
            candidate.tests[:] = candidate.tests[: policy.max_relationships_per_kind]

    if relevant_dirty and intent in {"impact", "trace", "change"}:
        pending_edges = max(pending_edges, len(relevant_dirty))
        limitations.append(
            "Live dirty-file relationships are locally parsed, but cross-file edge resolution remains partial until reindex."
        )

    selected, truncated = _apply_budget(
        root, primary, capped_budget, capped_limit, query, policy
    )
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
        confidence = min(confidence, policy.partial_confidence_cap)
    next_ranges = [
        f"{candidate.file_path}:{candidate.line_start}-{candidate.line_end}"
        for candidate in _missing_evidence_candidates(primary, selected, policy)
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
        flow=flow,
        blast_radius=blast_radius,
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
        settings=query_settings,
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
    settings: CodeGraphSettings | None = None,
) -> CodeQueryResult:
    """Query linked repositories without flushing or extra model calls."""
    query_settings = settings or load_runtime_settings().code_graph
    policy = query_settings.query_policy
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
            settings=query_settings,
        )
    per_workspace_budget = max(
        policy.min_budget_tokens,
        min(policy.max_budget_tokens, budget_tokens),
    )
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
            limit=max(
                1,
                min(
                    policy.max_candidates,
                    (limit + len(unique) - 1) // len(unique) * 2,
                ),
            ),
            enable_lsp=enable_lsp and index == 0,
            settings=query_settings,
        )
        collected.append((label, value))

    combined_candidates = sorted(
        (
            replace(
                candidate,
                repository=label,
                score=candidate.score
                + (policy.cross_repo_primary_bonus if index == 0 else 0.0),
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
                    .limit(policy.max_cross_repo_edges)
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

    all_combined_candidates = combined_candidates
    combined_candidates, globally_truncated = _apply_existing_snippet_budget(
        all_combined_candidates,
        max(
            policy.min_budget_tokens,
            min(budget_tokens, policy.max_budget_tokens),
        ),
        max(1, min(limit, policy.max_candidates)),
        policy,
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
        flow=[hop for _label, value in collected for hop in value.flow],
        blast_radius=[
            impact for _label, value in collected for impact in value.blast_radius
        ],
        limitations=list(dict.fromkeys(limitations)),
        next_read_ranges=[
            f"{candidate.repository}/{candidate.file_path}:"
            f"{candidate.line_start}-{candidate.line_end}"
            for candidate in _missing_evidence_candidates(
                all_combined_candidates,
                combined_candidates,
                policy,
            )
        ],
        truncated=globally_truncated
        or any(value.truncated for _label, value in collected),
        cache_hit=all(value.cache_hit for _label, value in collected),
    )


async def get_capabilities(
    db: AsyncSession, *, root_path: str, workspace_id: UUID | None
) -> list[LanguageCapability]:
    states = await _states(db, workspace_id)
    counts = _indexed_extension_counts(states)
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
