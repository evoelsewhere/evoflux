"""API contracts for task-oriented code retrieval diagnostics."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from app.api.schemas.code_graph import CodeQueryRequest


@pytest.mark.asyncio
async def test_query_endpoint_rejects_unregistered_source_directory(
    setup_db, tmp_path: Path
):
    from app.api.routes.code_graph import code_query
    from app.core.db import async_session_factory

    (tmp_path / "secret.py").write_text("token = 'hidden'\n", encoding="utf-8")
    async with async_session_factory() as db:
        with pytest.raises(HTTPException) as exc:
            await code_query(
                db,
                CodeQueryRequest(query="hidden"),
                workspace=str(tmp_path),
            )

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_query_endpoint_supports_unindexed_workspace(setup_db, tmp_path: Path):
    from app.api.routes.code_graph import code_query
    from app.core.db import async_session_factory
    from app.services.coding_workspace_service import upsert_coding_workspace

    (tmp_path / "worker.ex").write_text(
        "defmodule Worker do\n  def reconnect_session(id), do: id\nend\n",
        encoding="utf-8",
    )
    async with async_session_factory() as db:
        await upsert_coding_workspace(db, path=str(tmp_path))
        await db.commit()
        response = await code_query(
            db,
            CodeQueryRequest(query="reconnect_session"),
            workspace=str(tmp_path),
        )

    assert response.strategy == "lexical"
    assert response.freshness == "unavailable"
    assert response.results[0].file_path == "worker.ex"
    assert any(not item.graph for item in response.capabilities)


@pytest.mark.asyncio
async def test_freshness_endpoint_does_not_require_index(setup_db, tmp_path: Path):
    from app.api.routes.code_graph import freshness
    from app.core.db import async_session_factory
    from app.services.coding_workspace_service import upsert_coding_workspace

    async with async_session_factory() as db:
        await upsert_coding_workspace(db, path=str(tmp_path))
        await db.commit()
        response = await freshness(db, workspace=str(tmp_path))

    assert response.freshness == "unavailable"
    assert response.indexed_files == 0
