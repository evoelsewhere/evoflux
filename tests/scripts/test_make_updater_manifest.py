from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_manifest_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "make_updater_manifest.py"
    spec = importlib.util.spec_from_file_location("make_updater_manifest", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_default_manifest_urls_point_at_shared_release_tag(tmp_path, monkeypatch):
    module = _load_manifest_module()
    artefact_dir = tmp_path / "artefacts"
    artefact_dir.mkdir()
    (artefact_dir / "evoflux.app.tar.gz").write_text("tar")
    (artefact_dir / "evoflux.app.tar.gz.sig").write_text("minisign-signature")
    out = tmp_path / "latest.json"

    monkeypatch.setattr(
        "sys.argv",
        [
            "make_updater_manifest.py",
            "--version",
            "1.2.0",
            "--artefact-dir",
            str(artefact_dir),
            "--out",
            str(out),
            "--require-platform",
            "darwin-aarch64",
        ],
    )
    monkeypatch.setenv("GITHUB_REPOSITORY", "khuonghung/evoflux")

    assert module.main() == 0

    manifest = json.loads(out.read_text())
    assert manifest["platforms"]["darwin-aarch64"]["url"] == (
        "https://github.com/khuonghung/evoflux/releases/download/"
        "v1.2.0/evoflux.app.tar.gz"
    )
    assert manifest["platforms"]["darwin-aarch64"]["signature"] == "minisign-signature"


def test_manifest_fails_when_updater_signature_is_missing(
    tmp_path, monkeypatch, capsys
):
    module = _load_manifest_module()
    artefact_dir = tmp_path / "artefacts"
    artefact_dir.mkdir()
    (artefact_dir / "evoflux.app.tar.gz").write_text("tar")
    out = tmp_path / "latest.json"

    monkeypatch.setattr(
        "sys.argv",
        [
            "make_updater_manifest.py",
            "--version",
            "1.2.0",
            "--artefact-dir",
            str(artefact_dir),
            "--out",
            str(out),
        ],
    )

    assert module.main() == 1
    assert "missing updater signature for evoflux.app.tar.gz" in capsys.readouterr().err
    assert not out.exists()


def test_manifest_fails_when_required_platform_is_missing(
    tmp_path, monkeypatch, capsys
):
    module = _load_manifest_module()
    artefact_dir = tmp_path / "artefacts"
    artefact_dir.mkdir()
    # Provide a Linux artefact so the script *does* build a non-empty
    # platform map; the assertion is then that requiring a missing
    # platform (darwin-aarch64) is what trips the failure.
    (artefact_dir / "EVOFLUX_1.2.0_amd64.AppImage").write_text("appimage")
    (artefact_dir / "EVOFLUX_1.2.0_amd64.AppImage.sig").write_text("sig")
    out = tmp_path / "latest.json"

    monkeypatch.setattr(
        "sys.argv",
        [
            "make_updater_manifest.py",
            "--version",
            "1.2.0",
            "--artefact-dir",
            str(artefact_dir),
            "--out",
            str(out),
            "--require-platform",
            "darwin-aarch64",
        ],
    )

    assert module.main() == 1
    assert (
        "missing required updater platform(s): darwin-aarch64"
        in capsys.readouterr().err
    )
    assert not out.exists()
