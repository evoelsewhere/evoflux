"""Uvicorn entry point.

Run with:
    uv run python -m app.server
    # or
    uv run uvicorn app.server:app --reload
"""

import asyncio
import sys

from app._onnx_preload import preload_onnxruntime

if sys.platform == "win32":
    # Preload onnxruntime's native DLLs before importing other C extensions
    # (truststore/_ssl, SQLAlchemy's Cython modules, …). Otherwise, on
    # Python 3.14, loading onnxruntime.dll as a static dependency later runs its
    # DllMain under the loader lock and fails with an initialisation error
    # (1114). No-op when onnxruntime is not installed.
    preload_onnxruntime()
    # asyncio defaults to ProactorEventLoop on Windows, but Uvicorn's --reload
    # mode can leave a SelectorEventLoop active in the worker process;
    # asyncio.create_subprocess_exec() then raises NotImplementedError, breaking
    # browser_use and shell tools. Force ProactorEventLoop explicitly via policy
    # AND replace the current default loop so uvicorn picks it up.
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())  # type: ignore[attr-defined]
    # Pre-create a ProactorEventLoop and install it as the current loop so that
    # uvicorn (which calls asyncio.get_event_loop() or new_event_loop() under
    # the hood) always ends up with a subprocess-capable loop.
    _proactor_loop = asyncio.ProactorEventLoop()  # type: ignore[attr-defined]
    asyncio.set_event_loop(_proactor_loop)

import truststore  # noqa: F401 — patches ssl to use OS cert store

import uvicorn

from app.api.app import create_app
from app.core.config import settings
from app.core.logging_config import setup_logging
from app.core.ssl_patch import apply_ssl_patch

setup_logging(
    settings.LOG_LEVEL
)  # configure sinks before anything else imports the logger

apply_ssl_patch()

app = create_app()

if __name__ == "__main__":
    uvicorn.run(
        "app.server:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=settings.API_RELOAD,
        loop="asyncio",
    )
