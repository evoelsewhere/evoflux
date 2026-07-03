"""Tests for P4/P5/P6 code graph features: references, ranked map, shortest path."""

from __future__ import annotations

from pathlib import Path

import pytest

# Ensure all SQLModel tables are registered before the session-scoped setup_db
# fixture calls SQLModel.metadata.create_all (needed when running this file alone).
import app.models.chat  # noqa: F401
import app.models.code_graph  # noqa: F401


async def _setup_workspace(tmp_path: Path):
    """Create a multi-file workspace and index it. Returns workspace_id."""
    from app.core.db import async_session_factory
    from app.services.code_graph_service import reindex_workspace
    from app.services.coding_workspace_service import upsert_coding_workspace

    # Create a realistic multi-file codebase with cross-references:
    # base.py defines BaseService (called by many)
    # service.py defines UserService(BaseService), calls helper + base
    # helper.py defines helper() used by service
    # controller.py calls UserService
    (tmp_path / "base.py").write_text(
        "class BaseService:\n    def connect(self):\n        pass\n",
        encoding="utf-8",
    )
    (tmp_path / "helper.py").write_text(
        "def validate(data):\n"
        "    return bool(data)\n\n"
        "def format_output(result):\n"
        "    return str(result)\n",
        encoding="utf-8",
    )
    (tmp_path / "service.py").write_text(
        "class UserService(BaseService):\n"
        "    def get_user(self, uid):\n"
        "        validate(uid)\n"
        "        self.connect()\n"
        "        return format_output(uid)\n",
        encoding="utf-8",
    )
    (tmp_path / "controller.py").write_text(
        "def handle_request(request):\n"
        "    svc = UserService()\n"
        "    return svc.get_user(request.uid)\n",
        encoding="utf-8",
    )

    async with async_session_factory() as db:
        ws = await upsert_coding_workspace(db, path=str(tmp_path))
        await db.commit()
        workspace_id = ws.id

    async with async_session_factory() as db:
        await reindex_workspace(db, workspace_id=workspace_id, root_path=str(tmp_path))
        await db.commit()

    return workspace_id


# ── P4: find_references ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_find_references_returns_callers(setup_db, tmp_path: Path):
    from app.core.db import async_session_factory
    from app.services.code_graph_service import find_nodes_by_name, find_references

    workspace_id = await _setup_workspace(tmp_path)

    async with async_session_factory() as db:
        # validate() is called from service.py
        nodes = await find_nodes_by_name(db, workspace_id=workspace_id, name="validate")
        assert len(nodes) >= 1
        node = nodes[0]

        refs = await find_references(db, workspace_id=workspace_id, node_id=node.id)
        assert len(refs) >= 1
        # At least one reference should be a "calls" edge from get_user
        edge_kinds = {ek for ek, _, _ in refs}
        assert "calls" in edge_kinds


@pytest.mark.asyncio
async def test_find_references_returns_empty_for_leaf(setup_db, tmp_path: Path):
    from app.core.db import async_session_factory
    from app.services.code_graph_service import find_nodes_by_name, find_references

    workspace_id = await _setup_workspace(tmp_path)

    async with async_session_factory() as db:
        # handle_request is a leaf — nothing calls it
        nodes = await find_nodes_by_name(
            db, workspace_id=workspace_id, name="handle_request"
        )
        assert len(nodes) >= 1
        node = nodes[0]

        refs = await find_references(db, workspace_id=workspace_id, node_id=node.id)
        assert len(refs) == 0


# ── P5: get_ranked_symbols ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_ranked_symbols_returns_most_referenced(setup_db, tmp_path: Path):
    from app.core.db import async_session_factory
    from app.services.code_graph_service import get_ranked_symbols

    workspace_id = await _setup_workspace(tmp_path)

    async with async_session_factory() as db:
        ranked = await get_ranked_symbols(db, workspace_id=workspace_id, budget=10)
        assert len(ranked) >= 1
        # The most-referenced symbols should appear first; validate and
        # format_output and connect are all called, so at least some show up
        names = [node.name for node, _count in ranked]
        # validate is called → should be in the list
        assert "validate" in names
        # Counts are descending
        counts = [count for _, count in ranked]
        assert counts == sorted(counts, reverse=True)


# ── P6: find_shortest_path ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_find_shortest_path_direct_call(setup_db, tmp_path: Path):
    from app.core.db import async_session_factory
    from app.services.code_graph_service import find_nodes_by_name, find_shortest_path

    workspace_id = await _setup_workspace(tmp_path)

    async with async_session_factory() as db:
        src_nodes = await find_nodes_by_name(
            db, workspace_id=workspace_id, name="get_user"
        )
        dst_nodes = await find_nodes_by_name(
            db, workspace_id=workspace_id, name="validate"
        )
        assert src_nodes and dst_nodes

        path = await find_shortest_path(
            db,
            src_workspace_id=workspace_id,
            src_id=src_nodes[0].id,
            dst_id=dst_nodes[0].id,
        )
        # get_user calls validate directly → 1 hop
        assert path is not None
        assert len(path) >= 1


@pytest.mark.asyncio
async def test_find_shortest_path_multi_hop(setup_db, tmp_path: Path):
    from app.core.db import async_session_factory
    from app.services.code_graph_service import find_nodes_by_name, find_shortest_path

    workspace_id = await _setup_workspace(tmp_path)

    async with async_session_factory() as db:
        src_nodes = await find_nodes_by_name(
            db, workspace_id=workspace_id, name="handle_request"
        )
        dst_nodes = await find_nodes_by_name(
            db, workspace_id=workspace_id, name="validate"
        )
        assert src_nodes and dst_nodes

        path = await find_shortest_path(
            db,
            src_workspace_id=workspace_id,
            src_id=src_nodes[0].id,
            dst_id=dst_nodes[0].id,
        )
        # handle_request → get_user → validate (2+ hops through the graph)
        assert path is not None
        assert len(path) >= 1


