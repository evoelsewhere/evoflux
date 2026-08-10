from __future__ import annotations

import zipfile

from scripts.build_sidecar import strip_bundle, zip_pure_python_packages


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
