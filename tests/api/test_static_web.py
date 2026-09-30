"""Static mount for the bundled web UI."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import static_web
from app.api.static_web import default_web_dist, mount_web_ui


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


def _point_module_at(root: Path, monkeypatch) -> Path:
    """Fake ``app/api/static_web.py`` living under ``root`` so path math is real."""
    module_file = root / "app" / "api" / "static_web.py"
    module_file.parent.mkdir(parents=True)
    module_file.write_text("", encoding="utf-8")
    monkeypatch.setattr(static_web, "__file__", str(module_file))
    monkeypatch.delenv(static_web._ENV_DIST, raising=False)
    return module_file


def _write_dist(path: Path, marker: str) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "index.html").write_text(marker, encoding="utf-8")
    return path


def test_default_web_dist_prefers_repo_layout(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "checkout"
    _point_module_at(root, monkeypatch)
    repo_dist = _write_dist(root / "web" / "dist", "repo")
    _write_dist(root / "app" / "_web_dist", "packaged")

    assert default_web_dist() == repo_dist


def test_default_web_dist_falls_back_to_packaged_bundle(
    tmp_path: Path, monkeypatch
) -> None:
    # Packaged sidecar layout: site-packages/app/_web_dist, no web/ sibling.
    root = tmp_path / "site-packages"
    _point_module_at(root, monkeypatch)
    packaged = _write_dist(root / "app" / "_web_dist", "packaged")

    assert default_web_dist() == packaged


def test_default_web_dist_without_any_bundle(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "site-packages"
    _point_module_at(root, monkeypatch)

    # Still the conventional path, so mount_web_ui() skips the mount entirely.
    assert default_web_dist() == root / "web" / "dist"


def test_default_web_dist_env_override_wins(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "checkout"
    _point_module_at(root, monkeypatch)
    _write_dist(root / "web" / "dist", "repo")
    override = _write_dist(tmp_path / "elsewhere", "override")
    monkeypatch.setenv(static_web._ENV_DIST, str(override))

    assert default_web_dist() == override


def test_spa_fallback_renders_client_side_routes(tmp_path: Path) -> None:
    app = FastAPI()
    assert mount_web_ui(app, dist=_make_dist(tmp_path)) is True

    client = TestClient(app)
    route = client.get("/settings/remote")
    assert route.status_code == 200
    assert "<title>evo</title>" in route.text


def test_api_paths_keep_their_json_404(tmp_path: Path) -> None:
    app = FastAPI()
    assert mount_web_ui(app, dist=_make_dist(tmp_path)) is True

    client = TestClient(app)
    missing = client.get("/api/nope")
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Not Found"}
    assert "text/html" not in missing.headers.get("content-type", "")


def test_missing_static_assets_still_404(tmp_path: Path) -> None:
    app = FastAPI()
    assert mount_web_ui(app, dist=_make_dist(tmp_path)) is True

    client = TestClient(app)
    assert client.get("/assets/gone.js").status_code == 404
