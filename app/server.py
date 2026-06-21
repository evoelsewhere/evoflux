"""Uvicorn entry point.

Run with:
    uv run python -m app.server
    # or
    uv run uvicorn app.server:app --reload
"""

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
    )
