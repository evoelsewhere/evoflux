"""Helpers for launching the uvicorn server subprocess."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


def _resolve_uvicorn() -> list[str]:
    """Pick the right uvicorn invocation for the current install.

    1. Sibling of ``sys.executable`` — works for both ``uv tool install``
       wheels (``~/.local/share/uv/tools/EvoFlux/bin/uvicorn``) and
       plain venvs (``.venv/bin/uvicorn``). This is the common case for
       end users.
    2. ``shutil.which("uvicorn")`` — covers source-checkout dev where
       the user activated their venv themselves.
    3. ``[sys.executable, "-m", "uvicorn"]`` — last-resort fallback so
       we never crash with FileNotFoundError, even on weirdly-shimmed
       installs.

    Note: we deliberately do *not* use ``uv run uvicorn``. ``uv run``
    adds a wrapper process between the daemon parent and the actual
    server, breaking PID-based stop logic and signal propagation.
    """
    sibling = Path(sys.executable).with_name("uvicorn")
    if sibling.is_file():
        return [str(sibling)]
    found = shutil.which("uvicorn")
    if found:
        return [found]
    return [sys.executable, "-m", "uvicorn"]


def _server_cmd(*, host: str, port: int) -> list[str]:
    return [
        *_resolve_uvicorn(),
        "app.server:app",
        "--host",
        host,
        "--port",
        str(port),
    ]
