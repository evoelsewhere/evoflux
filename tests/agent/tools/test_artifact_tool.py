from __future__ import annotations

import json

import pytest

from app.agent.loader import _default_tool_registry
from app.agent.tools.builtin import artifact


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
