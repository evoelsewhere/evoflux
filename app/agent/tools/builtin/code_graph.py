"""The single model-facing code exploration tool.

The model supplies a question and an output file budget. Retrieval policy,
freshness checks, graph expansion, and source fallback stay behind this stable
function contract.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from app.agent.code_query_observation import (
    CODE_QUERY_DEFAULT_MAX_FILES,
    CodeQueryObservation,
    publish_code_query_observation,
)
from app.agent.sandbox import get_sandbox
from app.agent.tools.registry import Tool
from app.core.db import async_session_factory
from app.services import code_graph_service as graph_service


def _selected_files(result, max_files: int):  # noqa: ANN001
    grouped: dict[tuple[str | None, str], list[object]] = {}
    for candidate in result.results:
        key = (candidate.repository, candidate.file_path)
        if key not in grouped and len(grouped) >= max_files:
            continue
        grouped.setdefault(key, []).append(candidate)
    return list(grouped.items())


def _render_code_query(
    result, *, max_files: int = CODE_QUERY_DEFAULT_MAX_FILES
) -> str:  # noqa: ANN001
    """Render current source grouped by file with structural evidence attached."""
    sections = [
        "Code exploration\n"
        f"strategy: {result.strategy}\n"
        f"freshness: {result.freshness}\n"
        f"coverage: {result.coverage:.0%}\n"
        f"confidence: {result.confidence:.2f}\n"
        f"dirty files: {result.dirty_files}\n"
        f"pending edges: {result.pending_edges}"
    ]
    if result.flow:
        sections.append(
            "Flow\n"
            + "\n".join(
                f"- {hop.source} [{hop.source_location}] --{hop.relation}--> "
                f"{hop.target} [{hop.target_location}]"
                for hop in result.flow
            )
        )
    if result.blast_radius:
        lines = ["Blast radius"]
        for impact in result.blast_radius:
            lines.append(f"- {impact.root}")
            if impact.references:
                lines.extend(f"  - {reference}" for reference in impact.references)
            else:
                lines.append("  - no indexed inbound references")
            if impact.truncated:
                lines.append("  - additional references omitted")
        sections.append("\n".join(lines))
    for (repository, file_path), candidates in _selected_files(result, max_files):
        display_path = f"{repository}/{file_path}" if repository else file_path
        lines = [f"## {display_path}"]
        for candidate in candidates:
            label = candidate.symbol or "source match"
            metadata = [candidate.provenance]
            if candidate.kind:
                metadata.append(candidate.kind)
            if candidate.language:
                metadata.append(candidate.language)
            lines.append(
                f"- {label} ({', '.join(metadata)}) "
                f"lines {candidate.line_start}-{candidate.line_end}"
            )
            if candidate.signature:
                lines.append(f"  signature: {candidate.signature}")
            if candidate.callers:
                lines.append("  inbound:\n    " + "\n    ".join(candidate.callers[:8]))
            if candidate.callees:
                lines.append("  outbound:\n    " + "\n    ".join(candidate.callees[:8]))
            if candidate.tests:
                lines.append("  tests: " + ", ".join(candidate.tests[:8]))
            if candidate.snippet:
                lines.append(f"```text\n{candidate.snippet}\n```")
        sections.append("\n".join(lines))
    if not result.results:
        sections.append("No indexed or current-source candidates matched the query.")
    if result.limitations:
        sections.append(
            "Limitations:\n" + "\n".join(f"- {item}" for item in result.limitations)
        )
    if result.next_read_ranges:
        sections.append("Source not included: " + ", ".join(result.next_read_ranges))
    if result.truncated:
        sections.append(
            "Output reached its budget. Query a named symbol or file for more source."
        )
    return "\n\n".join(sections)


async def _code_query(
    query: Annotated[
        str,
        Field(
            min_length=1,
            description=(
                "Natural-language code question or related symbol/file names."
            ),
        ),
    ],
    operation: Annotated[
        Literal["locate", "explain", "impact", "trace", "change"],
        Field(
            description=(
                "Structural operation to perform: locate definitions, explain "
                "implementation, inspect inbound impact, trace a flow, or analyze "
                "working-tree changes."
            )
        ),
    ] = "explain",
    max_files: Annotated[
        int,
        Field(
            ge=1,
            le=CODE_QUERY_DEFAULT_MAX_FILES,
            description=(
                "Maximum source files to include. Usually leave at the default."
            ),
        ),
    ] = CODE_QUERY_DEFAULT_MAX_FILES,
) -> str:
    """Explore code and return current source plus structural relationships.

    Included line-numbered source is equivalent to reading those ranges. The
    tool automatically checks dirty files and uses bounded source fallback when
    a language or recent change is not represented by the graph.
    """
    from app.services.code_query_service import query_code_across_workspaces
    from app.core.runtime_settings import load_runtime_settings

    sandbox = get_sandbox()
    query_settings = load_runtime_settings().code_graph
    policy = query_settings.query_policy
    roots = [
        str(sandbox.workspace_root),
        *getattr(sandbox, "extra_workspace_paths", []),
    ]
    workspaces: list[tuple[str, UUID | None, str]] = []
    async with async_session_factory() as db:
        for root in dict.fromkeys(str(Path(value).resolve()) for value in roots):
            if not Path(root).is_dir():
                continue
            workspaces.append(
                (
                    root,
                    await graph_service.resolve_workspace_id(db, path=root),
                    Path(root).name or root,
                )
            )
        result = await query_code_across_workspaces(
            db,
            workspaces=workspaces,
            query=query,
            intent=operation,
            budget_tokens=min(
                policy.max_budget_tokens,
                max(
                    policy.tool_min_budget_tokens,
                    max_files * policy.tokens_per_file,
                ),
            ),
            limit=min(
                policy.max_candidates,
                max_files * policy.candidates_per_file,
            ),
            enable_lsp=True,
            settings=query_settings,
        )

    rendered = _render_code_query(result, max_files=max_files)
    publish_code_query_observation(
        CodeQueryObservation(
            strategy=result.strategy,
            freshness=result.freshness,
            cache_hit=result.cache_hit,
            result_tokens=(len(rendered.encode("utf-8")) + 3) // 4,
        )
    )
    return rendered


code_query = Tool(
    _code_query,
    name="code_query",
    description=(
        "Primary code explorer. Pass a natural-language question or symbol/file "
        "names and select the structural operation. Each call returns current "
        "line-numbered source grouped by file, relevant relationships and change "
        "impact, with explicit fallback when the graph cannot cover a language "
        "or recent edits."
    ),
    concurrency_safe=True,
    read_only=True,
    tiers=("coding", "aim"),
    deferred=False,
    capabilities=("code_navigation", "code_graph_navigation"),
    deduplicate_in_batch=True,
)
