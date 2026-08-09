#!/usr/bin/env python3
"""Assemble, stage, and verify EvoFlux's relocatable document runtime.

The generated directory is embedded in the desktop sidecar and contains every
native dependency used by Artifact Fabric: Node.js, ``@oai/artifact-tool``,
Chromium, LibreOffice, Poppler, and a deterministic open-font pack. Production bundles
must be assembled from redistributable inputs; this script intentionally does
not copy tools from a developer cache or discover them on ``PATH``.

Examples::

    python scripts/build_document_runtime.py assemble \
      --out desktop/document-runtime \
      --bundle-version 2026.08.1 \
      --node-root /opt/evoflux-runtime/node \
      --artifact-tool-root /opt/evoflux-runtime/artifact-tool \
      --artifact-tool-distribution-authorized \
      --chromium-root /opt/evoflux-runtime/chromium \
      --libreoffice-root /opt/evoflux-runtime/libreoffice \
      --poppler-root /opt/evoflux-runtime/poppler

    python scripts/build_document_runtime.py verify desktop/document-runtime

    python scripts/build_document_runtime.py stage \
      --source /secure/releases/document-runtime.tar.gz \
      --sha256 <archive-sha256> \
      --out desktop/document-runtime

``stage`` supports tar and zip archives. Archive extraction rejects absolute
paths, traversal, external symlinks, and device files before writing anything.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Final

SCHEMA_VERSION: Final = 2
MANIFEST_NAME: Final = "manifest.json"
DOCUMENT_RUNTIME_SOURCE_ENV: Final = "EVOFLUX_DOCUMENT_RUNTIME_SOURCE"
DOCUMENT_RUNTIME_SHA256_ENV: Final = "EVOFLUX_DOCUMENT_RUNTIME_SHA256"

_FONT_SUFFIXES: Final = {".otf", ".ttc", ".ttf"}
_REQUIRED_COMPONENTS: Final = {
    "node",
    "artifact_tool",
    "chromium",
    "libreoffice",
    "poppler",
    "fonts",
}


class DocumentRuntimeError(RuntimeError):
    """Raised when a document runtime is incomplete or cannot be trusted."""


def normalized_platform(value: str | None = None) -> str:
    raw = (value or platform.system()).strip().lower()
    aliases = {
        "darwin": "darwin",
        "mac": "darwin",
        "macos": "darwin",
        "linux": "linux",
        "win32": "windows",
        "windows": "windows",
    }
    try:
        return aliases[raw]
    except KeyError as exc:
        raise DocumentRuntimeError(f"unsupported target platform: {raw}") from exc


def normalized_architecture(value: str | None = None) -> str:
    raw = (value or platform.machine()).strip().lower()
    aliases = {
        "aarch64": "arm64",
        "arm64": "arm64",
        "amd64": "x86_64",
        "x64": "x86_64",
        "x86_64": "x86_64",
    }
    try:
        return aliases[raw]
    except KeyError as exc:
        raise DocumentRuntimeError(f"unsupported target architecture: {raw}") from exc


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_sha256(root: Path, *, exclude_manifest: bool = False) -> tuple[str, int, int]:
    """Return a deterministic content hash, regular-file count, and byte size."""
    digest = hashlib.sha256()
    file_count = 0
    byte_size = 0
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix()
        if exclude_manifest and relative == MANIFEST_NAME:
            continue
        if path.is_symlink():
            digest.update(f"L\0{relative}\0{os.readlink(path)}\0".encode())
            continue
        if not path.is_file():
            continue
        size = path.stat().st_size
        digest.update(f"F\0{relative}\0{size}\0".encode())
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        file_count += 1
        byte_size += size
    return digest.hexdigest(), file_count, byte_size


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _copy_tree(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise DocumentRuntimeError(f"component root is not a directory: {source}")
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination, symlinks=True)


def _find_named_file(root: Path, names: tuple[str, ...]) -> Path:
    by_name = {name.lower() for name in names}
    matches = [
        path
        for path in root.rglob("*")
        if path.is_file() and path.name.lower() in by_name
    ]
    if not matches:
        raise DocumentRuntimeError(
            f"none of {', '.join(names)} exists under component root {root}"
        )
    return sorted(matches, key=lambda path: (len(path.parts), path.as_posix()))[0]


def _license_files(root: Path) -> list[str]:
    matches: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        name = path.name.lower()
        if (
            name.startswith(("license", "licence", "copying", "notice"))
            or "ofl" in name
        ):
            matches.append(_relative(root, path))
    return sorted(matches)


def _require_licenses(root: Path, component: str) -> list[str]:
    licenses = _license_files(root)
    if not licenses:
        raise DocumentRuntimeError(
            f"{component} source contains no LICENSE/COPYING/NOTICE file: {root}"
        )
    return licenses


def _probe_version(command: list[str], component: str) -> str:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DocumentRuntimeError(
            f"cannot execute {component} to determine its version; pass an explicit version"
        ) from exc
    output = "\n".join((completed.stdout, completed.stderr)).strip()
    first_line = next(
        (line.strip() for line in output.splitlines() if line.strip()), ""
    )
    if completed.returncode != 0 or not first_line:
        raise DocumentRuntimeError(
            f"cannot determine {component} version from {' '.join(command)}"
        )
    return first_line


def _validate_node_version(version: str) -> str:
    match = re.search(r"(?:^|\s)v?(\d+)\.", version)
    if match is None:
        raise DocumentRuntimeError(f"cannot parse Node.js version: {version!r}")
    if int(match.group(1)) < 20:
        raise DocumentRuntimeError(
            f"Node.js 20+ is required in the document runtime, got {version!r}"
        )
    return version


def _component_record(
    runtime_root: Path,
    component_root: Path,
    *,
    version: str,
    paths: dict[str, Path],
    licenses: list[str],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    digest, count, size = tree_sha256(component_root)
    record: dict[str, Any] = {
        "version": version,
        "root": _relative(runtime_root, component_root),
        "sha256": digest,
        "file_count": count,
        "byte_size": size,
        "licenses": [
            _relative(runtime_root, component_root / license) for license in licenses
        ],
    }
    record.update({name: _relative(runtime_root, path) for name, path in paths.items()})
    if extra:
        record.update(extra)
    return record


def _resolve_artifact_tool_root(source: Path) -> Path:
    candidates = (
        source,
        source / "node_modules" / "@oai" / "artifact-tool",
        source / "@oai" / "artifact-tool",
    )
    for candidate in candidates:
        package_json = candidate / "package.json"
        if not package_json.is_file():
            continue
        try:
            package = json.loads(package_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if package.get("name") == "@oai/artifact-tool":
            return candidate
    raise DocumentRuntimeError(
        f"@oai/artifact-tool package.json was not found under {source}"
    )


def _write_fontconfig(runtime_root: Path) -> Path:
    config_dir = runtime_root / "fontconfig"
    config_dir.mkdir(parents=True, exist_ok=True)
    config = config_dir / "fonts.conf"
    config.write_text(
        """<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">
