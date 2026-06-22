"""Uvicorn entry point.

Run with:
    uv run python -m app.server
    # or
    uv run uvicorn app.server:app --reload
"""

import asyncio
import sys

import truststore  # noqa: F401 — patches ssl to use OS cert store

# On Windows, asyncio defaults to ProactorEventLoop since Python 3.8, but
# Uvicorn's --reload mode can inadvertently leave a SelectorEventLoop active
# in the worker process.  asyncio.create_subprocess_exec() raises
# NotImplementedError with SelectorEventLoop, breaking shell/python tools.
# Setting the policy explicitly here guarantees ProactorEventLoop.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())  # type: ignore[attr-defined]

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
    )
