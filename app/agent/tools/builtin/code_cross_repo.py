"""Cross-repo code search — the first caller of ``search_across_workspaces``.

``code_search`` (see ``code_graph.py``) is scoped to the single active
workspace; in a multi-repo CodingProject session that's only the primary
repo. This tool fans the same lexical/structural search out across every repo
in the project, using the paths ``MultiRepoContextHook`` already injects into
the sandbox context (``SandboxConfig.extra_workspace_paths``) — no
model-facing workspace-path argument, consistent with every other code_graph
tool's ambient-workspace convention.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from app.agent.sandbox import get_sandbox
from app.agent.tools.registry import Tool
from app.core.db import async_session_factory
from app.models.code_graph import CodeNode
from app.services import code_graph_service as svc

_NO_SIBLING_REPOS = (
    "This session isn't part of a multi-repo project (or the project has "
    "only one repo) — there are no sibling repos to search. Use code_search "
    "for the active workspace instead."
)


def _repo_label(path: str) -> str:
    return Path(path).name or path


def _loc(node: CodeNode) -> str:
    return f"{node.file_path}:{node.line_start}-{node.line_end}"


async def _code_cross_repo_search(
    query: Annotated[str, Field(description="Symbol name or fragment to search for.")],
    kind: Annotated[
        Literal["file", "class", "function", "method", "interface"] | None,
        Field(description="Restrict results to a single symbol kind."),
    ] = None,
    limit_per_repo: Annotated[
        int, Field(description="Maximum number of symbols to return per repo (max 20).")
    ] = 10,
) -> str:
    """Search for a symbol across every repo in the current project.

    Unlike ``code_search`` (scoped to the active workspace), this fans the
    same search out to every other repo in the project and groups results by
    repo — use it when a symbol might be defined in a sibling repo rather
    than the one the agent is currently working in.
    """
    sandbox = get_sandbox()
    if not sandbox.extra_workspace_paths:
        return _NO_SIBLING_REPOS

    capped = max(1, min(limit_per_repo, 20))
    paths = [str(sandbox.workspace_root), *sandbox.extra_workspace_paths]
    async with async_session_factory() as db:
        results = await svc.search_across_workspaces(
            db, workspace_paths=paths, query=query, kind=kind, limit_per_workspace=capped
        )

    if not results:
        return f"No symbols matched '{query}' in any repo of this project."

    grouped: dict[str, list[CodeNode]] = {}
    for path, node in results:
        grouped.setdefault(path, []).append(node)

    total = len(results)
    header = f"Found {total} symbol(s) for '{query}' across {len(grouped)} repo(s):"
    sections = []
    for path, nodes in grouped.items():
        lines = "\n".join(
            f"  {i}. [{n.kind}] {n.qualified_name} — {_loc(n)}"
            for i, n in enumerate(nodes, start=1)
        )
        sections.append(f"{_repo_label(path)} ({path}):\n{lines}")
    return f"{header}\n" + "\n".join(sections)


code_cross_repo_search = Tool(
    _code_cross_repo_search,
    name="code_cross_repo_search",
    description=(
        "Search for a symbol across EVERY repo in the current project, not "
        "just the active workspace. Use when a symbol might be defined in a "
        "sibling repo (e.g. a shared library or another service) rather "
        "than the repo you're currently working in."
    ),
    concurrency_safe=True,
    read_only=True,
)