<fontconfig>
  <dir prefix="relative">../fonts</dir>
  <cachedir prefix="xdg">fontconfig</cachedir>
  <alias><family>Calibri</family><prefer><family>Instrument Sans</family></prefer></alias>
  <alias><family>Aptos</family><prefer><family>Instrument Sans</family></prefer></alias>
  <alias><family>Arial</family><prefer><family>Instrument Sans</family></prefer></alias>
  <alias><family>Helvetica</family><prefer><family>Instrument Sans</family></prefer></alias>
  <alias><family>Cambria</family><prefer><family>Lora</family></prefer></alias>
  <alias><family>Times New Roman</family><prefer><family>Lora</family></prefer></alias>
  <alias><family>Courier New</family><prefer><family>JetBrains Mono</family></prefer></alias>
  <config></config>
</fontconfig>
""",
        encoding="utf-8",
    )
    return config


def assemble_document_runtime(
    *,
    out: Path,
    bundle_version: str,
    node_root: Path,
    artifact_tool_root: Path,
    artifact_tool_distribution_authorized: bool,
    chromium_root: Path,
    libreoffice_root: Path,
    poppler_root: Path,
    fonts_root: Path,
    target_platform: str | None = None,
    target_architecture: str | None = None,
    node_version: str | None = None,
    chromium_version: str | None = None,
    libreoffice_version: str | None = None,
    poppler_version: str | None = None,
) -> dict[str, Any]:
    """Build a complete runtime and return its verified manifest."""
    if not artifact_tool_distribution_authorized:
        raise DocumentRuntimeError(
            "artifact-tool redistribution was not authorized; obtain distribution "
            "rights and pass --artifact-tool-distribution-authorized"
        )
    if not bundle_version.strip():
        raise DocumentRuntimeError("bundle version must not be empty")

    artifact_source = _resolve_artifact_tool_root(artifact_tool_root.resolve())
    sources = {
        "node": node_root.resolve(),
        "artifact_tool": artifact_source,
        "chromium": chromium_root.resolve(),
        "libreoffice": libreoffice_root.resolve(),
        "poppler": poppler_root.resolve(),
        "fonts": fonts_root.resolve(),
    }
    for name, source in sources.items():
        if not source.is_dir():
            raise DocumentRuntimeError(f"{name} source is not a directory: {source}")

    out = out.resolve()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for name, source in sources.items():
        _copy_tree(source, out / name.replace("_", "-"))

    node_dir = out / "node"
    artifact_dir = out / "artifact-tool"
    chromium_dir = out / "chromium"
    libreoffice_dir = out / "libreoffice"
    poppler_dir = out / "poppler"
    fonts_dir = out / "fonts"

    node = _find_named_file(node_dir, ("node.exe", "node"))
    chromium = _find_named_file(
        chromium_dir,
        (
            "chrome.exe",
            "chrome",
            "chrome-headless-shell",
            "chromium",
            "chromium-browser",
            "google-chrome",
            "google chrome",
            "google chrome for testing",
        ),
    )
    soffice = _find_named_file(
        libreoffice_dir, ("soffice.exe", "soffice", "libreoffice")
    )
    pdftoppm = _find_named_file(poppler_dir, ("pdftoppm.exe", "pdftoppm"))
    pdfinfo = _find_named_file(poppler_dir, ("pdfinfo.exe", "pdfinfo"))
    entrypoint_candidates = (
        artifact_dir / "dist" / "node" / "artifact_tool.mjs",
        artifact_dir / "dist" / "artifact_tool.mjs",
    )
    artifact_entrypoint = next(
        (candidate for candidate in entrypoint_candidates if candidate.is_file()), None
    )
    if artifact_entrypoint is None:
        raise DocumentRuntimeError(
            f"artifact-tool has no built artifact_tool.mjs under {artifact_dir}"
        )
    package = json.loads((artifact_dir / "package.json").read_text(encoding="utf-8"))
    artifact_version = str(package.get("version") or "").strip()
    if not artifact_version:
        raise DocumentRuntimeError("artifact-tool package.json has no version")

    font_files = [
        path
        for path in fonts_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in _FONT_SUFFIXES
    ]
    if not font_files:
        raise DocumentRuntimeError(f"font pack has no TTF/OTF/TTC files: {fonts_dir}")
    fontconfig = _write_fontconfig(out)

    node_detected = _validate_node_version(
        node_version or _probe_version([str(node), "--version"], "Node.js")
    )
    chromium_detected = chromium_version or _probe_version(
        [str(chromium), "--version"], "Chromium"
    )
    libreoffice_detected = libreoffice_version or _probe_version(
        [str(soffice), "--version"], "LibreOffice"
    )
    poppler_detected = poppler_version or _probe_version(
        [str(pdftoppm), "-v"], "Poppler"
    )

    components = {
        "node": _component_record(
            out,
            node_dir,
            version=node_detected,
            paths={"executable": node},
            licenses=_require_licenses(node_dir, "Node.js"),
        ),
        "artifact_tool": _component_record(
            out,
            artifact_dir,
            version=artifact_version,
            paths={"entrypoint": artifact_entrypoint},
            licenses=_require_licenses(artifact_dir, "artifact-tool"),
            extra={"distribution_authorized": True},
        ),
        "chromium": _component_record(
            out,
            chromium_dir,
            version=chromium_detected,
            paths={"executable": chromium},
            licenses=_require_licenses(chromium_dir, "Chromium"),
        ),
        "libreoffice": _component_record(
            out,
            libreoffice_dir,
            version=libreoffice_detected,
            paths={"executable": soffice},
            licenses=_require_licenses(libreoffice_dir, "LibreOffice"),
        ),
        "poppler": _component_record(
            out,
            poppler_dir,
            version=poppler_detected,
            paths={"pdftoppm": pdftoppm, "pdfinfo": pdfinfo},
            licenses=_require_licenses(poppler_dir, "Poppler"),
        ),
        "fonts": _component_record(
            out,
            fonts_dir,
            version="evoflux-open-fonts-1",
            paths={"fontconfig": fontconfig},
            licenses=_require_licenses(fonts_dir, "font pack"),
            extra={"font_count": len(font_files)},
        ),
    }
    payload_digest, payload_count, payload_size = tree_sha256(
        out, exclude_manifest=True
    )
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "bundle_version": bundle_version,
        "target": {
            "platform": normalized_platform(target_platform),
            "architecture": normalized_architecture(target_architecture),
        },
        "payload_sha256": payload_digest,
        "payload_file_count": payload_count,
        "payload_byte_size": payload_size,
        "components": components,
    }
    (out / MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return verify_document_runtime(
        out,
        expected_platform=manifest["target"]["platform"],
        expected_architecture=manifest["target"]["architecture"],
        deep=True,
    )


def _safe_manifest_path(root: Path, value: object, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise DocumentRuntimeError(f"manifest field {label} is missing")
    relative = Path(value)
    if relative.is_absolute():
        raise DocumentRuntimeError(f"manifest field {label} must be relative")
    resolved_root = root.resolve()
    resolved = (resolved_root / relative).resolve()
    if not resolved.is_relative_to(resolved_root):
        raise DocumentRuntimeError(f"manifest field {label} escapes runtime root")
    if not resolved.is_file():
        raise DocumentRuntimeError(f"manifest field {label} is missing: {resolved}")
    return resolved


def verify_document_runtime(
    root: Path,
    *,
    expected_platform: str | None = None,
    expected_architecture: str | None = None,
    deep: bool = True,
) -> dict[str, Any]:
    """Validate paths, target, license evidence, and payload checksums."""
    root = root.resolve()
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.is_file():
        raise DocumentRuntimeError(
            f"document runtime manifest is missing: {manifest_path}"
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DocumentRuntimeError(f"invalid document runtime manifest: {exc}") from exc
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise DocumentRuntimeError(
            f"unsupported document runtime schema: {manifest.get('schema_version')!r}"
        )
    if not isinstance(manifest.get("bundle_version"), str):
        raise DocumentRuntimeError("manifest bundle_version is missing")
    target = manifest.get("target")
    if not isinstance(target, dict):
        raise DocumentRuntimeError("manifest target is missing")
    if expected_platform and target.get("platform") != normalized_platform(
        expected_platform
    ):
        raise DocumentRuntimeError(
            f"runtime platform {target.get('platform')!r} does not match "
            f"{normalized_platform(expected_platform)!r}"
        )
    if expected_architecture and target.get("architecture") != normalized_architecture(
        expected_architecture
    ):
        raise DocumentRuntimeError(
            f"runtime architecture {target.get('architecture')!r} does not match "
            f"{normalized_architecture(expected_architecture)!r}"
        )
    components = manifest.get("components")
    if not isinstance(components, dict) or set(components) != _REQUIRED_COMPONENTS:
        raise DocumentRuntimeError(
            f"manifest components must be exactly {sorted(_REQUIRED_COMPONENTS)}"
        )
    required_paths = {
        "node": ("executable",),
        "artifact_tool": ("entrypoint",),
        "chromium": ("executable",),
        "libreoffice": ("executable",),
        "poppler": ("pdftoppm", "pdfinfo"),
        "fonts": ("fontconfig",),
    }
    for name, fields in required_paths.items():
        record = components[name]
        if not isinstance(record, dict) or not str(record.get("version") or "").strip():
            raise DocumentRuntimeError(f"manifest component {name} has no version")
        root_value = record.get("root")
        if not isinstance(root_value, str):
            raise DocumentRuntimeError(f"manifest component {name} has no root")
        component_root = (root / root_value).resolve()
        if not component_root.is_relative_to(root) or not component_root.is_dir():
            raise DocumentRuntimeError(f"manifest component {name} root is invalid")
        for field in fields:
            _safe_manifest_path(root, record.get(field), f"components.{name}.{field}")
        licenses = record.get("licenses")
        if not isinstance(licenses, list) or not licenses:
            raise DocumentRuntimeError(
                f"manifest component {name} has no license evidence"
            )
        for index, license_path in enumerate(licenses):
            _safe_manifest_path(
                root, license_path, f"components.{name}.licenses[{index}]"
            )
        if deep:
            digest, count, size = tree_sha256(component_root)
            if digest != record.get("sha256"):
                raise DocumentRuntimeError(f"{name} checksum does not match manifest")
            if count != record.get("file_count") or size != record.get("byte_size"):
                raise DocumentRuntimeError(
                    f"{name} size metadata does not match manifest"
                )
    if components["artifact_tool"].get("distribution_authorized") is not True:
        raise DocumentRuntimeError(
            "artifact-tool distribution authorization is missing"
        )
    if int(components["fonts"].get("font_count") or 0) <= 0:
        raise DocumentRuntimeError("font pack is empty")
    if deep:
        digest, count, size = tree_sha256(root, exclude_manifest=True)
        if digest != manifest.get("payload_sha256"):
            raise DocumentRuntimeError(
                "document runtime payload checksum does not match"
            )
        if count != manifest.get("payload_file_count") or size != manifest.get(
            "payload_byte_size"
        ):
            raise DocumentRuntimeError(
                "document runtime payload size metadata does not match"
            )
    return manifest


def _validated_archive_member(name: str, destination: Path) -> Path:
    pure = PurePosixPath(name.replace("\\", "/"))
    if pure.is_absolute() or ".." in pure.parts:
        raise DocumentRuntimeError(f"unsafe archive path: {name}")
    target = (destination / Path(*pure.parts)).resolve()
    if not target.is_relative_to(destination.resolve()):
        raise DocumentRuntimeError(f"archive path escapes destination: {name}")
    return target


def _extract_archive(source: Path, destination: Path) -> None:
    if zipfile.is_zipfile(source):
        with zipfile.ZipFile(source) as archive:
            for info in archive.infolist():
                _validated_archive_member(info.filename, destination)
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise DocumentRuntimeError(
                        "zip document runtimes may not contain symlinks"
                    )
            archive.extractall(destination)
        return
    if tarfile.is_tarfile(source):
        with tarfile.open(source, mode="r:*") as archive:
            for member in archive.getmembers():
                member_target = _validated_archive_member(member.name, destination)
                if member.isdev() or member.isfifo():
                    raise DocumentRuntimeError(
                        f"archive contains a special file: {member.name}"
                    )
                if member.issym():
                    link = Path(member.linkname)
                    if link.is_absolute() or not (
                        member_target.parent / link
                    ).resolve().is_relative_to(destination.resolve()):
                        raise DocumentRuntimeError(
                            f"archive symlink escapes destination: {member.name}"
                        )
                if member.islnk():
                    _validated_archive_member(member.linkname, destination)
            archive.extractall(destination, filter="fully_trusted")
        return
    raise DocumentRuntimeError(f"unsupported document runtime archive: {source}")


def _locate_extracted_runtime(root: Path) -> Path:
    if (root / MANIFEST_NAME).is_file():
        return root
    candidates = [
        child
        for child in root.iterdir()
        if child.is_dir() and (child / MANIFEST_NAME).is_file()
    ]
    if len(candidates) != 1:
        raise DocumentRuntimeError(
            "archive must contain manifest.json at its root or in one top-level directory"
        )
    return candidates[0]


def stage_document_runtime(
    source: Path,
    destination: Path,
    *,
    expected_sha256: str | None = None,
    expected_platform: str | None = None,
    expected_architecture: str | None = None,
) -> dict[str, Any]:
    """Copy a verified runtime directory/archive into a release bundle."""
    source = source.resolve()
    destination = destination.resolve()
    if not source.exists():
        raise DocumentRuntimeError(f"document runtime source does not exist: {source}")
    if source.is_file():
        if not expected_sha256:
            raise DocumentRuntimeError(
                "an archive SHA-256 is required for document runtime staging"
            )
        actual = file_sha256(source)
        if actual.lower() != expected_sha256.strip().lower():
            raise DocumentRuntimeError(
                f"document runtime archive SHA-256 mismatch: expected {expected_sha256}, got {actual}"
            )
        with tempfile.TemporaryDirectory(prefix="evoflux-document-runtime-") as temp:
            extracted = Path(temp)
            _extract_archive(source, extracted)
            runtime_source = _locate_extracted_runtime(extracted)
            verify_document_runtime(
                runtime_source,
                expected_platform=expected_platform,
                expected_architecture=expected_architecture,
                deep=True,
            )
            if destination.exists():
                shutil.rmtree(destination)
            shutil.copytree(runtime_source, destination, symlinks=True)
    elif source.is_dir():
        manifest = verify_document_runtime(
            source,
            expected_platform=expected_platform,
            expected_architecture=expected_architecture,
            deep=True,
        )
        if expected_sha256 and manifest.get("payload_sha256") != expected_sha256:
            raise DocumentRuntimeError(
                "document runtime directory payload SHA-256 does not match expected value"
            )
        if source == destination:
            return manifest
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source, destination, symlinks=True)
    return verify_document_runtime(
        destination,
        expected_platform=expected_platform,
        expected_architecture=expected_architecture,
        deep=True,
    )


def _default_fonts_root() -> Path:
    return (
        Path(__file__).resolve().parents[1]
        / "app"
        / "agent"
        / "builtin_skills"
        / "canvas-design"
        / "canvas-fonts"
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    assemble = subparsers.add_parser("assemble", help="assemble from component roots")
    assemble.add_argument("--out", required=True)
    assemble.add_argument("--bundle-version", required=True)
    assemble.add_argument("--node-root", required=True)
    assemble.add_argument("--artifact-tool-root", required=True)
    assemble.add_argument(
        "--artifact-tool-distribution-authorized", action="store_true"
    )
    assemble.add_argument("--chromium-root", required=True)
    assemble.add_argument("--libreoffice-root", required=True)
    assemble.add_argument("--poppler-root", required=True)
    assemble.add_argument("--fonts-root", default=str(_default_fonts_root()))
    assemble.add_argument("--target-platform")
    assemble.add_argument("--target-architecture")
    assemble.add_argument("--node-version")
    assemble.add_argument("--chromium-version")
    assemble.add_argument("--libreoffice-version")
    assemble.add_argument("--poppler-version")

    verify = subparsers.add_parser("verify", help="verify an assembled runtime")
    verify.add_argument("path")
    verify.add_argument("--expected-platform")
    verify.add_argument("--expected-architecture")
    verify.add_argument("--shallow", action="store_true")

    stage = subparsers.add_parser("stage", help="stage a directory or checked archive")
    stage.add_argument("--source", default=os.environ.get(DOCUMENT_RUNTIME_SOURCE_ENV))
    stage.add_argument("--sha256", default=os.environ.get(DOCUMENT_RUNTIME_SHA256_ENV))
    stage.add_argument("--out", required=True)
    stage.add_argument("--expected-platform")
    stage.add_argument("--expected-architecture")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    try:
        if args.command == "assemble":
            manifest = assemble_document_runtime(
                out=Path(args.out),
                bundle_version=args.bundle_version,
                node_root=Path(args.node_root),
                artifact_tool_root=Path(args.artifact_tool_root),
                artifact_tool_distribution_authorized=args.artifact_tool_distribution_authorized,
                chromium_root=Path(args.chromium_root),
                libreoffice_root=Path(args.libreoffice_root),
                poppler_root=Path(args.poppler_root),
                fonts_root=Path(args.fonts_root),
                target_platform=args.target_platform,
                target_architecture=args.target_architecture,
                node_version=args.node_version,
                chromium_version=args.chromium_version,
                libreoffice_version=args.libreoffice_version,
                poppler_version=args.poppler_version,
            )
        elif args.command == "verify":
            manifest = verify_document_runtime(
                Path(args.path),
                expected_platform=args.expected_platform,
                expected_architecture=args.expected_architecture,
                deep=not args.shallow,
            )
        else:
            if not args.source:
                raise DocumentRuntimeError(
                    f"--source or {DOCUMENT_RUNTIME_SOURCE_ENV} is required"
                )
            manifest = stage_document_runtime(
                Path(args.source),
                Path(args.out),
                expected_sha256=args.sha256,
                expected_platform=args.expected_platform or normalized_platform(),
                expected_architecture=args.expected_architecture
                or normalized_architecture(),
            )
    except DocumentRuntimeError as exc:
        print(f"document runtime error: {exc}", file=sys.stderr)
        return 2
    print(
        f"document runtime {manifest['bundle_version']} verified for "
        f"{manifest['target']['platform']}/{manifest['target']['architecture']}"
    )
    print(f"payload sha256: {manifest['payload_sha256']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
