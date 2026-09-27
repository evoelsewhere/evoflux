"""Static mount for the bundled web UI."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.static_web import mount_web_ui


def _make_dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(
        "<!doctype html><title>evo</title>", encoding="utf-8"
    )
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    return dist


def test_serves_index_and_assets_when_dist_exists(tmp_path: Path) -> None:
    app = FastAPI()
    assert mount_web_ui(app, dist=_make_dist(tmp_path)) is True

    client = TestClient(app)
    root = client.get("/")
    assert root.status_code == 200
    assert "<title>evo</title>" in root.text
    assert client.get("/assets/app.js").status_code == 200


def test_no_mount_without_dist(tmp_path: Path) -> None:
    app = FastAPI()

    @app.get("/api/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    assert mount_web_ui(app, dist=tmp_path / "missing") is False

    client = TestClient(app)
    assert client.get("/api/health").json() == {"ok": True}
    assert client.get("/").status_code == 404


def test_api_routes_win_over_mount(tmp_path: Path) -> None:
    app = FastAPI()

    @app.get("/api/ping")
    def ping() -> dict[str, str]:
        return {"pong": "yes"}

    assert mount_web_ui(app, dist=_make_dist(tmp_path)) is True

    client = TestClient(app)
    assert client.get("/api/ping").json() == {"pong": "yes"}
    assert client.get("/").status_code == 200
