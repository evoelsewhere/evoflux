#!/usr/bin/env python3
"""Build the embedded tsnet helper into a desktop sidecar bundle.

The build is host-targeted by default because desktop packages are produced on
native GitHub runners. ``--goos``/``--goarch`` are available for explicit
cross-builds; CGO stays disabled so the helper remains a single relocatable
binary.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path


def host_target() -> tuple[str, str]:
    system = platform.system().lower()
    goos = {"darwin": "darwin", "linux": "linux", "windows": "windows"}.get(system)
    if goos is None:
        raise SystemExit(f"unsupported host OS: {platform.system()}")
    machine = platform.machine().lower()
    goarch = "arm64" if machine in {"arm64", "aarch64"} else "amd64"
    return goos, goarch


def project_version(root: Path) -> str:
    with (root / "pyproject.toml").open("rb") as handle:
        return str(tomllib.load(handle)["project"]["version"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--out", default="desktop/sidecar-bundle/tailnet")
    parser.add_argument("--goos")
    parser.add_argument("--goarch")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    source = root / "desktop" / "tailnet"
    out = Path(args.out).resolve()
    host_goos, host_goarch = host_target()
    goos = args.goos or host_goos
    goarch = args.goarch or host_goarch
    go = shutil.which("go")
    if go is None:
        raise SystemExit(
            "Go is required to build the embedded tailnet helper "
            "(release toolchain: Go 1.26.6)."
        )

    out.mkdir(parents=True, exist_ok=True)
    binary = out / ("evoflux-tailnet.exe" if goos == "windows" else "evoflux-tailnet")
    env = {
        **os.environ,
        "CGO_ENABLED": "0",
        "GOOS": goos,
        "GOARCH": goarch,
    }
    version = project_version(root)
    command = [
        go,
        "build",
        "-trimpath",
        "-ldflags",
        f"-s -w -X main.version={version}",
        "-o",
        str(binary),
        ".",
    ]
    print(">>", " ".join(command), flush=True)
    subprocess.run(command, cwd=source, env=env, check=True)
    if goos != "windows":
        binary.chmod(0o755)

    for name in ("NOTICE.md", "LICENSE.tailscale"):
        shutil.copy2(source / name, out / name)

    if (goos, goarch) == (host_goos, host_goarch):
        completed = subprocess.run(
            [str(binary), "--version"],
            check=True,
            capture_output=True,
            text=True,
        )
        if completed.stdout.strip() != version:
            raise SystemExit(
                f"tailnet smoke test returned {completed.stdout.strip()!r}, "
                f"expected {version!r}"
            )
    print(f"embedded tailnet: {binary} ({goos}/{goarch})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
