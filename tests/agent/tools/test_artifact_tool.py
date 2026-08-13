from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agent.loader import _default_tool_registry
from app.agent.schemas.chat import ImageDataBlock, TextBlock
from app.agent.tools.builtin import artifact
from app.agent.tools.builtin.artifact import _result_parts


@pytest.mark.asyncio
async def test_artifact_catalog_exposes_all_native_format_drivers() -> None:
    payload = json.loads(await artifact.arun(action="catalog"))

    assert sorted(payload["formats"]) == ["docx", "pdf", "pptx", "xlsx"]
    assert payload["actions"] == [
        "catalog",
        "inspect",
        "validate",
        "preview",
        "publish",
        "status",
        "cancel",
    ]
    assert payload["schema_version"] == 1
    assert sorted(payload["formats"]["pptx"]["lanes"]) == ["new", "template"]


def test_artifact_is_deferred_work_tool() -> None:
    registry = _default_tool_registry()

    assert registry["artifact"] is artifact
    assert artifact.deferred is True
    assert artifact.tiers == {"work"}
    assert {
        "docx_document",
        "xlsx_artifact",
        "pptx_template",
        "pptx_html",
    }.isdisjoint(registry)


def test_artifact_preview_images_are_paginated_for_long_decks(tmp_path: Path) -> None:
    previews = []
    for index in range(10):
        path = tmp_path / f"slide-{index + 1:03d}.png"
        path.write_bytes(f"png-{index}".encode())
        previews.append(str(path))

    parts = _result_parts(
        {"result": {"previews": previews}}, preview_offset=6, preview_limit=3
    )

    assert sum(isinstance(part, ImageDataBlock) for part in parts) == 3
    pagination = [part.text for part in parts if isinstance(part, TextBlock)][-1]
    assert "Preview images 7-9 of 10" in pagination
    assert "preview_offset=9" in pagination
