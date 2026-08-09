from __future__ import annotations

from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from app.services import docx_document_pipeline
from app.services.office import rendering


@pytest.fixture(autouse=True)
def _isolate_binaries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "")
    monkeypatch.delenv(rendering.SOFFICE_BIN_ENV, raising=False)
    monkeypatch.delenv(rendering.PDFTOPPM_BIN_ENV, raising=False)
    monkeypatch.delenv("EVOFLUX_DOCUMENT_RUNTIME_DIR", raising=False)
    monkeypatch.setattr(
        rendering, "codex_runtime_dependencies", lambda: Path("/nowhere")
    )
    monkeypatch.setattr(rendering, "host_binary_dirs", lambda: ())


def test_renderer_is_unavailable_without_libreoffice() -> None:
    assert rendering.renderer_available() is False


def test_renderer_is_available_once_both_binaries_resolve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    soffice = tmp_path / "soffice"
    pdftoppm = tmp_path / "pdftoppm"
    for binary in (soffice, pdftoppm):
        binary.write_text("runtime placeholder\n", encoding="utf-8")
    monkeypatch.setenv(rendering.SOFFICE_BIN_ENV, str(soffice))
    monkeypatch.setenv(rendering.PDFTOPPM_BIN_ENV, str(pdftoppm))

    assert rendering.renderer_available() is True


def test_renderer_prefers_bundled_binaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    soffice = tmp_path / "runtime" / "soffice"
    pdftoppm = tmp_path / "runtime" / "pdftoppm"
    for binary in (soffice, pdftoppm):
        binary.parent.mkdir(parents=True, exist_ok=True)
        binary.write_text("bundled\n", encoding="utf-8")
    monkeypatch.setattr(
        rendering,
        "resolve_document_runtime",
        lambda: SimpleNamespace(soffice=soffice, pdftoppm=pdftoppm),
    )

    assert rendering.find_render_binary(
        rendering.SOFFICE_BIN_ENV, ("soffice", "libreoffice")
    ) == str(soffice.resolve())
    assert rendering.find_render_binary(
        rendering.PDFTOPPM_BIN_ENV, ("pdftoppm",)
    ) == str(pdftoppm.resolve())


def test_render_pages_reports_a_conversion_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rendering, "find_render_binary", lambda *a, **k: "/bin/true")

    def failed_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(command, 1, "", "LibreOffice exploded")

    monkeypatch.setattr(subprocess, "run", failed_run)

    pages, issues = rendering.render_pages(
        tmp_path / "deck.pptx", tmp_path / "out", code_prefix="pptx"
    )

    assert pages == []
    # The code prefix identifies the caller, so DOCX and PPTX stay distinguishable.
    assert issues == [
        {
            "severity": "error",
            "code": "pptx-render-failed",
            "message": "LibreOffice exploded",
        }
    ]


def test_render_pages_passes_a_portable_profile_uri(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rendering, "find_render_binary", lambda *a, **k: "binary")
    source = tmp_path / "deck.pptx"
    seen_command: list[str] = []

    def failed_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        seen_command.extend(command)
        return subprocess.CompletedProcess(command, 1, "", "expected failure")

    monkeypatch.setattr(subprocess, "run", failed_run)

    rendering.render_pages(source, tmp_path / "path with spaces", code_prefix="pptx")

    profile_arg = next(
        arg for arg in seen_command if arg.startswith("-env:UserInstallation=")
    )
    assert profile_arg.startswith("-env:UserInstallation=file://")
    assert "path%20with%20spaces" in profile_arg
    assert "\\" not in profile_arg


def test_render_pages_reports_a_raster_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rendering, "find_render_binary", lambda *a, **k: "/bin/true")
    source = tmp_path / "deck.pptx"

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        if "--convert-to" in command:
            outdir = Path(command[command.index("--outdir") + 1])
            (outdir / f"{source.stem}.pdf").write_bytes(b"%PDF-1.4")
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(command, 1, "", "pdftoppm exploded")

    monkeypatch.setattr(subprocess, "run", run)

    pages, issues = rendering.render_pages(source, tmp_path / "out", code_prefix="docx")

    assert pages == []
    assert issues[0]["code"] == "docx-raster-failed"


def test_render_pages_passes_bundled_font_environment_to_both_processes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rendering, "find_render_binary", lambda *a, **k: "binary")
    monkeypatch.setattr(
        rendering,
        "document_runtime_subprocess_env",
        lambda: {"FONTCONFIG_FILE": "/runtime/fonts.conf", "SAL_FONTPATH": "/fonts"},
    )
    source = tmp_path / "deck.pptx"
    seen_envs: list[dict[str, str]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        seen_envs.append(kwargs["env"])  # type: ignore[arg-type]
        if "--convert-to" in command:
            outdir = Path(command[command.index("--outdir") + 1])
            (outdir / f"{source.stem}.pdf").write_bytes(b"%PDF-1.4")
        else:
            Path(f"{command[-1]}-1.png").write_bytes(b"png")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", run)

    pages, issues = rendering.render_pages(source, tmp_path / "out", code_prefix="pptx")

    assert issues == []
    assert len(pages) == 1
    assert len(seen_envs) == 2
    assert all(env["FONTCONFIG_FILE"] == "/runtime/fonts.conf" for env in seen_envs)
    assert all(env["SAL_FONTPATH"] == "/fonts" for env in seen_envs)


def test_docx_pipeline_delegates_to_the_shared_renderer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The DOCX pipeline keeps its issue codes now that rendering is shared."""

    seen: dict[str, object] = {}

    def fake_render_pages(
        source: Path, render_dir: Path, *, code_prefix: str, dpi: int = 144
    ) -> tuple[list[Path], list[dict[str, object]]]:
        seen.update({"source": source, "code_prefix": code_prefix, "dpi": dpi})
        return [render_dir / "page-001.png"], []

    monkeypatch.setattr(docx_document_pipeline, "render_pages", fake_render_pages)

    pages, issues = docx_document_pipeline.render_docx_pages(
        tmp_path / "letter.docx", tmp_path / "previews"
    )

    assert issues == []
    assert pages == [tmp_path / "previews" / "page-001.png"]
    assert seen["code_prefix"] == "docx"
    assert seen["dpi"] == 144
