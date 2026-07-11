"""Tests for app/api/routes/loop.py — Loop Engine settings endpoints."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.loop import router


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


@pytest.fixture
def isolated_settings(tmp_path: Path):
    """Point runtime_settings at a temporary settings.yaml."""
    target = tmp_path / "settings.yaml"
    with patch("app.core.runtime_settings.runtime_settings_path", return_value=target):
        yield target


def test_get_loop_returns_defaults(isolated_settings: Path) -> None:
    client = TestClient(_make_app())
    response = client.get("/api/loop/config")
    assert response.status_code == 200
    body = response.json()
    assert body["default_max_iterations"] == 10
    assert body["default_evolve_prompt"] is True
    assert body["default_verify_command"] == ""
    assert body["default_max_total_tokens"] is None
    assert body["default_no_progress_threshold"] == 3
    assert body["default_max_consecutive_errors"] == 3
    assert body["default_delay_between_iterations"] == 0.0


def test_put_loop_saves_settings(isolated_settings: Path) -> None:
    client = TestClient(_make_app())
    body = {
        "default_max_iterations": 20,
        "default_evolve_prompt": False,
        "default_verify_command": "uv run pytest -q",
        "default_max_total_tokens": 5000,
        "default_no_progress_threshold": 5,
        "default_max_consecutive_errors": 4,
        "default_delay_between_iterations": 1.5,
    }
    response = client.put("/api/loop/config", json=body)
    assert response.status_code == 200
    assert response.json() == body


def test_put_then_get_roundtrip(isolated_settings: Path) -> None:
    client = TestClient(_make_app())
    body = {
        "default_max_iterations": 25,
        "default_evolve_prompt": False,
        "default_verify_command": "make test",
        "default_max_total_tokens": None,
        "default_no_progress_threshold": 7,
        "default_max_consecutive_errors": 5,
        "default_delay_between_iterations": 2.0,
    }
    client.put("/api/loop/config", json=body)
    response = client.get("/api/loop/config")
    assert response.status_code == 200
    assert response.json() == body


def test_put_loop_strips_whitespace_from_verify_command(isolated_settings: Path) -> None:
    client = TestClient(_make_app())
    body = {
        "default_max_iterations": 10,
        "default_evolve_prompt": True,
        "default_verify_command": "  pytest  ",
        "default_no_progress_threshold": 3,
        "default_max_consecutive_errors": 3,
        "default_delay_between_iterations": 0.0,
    }
    response = client.put("/api/loop/config", json=body)
    assert response.status_code == 200
    assert response.json()["default_verify_command"] == "pytest"


def test_put_loop_empty_verify_command_becomes_none(isolated_settings: Path) -> None:
    client = TestClient(_make_app())
    body = {
        "default_max_iterations": 10,
        "default_evolve_prompt": True,
        "default_verify_command": "",
        "default_no_progress_threshold": 3,
        "default_max_consecutive_errors": 3,
        "default_delay_between_iterations": 0.0,
    }
    response = client.put("/api/loop/config", json=body)
    assert response.status_code == 200
    # Empty string should be stored as None internally but returned as ""
    assert response.json()["default_verify_command"] == ""


def test_get_loop_ignores_extra_fields(isolated_settings: Path) -> None:
    """Extra fields in settings.yaml should not cause errors (extra='ignore')."""
    # Write settings.yaml with extra fields
    isolated_settings.write_text(
        "loop:\n  default_max_iterations: 5\n  unknown_field: hello\n",
        encoding="utf-8",
    )
    client = TestClient(_make_app())
    response = client.get("/api/loop/config")
    assert response.status_code == 200
    assert response.json()["default_max_iterations"] == 5


def test_loop_settings_backward_compat_without_key(isolated_settings: Path) -> None:
    """settings.yaml without a 'loop' key should use defaults."""
    # Write settings.yaml with only dream settings
    isolated_settings.write_text(
        "dream:\n  enabled: true\n  model: test:model\n  schedule: '0 2 * * *'\n",
        encoding="utf-8",
    )
    client = TestClient(_make_app())
    response = client.get("/api/loop/config")
    assert response.status_code == 200
    assert response.json()["default_max_iterations"] == 10
    assert response.json()["default_evolve_prompt"] is True


def test_loop_settings_does_not_clobber_other_settings(isolated_settings: Path) -> None:
    """Saving loop settings should preserve dream and other settings."""
    client = TestClient(_make_app())

    # First, save dream config via a separate endpoint (simulated by direct write)
    isolated_settings.write_text(
        "dream:\n  enabled: true\n  model: test:model\n  schedule: '0 3 * * *'\n",
        encoding="utf-8",
    )

    # Save loop settings
    loop_body = {
        "default_max_iterations": 15,
        "default_evolve_prompt": True,
        "default_verify_command": "",
        "default_no_progress_threshold": 3,
        "default_max_consecutive_errors": 3,
        "default_delay_between_iterations": 0.0,
    }
    client.put("/api/loop/config", json=loop_body)

    # Read the raw YAML and verify dream settings are preserved
    import yaml

    data = yaml.safe_load(isolated_settings.read_text(encoding="utf-8"))
    assert data["dream"]["enabled"] is True
    assert data["dream"]["model"] == "test:model"
    assert data["loop"]["default_max_iterations"] == 15
