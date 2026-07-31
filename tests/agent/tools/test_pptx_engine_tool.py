from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agent.sandbox import SandboxConfig, _sandbox_ctx, set_sandbox
from app.agent.tools.builtin.pptx_engine import pptx_engine


@pytest.fixture
def pptx_workspace(tmp_path: Path):
    token = set_sandbox(SandboxConfig(workspace=str(tmp_path)))
    yield tmp_path
    _sandbox_ctx.reset(token)


def _tool_spec() -> dict:
    return {
        "title": "Tool contract",
        "slides": [
            {
                "title": "The tool compiles a validated spec",
                "layout": "hero",
                "slots": {
                    "canvas": {
                        "type": "text",
                        "text": "The agent selects a layout and content; the engine owns geometry and QA.",
                        "bold": True,
                        "align": "center",
                        "max_lines": 4,
                    }
                },
            }
        ],
    }


@pytest.mark.asyncio
async def test_pptx_engine_catalog_is_deferred_and_descriptive() -> None:
    payload = json.loads(await pptx_engine(action="catalog"))

    assert pptx_engine.deferred
    assert len(payload["layouts"]) == 18
    assert "image" in payload["block_types"]
    assert payload["capabilities"]["smartart"]["edit"] == "preserve-only"


@pytest.mark.asyncio
async def test_pptx_engine_compose_writes_inside_workspace(
    pptx_workspace: Path,
) -> None:
    payload = json.loads(
        await pptx_engine(
            action="compose",
            path="artifacts/tool-deck.pptx",
            spec=_tool_spec(),
            render=False,
            allow_shape_only=True,
        )
    )

    assert payload["passed"]
    assert (pptx_workspace / "artifacts" / "tool-deck.pptx").is_file()


@pytest.mark.asyncio
async def test_pptx_engine_rejects_output_outside_workspace(
    pptx_workspace: Path,
) -> None:
    with pytest.raises(PermissionError):
        await pptx_engine(
            action="compose",
            path="../outside.pptx",
            spec=_tool_spec(),
            render=False,
        )
