from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys
import textwrap

from app.agent.builtin_plugins.documents.engines.docx import docx_sha256
from app.agent.builtin_plugins.documents.engines.pptx_template import pptx_sha256
from app.agent.builtin_plugins.documents.engines.xlsx import xlsx_sha256
from app.agent.builtin_plugins.documents.rendering import runtime


def test_file_sha256_matches_whole_file_digest(tmp_path: Path) -> None:
    source = tmp_path / "large-document.bin"
    payload = os.urandom(3 * 1024 * 1024 + 17)
    source.write_bytes(payload)

    assert runtime.file_sha256(source) == hashlib.sha256(payload).hexdigest()


def test_document_pipelines_share_streaming_hash_implementation() -> None:
    assert docx_sha256 is runtime.file_sha256
    assert pptx_sha256 is runtime.file_sha256
    assert xlsx_sha256 is runtime.file_sha256


def test_artifact_service_initializes_without_document_engines(tmp_path: Path) -> None:
    script = textwrap.dedent(
        """
        import builtins
        from pathlib import Path
        import sys

        original_import = builtins.__import__
        blocked_roots = {
            "PIL",
            "docx",
            "openpyxl",
            "pdfplumber",
            "pptx",
            "pypdf",
            "pypdfium2",
            "reportlab",
        }

        def reject_document_engines(name, globals=None, locals=None, fromlist=(), level=0):
            root = name.partition(".")[0]
            if (
                root in blocked_roots
                or name.startswith("app.agent.builtin_plugins.documents.engines")
            ):
                raise ModuleNotFoundError(f"blocked optional dependency: {name}")
            return original_import(name, globals, locals, fromlist, level)

        builtins.__import__ = reject_document_engines

        from app.agent.builtin_plugins.documents.runtime import artifact_drivers
        from app.artifacts.service import ArtifactService
        from app.artifacts.storage import ArtifactStore

        drivers = artifact_drivers()
        assert {driver.format for driver in drivers} == {"docx", "xlsx", "pptx", "pdf"}

        service = ArtifactService(store=ArtifactStore(Path(sys.argv[1])))
        assert {
            service.registry.get(name).format
            for name in ("docx", "xlsx", "pptx", "pdf")
        } == {"docx", "xlsx", "pptx", "pdf"}
        catalog = service.catalog()
        assert set(catalog["formats"]) == {"docx", "xlsx", "pptx", "pdf"}
        assert all(
            item["available"] is False
            and item["required_extra"] == "documents"
            for item in catalog["formats"].values()
        )
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path / "artifacts")],
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
