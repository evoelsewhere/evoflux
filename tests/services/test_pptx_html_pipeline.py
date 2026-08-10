from __future__ import annotations

import base64
from io import BytesIO
import json
from pathlib import Path
from typing import Any

from PIL import Image
from pptx import Presentation
import pytest

from app.services.html_slide_render_service import get_html_slide_render_broker
from app.services.pptx_html_pipeline import (
    compose_html_pptx_project,
    html_pptx_catalog,
    load_html_pptx_project,
    validate_html_pptx_project,
)


def _png_base64(width: int, height: int, *, blank: bool = False) -> str:
    image = (
        Image.new("RGB", (width, height), "white")
        if blank
        else Image.effect_noise((width, height), 48).convert("RGB")
    )
    stream = BytesIO()
    image.save(stream, format="PNG")
    return base64.b64encode(stream.getvalue()).decode("ascii")


def _project(tmp_path: Path) -> Path:
    (tmp_path / "slide.html").write_text(
        """
        <section data-slide-root class="relative h-full w-full">
          <h1 data-pptx-editable="text">HTML owns the composition</h1>
          <img src="asset://hero" data-pptx-editable="image"
               data-pptx-asset="hero" alt="Hero" />
        </section>
        """,
        encoding="utf-8",
    )
    (tmp_path / "slide.css").write_text(
        "[data-slide-root]{background:linear-gradient(135deg,#07111f,#3355ff)}",
        encoding="utf-8",
    )
    Image.new("RGB", (120, 80), "#22d3ee").save(tmp_path / "hero.png")
    path = tmp_path / "deck.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 4,
                "title": "HTML deck",
                "width": 1280,
                "height": 720,
                "slides": [
                    {
                        "id": "opening",
                        "html_path": "slide.html",
                        "style_paths": ["slide.css"],
                        "assets": {"hero": "hero.png"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_html_catalog_and_validation(tmp_path: Path) -> None:
    path = _project(tmp_path)
    project = load_html_pptx_project(path)

    result = validate_html_pptx_project(project, path)

    assert result["valid"] is True
    assert result["rendering"] == "desktop-webview-html-tailwind"
    catalog = html_pptx_catalog()
    assert catalog["workflow"] == "html-tailwind-hybrid-pptx"
    assert catalog["runtime"]["headless_fallback"] is False


@pytest.mark.parametrize(
    ("html", "message"),
    [
        ("<section data-slide-root><script>x()</script></section>", "unsafe HTML"),
        (
            '<section data-slide-root style="background:url(https://bad.test/x)"></section>',
            "network or executable URL",
        ),
        (
            '<section data-slide-root><img src="asset://missing"></section>',
            "undeclared assets",
        ),
    ],
)
def test_html_validation_rejects_unsafe_or_missing_resources(
    tmp_path: Path, html: str, message: str
) -> None:
    path = _project(tmp_path)
    (tmp_path / "slide.html").write_text(html, encoding="utf-8")
    project = load_html_pptx_project(path)

    with pytest.raises(ValueError, match=message):
        validate_html_pptx_project(project, path)


def test_html_validation_rejects_css_that_escapes_style_element(
    tmp_path: Path,
) -> None:
    path = _project(tmp_path)
    (tmp_path / "slide.css").write_text(
        "</style><img src=x onerror=alert(1)>", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="unsafe CSS"):
        validate_html_pptx_project(load_html_pptx_project(path), path)


def test_html_project_paths_cannot_escape_project(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    path = _project(project_dir)
    value = json.loads(path.read_text(encoding="utf-8"))
    value["slides"][0]["html_path"] = "../outside.html"
    (tmp_path / "outside.html").write_text(
        "<section data-slide-root></section>", encoding="utf-8"
    )
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(ValueError, match="inside the project directory"):
        validate_html_pptx_project(load_html_pptx_project(path), path)


@pytest.mark.asyncio
async def test_html_pipeline_builds_shell_with_editable_overlays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _project(tmp_path)

    async def fake_request(
        session_id: str | None,
        payload: dict[str, Any],
        *,
        timeout_seconds: float = 60,
    ) -> dict[str, Any]:
        del timeout_seconds
        assert session_id == "session-1"
        assert "data:image/png;base64" in payload["html"]
        return {
            "preview_png_base64": _png_base64(1280, 720),
            "shell_png_base64": _png_base64(2560, 1440),
            "editable_elements": [
                {
                    "kind": "text",
                    "name": "Title",
                    "x": 80,
                    "y": 90,
                    "width": 800,
                    "height": 90,
                    "text": "HTML owns the composition",
                    "font_family": "Arial",
                    "font_size": 48,
                    "bold": True,
                    "italic": False,
                    "underline": False,
                    "color": "#FFFFFF",
                    "text_align": "left",
                    "vertical_align": "top",
                    "line_height_ratio": 1.05,
                    "rotation": 0,
                },
                {
                    "kind": "image",
                    "name": "Hero",
                    "x": 900,
                    "y": 120,
                    "width": 240,
                    "height": 180,
                    "asset_id": "hero",
                    "alt": "Hero",
                },
            ],
            "issues": [],
        }

    monkeypatch.setattr(get_html_slide_render_broker(), "request", fake_request)
    output = tmp_path / "output.pptx"

    result = await compose_html_pptx_project(
        path,
        output,
        workspace_root=tmp_path,
        work_dir=tmp_path / "work",
        session_id="session-1",
    )

    assert result.passed is True
    assert result.output == output
    assert result.metadata["editable_object_count"] == 2
    assert result.metadata["visual_verification"] == "html-source-preview"
    deck = Presentation(str(output))
    assert len(deck.slides) == 1
    assert len(deck.slides[0].shapes) == 3
    assert deck.slides[0].shapes[1].text == "HTML owns the composition"


@pytest.mark.asyncio
async def test_html_pipeline_rejects_blank_webview_preview(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _project(tmp_path)

    async def fake_request(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "preview_png_base64": _png_base64(1280, 720, blank=True),
            "shell_png_base64": _png_base64(2560, 1440, blank=True),
            "editable_elements": [],
            "issues": [],
        }

    monkeypatch.setattr(get_html_slide_render_broker(), "request", fake_request)
    output = tmp_path / "blank.pptx"

    result = await compose_html_pptx_project(
        path,
        output,
        workspace_root=tmp_path,
        work_dir=tmp_path / "work",
        session_id="session-1",
    )

    assert result.passed is False
    assert result.output is None
    assert not output.exists()
    assert any(issue["code"] == "invalid-html-slide-preview" for issue in result.issues)


@pytest.mark.asyncio
async def test_html_pipeline_rejects_wrong_shell_dimensions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _project(tmp_path)

    async def fake_request(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "preview_png_base64": _png_base64(1280, 720),
            "shell_png_base64": _png_base64(1280, 720),
            "editable_elements": [],
            "issues": [],
        }

    monkeypatch.setattr(get_html_slide_render_broker(), "request", fake_request)

    with pytest.raises(ValueError, match="shell must be 2560x1440"):
        await compose_html_pptx_project(
            path,
            tmp_path / "wrong-shell.pptx",
            workspace_root=tmp_path,
            work_dir=tmp_path / "work",
            session_id="session-1",
        )
