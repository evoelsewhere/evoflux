from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

from app.services.office import runtime
from app.services.docx_document_pipeline import docx_sha256
from app.services.pptx_template_pipeline import pptx_sha256
from app.services.xlsx_artifact_pipeline import xlsx_sha256


def _artifact_tool(root: Path) -> Path:
    entrypoint = root / "node_modules" / "@oai" / "artifact-tool" / "dist" / "node"
    entrypoint.mkdir(parents=True)
    target = entrypoint / "artifact_tool.mjs"
    target.write_text("export default null;\n", encoding="utf-8")
    return target


def _executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("runtime placeholder\n", encoding="utf-8")
    return path


def _document_runtime(root: Path) -> dict[str, Path]:
    paths = {
        "node": _executable(root / "node" / "bin" / "node"),
        "artifact_tool": _executable(
            root / "artifact-tool" / "dist" / "node" / "artifact_tool.mjs"
        ),
        "soffice": _executable(root / "libreoffice" / "program" / "soffice"),
        "pdftoppm": _executable(root / "poppler" / "bin" / "pdftoppm"),
        "pdfinfo": _executable(root / "poppler" / "bin" / "pdfinfo"),
        "chromium": _executable(root / "chromium" / "bin" / "chromium"),
        "fontconfig": _executable(root / "fontconfig" / "fonts.conf"),
    }
    fonts = root / "fonts"
    fonts.mkdir()
    manifest = {
        "schema_version": 2,
        "bundle_version": "runtime-test-1",
        "payload_sha256": "abc123",
        "target": {
            "platform": runtime._host_platform(),
            "architecture": runtime._host_architecture(),
        },
        "components": {
            "node": {"version": "v24", "executable": "node/bin/node"},
            "artifact_tool": {
                "version": "2.8.39",
                "entrypoint": "artifact-tool/dist/node/artifact_tool.mjs",
                "distribution_authorized": True,
            },
            "libreoffice": {
                "version": "25.2",
                "executable": "libreoffice/program/soffice",
            },
            "poppler": {
                "version": "26.05",
                "pdftoppm": "poppler/bin/pdftoppm",
                "pdfinfo": "poppler/bin/pdfinfo",
            },
            "chromium": {
                "version": "140.0",
                "executable": "chromium/bin/chromium",
            },
            "fonts": {
                "version": "1",
                "root": "fonts",
                "fontconfig": "fontconfig/fonts.conf",
            },
        },
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return paths


@pytest.fixture(autouse=True)
def _isolate_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Detach every discovery fallback from the developer's real machine."""
    monkeypatch.delenv(runtime.ARTIFACT_TOOL_ENTRYPOINT_ENV, raising=False)
    monkeypatch.delenv(runtime.CHROMIUM_BIN_ENV, raising=False)
    monkeypatch.delenv(runtime.DOCUMENT_RUNTIME_DIR_ENV, raising=False)
    monkeypatch.delenv(runtime.NODE_BIN_ENV, raising=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(runtime, "_repo_root", lambda: tmp_path / "repo")
    empty_path = tmp_path / "empty-path"
    empty_path.mkdir()
    monkeypatch.setenv("PATH", str(empty_path))


def test_file_sha256_matches_whole_file_digest(tmp_path: Path) -> None:
    source = tmp_path / "big.xlsx"
    payload = os.urandom(3 * 1024 * 1024 + 17)
    source.write_bytes(payload)

    assert runtime.file_sha256(source) == hashlib.sha256(payload).hexdigest()


def test_pipeline_hash_names_remain_backward_compatible() -> None:
    assert docx_sha256 is runtime.file_sha256
    assert pptx_sha256 is runtime.file_sha256
    assert xlsx_sha256 is runtime.file_sha256


def test_resolve_executable_prefers_env_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fallback = tmp_path / "fallback-bin"
    fallback.mkdir()
    _executable(fallback / "node")
    override = _executable(tmp_path / "custom-node")
    monkeypatch.setenv(runtime.NODE_BIN_ENV, str(override))

    assert runtime.resolve_executable(
        runtime.NODE_BIN_ENV,
        ("node",),
        fallback_dirs=(fallback,),
        requirement="unused",
    ) == str(override)


def test_resolve_executable_falls_back_to_directories(tmp_path: Path) -> None:
    fallback = tmp_path / "override-bin"
    fallback.mkdir()
    binary = _executable(fallback / "soffice")

    assert runtime.resolve_executable(
        "EVOFLUX_SOFFICE_BIN",
        ("soffice", "libreoffice"),
        fallback_dirs=(fallback,),
        requirement="unused",
    ) == str(binary)


def test_resolve_executable_reports_requirement(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="pdftoppm is missing"):
        runtime.resolve_executable(
            "EVOFLUX_PDFTOPPM_BIN",
            ("pdftoppm",),
            fallback_dirs=(tmp_path / "absent",),
            requirement="pdftoppm is missing",
        )


def test_resolve_artifact_tool_prefers_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    expected = _artifact_tool(workspace)
    _artifact_tool(tmp_path / "repo")

    assert (
        runtime.resolve_artifact_tool(workspace, purpose="testing")
        == expected.resolve()
    )


def test_resolve_artifact_tool_finds_repo_root_install(tmp_path: Path) -> None:
    """Every artifact-tool pipeline sees a repo-root install.

    The per-pipeline copies of this lookup had drifted: only the PPTX version
    searched the repository's own ``node_modules``, so a checkout-local install
    silently failed for XLSX.
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    expected = _artifact_tool(tmp_path / "repo")

    assert (
        runtime.resolve_artifact_tool(workspace, purpose="testing")
        == expected.resolve()
    )


def test_resolve_artifact_tool_appends_hint(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with pytest.raises(RuntimeError) as error:
        runtime.resolve_artifact_tool(
            workspace, purpose="uploaded PPTX templates", hint="No fallback exists."
        )
    message = str(error.value)
    assert "uploaded PPTX templates" in message
    assert message.endswith("No fallback exists.")


def test_resolve_node_binary_uses_codex_runtime_fallback(tmp_path: Path) -> None:
    bundled_dir = runtime.codex_runtime_dependencies() / "node" / "bin"
    bundled_dir.mkdir(parents=True)
    bundled = _executable(bundled_dir / "node")

    assert runtime.resolve_node_binary(purpose="testing") == str(bundled)


def test_bundled_runtime_precedes_host_and_workspace_fallbacks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime_root = tmp_path / "document-runtime"
    bundled = _document_runtime(runtime_root)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _artifact_tool(workspace)
    monkeypatch.setenv(runtime.DOCUMENT_RUNTIME_DIR_ENV, str(runtime_root))

    assert runtime.resolve_node_binary(purpose="testing") == str(
        bundled["node"].resolve()
    )
    assert (
        runtime.resolve_artifact_tool(workspace, purpose="testing")
        == bundled["artifact_tool"].resolve()
    )
    assert runtime.resolve_chromium_binary(purpose="testing") == str(
        bundled["chromium"].resolve()
    )


def test_document_runtime_exports_deterministic_font_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime_root = tmp_path / "document-runtime"
    bundled = _document_runtime(runtime_root)
    monkeypatch.setenv(runtime.DOCUMENT_RUNTIME_DIR_ENV, str(runtime_root))

    env = runtime.document_runtime_subprocess_env()
    diagnostics = runtime.document_runtime_diagnostics()

    assert env["EVOFLUX_DOCUMENT_RUNTIME_DIR"] == str(runtime_root.resolve())
    assert env["EVOFLUX_CHROMIUM_BIN"] == str(bundled["chromium"].resolve())
    assert env["FONTCONFIG_FILE"] == str(bundled["fontconfig"].resolve())
    assert env["SAL_FONTPATH"] == str((runtime_root / "fonts").resolve())
    assert diagnostics["available"] is True
    assert diagnostics["bundle_version"] == "runtime-test-1"
    assert diagnostics["components"]["libreoffice"]["version"] == "25.2"


def test_explicit_invalid_document_runtime_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(runtime.DOCUMENT_RUNTIME_DIR_ENV, str(tmp_path / "missing"))

    with pytest.raises(RuntimeError, match=runtime.DOCUMENT_RUNTIME_DIR_ENV):
        runtime.resolve_node_binary(purpose="testing")


def test_resolve_node_binary_reports_env_override(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match=runtime.NODE_BIN_ENV):
        runtime.resolve_node_binary(purpose="XLSX authoring")


def _worker_runtime(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, script: str
) -> runtime.NodeWorkerRuntime:
    monkeypatch.setenv(
        runtime.ARTIFACT_TOOL_ENTRYPOINT_ENV,
        str(_artifact_tool(tmp_path / "workspace-tool")),
    )
    monkeypatch.setenv(runtime.NODE_BIN_ENV, sys.executable)
    worker_path = tmp_path / "worker.py"
    worker_path.write_text(script, encoding="utf-8")
    return runtime.NodeWorkerRuntime(
        worker=worker_path,
        label="XLSX",
        purpose="XLSX authoring",
    )


@pytest.mark.asyncio
async def test_worker_run_returns_last_json_object(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    worker = _worker_runtime(
        monkeypatch,
        tmp_path,
        'print("progress noise")\n'
        "print('[\"not an object\"]')\n"
        'print(\'{"outputPath": "book.xlsx"}\')\n',
    )
    work_dir = tmp_path / "work"

    value = await worker.run(
        "compose",
        {"sheet": "Inputs"},
        workspace_root=tmp_path,
        work_dir=work_dir,
    )

    assert value == {"outputPath": "book.xlsx"}
    request = json.loads((work_dir / "compose-request.json").read_text("utf-8"))
    assert request == {"sheet": "Inputs"}


@pytest.mark.asyncio
async def test_worker_run_surfaces_stderr_on_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    worker = _worker_runtime(
        monkeypatch,
        tmp_path,
        'import sys\nprint("range A1 is malformed", file=sys.stderr)\nsys.exit(1)\n',
    )

    with pytest.raises(RuntimeError, match="range A1 is malformed"):
        await worker.run(
            "render",
            {},
            workspace_root=tmp_path,
            work_dir=tmp_path / "work",
        )


@pytest.mark.asyncio
async def test_worker_run_rejects_unparseable_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    worker = _worker_runtime(monkeypatch, tmp_path, 'print("plain text only")\n')

    with pytest.raises(RuntimeError, match="XLSX worker returned invalid JSON"):
        await worker.run(
            "inspect",
            {},
            workspace_root=tmp_path,
            work_dir=tmp_path / "work",
        )


@pytest.mark.asyncio
async def test_worker_run_kills_a_hung_worker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    worker = _worker_runtime(monkeypatch, tmp_path, "import time\ntime.sleep(30)\n")

    with pytest.raises(RuntimeError, match="XLSX inspect exceeded 1 seconds"):
        await worker.run(
            "inspect",
            {},
            workspace_root=tmp_path,
            work_dir=tmp_path / "work",
            timeout_seconds=1,
        )
