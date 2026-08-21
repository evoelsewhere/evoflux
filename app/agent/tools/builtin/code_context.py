"""Unified source discovery and graph navigation tool."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BeforeValidator, Field

from app.agent.code_context_observation import (
    CodeContextObservation,
    publish_code_context_observation,
)
from app.agent.sandbox import get_sandbox
from app.agent.tools.registry import Tool
from app.services.code_index.models import CodeContextResult, RepositoryScope
from app.services.code_index.service import query_code_context

_INLINE_CHAR_LIMIT = 20_000
_TRUNCATION_NOTICE = (
    "Output truncated. Narrow repository/path/language, reduce depth, or "
    "query a returned symbol."
)


def _coerce_string_list(value: Any) -> Any:
    """Recover list filters that a model emitted as one encoded string."""
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped:
        return None
    try:
        decoded = json.loads(stripped)
    except (TypeError, ValueError):
        return [stripped]
    if isinstance(decoded, list):
        return decoded
    if isinstance(decoded, str) and decoded.strip():
        return [decoded.strip()]
    return value


def _render_code_context(result: CodeContextResult) -> str:
    stats = ", ".join(
        f"{label}={value.files} files/{value.symbols} symbols/{value.relations} relations"
        for label, value in result.stats.items()
    )
    header = (
        "Code context\n"
        f"action: {result.action}\n"
        f"query: {result.query}\n"
        f"strategy: {result.strategy}\n"
        f"index version: {result.index_version or 'unavailable'}\n"
        f"repositories: {', '.join(result.repositories) or 'none'}\n"
        f"index stats: {stats or 'unavailable'}"
    )
    content_limit = _INLINE_CHAR_LIMIT - len(_TRUNCATION_NOTICE) - 2
    output_truncated = len(header) > content_limit
    if output_truncated:
        suffix = "\n… [metadata truncated]"
        header = header[: content_limit - len(suffix)].rstrip() + suffix
    sections = [header]
    used = len(header)

    def append(section: str, *, clip: bool = False) -> bool:
        nonlocal used, output_truncated
        remaining = content_limit - used - 2
        if len(section) <= remaining:
            sections.append(section)
            used += len(section) + 2
            return True
        output_truncated = True
        if clip and remaining > 80:
            suffix = "\n… [section truncated]"
            prefix = section[: max(1, remaining - len(suffix))].rstrip()
            if prefix.count("```") % 2:
                suffix += "\n```"
                prefix = section[: max(1, remaining - len(suffix))].rstrip()
            clipped = prefix + suffix
            sections.append(clipped)
            used += len(clipped) + 2
        return False

    if result.hits:
        append("Matches")
    for hit in result.hits:
        symbol = f"\n- symbol: {hit.symbol}" if hit.symbol else ""
        if not append(
            f"## {hit.repository}/{hit.file_path}:{hit.line_start}-{hit.line_end}"
            f"{symbol}\n- language: {hit.language}; score: {hit.score:.4f}\n"
            f"```text\n{hit.content}\n```",
            clip=True,
        ):
            break

    if result.matches:
        append("Definitions")
    for match in result.matches:
        body = (
            f"## {match.repository}/{match.file_path}:{match.line_start}\n"
            f"- {match.qualified_name} ({match.kind}, {match.language})"
        )
        if match.source:
            body += f"\n```text\n{match.source}\n```"
        else:
            body += f"\nsource range: {match.line_start}-{match.line_end}"
        if not append(body, clip=True):
            break

    if result.relations:
        append("Relationships")
    for relation in result.relations:
        cross = " cross-repo" if relation.cross_repo else ""
        body = (
            f"- [depth {relation.depth}{cross}] {relation.kind}: "
            f"{relation.source.qualified_name} "
            f"[{relation.source.repository}/{relation.source.file_path}:"
            f"{relation.source.line_start}] -> {relation.target.qualified_name} "
            f"[{relation.target.repository}/{relation.target.file_path}:"
            f"{relation.target.line_start}]\n"
            f"  callsite: {relation.source.repository}/{relation.callsite_file}:"
            f"{relation.callsite_line}"
        )
        if relation.callsite_source:
            body += f"\n```text\n{relation.callsite_source}\n```"
        if not append(body, clip=True):
            break

    if result.suggestions:
        suggestion_heading = (
            "Unresolved relationship candidates (not traversed):"
            if result.matches
            else "Exact symbol not found. Suggestions (not traversed):"
        )
        append(
            suggestion_heading
            + "\n"
            + "\n".join(
                f"- {item.qualified_name} — "
                f"{item.repository}/{item.file_path}:{item.line_start}"
                for item in result.suggestions
            ),
            clip=True,
        )
    if result.limitations:
        append(
            "Limitations:\n" + "\n".join(f"- {item}" for item in result.limitations),
            clip=True,
        )
    if result.truncated or output_truncated:
        sections.append(_TRUNCATION_NOTICE)
    return "\n\n".join(sections)


async def _code_context(
    action: Annotated[
        Literal[
            "search",
            "grep",
            "definition",
            "callers",
            "callees",
            "references",
            "impact",
            "neighborhood",
        ],
        Field(
            description=(
                "Use search for natural-language or fuzzy discovery; grep for a "
                "by-example structural pattern; otherwise choose one exact-symbol "
                "graph direction."
            )
        ),
    ],
    query: Annotated[
        str,
        Field(
            min_length=1,
            max_length=2_000,
            description=(
                "Natural-language/code text for search, a by-example structural "
                "pattern for grep, or one whitespace-free exact symbol for graph "
                "actions."
            ),
        ),
    ],
    repository: Annotated[
        str | None,
        Field(
            description=(
                "Optional authorized repository label or absolute root path. A dot "
                "selects the primary workspace. Omit to search every authorized "
                "repository. For multi-repository discovery, do not default to the "
                "primary: omit this until user input or returned evidence identifies "
                "the owner. For graph actions it disambiguates only the root symbol."
            )
        ),
    ] = None,
    paths: Annotated[
        list[str] | None,
        BeforeValidator(_coerce_string_list),
        Field(
            description=(
                "Optional native JSON array of repository-relative globs or path "
                "fragments. One path string is also accepted. For graph actions "
                "these filters disambiguate same-named definitions."
            )
        ),
    ] = None,
    languages: Annotated[
        list[str] | None,
        BeforeValidator(_coerce_string_list),
        Field(
            description=(
                "Optional native JSON array of language filters for search or grep; "
                "one language string is also accepted. Omit during unknown-root "
                "discovery; a guessed language can hide the owning repository."
            )
        ),
    ] = None,
    depth: Annotated[
        int,
        Field(
            ge=1, le=3, description="Graph depth; keep 1 unless impact is transitive."
        ),
    ] = 1,
    limit: Annotated[
        int,
        Field(ge=1, le=50, description="Maximum merged matches or relationships."),
    ] = 10,
    refresh: Annotated[
        bool,
        Field(
            description=(
                "Run incremental desired-state catch-up before the action. Leave true "
                "after edits; set false only for immediate follow-up queries against "
                "the same committed index version."
            )
        ),
    ] = True,
) -> str:
    sandbox = get_sandbox()
    roots = [
        Path(sandbox.workspace_root).expanduser().resolve(),
        *(
            Path(value).expanduser().resolve()
            for value in getattr(sandbox, "extra_workspace_paths", [])
        ),
    ]
    scopes = tuple(
        RepositoryScope(root=root, label=root.name or str(root))
        for root in dict.fromkeys(roots)
        if root.is_dir()
    )
    result = await query_code_context(
        scopes=scopes,
        action=action,
        query=query,
        repository=repository,
        paths=paths,
        languages=languages,
        depth=depth,
        limit=limit,
        refresh=refresh,
    )
    rendered = _render_code_context(result)
    publish_code_context_observation(
        CodeContextObservation(
            strategy=result.strategy,
            freshness="refreshed" if refresh else "cached",
            result_tokens=(len(rendered.encode("utf-8")) + 3) // 4,
        )
    )
    return rendered


code_context = Tool(
    _code_context,
    name="code_context",
    description=(
        "Self-contained code retrieval across every authorized repository. The "
        "native desired-state code index incrementally refreshes AST-aware "
        "source chunks, performs natural-language "
        "discovery or structural pattern matching, and navigates exact definitions, "
        "callers, callees, references, impact, and neighborhoods through one bounded "
        "interface. Cross-repository links are resolved from the current authorized "
        "snapshot rather than a stale central edge table."
    ),
    concurrency_safe=True,
    read_only=True,
    tiers=("coding",),
    observation_kind="retrieval",
    deferred=False,
    capabilities=("code_context", "code_source_search", "code_context_navigation"),
    deduplicate_in_batch=True,
)


__all__ = ["code_context"]
