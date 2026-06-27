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
            workspace_id=workspace_id,
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
            workspace_id=workspace_id,
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
            workspace_id=workspace_id,
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
            workspace_id=workspace_id,
            src_id=nodes[0].id,
            dst_id=nodes[0].id,
        )
        assert path == []
