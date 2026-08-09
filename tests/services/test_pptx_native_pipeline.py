from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from pydantic import ValidationError

from app.services import pptx_native_pipeline as pipeline
from app.services.pptx_native_pipeline import (
    compose_native_pptx_project,
    load_native_pptx_project,
    native_pptx_catalog,
    validate_native_pptx_project,
)


def test_native_pptx_schema_keeps_content_in_editable_object_types(
    tmp_path: Path,
) -> None:
    project_path = tmp_path / "deck.json"
    project_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "mode": "new",
                "quality_profile": "native",
                "title": "Native deck",
                "slides": [
                    {
                        "id": "title",
                        "elements": [
                            {
                                "type": "text",
                                "position": {
                                    "left": 80,
                                    "top": 80,
                                    "width": 800,
                                    "height": 120,
                                },
                                "text": "Artifact Fabric",
                                "font_size": 48,
                            },
                            {
                                "type": "chart",
                                "position": {
                                    "left": 80,
                                    "top": 240,
                                    "width": 800,
                                    "height": 360,
                                },
                                "chart_type": "bar",
                                "categories": ["DOCX", "XLSX", "PPTX", "PDF"],
                                "series": [{"name": "Native", "values": [1, 1, 1, 1]}],
                            },
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    project = load_native_pptx_project(project_path)
    value = validate_native_pptx_project(project, project_path)

    assert value["valid"] is True
    assert value["element_count"] == 2
    assert native_pptx_catalog()["supported_elements"] == [
        "text",
        "shape",
        "image",
        "table",
        "chart",
    ]


def test_native_pptx_rejects_out_of_slide_geometry(tmp_path: Path) -> None:
    project_path = tmp_path / "bad.json"
    project_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "mode": "new",
                "quality_profile": "native",
                "title": "Bad deck",
                "width": 1280,
                "height": 720,
                "slides": [
                    {
                        "id": "bad",
                        "elements": [
                            {
                                "type": "text",
                                "position": {
                                    "left": 1200,
                                    "top": 10,
                                    "width": 200,
                                    "height": 40,
                                },
                                "text": "Outside",
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="right slide boundary"):
        load_native_pptx_project(project_path)


def test_fidelity_profile_accepts_static_local_html_and_no_native_elements(
    tmp_path: Path,
) -> None:
    (tmp_path / "slide.html").write_text(
        "<!doctype html><html><body style='margin:0'>Exact slide</body></html>",
        encoding="utf-8",
    )
    project_path = tmp_path / "deck.json"
    project_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "mode": "new",
                "quality_profile": "fidelity",
                "title": "Exact deck",
                "slides": [
                    {
                        "id": "exact",
                        "visual_shell": {
                            "html_path": "slide.html",
                            "alt": "Exact rendered title slide",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    project = load_native_pptx_project(project_path)
    value = validate_native_pptx_project(project, project_path)

    assert value["quality_profile"] == "fidelity"
    assert value["element_count"] == 0
    assert "fidelity" in native_pptx_catalog()["quality_profiles"]


def test_fidelity_profile_accepts_safe_project_local_stylesheet(
    tmp_path: Path,
) -> None:
    theme_dir = tmp_path / "theme"
    theme_dir.mkdir()
    (theme_dir / "dot.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8">'
        '<circle cx="4" cy="4" r="4" fill="#073b82"/></svg>',
        encoding="utf-8",
    )
    (theme_dir / "paper.css").write_text(
        "body{color:#073b82;background-image:url('dot.svg')}", encoding="utf-8"
    )
    (tmp_path / "slide.html").write_text(
        '<!doctype html><html><head><link rel="stylesheet" '
        'href="theme/paper.css"></head><body>Evidence</body></html>',
        encoding="utf-8",
    )
    project_path = tmp_path / "deck.json"
    project_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "mode": "new",
                "quality_profile": "fidelity",
                "title": "Local stylesheet",
                "slides": [
                    {
                        "id": "styled",
                        "visual_shell": {
                            "html_path": "slide.html",
                            "alt": "Research slide using a local stylesheet",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    project = load_native_pptx_project(project_path)

    assert validate_native_pptx_project(project, project_path)["valid"] is True


def test_html_visual_shell_rejects_unsafe_local_stylesheet(tmp_path: Path) -> None:
    (tmp_path / "unsafe.css").write_text(
        '@import url("https://example.com/theme.css");', encoding="utf-8"
    )
    (tmp_path / "slide.html").write_text(
        '<!doctype html><html><head><link rel="stylesheet" '
        'href="unsafe.css"></head><body>Unsafe</body></html>',
        encoding="utf-8",
    )
    project_path = tmp_path / "deck.json"
    project_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "mode": "new",
                "quality_profile": "fidelity",
                "title": "Unsafe stylesheet",
                "slides": [
                    {
                        "id": "unsafe-css",
                        "visual_shell": {
                            "html_path": "slide.html",
                            "alt": "Unsafe stylesheet slide",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    project = load_native_pptx_project(project_path)

    with pytest.raises(ValueError, match="stylesheet contains unsafe CSS"):
        validate_native_pptx_project(project, project_path)


def test_html_visual_shell_rejects_active_or_remote_content(tmp_path: Path) -> None:
    (tmp_path / "unsafe.html").write_text(
        "<script>fetch('https://example.com')</script>", encoding="utf-8"
    )
    project_path = tmp_path / "deck.json"
    project_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "mode": "new",
                "quality_profile": "fidelity",
                "title": "Unsafe deck",
                "slides": [
                    {
                        "id": "unsafe",
                        "visual_shell": {
                            "html_path": "unsafe.html",
                            "alt": "Unsafe slide",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    project = load_native_pptx_project(project_path)
    with pytest.raises(ValueError, match="forbidden <script>"):
        validate_native_pptx_project(project, project_path)


def test_visual_parity_tolerates_round_trip_resampling(tmp_path: Path) -> None:
    reference_path = tmp_path / "reference.png"
    preview_path = tmp_path / "preview.png"
    reference = Image.new("RGB", (1280, 720), "#fbfaf7")
    draw = ImageDraw.Draw(reference)
    draw.rectangle((40, 80, 1240, 650), outline="#a9c3e5", width=2)
    draw.rectangle((40, 80, 1240, 140), fill="#073b82")
    draw.text((70, 98), "EVIDENCE", fill="white")
    reference.save(reference_path)
    reference.resize((1921, 1080), Image.Resampling.LANCZOS).save(preview_path)

    metric = pipeline._visual_parity(
        reference_path,
        preview_path,
        max_changed_pixel_ratio=0.02,
        max_mean_absolute_error=0.01,
    )

    assert metric["passed"] is True
    assert metric["comparison_size"] == [240, 135]
    assert metric["detail_comparison_size"] == [960, 540]


def test_visual_parity_rejects_structural_displacement(tmp_path: Path) -> None:
    reference_path = tmp_path / "reference.png"
    preview_path = tmp_path / "preview.png"
    reference = Image.new("RGB", (1280, 720), "white")
    preview = reference.copy()
    ImageDraw.Draw(reference).rectangle((120, 120, 760, 520), fill="#073b82")
    ImageDraw.Draw(preview).rectangle((220, 120, 860, 520), fill="#073b82")
    reference.save(reference_path)
    preview.save(preview_path)

    metric = pipeline._visual_parity(
        reference_path,
        preview_path,
        max_changed_pixel_ratio=0.02,
        max_mean_absolute_error=0.01,
    )

    assert metric["passed"] is False
    assert metric["changed_pixel_ratio"] > 0.02


@pytest.mark.asyncio
async def test_fidelity_profile_round_trips_html_shell_without_visual_drift(
    tmp_path: Path,
) -> None:
    html = tmp_path / "slide.html"
    html.write_text(
        """<!doctype html>
<html><head><style>
html,body{margin:0;width:1280px;height:720px;overflow:hidden}
body{background:linear-gradient(135deg,#071426,#123b70);color:#fff;
font-family:Arial,sans-serif;display:flex;align-items:center}
main{padding:88px} .eyebrow{color:#5eead4;font-size:22px;font-weight:700}
h1{font-size:72px;line-height:1.02;margin:18px 0 28px;max-width:900px}
p{font-size:28px;color:#cbd5e1;max-width:760px}
.accent{position:absolute;right:90px;bottom:70px;width:230px;height:230px;
border-radius:50%;background:radial-gradient(circle at 35% 30%,#5eead4,#2563eb)}
</style></head><body><main><div class="eyebrow">ARTIFACT FABRIC</div>
<h1>HTML fidelity, valid PowerPoint.</h1><p>Deterministic Chromium visual shell.</p>
</main><div class="accent"></div></body></html>""",
        encoding="utf-8",
    )
    project_path = tmp_path / "deck.json"
    project_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "mode": "new",
                "quality_profile": "fidelity",
                "title": "Fidelity smoke",
                "slides": [
                    {
                        "id": "fidelity",
                        "visual_shell": {
                            "html_path": "slide.html",
                            "alt": "Dark blue Artifact Fabric title slide",
                            "render_scale": 1,
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "fidelity.pptx"

    try:
        result = await compose_native_pptx_project(
            project_path,
            output,
            workspace_root=Path.cwd(),
            work_dir=tmp_path / "work",
        )
    except RuntimeError as exc:
        if "Chromium is required" in str(exc) or "artifact-tool is required" in str(
            exc
        ):
            pytest.skip(str(exc))
        raise

    assert result.passed, result.issues
    assert output.is_file()
    assert len(result.previews) == 1
    assert result.metadata["quality_profile"] == "fidelity"
    assert result.metadata["visual_parity"][0]["passed"] is True


@pytest.mark.asyncio
async def test_native_project_defaults_are_materialized_before_node_worker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project_path = tmp_path / "deck.json"
    project_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "mode": "new",
                "quality_profile": "native",
                "title": "Defaults",
                "slides": [
                    {
                        "id": "defaults",
                        "elements": [
                            {
                                "type": "text",
                                "position": {
                                    "left": 80,
                                    "top": 80,
                                    "width": 600,
                                    "height": 100,
                                },
                                "text": "No undefined style fields",
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    captured: dict = {}

    class FakeWorker:
        async def run(self, action, request, **kwargs):
            captured.update(json.loads(Path(request["projectPath"]).read_text("utf-8")))
            return {
                "outputPath": None,
                "previewPaths": [str(tmp_path / "preview.png")],
                "referencePaths": [None],
                "layoutPaths": [],
                "issues": [],
            }

    monkeypatch.setattr(pipeline, "_WORKER", FakeWorker())

    result = await compose_native_pptx_project(
        project_path,
        tmp_path / "deck.pptx",
        workspace_root=tmp_path,
        work_dir=tmp_path / "work",
    )

    text = captured["slides"][0]["elements"][0]
    assert result.passed
    assert text["line_width"] == 0
    assert text["line_fill"] == "none"
    assert text["auto_fit"] == "shrinkText"


def test_non_rectangular_shape_rejects_border_radius(tmp_path: Path) -> None:
    project_path = tmp_path / "bad-radius.json"
    project_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "mode": "new",
                "quality_profile": "native",
                "title": "Bad radius",
                "slides": [
                    {
                        "id": "bad-radius",
                        "elements": [
                            {
                                "type": "shape",
                                "position": {
                                    "left": 80,
                                    "top": 80,
                                    "width": 200,
                                    "height": 200,
                                },
                                "geometry": "ellipse",
                                "border_radius": 24,
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="rectangular shapes"):
        load_native_pptx_project(project_path)
