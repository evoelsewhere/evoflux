from __future__ import annotations

import zipfile

import scripts.build_local_stt_runtime as builder

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


def test_build_model_can_run_on_windows_and_keeps_platform_neutral(tmp_path, monkeypatch):
    monkeypatch.setattr(builder, "host_platform", lambda: "win32-x64")

    def fake_run(command, *, cwd, env=None):
        if "-c" in command:
            model_root = cwd / "model"
            for filename in builder.MODEL_FILES:
                (model_root / filename).write_bytes(filename.encode("utf-8"))

    monkeypatch.setattr(builder, "_run", fake_run)

    record = builder.build_model(tmp_path, "https://local.invalid")

    assert record["platform"] == "all"
    assert record["sha256"]
    with zipfile.ZipFile(tmp_path / str(record["archive"])) as archive:
        assert "model/model.bin" in archive.namelist()
