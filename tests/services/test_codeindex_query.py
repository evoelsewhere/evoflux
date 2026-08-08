"""Parser-aligned code-index query and cross-repository ranking tests."""

from __future__ import annotations

from pathlib import Path

import pytest

import app.models  # noqa: F401 -- populate SQLModel metadata before DB fixture


async def _index_repository(path: Path):
    from app.core.db import async_session_factory
    from app.services.code_graph_service import reindex_workspace
    from app.services.coding_workspace_service import upsert_coding_workspace

    async with async_session_factory() as db:
        workspace = await upsert_coding_workspace(db, path=str(path))
        await db.commit()
        await reindex_workspace(
            db,
            workspace_id=workspace.id,
            root_path=str(path),
            incremental=False,
        )
        await db.commit()
        return workspace.id


@pytest.mark.asyncio
async def test_codeindex_ranks_exact_symbol_over_source_token_match(
    setup_db, tmp_path: Path
):
    from app.core.db import async_session_factory
    from app.services.code_intelligence.models import WorkspaceScope
    from app.services.codeindex.query import search_code_index

    (tmp_path / "orders.py").write_text(
        "def process_order(cart):\n"
        '    """Validate cart and charge the customer."""\n'
        "    return cart\n\n"
        "def audit_log():\n"
        "    return 'process_order mentioned in an audit message'\n",
        encoding="utf-8",
    )
    workspace_id = await _index_repository(tmp_path)
    scope = WorkspaceScope(root=tmp_path, workspace_id=workspace_id, label="orders")

    async with async_session_factory() as db:
        result = await search_code_index(
            db,
            scopes=(scope,),
            query="process_order",
            limit=10,
            freshness_policy="fast",
        )

    assert result.strategy == "codeindex-fts5-structural"
    assert result.freshness == "fresh"
    assert result.matches
    assert result.matches[0].chunk.name == "process_order"
    assert "exact-qualified-name" in result.matches[0].match_reasons
    assert "Validate cart" in result.matches[0].chunk.content


@pytest.mark.asyncio
async def test_codeindex_merges_and_filters_cross_repository_results(
    setup_db, tmp_path: Path
):
    from app.core.db import async_session_factory
    from app.services.code_intelligence.models import WorkspaceScope
    from app.services.codeindex.query import search_code_index

    api = tmp_path / "api"
    worker = tmp_path / "worker"
    api.mkdir()
    worker.mkdir()
    (api / "checkout.py").write_text(
        "def dispatch_payment():\n"
        '    """Queue a payment settlement job."""\n'
        "    return True\n",
        encoding="utf-8",
    )
    (worker / "settlement.py").write_text(
        "def settle_payment():\n"
        '    """Consume the payment settlement job."""\n'
        "    return True\n",
        encoding="utf-8",
    )
    api_id = await _index_repository(api)
    worker_id = await _index_repository(worker)
    scopes = (
        WorkspaceScope(root=api, workspace_id=api_id, label="api"),
        WorkspaceScope(root=worker, workspace_id=worker_id, label="worker"),
    )

    async with async_session_factory() as db:
        merged = await search_code_index(
            db,
            scopes=scopes,
            query="payment settlement job",
            limit=10,
        )
        worker_only = await search_code_index(
            db,
            scopes=scopes,
            query="payment settlement job",
            repository="worker",
            path="settlement.py",
            limit=10,
        )

    assert {match.scope.label for match in merged.matches} == {"api", "worker"}
    assert worker_only.matches
    assert {match.scope.label for match in worker_only.matches} == {"worker"}
    assert {match.chunk.file_path for match in worker_only.matches} == {
        "settlement.py"
    }
