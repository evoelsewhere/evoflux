"""Tests for app/core/logging_config.py."""

import logging
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.core.logging_config import setup_logging, LOGS_DIR


def test_logs_dir_is_path():
    assert isinstance(LOGS_DIR, Path)


def test_setup_logging_creates_logs_dir(tmp_path):
    with (
        patch("app.core.logging_config.LOGS_DIR", tmp_path),
        patch("app.core.logging_config.logger") as mock_logger,
    ):
        mock_logger.remove = MagicMock()
        mock_logger.add = MagicMock()

        setup_logging("INFO")

        assert tmp_path.exists()
        mock_logger.remove.assert_called_once()
        assert mock_logger.add.call_count == 2  # stderr + app.log


def test_setup_logging_uses_level(tmp_path):
    calls = []
    with (
        patch("app.core.logging_config.LOGS_DIR", tmp_path),
        patch("app.core.logging_config.logger") as mock_logger,
    ):
        mock_logger.remove = MagicMock()

        def capture_add(*args, **kwargs):
            calls.append(kwargs)

        mock_logger.add = capture_add
        setup_logging("DEBUG")

    # First sink is stderr — level should be "DEBUG"
    assert calls[0]["level"] == "DEBUG"
    # Explicit DEBUG is the only mode that enables verbose persistent logs.
    assert calls[1]["level"] == "DEBUG"


def test_setup_logging_keeps_persistent_log_compact(tmp_path):
    calls = []
    with (
        patch("app.core.logging_config.LOGS_DIR", tmp_path),
        patch("app.core.logging_config.logger") as mock_logger,
    ):
        mock_logger.remove = MagicMock()

        def capture_add(*args, **kwargs):
            calls.append(kwargs)

        mock_logger.add = capture_add
        setup_logging("INFO")

    assert calls[1]["level"] == "WARNING"
    assert calls[1]["rotation"] == "5 MB"
    assert calls[1]["retention"] == 3
    assert calls[1]["compression"] == "gz"


def test_setup_logging_silences_noisy_loggers(tmp_path):
    with (
        patch("app.core.logging_config.LOGS_DIR", tmp_path),
        patch("app.core.logging_config.logger") as mock_logger,
    ):
        mock_logger.remove = MagicMock()
        mock_logger.add = MagicMock()
        setup_logging()

    for name in (
        "aiosqlite",
        "asyncio",
        "google.genai",
        "httpcore",
        "httpcore2",
        "httpx",
        "httpx2",
        "multipart",
        "uvicorn",
        "uvicorn.access",
        "uvicorn.error",
        "watchfiles.main",
        "watchfiles.watcher",
    ):
        assert logging.getLogger(name).level == logging.WARNING


def test_setup_logging_default_level_is_info(tmp_path):
    calls = []
    with (
        patch("app.core.logging_config.LOGS_DIR", tmp_path),
        patch("app.core.logging_config.logger") as mock_logger,
    ):
        mock_logger.remove = MagicMock()

        def capture_add(*args, **kwargs):
            calls.append(kwargs)

        mock_logger.add = capture_add
        setup_logging()  # default

    assert calls[0]["level"] == "INFO"


def test_setup_logging_console_is_plain_dated_and_hides_locals(tmp_path, monkeypatch):
    """backend.log is the sidecar's redirected stderr: no ANSI escapes, a full
    date with UTC offset, and tracebacks without local variable values."""
    import io
    import re
    import sys

    from loguru import logger

    stream = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stream)
    monkeypatch.setattr("app.core.logging_config.APP_LOG_DIR", tmp_path)
    setup_logging("INFO")
    try:
        secret = "tok-should-not-be-logged"
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            logger.exception("probe_failed key={}", len(secret))
    finally:
        logger.remove()
        logger.add(sys.__stderr__)

    out = stream.getvalue()
    assert "\x1b[" not in out
    assert re.match(
        r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}[+-]\d{2}:\d{2} \| ERROR", out
    )
    assert "RuntimeError: boom" in out
    assert secret not in out
    assert secret not in (tmp_path / "app.log").read_text(encoding="utf-8")
