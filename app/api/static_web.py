"""Serve the bundled web UI from the sidecar origin.

The desktop shell and a remote Tailscale Serve session both need the SPA
and the API on one origin: the SPA loads first (its ``/``, ``index.html``
and ``assets/*`` requests are token [REDACTED:authorization] in
:mod:`app.core.desktop_auth`), then calls ``/api`` against the same host.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from loguru import logger

#: Override for tests and packagers; defaults to ``<repo>/web/dist``.
_ENV_DIST = "EVOFLUX_WEB_DIST"


def default_web_dist() -> Path:
    """Resolve the built web bundle directory."""
    override = os.environ.get(_ENV_DIST)
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "web" / "dist"


def mount_web_ui(app: FastAPI, *, dist: Path | None = None) -> bool:
    """Mount ``dist`` at ``/`` when it holds a built ``index.html``.

    Returns ``False`` (and mounts nothing) when the bundle is missing, so a
    pure-API dev server never gains a catch-all route. Call this **after**
    every API router is registered: Starlette matches routes in registration
    order and this mount is the catch-all of last resort.
    """
    target = dist if dist is not None else default_web_dist()
    if not (target / "index.html").is_file():
        logger.debug("web_ui_mount_skipped path={}", target)
        return False
    app.mount("/", StaticFiles(directory=str(target), html=True), name="web_ui")
    logger.debug("web_ui_mounted path={}", target)
    return True
