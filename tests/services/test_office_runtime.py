from __future__ import annotations

import hashlib
import os
from pathlib import Path

from app.services.docx_document_pipeline import docx_sha256
from app.services.office import runtime
from app.services.pptx_template_pipeline import pptx_sha256
from app.services.xlsx_artifact_pipeline import xlsx_sha256


def test_file_sha256_matches_whole_file_digest(tmp_path: Path) -> None:
    source = tmp_path / "large-document.bin"
    payload = os.urandom(3 * 1024 * 1024 + 17)
    source.write_bytes(payload)

    assert runtime.file_sha256(source) == hashlib.sha256(payload).hexdigest()


def test_document_pipelines_share_streaming_hash_implementation() -> None:
    assert docx_sha256 is runtime.file_sha256
    assert pptx_sha256 is runtime.file_sha256
    assert xlsx_sha256 is runtime.file_sha256
