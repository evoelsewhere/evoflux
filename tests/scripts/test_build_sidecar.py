from __future__ import annotations

import hashlib
import io
import tarfile
import zipfile

from pathlib import Path

import pytest

import scripts.build_sidecar as build_sidecar
from scripts.build_sidecar import (
    bundle_msvc_runtime,
    strip_bundle,
    zip_pure_python_packages,
)


def test_install_packages_installs_locked_versions(tmp_path, monkeypatch) -> None:
    calls: list[list[str]] = []
    exported: list[str] = []

    def fake_run(cmd: list[str], **kwargs) -> None:
        calls.append(cmd)
        if "--requirements" in cmd:
            exported.append(
                Path(cmd[cmd.index("--requirements") + 1]).read_text(encoding="utf-8")
            )
        if cmd[1] == "export":
            Path(cmd[cmd.index("--output-file") + 1]).write_text(
                "pypdfium2==5.7.0\n", encoding="utf-8"
            )

    monkeypatch.setattr(build_sidecar, "run", fake_run)

    build_sidecar.install_packages(
        Path("python"), tmp_path, tmp_path / "site-packages", ["office-preview"]
    )

    export, deps, project = calls
    assert export[:3] == ["uv", "export", "--locked"]
    assert {"--no-dev", "--no-emit-project"} <= set(export)
    assert export[export.index("--extra") + 1] == "office-preview"
    assert exported == ["pypdfium2==5.7.0\n"]
    assert "--no-deps" not in deps
    assert project[-2:] == ["--no-deps", "."]


