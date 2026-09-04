from __future__ import annotations

import pytest

from scripts.generate_updater_manifest import build_manifest


def _write_updater_pair(root, filename: str, signature: str) -> None:
    (root / filename).write_bytes(b"updater")
    (root / f"{filename}.sig").write_text(signature, encoding="utf-8")


def test_build_manifest_maps_native_targets_to_versioned_release_assets(
    tmp_path,
) -> None:
    _write_updater_pair(
        tmp_path, "EvoFlux_0.0.7_aarch64.app.tar.gz", "mac-arm-signature\n"
    )
    _write_updater_pair(
        tmp_path, "EvoFlux_0.0.7_x64.app.tar.gz", "mac-intel-signature\n"
    )
    _write_updater_pair(tmp_path, "EvoFlux_0.0.7_x64-setup.exe", "windows-signature\n")

    manifest = build_manifest(
        artifacts_dir=tmp_path,
        repository="evoelsewhere/evoflux",
        tag="v0.0.7",
        version="0.0.7",
        notes="Release notes\n",
        pub_date="2026-08-18T12:00:00Z",
    )

    assert manifest["version"] == "0.0.7"
    assert manifest["notes"] == "Release notes"
    platforms = manifest["platforms"]
    assert set(platforms) == {
        "darwin-aarch64",
        "darwin-x86_64",
        "windows-x86_64-nsis",
    }
    assert platforms["darwin-aarch64"]["signature"] == "mac-arm-signature"
    assert platforms["windows-x86_64-nsis"]["url"].endswith(
        "/v0.0.7/EvoFlux_0.0.7_x64-setup.exe"
    )


def test_build_manifest_rejects_a_tag_that_does_not_match_version(tmp_path) -> None:
    with pytest.raises(ValueError, match="must equal"):
        build_manifest(
            artifacts_dir=tmp_path,
            repository="evoelsewhere/evoflux",
            tag="v0.0.8",
            version="0.0.7",
            notes="",
            pub_date="2026-08-18T12:00:00Z",
        )


def test_build_manifest_requires_every_signature(tmp_path) -> None:
    (tmp_path / "EvoFlux_0.0.7_aarch64.app.tar.gz").write_bytes(b"updater")
    _write_updater_pair(tmp_path, "EvoFlux_0.0.7_x64.app.tar.gz", "mac-intel")
    _write_updater_pair(tmp_path, "EvoFlux_0.0.7_x64-setup.exe", "windows")

    with pytest.raises(ValueError, match="missing updater signature"):
        build_manifest(
            artifacts_dir=tmp_path,
            repository="evoelsewhere/evoflux",
            tag="v0.0.7",
            version="0.0.7",
            notes="Release notes",
            pub_date="2026-08-18T12:00:00Z",
        )
