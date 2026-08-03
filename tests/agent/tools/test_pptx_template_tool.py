from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path

from PIL import Image
import pytest

from app.agent.sandbox import SandboxConfig, _sandbox_ctx, set_sandbox
from app.agent.schemas.chat import ImageDataBlock, ToolResult
from app.agent.tools.builtin import pptx_template as pptx_template_tool
from app.services.pptx_template_pipeline import TemplatePipelineResult


_module = importlib.import_module("app.agent.tools.builtin.pptx_template")


@pytest.fixture
def sandbox(tmp_path: Path):
    token = set_sandbox(
        SandboxConfig(
            workspace=str(tmp_path),
            session_id="00000000-0000-0000-0000-000000000001",
            denied_roots=[],
        )
    )
    try:
        yield tmp_path
    finally:
        _sandbox_ctx.reset(token)


def _files(root: Path) -> tuple[Path, Path, Path]:
    source = root / "template.pptx"
    source.write_bytes(b"pptx")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest = root / "template-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "sourceSha256": digest,
                "slideCount": 1,
                "records": [{"id": "sh/title", "slide": 1, "kind": "textbox"}],
            }
        ),
        encoding="utf-8",
    )
    project = root / "template-project.json"
    project.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "title": "Deck",
                "source_sha256": digest,
                "template_confirmed": True,
                "output_slides": [
                    {
                        "output_slide": 1,
                        "source_slide": 1,
                        "narrative_role": "opening",
                        "edits": [],
                    }
                ],
                "omitted_source_slides": [],
            }
        ),
        encoding="utf-8",
    )
    return source, manifest, project


def _result(root: Path, source: Path, *, passed: bool = True) -> TemplatePipelineResult:
    preview = root / "preview.png"
    Image.new("RGB", (32, 18), "white").save(preview)
    return TemplatePipelineResult(
        action="compose",
        source_pptx=source,
        work_dir=root,
        output=(root / "deliverables" / "deck.pptx") if passed else None,
        previews=[preview],
        slide_count=1,
        issues=([] if passed else [{"severity": "error", "code": "fidelity"}]),
    )


async def test_catalog_exposes_template_following_contract() -> None:
    payload = json.loads(await pptx_template_tool.arun(action="catalog"))

    assert payload["workflow"] == "uploaded-pptx-template-following"
    assert payload["style_behavior"]["ask_style_question"] is False


async def test_inspect_returns_source_previews(
    sandbox: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, _, _ = _files(sandbox)

    async def fake_inspect(*args, **kwargs):
        return _result(sandbox, source)

    monkeypatch.setattr(_module, "inspect_pptx_template", fake_inspect)
    result = await pptx_template_tool.arun(
        action="inspect", source_pptx="template.pptx"
    )

    assert isinstance(result, ToolResult)
    assert any(isinstance(part, ImageDataBlock) for part in result.parts)


async def test_inspect_accepts_a_read_only_uploaded_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    uploads = tmp_path / "uploads"
    workspace.mkdir()
    uploads.mkdir()
    source = uploads / "client-template.pptx"
    source.write_bytes(b"uploaded-pptx")
    token = set_sandbox(
        SandboxConfig(
            workspace=str(workspace),
            session_id=None,
            denied_roots=[],
            read_only_paths=[str(uploads)],
        )
    )

    async def fake_inspect(*args, **kwargs):
        return _result(workspace, source)

    monkeypatch.setattr(_module, "inspect_pptx_template", fake_inspect)
    try:
        result = await pptx_template_tool.arun(
            action="inspect", source_pptx=str(source)
        )
    finally:
        _sandbox_ctx.reset(token)

    assert isinstance(result, ToolResult)
    assert source.read_bytes() == b"uploaded-pptx"


async def test_validate_checks_manifest_and_source_hash(sandbox: Path) -> None:
    _files(sandbox)

    payload = json.loads(
        await pptx_template_tool.arun(
            action="validate",
            source_pptx="template.pptx",
            project_path="template-project.json",
            manifest_path="template-manifest.json",
        )
    )

    assert payload["valid"] is True
    assert payload["template_confirmed"] is True


async def test_compose_publishes_inherited_pptx(
    sandbox: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, _, _ = _files(sandbox)

    async def fake_compose(*args, **kwargs):
        output = Path(args[3])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"pptx")
        result = _result(sandbox, source)
        result.output = output
        return result

    monkeypatch.setattr(_module, "compose_pptx_template", fake_compose)
    result = await pptx_template_tool.arun(
        action="compose",
        source_pptx="template.pptx",
        project_path="template-project.json",
        manifest_path="template-manifest.json",
        output="deliverables/deck.pptx",
    )

    assert isinstance(result, ToolResult)
    assert result.attachments
    assert result.attachments[0]["workspace_path"] == "deliverables/deck.pptx"
    assert (
        "/office-preview/deliverables/deck.pptx" in result.attachments[0]["preview_url"]
    )
