from __future__ import annotations

import hashlib
import os
from pathlib import Path
from app.agent.builtin_plugins.documents.rendering import runtime


def test_file_sha256_matches_whole_file_digest(tmp_path: Path) -> None:
    source = tmp_path / "large-document.bin"
    payload = os.urandom(3 * 1024 * 1024 + 17)
    source.write_bytes(payload)

    assert runtime.file_sha256(source) == hashlib.sha256(payload).hexdigest()
