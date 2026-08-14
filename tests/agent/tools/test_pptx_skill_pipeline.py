from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

from PIL import Image

from app.plugin_platform.builtins import builtin_plugins_root


STYLE_PREVIEW_NAMES = {
    "clean-professional",
    "creative-magazine",
    "data-dashboard",
    "e-ink-magazine",
    "handdrawn-technical",
    "handdrawn-whiteboard",
    "mckinsey-style",
    "party-government-red",
    "retro-flat-illustration",
    "scientific-defense",
    "teaching-courseware",
    "warm-handmade",
}


def _pptx_skill_root() -> Path:
    return builtin_plugins_root() / "documents" / "skills" / "pptx"


def _run_validator(project: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(_pptx_skill_root() / "scripts" / "validate_html_svg_project.py"),
            str(project),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def _example_project(tmp_path: Path) -> Path:
    project_dir = tmp_path / "project"
    shutil.copytree(_pptx_skill_root() / "examples", project_dir)
    return project_dir / "project.example.json"


def test_pptx_html_svg_project_example_is_valid(tmp_path: Path) -> None:
    result = _run_validator(_example_project(tmp_path))

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["valid"] is True
    assert payload["schema_version"] == 8
    assert payload["canvas"] == {"width": 1280, "height": 720, "unit": "CSS px"}
    assert payload["slides"][0]["editable_counts"] == {
        "chart": 0,
        "image": 0,
        "shape": 1,
        "svg": 1,
        "table": 0,
        "text": 3,
    }
    assert payload["render_surfaces"] == "unverified"


def test_pptx_html_svg_project_rejects_network_urls(tmp_path: Path) -> None:
    project = _example_project(tmp_path)
    html = project.with_name("slide.example.html")
    html.write_text(
        html.read_text(encoding="utf-8").replace(
            "</section>", '<img src="https://example.test/remote.png"></section>'
        ),
        encoding="utf-8",
    )

    result = _run_validator(project)

    assert result.returncode == 1
    assert "network or executable URL" in json.loads(result.stdout)["error"]


def test_pptx_html_svg_project_rejects_foreign_object_in_editable_svg(
    tmp_path: Path,
) -> None:
    project = _example_project(tmp_path)
    html = project.with_name("slide.example.html")
    html.write_text(
        html.read_text(encoding="utf-8").replace(
            '<circle cx="180" cy="180" r="150" fill="#152547" />',
            '<foreignObject x="0" y="0" width="100" height="100"><div>HTML</div></foreignObject>',
        ),
        encoding="utf-8",
    )

    result = _run_validator(project)

    assert result.returncode == 1
    assert "foreignObject" in json.loads(result.stdout)["error"]


def test_pptx_style_previews_are_english_and_match_rendered_assets() -> None:
    root = _pptx_skill_root()
    source_dir = root / "examples" / "style-previews"
    asset_dir = root / "assets" / "style-previews"
    sources = {path.stem: path for path in source_dir.glob("*.html")}
    assets = {path.stem: path for path in asset_dir.glob("*.webp")}

    assert sources.keys() == STYLE_PREVIEW_NAMES
    assert assets.keys() == STYLE_PREVIEW_NAMES

    cjk = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
    for name, source in sources.items():
        assert cjk.search(source.read_text(encoding="utf-8")) is None, name

    for name, asset in assets.items():
        with Image.open(asset) as image:
            assert image.size == (640, 360), name


def test_pptx_skill_uses_conditional_vision_qa_without_office_suite_fallback() -> None:
    root = _pptx_skill_root()
    text_suffixes = {".css", ".html", ".json", ".md", ".py", ".yaml"}
    corpus = "\n".join(
        path.read_text(encoding="utf-8")
        for path in root.rglob("*")
        if path.is_file() and path.suffix.casefold() in text_suffixes
    )

    assert "LibreOffice" not in corpus
    assert "When the active model can inspect images" in corpus
    assert "skipped (capability unavailable)" in corpus
    assert "do not simulate visual inspection" in corpus
