"""The single model-facing code exploration tool.

The model supplies a question and an output file budget. Retrieval policy,
freshness checks, graph expansion, and source fallback stay behind this stable
function contract.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated
from uuid import UUID

from pydantic import Field

from app.agent.code_query_observation import (
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


def _render_code_query(result, *, max_files: int = 6) -> str:  # noqa: ANN001
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
        sections.append(
            "Source not included: " + ", ".join(result.next_read_ranges)
        )
    if result.truncated:
        sections.append(
            "Output reached its budget. Query a named symbol or file for more source."
        )
    return "\n\n".join(sections)


def _source_token_count(
    selected_files: list[tuple[tuple[str | None, str], list[object]]],
    workspaces: list[tuple[str, UUID | None, str]],
) -> int:
    roots_by_repository = {
        label: Path(root) for root, _workspace_id, label in workspaces
    }
    total = 0
    for (repository, file_path), _candidates in selected_files:
        root = roots_by_repository.get(repository)
        if root is None and len(workspaces) == 1:
            root = Path(workspaces[0][0])
        if root is None:
            continue
        try:
            total += ((root / file_path).stat().st_size + 3) // 4
        except OSError:
            continue
    return total


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
    max_files: Annotated[
        int,
        Field(
            ge=1,
            le=12,
            description="Maximum source files to include. Usually leave at 6.",
        ),
    ] = 6,
) -> str:
    """Explore code and return current source plus structural relationships.

    Included line-numbered source is equivalent to reading those ranges. The
    tool automatically checks dirty files and uses bounded source fallback when
    a language or recent change is not represented by the graph.
    """
    from app.services.code_query_service import query_code_across_workspaces

    sandbox = get_sandbox()
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
            budget_tokens=min(12_000, max(2_500, max_files * 900)),
            limit=min(30, max_files * 3),
        )

    selected = _selected_files(result, max_files)
    rendered = _render_code_query(result, max_files=max_files)
    publish_code_query_observation(
        CodeQueryObservation(
            strategy=result.strategy,
            freshness=result.freshness,
            cache_hit=result.cache_hit,
            file_reads=len(selected),
            source_tokens=_source_token_count(selected, workspaces),
            result_tokens=(len(rendered.encode("utf-8")) + 3) // 4,
        )
    )
    return rendered


code_query = Tool(
    _code_query,
    name="code_query",
    description=(
        "Primary code explorer. Pass a natural-language question or symbol/file "
        "names. One call returns current line-numbered source grouped by file, "
        "relevant relationships and change impact, with explicit fallback when "
        "the graph cannot cover a language or recent edits."
    ),
    concurrency_safe=True,
    read_only=True,
    tiers=("coding", "aim"),
    deferred=False,
    capabilities=("code_navigation",),
    max_calls_per_batch=2,
    deduplicate_in_batch=True,
)
