"""Structural release gates for the Linux x64 DEB job."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "desktop-packages.yml"
TAURI_CONFIG = ROOT / "desktop" / "src-tauri" / "tauri.conf.json"


def test_release_matrix_contains_linux_x64_deb() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert '- "linux-x64"' in source
    assert '"name":"DEB · Linux x64"' in source
    assert '"os":"ubuntu-22.04"' in source
    assert '"artifact":"evoflux-linux-x64"' in source
    assert '"deb_architecture":"amd64"' in source


def test_linux_job_builds_smokes_and_uploads_deb() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "Run Linux packaging regression tests" in source
    assert "cargo tauri build --bundles deb" in source
    assert "Verify Linux DEB contents and dependencies" in source
    assert "Smoke-test first Linux DEB launch" in source
    assert "startup_timing phase=server_ready" in source
    assert "Upload Linux DEB package" in source
    assert "target/release/bundle/deb/*.deb" in source


def test_deb_declares_external_linux_runtime_helpers() -> None:
    config = json.loads(TAURI_CONFIG.read_text(encoding="utf-8"))
    dependencies = set(config["bundle"]["linux"]["deb"]["depends"])

    assert {"xdotool", "xdg-utils", "libwebkit2gtk-4.1-0"} <= dependencies


def test_linux_runner_installs_native_build_and_smoke_dependencies() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "libwebkit2gtk-4.1-dev" in source
    assert "libpipewire-0.3-dev" in source
    assert "libxdo-dev" in source
    assert "xauth" in source
    assert "xvfb" in source
