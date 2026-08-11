from __future__ import annotations

import base64
from io import BytesIO
import json
from pathlib import Path
import shutil
from typing import Any

from PIL import Image
from pptx import Presentation
import pytest

from app.agent.builtin_plugins.documents.engines.html_slide_broker import (
    get_html_slide_render_broker,
)
from app.agent.builtin_plugins.documents.engines import pptx_html as pptx_html_engine
from app.agent.builtin_plugins.documents.engines.pptx_html import (
    compose_html_pptx_project,
    html_pptx_catalog,
    load_html_pptx_project,
    validate_html_pptx_project,
)


_BASELINE_PATH = (
    Path(__file__).resolve().parents[2]
    / "app"
    / "agent"
    / "builtin_plugins"
    / "documents"
    / "skills"
    / "pptx"
    / "templates"
    / "powerpoint-slide-dna.json"
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
    (tmp_path / "qa-evidence.txt").write_text(
        "Reviewed against the accepted WebView preview.", encoding="utf-8"
    )
    (tmp_path / "qa-ledger.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "dimensions": [
                    {
                        "id": "canvas-and-geometry",
                        "status": "unverified",
                        "awarded_points": 0,
                        "evidence": [],
                        "observed_gap": "awaiting runtime",
                        "disposition": "unverified",
                    },
                    *[
                        {
                            "id": dimension_id,
                            "status": "verified",
                            "awarded_points": points,
                            "evidence": ["qa-evidence.txt"],
                            "observed_gap": "",
                            "disposition": "preserved",
                        }
                        for dimension_id, points in [
                            ("typography-and-text-flow", 20),
                            ("images-color-and-effects", 15),
                            ("data-and-content-correctness", 15),
                            ("native-semantics-and-template-lineage", 10),
                        ]
                    ],
                    {
                        "id": "reopened-render-parity",
                        "status": "unverified",
                        "awarded_points": 0,
                        "evidence": [],
                        "observed_gap": "awaiting runtime",
                        "disposition": "unverified",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    baseline = json.loads(_BASELINE_PATH.read_text(encoding="utf-8"))
    (tmp_path / "slide-dna.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "format": "pptx",
                "baseline_id": "powerpoint-office-like-baseline",
                "id": "test-deck-dna",
                "deck": {
                    "communication_job": {
                        "audience": "test reviewers",
                        "decision": "accept the artifact",
                    },
                    "visual_signature": {
                        "mood": "technical",
                        "type_roles": ["title", "body"],
                    },
                    "canvas": {
                        "width": 1280,
                        "height": 720,
                        "unit": "px",
                        "aspect_ratio": "16:9",
                        "safe_area_px": {
                            "left": 32,
                            "right": 32,
                            "top": 24,
                            "bottom": 24,
                        },
                    },
                    "layout_family": ["cover"],
                    "representation_policy": {
                        "uniform-text": "hybrid-editable",
                        "plain-raster-image": "hybrid-editable",
                        "remaining-composition": "flattened-fidelity",
                    },
                    "fidelity_target": {
                        "target_score": 90,
                        "raster_targets": baseline["fidelity_scorecard"][
                            "raster_targets"
                        ],
                        "hard_failures": baseline["fidelity_scorecard"][
                            "hard_failures"
                        ],
                        "render_surfaces": [
                            item["id"] for item in baseline["render_surfaces"]
                        ],
                    },
                    "known_gaps": ["powerpoint-reference-unverified"],
                },
                "tokens": {
                    group: {"declared": True}
                    for group in baseline["visual_system_contract"][
                        "required_token_groups"
                    ]
                },
                "slides": [
                    {
                        "id": "opening",
                        "narrative_role": "opening",
                        "takeaway": "HTML owns the composition",
                        "archetype": "cover",
                        "dominant_object": "headline",
                        "reading_order": ["title", "hero"],
                        "density": "standard",
                        "editable_intent": ["title", "hero"],
                        "flattened_intent": ["background"],
                        "source_ids": [],
                        "risk_flags": ["font-metric-drift"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    path = tmp_path / "deck.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 6,
                "title": "HTML deck",
                "dna_path": "slide-dna.json",
                "qa_ledger_path": "qa-ledger.json",
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
    assert catalog["schema_version"] == 6
    assert catalog["slide_dna"]["required"] is True
    assert "schema" in catalog["slide_dna"]
    assert catalog["qa_ledger"]["required"] is True
    assert result["qa_ledger"]["runtime_overrides"] == [
        "canvas-and-geometry",
        "reopened-render-parity",
    ]


def test_html_validation_rejects_missing_or_incomplete_slide_dna(
    tmp_path: Path,
) -> None:
    path = _project(tmp_path)
    value = json.loads(path.read_text(encoding="utf-8"))
    value.pop("dna_path")
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(ValueError, match="dna_path"):
        load_html_pptx_project(path)

    path = _project(tmp_path)
    dna_path = tmp_path / "slide-dna.json"
    dna = json.loads(dna_path.read_text(encoding="utf-8"))
    dna["tokens"].pop("charts")
    dna_path.write_text(json.dumps(dna), encoding="utf-8")

    with pytest.raises(ValueError, match="tokens is missing baseline groups: charts"):
        validate_html_pptx_project(load_html_pptx_project(path), path)


def test_html_validation_requires_exact_qa_scorecard(tmp_path: Path) -> None:
    path = _project(tmp_path)
    project_value = json.loads(path.read_text(encoding="utf-8"))
    project_value.pop("qa_ledger_path")
    path.write_text(json.dumps(project_value), encoding="utf-8")

    with pytest.raises(ValueError, match="qa_ledger_path"):
        load_html_pptx_project(path)

    path = _project(tmp_path)
    qa_path = tmp_path / "qa-ledger.json"
    ledger = json.loads(qa_path.read_text(encoding="utf-8"))
    ledger["dimensions"].pop()
    qa_path.write_text(json.dumps(ledger), encoding="utf-8")

    with pytest.raises(ValueError, match="missing fidelity dimensions"):
        validate_html_pptx_project(load_html_pptx_project(path), path)


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("duplicate", "duplicate fidelity dimensions"),
        ("overweight", "exceeds its 20-point weight"),
        ("verified-without-evidence", "requires evidence"),
    ],
)
def test_html_validation_rejects_invalid_qa_dimension_contract(
    tmp_path: Path, case: str, message: str
) -> None:
    path = _project(tmp_path)
    qa_path = tmp_path / "qa-ledger.json"
    ledger = json.loads(qa_path.read_text(encoding="utf-8"))
    dimensions = ledger["dimensions"]

    if case == "duplicate":
        dimensions.append(dict(dimensions[0]))
    elif case == "overweight":
        dimensions[1]["awarded_points"] = 21
    else:
        dimensions[1]["evidence"] = []
    qa_path.write_text(json.dumps(ledger), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        validate_html_pptx_project(load_html_pptx_project(path), path)


@pytest.mark.parametrize("evidence", ["missing.txt", "../outside.txt"])
def test_html_qa_evidence_must_exist_inside_project(
    tmp_path: Path, evidence: str
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    path = _project(project_dir)
    (tmp_path / "outside.txt").write_text("outside", encoding="utf-8")
    qa_path = project_dir / "qa-ledger.json"
    ledger = json.loads(qa_path.read_text(encoding="utf-8"))
    ledger["dimensions"][1]["evidence"] = [evidence]
    qa_path.write_text(json.dumps(ledger), encoding="utf-8")

    message = (
        "inside the project directory"
        if evidence.startswith("..")
        else "does not exist"
    )
    with pytest.raises((ValueError, FileNotFoundError), match=message):
        validate_html_pptx_project(load_html_pptx_project(path), path)


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


def test_html_slide_dna_path_cannot_escape_project(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    path = _project(project_dir)
    value = json.loads(path.read_text(encoding="utf-8"))
    value["dna_path"] = "../outside-dna.json"
    shutil.copyfile(project_dir / "slide-dna.json", tmp_path / "outside-dna.json")
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

    def fake_reopened_render(
        source: Path, render_dir: Path, *, width: int = 1280
    ) -> list[Path]:
        assert source == output
        assert width == 1280
        render_dir.mkdir(parents=True, exist_ok=True)
        destination = render_dir / "slide-001.png"
        shutil.copyfile(tmp_path / "work" / "previews" / "slide-001.png", destination)
        return [destination]

    monkeypatch.setattr(pptx_html_engine, "render_pptx_pages", fake_reopened_render)

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
    assert result.metadata["visual_verification"] == "reopened-plugin-preview"
    assert result.metadata["slide_dna"]["target_score"] == 90
    assert result.metadata["reopened_parity"]["median"] == 1.0
    fidelity_score = result.metadata["fidelity_score"]
    assert fidelity_score["observed_score"] == 100
    assert fidelity_score["accepted"] is True
    dimensions = {item["id"]: item for item in fidelity_score["dimensions"]}
    assert dimensions["canvas-and-geometry"]["evaluator"] == "runtime"
    assert dimensions["canvas-and-geometry"]["awarded_points"] == 20
    assert dimensions["reopened-render-parity"]["evaluator"] == "runtime"
    assert dimensions["reopened-render-parity"]["awarded_points"] == 20
    surfaces = {
        surface["id"]: surface for surface in result.metadata["render_surfaces"]
    }
    assert set(surfaces) == {
        "source-preview",
        "flattened-shell",
        "reopened-plugin-preview",
        "powerpoint-reference",
    }
    assert surfaces["reopened-plugin-preview"]["status"] == "verified"
    assert surfaces["powerpoint-reference"]["status"] == "unverified"
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["slideDna"]["sha256"] == result.metadata["slide_dna"]["sha256"]
    assert manifest["fidelityScore"]["targetScore"] == 90
    assert manifest["fidelityScore"]["observedScore"] == 100
    assert manifest["fidelityScore"]["accepted"] is True
    assert manifest["representationLedger"]["slides"][0]["slide_id"] == "opening"
    deck = Presentation(str(output))
    assert len(deck.slides) == 1
    assert len(deck.slides[0].shapes) == 3
    assert deck.slides[0].shapes[1].text == "HTML owns the composition"


@pytest.mark.asyncio
async def test_html_pipeline_enforces_observed_score_beyond_raster_thresholds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _project(tmp_path)
    dna_path = tmp_path / "slide-dna.json"
    dna = json.loads(dna_path.read_text(encoding="utf-8"))
    dna["deck"]["fidelity_target"]["target_score"] = 100
    dna_path.write_text(json.dumps(dna), encoding="utf-8")

    async def fake_request(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "preview_png_base64": _png_base64(1280, 720),
            "shell_png_base64": _png_base64(2560, 1440),
            "editable_elements": [],
            "issues": [],
        }

    output = tmp_path / "target-100.pptx"

    def fake_reopened_render(
        source: Path, render_dir: Path, *, width: int = 1280
    ) -> list[Path]:
        assert source == output
        render_dir.mkdir(parents=True, exist_ok=True)
        preview = tmp_path / "work" / "previews" / "slide-001.png"
        destination = render_dir / "slide-001.png"
        with Image.open(preview).convert("RGB") as image:
            image.paste("white", (0, 0, 20, 20))
            image.save(destination)
        return [destination]

    monkeypatch.setattr(get_html_slide_render_broker(), "request", fake_request)
    monkeypatch.setattr(pptx_html_engine, "render_pptx_pages", fake_reopened_render)

    result = await compose_html_pptx_project(
        path,
        output,
        workspace_root=tmp_path,
        work_dir=tmp_path / "work",
        session_id="session-1",
    )

    assert result.metadata["reopened_parity"]["median"] >= 0.95
    assert not any(
        issue["code"] == "render-parity-below-target" for issue in result.issues
    )
    assert result.metadata["fidelity_score"]["observed_score"] < 100
    assert result.metadata["fidelity_score"]["accepted"] is False
    assert result.output is None
    assert not output.exists()
    assert any(
        issue["code"] == "fidelity-score-below-target" for issue in result.issues
    )


@pytest.mark.asyncio
async def test_html_pipeline_counts_only_verified_manual_dimension_points(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _project(tmp_path)
    qa_path = tmp_path / "qa-ledger.json"
    ledger = json.loads(qa_path.read_text(encoding="utf-8"))
    typography = next(
        item
        for item in ledger["dimensions"]
        if item["id"] == "typography-and-text-flow"
    )
    typography.update(
        {
            "status": "unverified",
            "awarded_points": 0,
            "evidence": [],
            "disposition": "unverified",
        }
    )
    qa_path.write_text(json.dumps(ledger), encoding="utf-8")

    async def fake_request(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "preview_png_base64": _png_base64(1280, 720),
            "shell_png_base64": _png_base64(2560, 1440),
            "editable_elements": [],
            "issues": [],
        }

    output = tmp_path / "unverified-dimension.pptx"

    def fake_reopened_render(
        source: Path, render_dir: Path, *, width: int = 1280
    ) -> list[Path]:
        assert source == output
        render_dir.mkdir(parents=True, exist_ok=True)
        destination = render_dir / "slide-001.png"
        shutil.copyfile(tmp_path / "work" / "previews" / "slide-001.png", destination)
        return [destination]

    monkeypatch.setattr(get_html_slide_render_broker(), "request", fake_request)
    monkeypatch.setattr(pptx_html_engine, "render_pptx_pages", fake_reopened_render)

    result = await compose_html_pptx_project(
        path,
        output,
        workspace_root=tmp_path,
        work_dir=tmp_path / "work",
        session_id="session-1",
    )

    assert result.metadata["reopened_parity"]["median"] == 1.0
    assert result.metadata["fidelity_score"]["observed_score"] == 80
    assert result.metadata["fidelity_score"]["accepted"] is False
    assert result.output is None
    assert any(
        issue["code"] == "fidelity-score-below-target" for issue in result.issues
    )


@pytest.mark.asyncio
async def test_html_pipeline_rejects_low_reopened_visual_parity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _project(tmp_path)

    async def fake_request(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "preview_png_base64": _png_base64(1280, 720),
            "shell_png_base64": _png_base64(2560, 1440),
            "editable_elements": [],
            "issues": [],
        }

    def fake_reopened_render(
        source: Path, render_dir: Path, *, width: int = 1280
    ) -> list[Path]:
        assert source == output
        render_dir.mkdir(parents=True, exist_ok=True)
        destination = render_dir / "slide-001.png"
        Image.new("RGB", (width, 720), "white").save(destination)
        return [destination]

    monkeypatch.setattr(get_html_slide_render_broker(), "request", fake_request)
    monkeypatch.setattr(pptx_html_engine, "render_pptx_pages", fake_reopened_render)
    output = tmp_path / "low-parity.pptx"

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
    assert result.metadata["reopened_parity"]["median"] < 0.9
    assert any(issue["code"] == "render-parity-below-target" for issue in result.issues)


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
