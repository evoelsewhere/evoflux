from __future__ import annotations

from pathlib import Path

import scripts.build_tailnet as build_tailnet


def test_host_target_normalizes_apple_silicon(monkeypatch) -> None:
    monkeypatch.setattr(build_tailnet.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(build_tailnet.platform, "machine", lambda: "arm64")
    assert build_tailnet.host_target() == ("darwin", "arm64")


def test_project_version_reads_pyproject(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "2.0.9"\n', encoding="utf-8"
    )
    assert build_tailnet.project_version(tmp_path) == "2.0.9"
