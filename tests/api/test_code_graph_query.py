"""API contracts for symbol-first code-graph navigation."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from app.api.schemas.code_graph import CodeGraphNavigateRequest


@pytest.mark.asyncio
async def test_navigate_endpoint_rejects_unregistered_source_directory(
    setup_db, tmp_path: Path
) -> None:
    from app.api.routes.code_graph import navigate_code_graph
    from app.core.db import async_session_factory

    (tmp_path / "secret.py").write_text("def hidden():\n    pass\n", encoding="utf-8")
    async with async_session_factory() as db:
        with pytest.raises(HTTPException) as exc:
            await navigate_code_graph(
                db,
                CodeGraphNavigateRequest(symbol="hidden"),
                workspace=str(tmp_path),
            )

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_navigate_endpoint_has_no_unsupported_source_fallback(
    setup_db, tmp_path: Path
) -> None:
    from app.api.routes.code_graph import navigate_code_graph
    from app.core.db import async_session_factory
    from app.services.coding_workspace_service import upsert_coding_workspace

    (tmp_path / "worker.ex").write_text(
        "defmodule Worker do\n  def reconnect_session(id), do: id\nend\n",
        encoding="utf-8",
    )
    async with async_session_factory() as db:
        await upsert_coding_workspace(db, path=str(tmp_path))
        await db.commit()
        response = await navigate_code_graph(
            db,
            CodeGraphNavigateRequest(symbol="reconnect_session"),
            workspace=str(tmp_path),
        )

    assert response.strategy == "native-index-unavailable"
    assert response.freshness == "unavailable"
    assert response.matches == []
    assert any("no source files" in item.lower() for item in response.limitations)


def test_navigate_request_rejects_natural_language() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        CodeGraphNavigateRequest(symbol="where is this function called")


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
