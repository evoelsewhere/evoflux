"""Shared builders for the ``terminal-processes`` contract (temp workspaces only)."""

from __future__ import annotations

import os
import re
import socket
from pathlib import Path
from typing import Any

UNAUTHORIZED_BODY = {"detail": "Unauthorized — EvoFlux access key required."}


def free_port() -> int:
    """A TCP port nothing listens on right now (bound and released)."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def port_open(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


class Scrub:
    """Replace the temp dir in JSON-able values and fold path separators."""

    def __init__(self, tmp: Path) -> None:
        self._roots = {str(tmp), str(tmp.resolve())}

    def text(self, value: str) -> str:
        for root in self._roots:
            pattern = re.escape(root) + r"[^\s'\"<>|?*:]*"
            value = re.sub(
                pattern,
                lambda m: m.group(0).replace(root, "<tmp>").replace("\\", "/"),
                value,
            )
        return value

    def __call__(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, list):
            return [self(item) for item in value]
        if isinstance(value, dict):
            return {key: self(item) for key, item in value.items()}
        return value


def same_path(left: str | Path, right: str | Path) -> bool:
    """Equal after link resolution and (on Windows) case folding."""
    return os.path.normcase(os.path.realpath(left)) == os.path.normcase(
        os.path.realpath(right)
    )
