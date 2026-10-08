#!/usr/bin/env python3
"""Build separate optional faster-whisper runtime or multilingual model assets."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

MODEL_REPO = "Systran/faster-whisper-small"
MODEL_REVISION = "2ec96c5472da50d38d40c0cfe0602af2e94b4c8a"
MODEL_FILES = ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt")


def host_platform() -> str:
    machine = platform.machine().lower()
    arch = "arm64" if machine in {"arm64", "aarch64"} else "x64"
    system = {"Windows": "win32", "Darwin": "darwin", "Linux": "linux"}.get(
        platform.system()
    )
    if system is None:
        raise SystemExit(f"Unsupported build host: {platform.system()}/{machine}")
    result = f"{system}-{arch}"
    if result not in {"win32-x64", "darwin-x64", "darwin-arm64", "linux-x64"}:
        raise SystemExit(f"Unsupported Local STT target: {result}")
    return result


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def tree_size(path: Path) -> int:
    return sum(file.stat().st_size for file in path.rglob("*") if file.is_file())


def zip_tree(source_root: Path, archive_path: Path) -> int:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        for file_path in sorted(item for item in source_root.rglob("*") if item.is_file()):
            relative = file_path.relative_to(source_root).as_posix()
            info = zipfile.ZipInfo(relative, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            mode = file_path.stat().st_mode
            info.external_attr = (stat.S_IFREG | (mode & 0o777)) << 16
            with file_path.open("rb") as source_handle, archive.open(info, "w") as target:
                shutil.copyfileobj(source_handle, target, 1024 * 1024)
    return tree_size(source_root)


def _run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> None:
    print(">>", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True)


def build_runtime(out: Path, version: str, base_url: str, requirements: Path) -> dict[str, object]:
    target = host_platform()
    with tempfile.TemporaryDirectory(prefix="evoflux-stt-runtime-") as temporary:
        stage = Path(temporary)
        package_root = stage / "runtime" / "site-packages"
        package_root.mkdir(parents=True)
        _run(
            [
                "uv", "pip", "install", "--python", sys.executable,
                "--target", str(package_root), "-r", str(requirements.resolve()),
            ],
            cwd=requirements.parent,
        )
        archive_name = f"evoflux-local-stt-{version}-{target}.zip"
        archive = out / archive_name
        installed_bytes = zip_tree(stage, archive)
        return {
            "kind": "runtime",
            "platform": target,
            "version": version,
            "url": f"{base_url.rstrip('/')}/{archive_name}",
            "sha256": sha256(archive),
            "size": archive.stat().st_size,
            "installedSize": installed_bytes,
            "root": "runtime/site-packages",
            "archive": archive_name,
        }


def build_model(out: Path, base_url: str) -> dict[str, object]:
    target = host_platform()
    if target != "linux-x64":
        raise SystemExit("Build the shared model archive on the Linux x64 workflow runner.")
    with tempfile.TemporaryDirectory(prefix="evoflux-stt-model-") as temporary:
        stage = Path(temporary)
        model_root = stage / "model"
        model_root.mkdir(parents=True)
        # The runtime package is pinned and loaded only inside this build step.
        _run(
            [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "huggingface-hub==0.35.3"],
            cwd=stage,
        )
        helper = (
            "from huggingface_hub import hf_hub_download; "
            "import os; "
            f"repo={MODEL_REPO!r}; revision={MODEL_REVISION!r}; target={str(model_root)!r}; "
            f"files={MODEL_FILES!r}; "
            "[shutil.copyfile(hf_hub_download(repo, f, revision=revision), os.path.join(target, f)) for f in files]"
        )
        _run([sys.executable, "-c", "import shutil; " + helper], cwd=stage)
        (model_root / "MODEL-NOTICE.txt").write_text(
            "Multilingual Whisper small model, converted to CTranslate2 format.\n"
            f"Source: https://huggingface.co/{MODEL_REPO}/tree/{MODEL_REVISION}\n"
            "License: MIT (model repository).\n",
            encoding="utf-8",
        )
        archive_name = f"evoflux-whisper-small-{MODEL_REVISION[:12]}.zip"
        archive = out / archive_name
        installed_bytes = zip_tree(stage, archive)
        return {
            "kind": "model",
            "platform": "all",
            "version": MODEL_REVISION[:12],
            "url": f"{base_url.rstrip('/')}/{archive_name}",
            "sha256": sha256(archive),
            "size": archive.stat().st_size,
            "installedSize": installed_bytes,
            "root": "model",
            "archive": archive_name,
            "source": f"{MODEL_REPO}@{MODEL_REVISION}",
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", choices=("runtime", "model"), required=True)
    parser.add_argument("--version", default="0.1.0", help="Managed runtime artifact version.")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--base-url", required=True, help="HTTPS GitHub release asset base URL.")
    parser.add_argument(
        "--requirements",
        type=Path,
        default=Path(__file__).parent / "local_stt_runtime" / "requirements.txt",
        help="Pinned runtime dependency list.",
    )
    args = parser.parse_args()
    if not args.base_url.startswith("https://"):
        parser.error("--base-url must use HTTPS")
    args.out.mkdir(parents=True, exist_ok=True)
    if args.asset == "runtime":
        record = build_runtime(args.out, args.version, args.base_url, args.requirements)
    else:
        record = build_model(args.out, args.base_url)
    manifest = args.out / f"{record['kind']}-{record['platform']}.json"
    manifest.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
