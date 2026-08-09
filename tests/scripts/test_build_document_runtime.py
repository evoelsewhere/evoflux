from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import tarfile

import pytest

from scripts.build_document_runtime import (
    DocumentRuntimeError,
    assemble_document_runtime,
    stage_document_runtime,
    verify_document_runtime,
)


def _file(path: Path, content: str = "runtime\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _component_sources(root: Path) -> dict[str, Path]:
    node = root / "node-source"
    _file(node / "bin" / "node")
    _file(node / "LICENSE", "Node license\n")

    artifact_tool = root / "artifact-source"
    _file(
        artifact_tool / "package.json",
        json.dumps({"name": "@oai/artifact-tool", "version": "9.8.7"}),
    )
    _file(artifact_tool / "dist" / "node" / "artifact_tool.mjs")
    _file(artifact_tool / "LICENSE.md", "Authorized test license\n")

    chromium = root / "chromium-source"
    _file(chromium / "bin" / "chromium")
    _file(chromium / "LICENSE", "Chromium BSD license\n")

    libreoffice = root / "libreoffice-source"
    _file(libreoffice / "program" / "soffice")
    _file(libreoffice / "COPYING", "LibreOffice license\n")

    poppler = root / "poppler-source"
    _file(poppler / "bin" / "pdftoppm")
    _file(poppler / "bin" / "pdfinfo")
    _file(poppler / "COPYING", "Poppler license\n")

    fonts = root / "font-source"
    _file(fonts / "InstrumentSans-Regular.ttf", "fake-font\n")
    _file(fonts / "InstrumentSans-OFL.txt", "OFL license\n")
    return {
        "node": node,
        "artifact_tool": artifact_tool,
        "chromium": chromium,
        "libreoffice": libreoffice,
        "poppler": poppler,
        "fonts": fonts,
    }


def _assemble(
    root: Path, *, authorized: bool = True, node_version: str = "v24.1.0"
) -> Path:
    sources = _component_sources(root / "sources")
    output = root / "document-runtime"
    assemble_document_runtime(
        out=output,
        bundle_version="2026.08.test",
        node_root=sources["node"],
        artifact_tool_root=sources["artifact_tool"],
        artifact_tool_distribution_authorized=authorized,
        chromium_root=sources["chromium"],
        libreoffice_root=sources["libreoffice"],
        poppler_root=sources["poppler"],
        fonts_root=sources["fonts"],
        node_version=node_version,
        chromium_version="Chromium 140.0.0",
        libreoffice_version="LibreOffice 25.2",
        poppler_version="pdftoppm 26.05",
    )
    return output


def test_assemble_writes_a_complete_versioned_manifest(tmp_path: Path) -> None:
    runtime = _assemble(tmp_path)

    manifest = verify_document_runtime(runtime, deep=True)

    assert manifest["bundle_version"] == "2026.08.test"
    assert set(manifest["components"]) == {
        "node",
        "artifact_tool",
        "chromium",
        "libreoffice",
        "poppler",
        "fonts",
    }
    assert manifest["components"]["artifact_tool"]["version"] == "9.8.7"
    assert manifest["components"]["artifact_tool"]["distribution_authorized"]
    assert manifest["components"]["fonts"]["font_count"] == 1
    assert (runtime / "fontconfig" / "fonts.conf").is_file()


def test_assemble_refuses_unlicensed_artifact_tool_distribution(tmp_path: Path) -> None:
    with pytest.raises(DocumentRuntimeError, match="redistribution was not authorized"):
        _assemble(tmp_path, authorized=False)


def test_assemble_rejects_unsupported_node_version(tmp_path: Path) -> None:
    with pytest.raises(DocumentRuntimeError, match=r"Node.js 20\+"):
        _assemble(tmp_path, node_version="v18.20.0")


def test_verify_detects_payload_tampering(tmp_path: Path) -> None:
    runtime = _assemble(tmp_path)
    (runtime / "artifact-tool" / "dist" / "node" / "artifact_tool.mjs").write_text(
        "tampered\n", encoding="utf-8"
    )

    with pytest.raises(DocumentRuntimeError, match="artifact_tool checksum"):
        verify_document_runtime(runtime, deep=True)


def test_stage_archive_requires_and_verifies_external_checksum(tmp_path: Path) -> None:
    runtime = _assemble(tmp_path / "build")
    archive = tmp_path / "document-runtime.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        output.add(runtime, arcname="document-runtime")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()

    with pytest.raises(DocumentRuntimeError, match="SHA-256 is required"):
        stage_document_runtime(archive, tmp_path / "missing-checksum")

    staged = tmp_path / "staged"
    manifest = stage_document_runtime(
        archive,
        staged,
        expected_sha256=digest,
    )

    assert manifest["bundle_version"] == "2026.08.test"
    assert (staged / "node" / "bin" / "node").is_file()


def test_stage_rejects_archive_path_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "malicious.tar.gz"
    payload = b"must-not-escape"
    with tarfile.open(archive, "w:gz") as output:
        member = tarfile.TarInfo("../escaped.txt")
        member.size = len(payload)
        output.addfile(member, io.BytesIO(payload))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()

    with pytest.raises(DocumentRuntimeError, match="unsafe archive path"):
        stage_document_runtime(
            archive,
            tmp_path / "staged",
            expected_sha256=digest,
        )

    assert not (tmp_path / "escaped.txt").exists()
