"""The model-facing native symbol graph tool."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from app.agent.code_graph_observation import (
    CodeGraphObservation,
    publish_code_graph_observation,
)
from app.agent.sandbox import get_sandbox
from app.agent.tools.registry import Tool
from app.core.db import async_session_factory
from app.services import code_graph_service as graph_service

_INLINE_CHAR_LIMIT = 38_000


def _render_code_graph(result) -> str:  # noqa: ANN001
    """Render exact definitions and graph relationships below offload size."""
    sections = [
        "Native code graph\n"
        f"symbol: {result.symbol}\n"
        f"operation: {result.operation}\n"
        f"strategy: {result.strategy}\n"
        f"freshness: {result.freshness}\n"
        f"matches: {len(result.matches)}\n"
        f"relationships: {len(result.relations)}\n"
        f"dirty files: {result.dirty_files}\n"
        f"pending cross-repo edges: {result.pending_edges}"
    ]
    length = len(sections[0])
    output_truncated = False

    def append(section: str) -> bool:
        nonlocal length, output_truncated
        required = len(section) + 2
        if length + required > _INLINE_CHAR_LIMIT:
            output_truncated = True
            return False
        sections.append(section)
        length += required
        return True

    if result.matches:
        append("Definitions")
    for match in result.matches:
        node = match.node
        location = f"{match.scope.label}/{node.file_path}:{node.line_start}"
        lines = [
            f"## {location}",
            f"- {node.qualified_name} ({node.kind}, {node.language}; {match.resolution})",
        ]
        if match.source:
            lines.append(f"```text\n{match.source}\n```")
        else:
            lines.append(
                f"source range: {match.scope.label}/{node.file_path}:"
                f"{node.line_start}-{node.line_end}"
            )
        if not append("\n".join(lines)):
            break

    if result.relations:
        append("Relationships")
    for relation in result.relations:
        source = relation.source
        target = relation.target
        cross = " cross-repo" if relation.cross_repo else ""
        section = (
            f"- [depth {relation.depth}{cross}] {relation.kind}: "
            f"{source.node.qualified_name} "
            f"[{source.scope.label}/{source.node.file_path}:{source.node.line_start}] "
            f"-> {target.node.qualified_name} "
            f"[{target.scope.label}/{target.node.file_path}:{target.node.line_start}]\n"
            f"  callsite: {source.scope.label}/{relation.callsite_file}:"
            f"{relation.callsite_line}"
        )
        if relation.callsite_source:
            section += f"\n```text\n{relation.callsite_source}\n```"
        if not append(section):
            break

    if result.suggestions:
        lines = ["Exact symbol not found. Prefix suggestions (not traversed):"]
        lines.extend(
            f"- {item.node.qualified_name} — "
            f"{item.scope.label}/{item.node.file_path}:{item.node.line_start}"
            for item in result.suggestions
        )
        append("\n".join(lines))
    if result.limitations:
        append("Limitations:\n" + "\n".join(f"- {item}" for item in result.limitations))
    if result.truncated or output_truncated:
        append(
            "Output truncated. Narrow with path/repository, reduce depth, or query "
            "a returned neighbor symbol."
        )
    return "\n\n".join(sections)


async def _code_graph(
    symbol: Annotated[
        str,
        Field(
            min_length=1,
            max_length=512,
            pattern=r"^\S+$",
            description=(
                "One raw symbol identifier or qualified symbol, for example "
                "calculate_total or ClassName.method. Derive it only from an "
                "identifier present in source. Never pass, translate, or summarize "
                "the user's natural-language request into this field."
            ),
        ),
    ],
    operation: Annotated[
        Literal[
            "definition",
            "callers",
            "callees",
            "references",
            "impact",
            "neighborhood",
        ],
        Field(
            description=(
                "Structural direction to navigate: definition only; direct or "
                "transitive callers/callees; all inbound references; inbound impact; "
                "or a bidirectional neighborhood."
            )
        ),
    ] = "definition",
    path: Annotated[
        str | None,
        Field(
            description=(
                "Optional repository-relative path fragment used only to disambiguate "
                "same-named symbols."
            )
        ),
    ] = None,
    repository: Annotated[
        str | None,
        Field(
            description=(
                "Optional linked repository label used only to disambiguate a symbol."
            )
        ),
    ] = None,
    freshness_policy: Annotated[
        Literal["fast", "balanced", "strict"],
        Field(
            description=(
                "Index freshness policy. Use fast for the first interactive query; "
                "use balanced once when dirty files overlap the question or current "
                "post-edit relationships are required; use strict only for a final "
                "high-consequence completeness check when watcher coverage is "
                "unavailable or untrusted."
            )
        ),
    ] = "fast",
    depth: Annotated[
        int,
        Field(
            ge=1,
            le=3,
            description="Relationship depth. Leave at 1 unless transitive impact is required.",
        ),
    ] = 1,
    limit: Annotated[
        int,
        Field(ge=1, le=100, description="Maximum resolved relationships to return."),
    ] = 40,
) -> str:
    """Resolve one symbol and navigate its native structural graph."""
    from app.services.code_graph_navigation_service import (
        navigate_code_graph_across_workspaces,
    )

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
        result = await navigate_code_graph_across_workspaces(
            db,
            workspaces=workspaces,
            symbol=symbol,
            operation=operation,
            path=path,
            repository=repository,
            depth=depth,
            limit=limit,
            # Keep the latency-sensitive path as the default while allowing a
            # skill to request explicit freshness at a justified proof gate.
            freshness_policy=freshness_policy,
        )

    rendered = _render_code_graph(result)
    publish_code_graph_observation(
        CodeGraphObservation(
            strategy=result.strategy,
            freshness=result.freshness,
            result_tokens=(len(rendered.encode("utf-8")) + 3) // 4,
        )
    )
    return rendered


code_graph = Tool(
    _code_graph,
    name="code_graph",
    description=(
        "Native structural navigator for a known code symbol, not a search engine. "
        "Given one exact identifier, returns its "
        "definition and requested callers, callees, references, impact, or graph "
        "neighborhood across authorized repositories with exact call-site lines. "
        "If multiple definitions match, disambiguate before traversal. This tool "
        "does not search natural-language requests."
    ),
    concurrency_safe=True,
    read_only=True,
    tiers=("coding",),
    observation_kind="structural",
    deferred=False,
    capabilities=("code_graph_navigation",),
    deduplicate_in_batch=True,
)
