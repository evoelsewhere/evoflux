"""Model-facing source discovery over the internal code index."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from app.agent.sandbox import get_sandbox
from app.agent.tools.registry import Tool
from app.core.db import async_session_factory
from app.services import code_graph_service as graph_service
from app.services.code_intelligence.models import WorkspaceScope
from app.services.codeindex.query import CodeIndexResult, search_code_index

_INLINE_CHAR_LIMIT = 38_000


def _render_code_search(result: CodeIndexResult) -> str:
    sections = [
        "Indexed code search\n"
        f"query: {result.query}\n"
        f"strategy: {result.strategy}\n"
        f"freshness: {result.freshness}\n"
        f"index version: {result.graph_version or 'unavailable'}\n"
        f"dirty files: {result.dirty_files}\n"
        f"matches: {len(result.matches)}"
    ]
    used = len(sections[0])
    output_truncated = False
    for match in result.matches:
        chunk = match.chunk
        reasons = ", ".join(match.match_reasons) or "fts-rank"
        section = (
            f"## {match.scope.label}/{chunk.file_path}:"
            f"{chunk.line_start}-{chunk.line_end}\n"
            f"- {chunk.qualified_name} ({chunk.kind}, {chunk.language})\n"
            f"- score: {match.score:.4f}; matched by: {reasons}\n"
            f"```text\n{chunk.content}\n```"
        )
        if used + len(section) + 2 > _INLINE_CHAR_LIMIT:
            output_truncated = True
            break
        sections.append(section)
        used += len(section) + 2
    if result.limitations:
        sections.append(
            "Limitations:\n" + "\n".join(f"- {item}" for item in result.limitations)
        )
    if result.truncated or output_truncated:
        sections.append(
            "Output truncated. Narrow repository, path, language, or query terms."
        )
    return "\n\n".join(sections)


async def _code_search(
    query: Annotated[
        str,
        Field(
            min_length=2,
            max_length=2_000,
            description=(
                "Behavior, concept, identifier fragments, error text, or code terms "
                "to locate. Use code_graph directly when the exact declared symbol "
                "is already known."
            ),
        ),
    ],
    repository: Annotated[
        str | None,
        Field(description="Optional authorized repository label to restrict search."),
    ] = None,
    path: Annotated[
        str | None,
        Field(description="Optional repository-relative path fragment."),
    ] = None,
    language: Annotated[
        str | None,
        Field(description="Optional exact indexed language name, such as python."),
    ] = None,
    freshness_policy: Annotated[
        Literal["fast", "balanced", "strict"],
        Field(
            description=(
                "Use fast for initial discovery. Use balanced once after relevant "
                "edits or when dirty files overlap the question. Use strict only "
                "for a final high-consequence completeness check when watcher "
                "coverage is unavailable or untrusted."
            )
        ),
    ] = "fast",
    limit: Annotated[
        int,
        Field(ge=1, le=50, description="Maximum merged cross-repository matches."),
    ] = 10,
) -> str:
    """Find source ranges before exact structural graph navigation."""
    sandbox = get_sandbox()
    raw_roots = [
        str(sandbox.workspace_root),
        *getattr(sandbox, "extra_workspace_paths", []),
    ]
    roots = tuple(
        dict.fromkeys(
            Path(value).expanduser().resolve()
            for value in raw_roots
            if Path(value).expanduser().is_dir()
        )
    )
    async with async_session_factory() as db:
        scopes: list[WorkspaceScope] = []
        for root in roots:
            workspace_id = await graph_service.resolve_workspace_id(db, path=str(root))
            if workspace_id is None:
                continue
            scopes.append(
                WorkspaceScope(
                    root=root,
                    workspace_id=workspace_id,
                    label=root.name or str(root),
                )
            )
        result = await search_code_index(
            db,
            scopes=tuple(scopes),
            query=query,
            repository=repository,
            path=path,
            language=language,
            freshness_policy=freshness_policy,
            limit=limit,
        )
    return _render_code_search(result)


code_search = Tool(
    _code_search,
    name="code_search",
    description=(
        "Local parser-aligned source discovery across every authorized repository. "
        "Use it when the implementation location or exact identifier is unknown; "
        "it searches bounded source chunks and returns repository-qualified ranges. "
        "After discovering a declared identifier, use code_graph for exact callers, "
        "callees, references, and impact."
    ),
    concurrency_safe=True,
    read_only=True,
    tiers=("coding",),
    observation_kind="retrieval",
    deferred=True,
    capabilities=("code_source_search",),
    deduplicate_in_batch=True,
)

__all__ = ["code_search"]
