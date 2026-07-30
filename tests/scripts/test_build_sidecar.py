from __future__ import annotations

import zipfile

from scripts.build_sidecar import zip_pure_python_packages


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
