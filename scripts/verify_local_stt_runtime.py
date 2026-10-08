#!/usr/bin/env python3
"""Verify built Local STT archives and load the multilingual model offline."""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from app.services.local_stt_runtime.installer import _extract_zip


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def verify_archive(path: Path, expected_root: str) -> int:
    with zipfile.ZipFile(path) as archive:
        names = [item.filename.replace("\\", "/") for item in archive.infolist()]
        if not names or any(name.split("/", 1)[0] != expected_root for name in names):
            raise ValueError(f"Archive {path.name} does not use the expected root.")
        if len({name.casefold() for name in names}) != len(names):
            raise ValueError(f"Archive {path.name} contains duplicate paths.")
        return sum(item.file_size for item in archive.infolist())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    args = parser.parse_args()
    runtime_size = verify_archive(args.runtime, "runtime")
    model_size = verify_archive(args.model, "model")
    with tempfile.TemporaryDirectory(prefix="evoflux-stt-verify-") as temporary:
        root = Path(temporary)
        runtime_stage = root / "runtime-stage"
        model_stage = root / "model-stage"
        runtime_stage.mkdir()
        model_stage.mkdir()
        _extract_zip(args.runtime, runtime_stage, "runtime")
        _extract_zip(args.model, model_stage, "model")
        runtime_root = runtime_stage / "runtime"
        model_root = model_stage / "model"
        env = os.environ.copy()
        env["PYTHONPATH"] = str(runtime_root / "site-packages") + (
            os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
        )
        env["HF_HUB_OFFLINE"] = "1"
        env["TRANSFORMERS_OFFLINE"] = "1"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "app.services.local_stt_runtime.worker",
                "--health",
                str(model_root),
            ],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=180,
            check=False,
        )
        if result.returncode != 0:
            raise SystemExit("The pinned speech runtime/model did not pass its offline load check.")
    print(f"Runtime SHA-256: {sha256(args.runtime)} ({args.runtime.stat().st_size} bytes, {runtime_size} installed)")
    print(f"Model SHA-256: {sha256(args.model)} ({args.model.stat().st_size} bytes, {model_size} installed)")
    print("Offline local model load succeeded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
