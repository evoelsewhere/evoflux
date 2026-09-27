"""Shared fixtures for remote-use tests: a stub ``tailscale`` CLI, no network.

The service resolves the CLI through ``EVOFLUX_TAILSCALE_BIN`` first, so the
stub script answers every invocation locally. Behaviour is steered with files
inside the stub directory:

- ``status.json`` / ``serve.json`` — canned payloads for ``status --json``
  and ``serve status --json``;
- ``status.fail`` / ``serve.fail`` / ``enable.fail`` / ``reset.fail`` —
  contents go to stderr and force a non-zero exit;
- ``calls.log`` — every argv the service passed, for exact-call assertions;
- ``enable.target`` — the ``serve --bg`` target that was requested.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi import FastAPI, Request

from app.core.desktop_auth import DesktopTokenMiddleware, remote_session_login
from app.services import remote_use_service as remote_use_service

DEFAULT_STATUS: dict = {
    "BackendState": "Running",
    "CertDomains": ["machine.tailnet-example.ts.net"],
    "Health": [],
}

DEFAULT_SERVE: dict = {
    "TCP": {"443": {"HTTPS": True}},
    "Web": {
        "https://machine.tailnet-example.ts.net:443": {
            "Handlers": {"/": {"Proxy": "http://127.0.0.1:4082"}}
        }
    },
}

_WINDOWS_STUB = r"""@echo off
setlocal
set DIR=%~dp0
>>"%DIR%calls.log" echo %*
if /I "%~1"=="status" goto status
if /I "%~1"=="serve" goto serve
echo unexpected args1>&2
exit /b 2

:status
if exist "%DIR%status.fail" goto status_fail
type "%DIR%status.json"
exit /b 0
:status_fail
type "%DIR%status.fail" 1>&2
exit /b 1

:serve
if /I "%~2"=="status" goto serve_status
if /I "%~2"=="--bg" goto serve_bg
if /I "%~2"=="reset" goto serve_reset
echo unexpected serve args1>&2
exit /b 2

:serve_status
if exist "%DIR%serve.fail" goto serve_status_fail
type "%DIR%serve.json"
exit /b 0
:serve_status_fail
type "%DIR%serve.fail" 1>&2
exit /b 1

:serve_bg
echo %~3> "%DIR%enable.target"
if exist "%DIR%enable.fail" goto serve_bg_fail
exit /b 0
:serve_bg_fail
type "%DIR%enable.fail" 1>&2
exit /b 1

:serve_reset
if exist "%DIR%reset.fail" goto serve_reset_fail
exit /b 0
:serve_reset_fail
type "%DIR%reset.fail" 1>&2
exit /b 1
"""

_POSIX_STUB = """#!/bin/sh
DIR=$(dirname "$0")
echo "$@" >> "$DIR/calls.log"
case "$1" in
  status)
    if [ -f "$DIR/status.fail" ]; then cat "$DIR/status.fail" >&2; exit 1; fi
    cat "$DIR/status.json"
    ;;
  serve)
    case "$2" in
      status)
        if [ -f "$DIR/serve.fail" ]; then cat "$DIR/serve.fail" >&2; exit 1; fi
        cat "$DIR/serve.json"
        ;;
      --bg)
        printf '%s\\n' "$3" > "$DIR/enable.target"
        if [ -f "$DIR/enable.fail" ]; then cat "$DIR/enable.fail" >&2; exit 1; fi
        ;;
      reset)
        if [ -f "$DIR/reset.fail" ]; then cat "$DIR/reset.fail" >&2; exit 1; fi
        ;;
      *)
        echo "unexpected serve args" >&2
        exit 2
        ;;
    esac
    ;;
  *)
    echo "unexpected args" >&2
    exit 2
    ;;
esac
exit 0
"""


@pytest.fixture
def tailscale_stub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Install the fake tailscale CLI; returns its directory (see module doc)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "status.json").write_text(json.dumps(DEFAULT_STATUS), encoding="utf-8")
    (bin_dir / "serve.json").write_text(json.dumps(DEFAULT_SERVE), encoding="utf-8")
    if os.name == "nt":
        script = bin_dir / "tailscale.cmd"
        script.write_text(_WINDOWS_STUB.replace("\n", "\r\n"), encoding="utf-8")
    else:
        script = bin_dir / "tailscale"
        script.write_text(_POSIX_STUB, encoding="utf-8")
        script.chmod(0o755)
    monkeypatch.setenv(remote_use_service.TAILSCALE_BIN_ENV, str(script))
    return bin_dir


@pytest.fixture
def identity_app() -> FastAPI:
    """Minimal app with the identity hook and probe routes."""
    app = FastAPI()
    app.add_middleware(DesktopTokenMiddleware)

    @app.get("/api/_probe/whoami")
    async def whoami(request: Request) -> dict:  # noqa: F821
        return {"login": remote_session_login(request)}  # noqa: F821

    @app.get("/assets/app.js")
    async def asset(request: Request) -> dict:  # noqa: F821
        return {"login": remote_session_login(request)}  # noqa: F821

    return app


@pytest.fixture
def token_app() -> FastAPI:
    """Same probe app, but with a configured desktop bearer token."""
    app = FastAPI()
    app.add_middleware(DesktopTokenMiddleware, expected_token="sekrit")

    @app.get("/api/_probe/whoami")
    async def whoami(request: Request) -> dict:  # noqa: F821
        return {"login": remote_session_login(request)}  # noqa: F821

    return app
