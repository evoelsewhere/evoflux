"""Build, trim and sign the LibreOffice runtime bundle the document viewer installs.

The sidecar never downloads LibreOffice's full installer. Maintainers run this
script (locally or in CI) to turn an official The Document Foundation package
into a trimmed ``soffice/`` tree that is enough for headless PDF conversion,
pack it as ``libreoffice-<version>-<platform>.tar.gz``, and sign its asset
record with the team's ed25519 key. The printed manifest entry is what goes
into ``app/services/office_runtime/manifest.py`` (``PINNED_ASSETS``) once the
archive is published as a release asset.

Only official TDF packages are accepted: the upstream SHA-256 is fetched from
``download.documentfoundation.org`` and checked before anything is extracted.

Examples::

    uv run python scripts/build_libreoffice_runtime.py --version 26.8.0 \\
        --platform win32-x64 --signing-key key.pem --key-id evoflux-office-1 \\
        --base-url https://github.com/evoelsewhere/evoflux/releases/download/office-runtime-26.8.0

    # Generate a new signing key pair (keep the private key in CI secrets):
    uv run python scripts/build_libreoffice_runtime.py --generate-key keys/office
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.office_runtime.manifest import RUNTIME_ROOT, signed_record  # noqa: E402

TDF_STABLE = "https://download.documentfoundation.org/libreoffice/stable"

#: Upstream package per runtime platform, relative to ``TDF_STABLE/<version>/``.
UPSTREAM_PACKAGES = {
    "win32-x64": "win/x86_64/LibreOffice_{version}_Win_x86-64.msi",
    "linux-x64": "deb/x86_64/LibreOffice_{version}_Linux_x86-64_deb.tar.gz",
    "darwin-arm64": "mac/aarch64/LibreOffice_{version}_MacOS_aarch64.dmg",
    "darwin-x64": "mac/x86_64/LibreOffice_{version}_MacOS_x86-64.dmg",
}

#: Executable inside the bundle, per platform.
EXECUTABLES = {
    "win32-x64": f"{RUNTIME_ROOT}/program/soffice.exe",
    "linux-x64": f"{RUNTIME_ROOT}/program/soffice",
    "darwin-arm64": f"{RUNTIME_ROOT}/LibreOffice.app/Contents/MacOS/soffice",
    "darwin-x64": f"{RUNTIME_ROOT}/LibreOffice.app/Contents/MacOS/soffice",
}

#: Data that headless PDF conversion never touches: UI help and translations,
#: icon themes other than the default, galleries, templates, wizards,
#: extensions (dictionaries, wiki publisher), PDF import and other languages'
#: configuration. Relative to the directory that holds LibreOffice's shared
#: data: ``share/`` on Windows/Linux, ``Contents/Resources`` on macOS.
SHARED_PRUNE = (
    "extensions",
    "gallery",
    "template",
    "wizards",
    "xpdfimport",
    "autotext",
    "wordbook",
    "config/images_*.zip",
    "registry/Langpack-*.xcd",
    "registry/res/fcfg_langpack_*.xcd",
)

#: Kept despite matching a pattern above.
SHARED_KEEP = (
    "config/images_colibre.zip",
    "registry/Langpack-en-US.xcd",
    "registry/res/fcfg_langpack_en-US.xcd",
)

#: Program-tree extras on Windows/Linux (relative to the install root). The
#: macOS app keeps its frameworks untouched: they are linked, not data.
PROGRAM_PRUNE = (
    "help",
    "readmes",
    "program/python-core-*",
    "program/python*.dll",
    "program/python.exe",
    "program/pythonw.exe",
    "program/classes",
    "program/resource/*",
)
PROGRAM_KEEP = ("program/resource/en-US",)
MACOS_RESOURCE_PRUNE = ("resource/*",)
MACOS_RESOURCE_KEEP = ("resource/en-US",)


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _download(url: str, destination: Path) -> None:
    _log(f"download {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "evoflux-build"})
    with (
        urllib.request.urlopen(request, timeout=120) as response,
        destination.open("wb") as handle,
    ):
        shutil.copyfileobj(response, handle, length=1024 * 1024)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _upstream_sha256(url: str) -> str:
    with urllib.request.urlopen(f"{url}.sha256", timeout=60) as response:
        value = response.read().decode("ascii").split()[0].lower()
    if len(value) != 64:
        raise SystemExit(f"Unexpected upstream checksum for {url}")
    return value


def _fetch_upstream(
    version: str, platform: str, work: Path, cached: Path | None
) -> Path:
    url = (
        f"{TDF_STABLE}/{version}/{UPSTREAM_PACKAGES[platform].format(version=version)}"
    )
    expected = _upstream_sha256(url)
    package = cached if cached is not None else work / Path(url).name
    if cached is None:
        _download(url, package)
    actual = _sha256(package)
    if actual != expected:
        raise SystemExit(f"Upstream checksum mismatch: {actual} != {expected}")
    _log(f"verified upstream sha256 {actual}")
    return package


def _extract_windows(package: Path, work: Path) -> Path:
    """Unpack the MSI as an administrative image: no install, no elevation."""
    target = work / "msi"
    target.mkdir()
    subprocess.run(
        ["msiexec", "/a", str(package), "/qn", f"TARGETDIR={target}"],
        check=True,
    )
    program_root = target
    fonts = target / "Fonts"
    destination = program_root / "share" / "fonts" / "truetype"
    destination.mkdir(parents=True, exist_ok=True)
    if fonts.is_dir():
        # The MSI installs its metric-compatible fonts (Liberation, Carlito,
        # Caladea, DejaVu, Noto) system-wide; the bundle ships them itself.
        for font in fonts.iterdir():
            shutil.copy2(font, destination / font.name)
    for runtime_dir in ("System64", "System"):
        runtime = target / runtime_dir
        if runtime.is_dir():
            # VC++ runtime DLLs, for machines without the redistributable.
            for dll in runtime.glob("*.dll"):
                if not (program_root / "program" / dll.name).exists():
                    shutil.copy2(dll, program_root / "program" / dll.name)
            break
    for leftover in ("Fonts", "System", "System64", package.name):
        path = target / leftover
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
    return program_root


def _extract_linux(package: Path, work: Path) -> Path:
    with tarfile.open(package) as archive:
        archive.extractall(work / "deb", filter="data")
    target = work / "root"
    target.mkdir()
    for deb in sorted((work / "deb").rglob("*.deb")):
        subprocess.run(["dpkg-deb", "-x", str(deb), str(target)], check=True)
    candidates = sorted((target / "opt").glob("libreoffice*"))
    if not candidates:
        raise SystemExit("No /opt/libreoffice* tree in the upstream packages")
    return candidates[0]


def _extract_macos(package: Path, work: Path) -> Path:
    mount = work / "mount"
    mount.mkdir()
    subprocess.run(
        [
            "hdiutil",
            "attach",
            "-nobrowse",
            "-readonly",
            "-mountpoint",
            str(mount),
            str(package),
        ],
        check=True,
    )
    try:
        app = work / "LibreOffice.app"
        subprocess.run(["ditto", str(mount / "LibreOffice.app"), str(app)], check=True)
    finally:
        subprocess.run(["hdiutil", "detach", str(mount)], check=False)
    return app


def _prune(
    program_root: Path, patterns: tuple[str, ...], kept: tuple[str, ...]
) -> None:
    keep = {(program_root / item).resolve() for item in kept}
    for pattern in patterns:
        for path in program_root.glob(pattern):
            resolved = path.resolve()
            if resolved in keep:
                continue
            if any(k.is_relative_to(resolved) for k in keep):
                # A kept path lives inside this one: prune around it.
                for child in path.iterdir():
                    if child.resolve() not in keep:
                        _remove(child)
                continue
            _remove(path)


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def _stage(program_root: Path, platform: str, work: Path) -> Path:
    stage = work / "stage"
    bundle = stage / RUNTIME_ROOT
    stage.mkdir()
    if platform.startswith("darwin"):
        bundle.mkdir()
        app = bundle / "LibreOffice.app"
        shutil.move(str(program_root), str(app))
        resources = app / "Contents" / "Resources"
        _prune(resources, SHARED_PRUNE, SHARED_KEEP)
        _prune(resources, MACOS_RESOURCE_PRUNE, MACOS_RESOURCE_KEEP)
        _resign_macos_app(app)
    else:
        shutil.move(str(program_root), str(bundle))
        _prune(bundle / "share", SHARED_PRUNE, SHARED_KEEP)
        _prune(bundle, PROGRAM_PRUNE, PROGRAM_KEEP)
    executable = stage / EXECUTABLES[platform]
    if not executable.is_file():
        raise SystemExit(f"Trimmed bundle is missing {EXECUTABLES[platform]}")
    return stage


def _resign_macos_app(app: Path) -> None:
    """Re-seal the trimmed app with an ad-hoc signature.

    Removing resources breaks TDF's sealed Developer ID signature, and Apple
    Silicon refuses to run code whose signature does not validate. An ad-hoc
    signature without the hardened runtime keeps every Mach-O valid and lets
    the app load its own (now ad-hoc signed) frameworks.
    """
    subprocess.run(
        ["codesign", "--force", "--deep", "--sign", "-", str(app)],
        check=True,
    )
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)


def _smoke_test(stage: Path, platform: str, sample: Path | None, work: Path) -> None:
    if sample is None:
        return
    profile = work / "profile"
    output = work / "smoke"
    output.mkdir()
    subprocess.run(
        [
            str(stage / EXECUTABLES[platform]),
            "--headless",
            "--norestore",
            "--nolockcheck",
            f"-env:UserInstallation={profile.resolve().as_uri()}",
            "--convert-to",
            "pdf",
            "--outdir",
            str(output),
            str(sample),
        ],
        check=True,
        timeout=600,
    )
    if not any(output.glob("*.pdf")):
        raise SystemExit("Smoke conversion produced no PDF")
    _log(f"smoke conversion ok: {sample.name}")


def _pack(stage: Path, destination: Path) -> None:
    def normalize(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
        if info.issym() or info.islnk():
            # macOS frameworks use symlinks; keep them only inside the bundle.
            target = Path(info.name).parent / info.linkname
            if ".." in Path(os.path.normpath(target)).parts:
                return None
        info.uid = info.gid = 0
        info.uname = info.gname = ""
        info.mtime = 0
        return info

    with tarfile.open(destination, "w:gz", compresslevel=9) as archive:
        archive.add(stage / RUNTIME_ROOT, arcname=RUNTIME_ROOT, filter=normalize)


def _sign(record: bytes, key_path: Path) -> str:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    key = load_pem_private_key(key_path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise SystemExit("Signing key must be an ed25519 private key")
    return base64.b64encode(key.sign(record)).decode("ascii")


def _generate_key(prefix: Path) -> None:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    prefix.parent.mkdir(parents=True, exist_ok=True)
    private_path = prefix.with_suffix(".private.pem")
    private_path.write_bytes(private)
    os.chmod(private_path, 0o600)
    prefix.with_suffix(".public.pem").write_bytes(public)
    _log(f"wrote {private_path} and {prefix.with_suffix('.public.pem')}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--version", help="LibreOffice version, e.g. 26.8.0")
    parser.add_argument("--platform", choices=sorted(UPSTREAM_PACKAGES))
    parser.add_argument("--output", type=Path, default=Path("dist/office-runtime"))
    parser.add_argument("--signing-key", type=Path, help="ed25519 private key (PEM)")
    parser.add_argument("--key-id", help="identifier pinned next to the public key")
    parser.add_argument("--base-url", help="release URL the archive is published under")
    parser.add_argument(
        "--upstream-package",
        type=Path,
        help="already downloaded TDF package (still checksum-verified)",
    )
    parser.add_argument(
        "--smoke-sample",
        type=Path,
        help="Office file to convert with the trimmed bundle before packing",
    )
    parser.add_argument(
        "--generate-key",
        type=Path,
        metavar="PREFIX",
        help="write PREFIX.private.pem / PREFIX.public.pem and exit",
    )
    args = parser.parse_args()
    if args.generate_key:
        _generate_key(args.generate_key)
        return
    missing = [
        name
        for name in ("version", "platform", "signing_key", "key_id", "base_url")
        if getattr(args, name) is None
    ]
    if missing:
        parser.error(
            "missing " + ", ".join(f"--{m.replace('_', '-')}" for m in missing)
        )

    args.output.mkdir(parents=True, exist_ok=True)
    archive_name = f"libreoffice-{args.version}-{args.platform}.tar.gz"
    archive = args.output / archive_name
    with tempfile.TemporaryDirectory(prefix="evoflux-lo-") as directory:
        work = Path(directory)
        package = _fetch_upstream(
            args.version, args.platform, work, args.upstream_package
        )
        extract = {
            "win32-x64": _extract_windows,
            "linux-x64": _extract_linux,
            "darwin-arm64": _extract_macos,
            "darwin-x64": _extract_macos,
        }[args.platform]
        program_root = extract(package, work)
        stage = _stage(program_root, args.platform, work)
        _smoke_test(stage, args.platform, args.smoke_sample, work)
        _pack(stage, archive)

    sha256 = _sha256(archive)
    size = archive.stat().st_size
    executable = EXECUTABLES[args.platform]
    record = signed_record(
        platform=args.platform,
        version=args.version,
        sha256=sha256,
        size=size,
        key_id=args.key_id,
        executable=executable,
    )
    entry = {
        "version": args.version,
        "url": f"{args.base_url.rstrip('/')}/{archive_name}",
        "sha256": sha256,
        "size": size,
        "keyId": args.key_id,
        "signature": _sign(record, args.signing_key),
        "executable": executable,
    }
    manifest = args.output / f"libreoffice-{args.version}-{args.platform}.json"
    manifest.write_text(json.dumps({args.platform: entry}, indent=2) + "\n")
    _log(f"wrote {archive} ({size / 1024 / 1024:.1f} MiB) and {manifest}")
    print(json.dumps({args.platform: entry}, indent=2))


if __name__ == "__main__":
    main()
