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
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.types import Scope

#: Override for tests and packagers; otherwise resolved from the repo's
#: ``web/dist`` or the packaged ``app/_web_dist`` — see `default_web_dist`.
_ENV_DIST = "EVOFLUX_WEB_DIST"


def default_web_dist() -> Path:
    """Resolve the built web bundle directory.

    Source checkouts use ``<repo>/web/dist``. Packaged desktop bundles ship the
    same build beside the package as ``app/_web_dist``, because ``site-packages``
    has no ``web/`` sibling there. Without that fallback a remote Tailscale
    session proxies to an API-only origin and every browser route falls through
    to the API's 404.
    """
    override = os.environ.get(_ENV_DIST)
    if override:
        return Path(override)
    repo_dist = Path(__file__).resolve().parents[2] / "web" / "dist"
    if (repo_dist / "index.html").is_file():
        return repo_dist
    packaged = Path(__file__).resolve().parents[1] / "_web_dist"
    if (packaged / "index.html").is_file():
        return packaged
    return repo_dist


def _needs_spa_fallback(path: str) -> bool:
    """True when an unknown path should render the SPA rather than 404.

    API paths keep their JSON 404 — a browser route must never paper over a
    missing endpoint — and paths ending in an extension are treated as missing
    static assets so a stale bundle still fails loudly.
    """
    normalized = path.lstrip("/")
    if normalized.startswith("api/"):
        return False
    return "." not in normalized.rsplit("/", 1)[-1]


class _SpaStaticFiles(StaticFiles):
    """``StaticFiles`` that falls back to ``index.html`` for client-side routes."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or not _needs_spa_fallback(path):
                raise
            return await super().get_response("index.html", scope)


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
    app.mount("/", _SpaStaticFiles(directory=str(target), html=True), name="web_ui")
    logger.debug("web_ui_mounted path={}", target)
    return True