@pytest.mark.asyncio
async def test_find_shortest_path_returns_none_when_unreachable(
    setup_db, tmp_path: Path
):
    from app.core.db import async_session_factory
    from app.services.code_graph_service import find_nodes_by_name, find_shortest_path

    workspace_id = await _setup_workspace(tmp_path)

    # Add an isolated file with no connections to the rest
    (tmp_path / "isolated.py").write_text(
        "def lonely():\n    return 42\n", encoding="utf-8"
    )
    from app.services.code_graph_service import reindex_workspace

    async with async_session_factory() as db:
        await reindex_workspace(db, workspace_id=workspace_id, root_path=str(tmp_path))
        await db.commit()

    async with async_session_factory() as db:
        src_nodes = await find_nodes_by_name(
            db, workspace_id=workspace_id, name="lonely"
        )
        dst_nodes = await find_nodes_by_name(
            db, workspace_id=workspace_id, name="validate"
        )
        assert src_nodes and dst_nodes

        path = await find_shortest_path(
            db,
            src_workspace_id=workspace_id,
            src_id=src_nodes[0].id,
            dst_id=dst_nodes[0].id,
            max_hops=4,
        )
        assert path is None


@pytest.mark.asyncio
async def test_find_shortest_path_same_node(setup_db, tmp_path: Path):
    from app.core.db import async_session_factory
    from app.services.code_graph_service import find_nodes_by_name, find_shortest_path

    workspace_id = await _setup_workspace(tmp_path)

    async with async_session_factory() as db:
        nodes = await find_nodes_by_name(db, workspace_id=workspace_id, name="validate")
        assert nodes

        path = await find_shortest_path(
            db,
            src_workspace_id=workspace_id,
            src_id=nodes[0].id,
            dst_id=nodes[0].id,
        )
        assert path == []


@pytest.mark.asyncio
async def test_find_shortest_path_continues_past_cross_repo_hop(
    setup_db, tmp_path: Path
):
    """BFS must keep traversing a sibling repo's OWN edges after crossing into
    it via a resolved CrossRepoEdge, not dead-end there.

    Regression test: the query that fetches a frontier node's neighbours used
    to be hardcoded to the *starting* workspace_id, so a node reached via a
    cross-repo hop (living in a different workspace) could never have its own
    outbound/inbound edges found on the next iteration."""
    from app.core.db import async_session_factory
    from app.models.code_graph import CrossRepoEdge
    from app.services.code_graph_service import (
        find_nodes_by_name,
        find_shortest_path,
        reindex_workspace,
    )
    from app.services.coding_project_service import create_project

    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    repo_a.mkdir()
    repo_b.mkdir()
    (repo_a / "main.py").write_text("def entry():\n    pass\n", encoding="utf-8")
    (repo_b / "lib.py").write_text(
        "def shared_service():\n    return internal_helper()\n\n"
        "def internal_helper():\n    return 1\n",
        encoding="utf-8",
    )

    async with async_session_factory() as db:
        project = await create_project(
            db, name="Path Test", workspace_paths=[str(repo_a), str(repo_b)]
        )
        await db.commit()
        project_id = project.id

    async with async_session_factory() as db:
        from app.services.code_graph_service import resolve_workspace_id

        repo_a_id = await resolve_workspace_id(db, path=str(repo_a))
        repo_b_id = await resolve_workspace_id(db, path=str(repo_b))
        await reindex_workspace(db, workspace_id=repo_a_id, root_path=str(repo_a))
        await reindex_workspace(db, workspace_id=repo_b_id, root_path=str(repo_b))
        await db.commit()

    async with async_session_factory() as db:
        entry_node = (
            await find_nodes_by_name(db, workspace_id=repo_a_id, name="entry")
        )[0]
        shared_service_node = (
            await find_nodes_by_name(db, workspace_id=repo_b_id, name="shared_service")
        )[0]
        internal_helper_node = (
            await find_nodes_by_name(db, workspace_id=repo_b_id, name="internal_helper")
        )[0]

        # Manually seed a resolved cross-repo edge, as the resolver pipeline
        # would produce: repo-a's entry() "calls" repo-b's shared_service().
        db.add(
            CrossRepoEdge(
                project_id=project_id,
                src_workspace_id=repo_a_id,
                src_node_id=entry_node.id,
                src_file_path="main.py",
                raw_reference="shared_service",
                dst_name_hint="shared_service",
                kind="calls",
                status="resolved",
                method="static_fqn",
                confidence=1.0,
                dst_workspace_id=repo_b_id,
                dst_node_id=shared_service_node.id,
                dst_qualified_name=shared_service_node.qualified_name,
            )
        )
        await db.commit()

        # entry (repo-a) --[cross-repo]--> shared_service (repo-b)
        #   --[intra-repo-b calls]--> internal_helper (repo-b)
        path = await find_shortest_path(
            db,
            src_workspace_id=repo_a_id,
            src_id=entry_node.id,
            dst_id=internal_helper_node.id,
            max_hops=4,
            project_id=project_id,
        )
        assert path is not None, (
            "BFS should follow the intra-repo-b hop after crossing into "
            "repo-b via the resolved CrossRepoEdge"
        )
        assert len(path) == 2
        hop_node_ids = [path[0][0].id, path[0][2].id, path[1][0].id, path[1][2].id]
        assert entry_node.id in hop_node_ids
        assert shared_service_node.id in hop_node_ids
        assert internal_helper_node.id in hop_node_ids
