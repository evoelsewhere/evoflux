#!/usr/bin/env python3
"""Generate the static Tauri ``latest.json`` manifest for a GitHub release."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote


SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")


@dataclass(frozen=True)
class UpdaterTarget:
    name: str
    pattern: str


TARGETS = (
    # Linux releases are Debian packages managed by dpkg/apt. They are
    # published with checksums but intentionally excluded from Tauri's
    # self-update manifest so package ownership remains consistent.
    UpdaterTarget("darwin-aarch64", "*_aarch64.app.tar.gz"),
    UpdaterTarget("darwin-x86_64", "*_x64.app.tar.gz"),
    UpdaterTarget("windows-x86_64-nsis", "*_x64-setup.exe"),
)


def _single_match(root: Path, pattern: str) -> Path:
    matches = sorted(path for path in root.rglob(pattern) if path.is_file())
    if len(matches) != 1:
        rendered = ", ".join(str(path) for path in matches) or "none"
        raise ValueError(
            f"expected exactly one updater artifact matching {pattern!r}; found {rendered}"
        )
    return matches[0]


def build_manifest(
    *,
    artifacts_dir: Path,
    repository: str,
    tag: str,
    version: str,
    notes: str,
    pub_date: str,
) -> dict[str, object]:
    if not SEMVER_RE.fullmatch(version):
        raise ValueError(f"version is not valid semantic versioning: {version!r}")
    if tag != f"v{version}":
        raise ValueError(f"release tag {tag!r} must equal 'v{version}'")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError(f"invalid GitHub repository name: {repository!r}")
    if not artifacts_dir.is_dir():
        raise ValueError(f"artifact directory does not exist: {artifacts_dir}")

    encoded_tag = quote(tag, safe="")
    platforms: dict[str, dict[str, str]] = {}
    for target in TARGETS:
        artifact = _single_match(artifacts_dir, target.pattern)
        signature_path = artifact.with_name(f"{artifact.name}.sig")
        if not signature_path.is_file():
            raise ValueError(f"missing updater signature: {signature_path}")
        signature = signature_path.read_text(encoding="utf-8").strip()
        if not signature:
            raise ValueError(f"updater signature is empty: {signature_path}")
        asset_name = quote(artifact.name, safe="")
        platforms[target.name] = {
            "signature": signature,
            "url": (
                f"https://github.com/{repository}/releases/download/"
                f"{encoded_tag}/{asset_name}"
            ),
        }

    return {
        "version": version,
        "notes": notes.strip() or "A new EvoFlux release is available.",
        "pub_date": pub_date,
        "platforms": platforms,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate latest.json for Tauri updater artifacts in a GitHub Release."
    )
    parser.add_argument("--artifacts-dir", type=Path, required=True)
    parser.add_argument("--repository", default="evoelsewhere/evoflux")
    parser.add_argument("--tag", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--notes-file", type=Path, required=True)
    parser.add_argument("--pub-date", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = build_manifest(
        artifacts_dir=args.artifacts_dir,
        repository=args.repository,
        tag=args.tag,
        version=args.version,
        notes=args.notes_file.read_text(encoding="utf-8"),
        pub_date=args.pub_date,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
