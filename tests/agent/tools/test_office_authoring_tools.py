from __future__ import annotations

import json

from app.agent.loader import _default_tool_registry
from app.agent.tools.builtin import docx_document, xlsx_artifact


async def test_docx_catalog_is_word_native() -> None:
    payload = json.loads(await docx_document.arun(action="catalog"))

    assert payload["workflow"] == "word-native-docx-with-template-fidelity"
    assert "standard_business_brief" in payload["presets"]
    assert "template_project_schema" in payload


async def test_xlsx_catalog_is_artifact_tool_native() -> None:
    payload = json.loads(await xlsx_artifact.arun(action="catalog"))

    assert payload["workflow"] == "editable-artifact-tool-xlsx"
    assert "write_range" in payload["operations"]
    assert "project_json_schema" in payload


def test_default_registry_exposes_office_authoring_tools() -> None:
    registry = _default_tool_registry()

    assert registry["docx_document"] is docx_document
    assert registry["xlsx_artifact"] is xlsx_artifact
    assert docx_document.deferred is True
    assert xlsx_artifact.deferred is True
