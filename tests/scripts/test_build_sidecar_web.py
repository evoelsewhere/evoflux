from __future__ import annotations

from pathlib import Path

import pytest

import scripts.build_sidecar as build_sidecar


def _stub_pipeline(monkeypatch, calls: list[list[str]]) -> None:
    def fake_run(cmd: list[str], **kwargs) -> None:
        calls.append(cmd)
        raise SystemExit("stop after web build")

    monkeypatch.setattr(build_sidecar, "run", fake_run)


def test_main_builds_the_web_ui_once_when_dist_is_missing(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "web").mkdir()
    calls: list[list[str]] = []
    _stub_pipeline(monkeypatch, calls)
    monkeypatch.setattr(build_sidecar, "BUN", "bun")

    with pytest.raises(SystemExit):
        build_sidecar.main(["--root", str(tmp_path), "--out", str(tmp_path / "out")])

    assert calls == [["bun", "install", "--frozen-lockfile"]]


def test_build_web_runs_install_then_build(tmp_path: Path, monkeypatch) -> None:
    calls: list[tuple[list[str], Path]] = []

    def fake_run(cmd: list[str], **kwargs) -> None:
        calls.append((cmd, kwargs["cwd"]))

    monkeypatch.setattr(build_sidecar, "run", fake_run)
    monkeypatch.setattr(build_sidecar, "BUN", "bun")

    build_sidecar.build_web(tmp_path)

    web = tmp_path / "web"
    assert calls == [
        (["bun", "install", "--frozen-lockfile"], web),
        (["bun", "run", "build"], web),
    ]


def test_main_skips_the_web_build_when_dist_exists(tmp_path: Path, monkeypatch) -> None:
    dist = tmp_path / "web" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    calls: list[list[str]] = []
    _stub_pipeline(monkeypatch, calls)

    with pytest.raises(SystemExit):
        build_sidecar.main(["--root", str(tmp_path), "--out", str(tmp_path / "out")])

    assert not any(cmd[:1] == ["bun"] for cmd in calls)


def test_no_build_web_exits_when_dist_is_missing(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    (tmp_path / "web").mkdir()
    calls: list[list[str]] = []
    _stub_pipeline(monkeypatch, calls)

    code = build_sidecar.main(
        ["--root", str(tmp_path), "--out", str(tmp_path / "out"), "--no-build-web"]
    )

    assert code == 1
    assert calls == []
    assert "web bundle missing" in capsys.readouterr().err
