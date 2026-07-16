"""Workflow policy — content hash, approval manifest, destructive lint.

The manifest (plan §7) is what the user explicitly approves per content
hash: every agent blueprint a run may spawn, every tool/MCP name a run may
call directly (bypassing the permission-hook layer, which is exactly why
approval is mandatory), every MCP server touched, every ``env.*``
reference templated anywhere.
"""

from __future__ import annotations

import hashlib
from typing import Any

from app.workflow.models import DESTRUCTIVE_TOOLS, Node, WorkflowDefinition
from app.workflow.template import referenced_env_names


def content_hash(raw_bytes: bytes) -> str:
    return hashlib.sha256(raw_bytes).hexdigest()


def _node_tools(node_like: Node | Any) -> set[str]:
    if node_like.kind == "tool" and node_like.tool:
        return {node_like.tool}
    return set()


def compute_manifest(
    definition: WorkflowDefinition,
    *,
    blueprint_tools: dict[str, set[str]] | None = None,
) -> dict:
    """The approval manifest. ``blueprint_tools`` (name → configured tools)
    is informational display data for agent nodes (plan §7.1: the manifest
    pins blueprint NAMES; tools shown at display time)."""
    agents: set[str] = set()
    tools: set[str] = set()
    mcp_servers: set[str] = set()

    def _collect(node_like: Node | Any) -> None:
        for name in getattr(node_like, "subagents", None) or []:
            agents.add(name)
        for tool in _node_tools(node_like):
            tools.add(tool)
            if tool.startswith("mcp_"):
                # mcp_<server>_<tool> — server is the first segment.
                parts = tool.split("_", 2)
                if len(parts) >= 3:
                    mcp_servers.add(parts[1])

    for node in definition.nodes:
        _collect(node)
        if node.kind == "foreach" and node.foreach_body is not None:
            _collect(node.foreach_body)

    env_refs = referenced_env_names(
        definition.model_dump(by_alias=True, exclude_none=True)
    )

    manifest: dict = {
        "agents": sorted(agents),
        "tools": sorted(tools),
        "mcp_servers": sorted(mcp_servers),
        "env_refs": sorted(env_refs),
    }
    if blueprint_tools:
        manifest["agent_tools"] = {
            name: sorted(blueprint_tools.get(name, set())) for name in sorted(agents)
        }
    return manifest


def destructive_lint(
    definition: WorkflowDefinition,
    *,
    blueprint_tools: dict[str, set[str]] | None = None,
    lead_tools: set[str] | None = None,
) -> list[str]:
    """Advisory warnings (plan §4.4): entry→node paths whose effective
    tools touch the destructive set without an intervening gate."""
    blueprint_tools = blueprint_tools or {}
    lead_tools = lead_tools or set()
    warnings: list[str] = []

    def _effective_tools(node: Node) -> set[str]:
        effective: set[str] = set()
        candidates = [node]
        if node.kind == "foreach" and node.foreach_body is not None:
            candidates.append(node.foreach_body)  # type: ignore[arg-type]
        for item in candidates:
            effective |= _node_tools(item)
            if item.kind == "agent":
                effective |= lead_tools
                for name in getattr(item, "subagents", None) or []:
                    effective |= blueprint_tools.get(name, set())
        return effective

    adjacency: dict[str, list[str]] = {}
    for edge in definition.edges:
        adjacency.setdefault(edge.from_, []).append(edge.to)
    by_id = {node.id: node for node in definition.nodes}

    # DFS from each entry; a gate on the path resets the exposure.
    def _walk(node_id: str, gated: bool, seen: frozenset[str]) -> None:
        node = by_id[node_id]
        if node.kind == "gate":
            gated = True
        elif not gated:
            hits = _effective_tools(node) & DESTRUCTIVE_TOOLS
            if hits:
                warnings.append(
                    f"node '{node_id}' can reach destructive tools "
                    f"({', '.join(sorted(hits))}) with no gate before it."
                )
        for child in adjacency.get(node_id, []):
            if child not in seen:
                _walk(child, gated, seen | {child})

    for entry in definition.entry_nodes():
        _walk(entry, False, frozenset({entry}))
    # A node reachable both gated and ungated warns once; dedupe.
    return sorted(set(warnings))
