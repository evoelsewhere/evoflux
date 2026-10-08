from __future__ import annotations

import zipfile

from scripts.build_local_stt_runtime import zip_tree


def test_zip_tree_archives_multiple_files_relative_to_source(tmp_path):
    source = tmp_path / "source"
    (source / "runtime" / "site-packages").mkdir(parents=True)
    (source / "runtime" / "site-packages" / "one.py").write_text("one", encoding="utf-8")
    (source / "runtime" / "site-packages" / "two.py").write_text("two!", encoding="utf-8")
    archive_path = tmp_path / "runtime.zip"

    installed_bytes = zip_tree(source, archive_path)

    assert installed_bytes == 7
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.namelist() == [
            "runtime/site-packages/one.py",
            "runtime/site-packages/two.py",
        ]
        assert archive.read("runtime/site-packages/one.py") == b"one"
        assert archive.read("runtime/site-packages/two.py") == b"two!"