def test_strip_bundle_removes_only_release_artefacts(tmp_path) -> None:
    package = tmp_path / "runtime_package"
    package.mkdir()
    (package / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (package / "api.pyi").write_text("VALUE: int\n", encoding="utf-8")
    (package / "py.typed").write_text("", encoding="utf-8")

    native_symbols = package / "extension.so.dSYM"
    native_symbols.mkdir()
    (native_symbols / "symbols").write_bytes(b"symbols")

    pyobjc_tests = tmp_path / "PyObjCTest"
    pyobjc_tests.mkdir()
    (pyobjc_tests / "test_bundle.so").write_bytes(b"test")

    discovery_cache = tmp_path / "googleapiclient" / "discovery_cache"
    discovery_documents = discovery_cache / "documents"
    discovery_documents.mkdir(parents=True)
    (discovery_cache / "__init__.py").write_text("", encoding="utf-8")
    (discovery_documents / "drive.v3.json").write_bytes(b"discovery")

    metadata = tmp_path / "runtime-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text("Name: runtime\n", encoding="utf-8")
    (metadata / "RECORD").write_text("runtime_package/__init__.py\n", encoding="utf-8")

    removed = strip_bundle(tmp_path)

    assert removed > 0
    assert (package / "__init__.py").is_file()
    assert not (package / "api.pyi").exists()
    assert not (package / "py.typed").exists()
    assert not native_symbols.exists()
    assert not pyobjc_tests.exists()
    assert (discovery_cache / "__init__.py").is_file()
    assert not discovery_documents.exists()
    assert (metadata / "METADATA").is_file()
    assert not (metadata / "RECORD").exists()


def _msvc_layout(tmp_path: Path) -> tuple[Path, Path, Path]:
    python_dir = tmp_path / "python"
    python_dir.mkdir()
    (python_dir / "vcruntime140.dll").write_bytes(b"runtime")
    site_packages = tmp_path / "site-packages"
    greenlet = site_packages / "greenlet"
    greenlet.mkdir(parents=True)
    (greenlet / "_greenlet.cp312-win_amd64.pyd").write_bytes(
        b"MZ\x00MSVCP140.dll\x00VCRUNTIME140.dll\x00python312.dll\x00"
    )
    # A package that ships its own copy next to the extension needs nothing.
    vendored = site_packages / "vendored"
    vendored.mkdir()
    (vendored / "ext.pyd").write_bytes(b"MZ\x00concrt140.dll\x00")
    (vendored / "concrt140.dll").write_bytes(b"own copy")
    redist = tmp_path / "redist"
    redist.mkdir()
    return python_dir, site_packages, redist


def test_bundle_msvc_runtime_copies_missing_cpp_runtime(tmp_path) -> None:
    python_dir, site_packages, redist = _msvc_layout(tmp_path)
    (redist / "msvcp140.dll").write_bytes(b"cpp runtime")

    copied = bundle_msvc_runtime(python_dir, site_packages, sources=[redist])

    assert copied == ["msvcp140.dll"]
    assert (python_dir / "msvcp140.dll").read_bytes() == b"cpp runtime"
    assert not (python_dir / "concrt140.dll").exists()


def test_bundle_msvc_runtime_fails_when_runtime_is_unavailable(tmp_path) -> None:
    python_dir, site_packages, redist = _msvc_layout(tmp_path)

    with pytest.raises(SystemExit, match="msvcp140.dll"):
        bundle_msvc_runtime(python_dir, site_packages, sources=[redist])


def _ripgrep_tarball() -> bytes:
    buffer = io.BytesIO()
    top = f"ripgrep-{build_sidecar.RIPGREP_VERSION}-x86_64-unknown-linux-musl"
    members = {
        f"{top}/rg": b"#!rg",
        f"{top}/COPYING": b"copying",
        f"{top}/LICENSE-MIT": b"mit",
        f"{top}/UNLICENSE": b"unlicense",
        f"{top}/doc/rg.1": b"manual",
        # Only base names inside the top directory are ever written.
        f"{top}/../escape": b"outside",
    }
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def _serve(monkeypatch, payload: bytes, sha256: str) -> None:
    monkeypatch.setattr(build_sidecar, "IS_WINDOWS", False)
    monkeypatch.setitem(
        build_sidecar.RIPGREP_ASSETS,
        "x86_64-unknown-linux-gnu",
        ("x86_64-unknown-linux-musl.tar.gz", sha256),
    )
    monkeypatch.setattr(
        build_sidecar.urllib.request,
        "urlopen",
        lambda url, timeout: io.BytesIO(payload),
    )


def test_fetch_ripgrep_keeps_binary_and_licenses(tmp_path, monkeypatch) -> None:
    payload = _ripgrep_tarball()
    _serve(monkeypatch, payload, hashlib.sha256(payload).hexdigest())

    rg = build_sidecar.fetch_ripgrep(tmp_path / "ripgrep", "x86_64-unknown-linux-gnu")

    assert rg == tmp_path / "ripgrep" / "rg"
    assert rg.read_bytes() == b"#!rg"
    assert sorted(p.name for p in rg.parent.iterdir()) == [
        "COPYING",
        "LICENSE-MIT",
        "UNLICENSE",
        "rg",
    ]
    assert not (tmp_path / "escape").exists()


def test_fetch_ripgrep_rejects_checksum_mismatch(tmp_path, monkeypatch) -> None:
    _serve(monkeypatch, _ripgrep_tarball(), "0" * 64)

    with pytest.raises(SystemExit, match="checksum mismatch"):
        build_sidecar.fetch_ripgrep(tmp_path / "ripgrep", "x86_64-unknown-linux-gnu")
    assert not (tmp_path / "ripgrep" / "rg").exists()


def test_ripgrep_is_pinned_for_every_sidecar_triple() -> None:
    triples = {
        "x86_64-pc-windows-msvc",
        "aarch64-pc-windows-msvc",
        "x86_64-apple-darwin",
        "aarch64-apple-darwin",
        "x86_64-unknown-linux-gnu",
        "aarch64-unknown-linux-gnu",
    }
    assert set(build_sidecar.RIPGREP_ASSETS) == triples
    for suffix, sha256 in build_sidecar.RIPGREP_ASSETS.values():
        assert suffix.endswith((".zip", ".tar.gz"))
        assert len(sha256) == 64 and int(sha256, 16) >= 0


def test_zip_pure_python_packages_keeps_runtime_data_on_disk(tmp_path) -> None:
    pure_package = tmp_path / "pure_package"
    pure_package.mkdir()
    (pure_package / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (pure_package / "module.py").write_text("VALUE = 2\n", encoding="utf-8")

    data_package = tmp_path / "data_package"
    data_package.mkdir()
    (data_package / "__init__.py").write_text("", encoding="utf-8")
    (data_package / "template.json").write_text("{}", encoding="utf-8")

    packages, files = zip_pure_python_packages(tmp_path)

    assert (packages, files) == (1, 2)
    assert not pure_package.exists()
    assert data_package.is_dir()
    assert (tmp_path / "evoflux-purelib.pth").read_text(encoding="utf-8") == (
        "evoflux-purelib.zip\n"
    )
    with zipfile.ZipFile(tmp_path / "evoflux-purelib.zip") as archive:
        assert set(archive.namelist()) == {
            "pure_package/__init__.py",
            "pure_package/module.py",
        }
