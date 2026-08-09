"""Safe local creation, linking, installation, packing, and removal."""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import uuid4

from app.plugin_platform.models import PLUGIN_SCHEMA_ID, PluginInstallation
from app.plugin_platform.registry import (
    add_installation,
    get_installation,
    installed_root,
    plugin_data_root,
    remove_installation,
    staging_root,
)
from app.plugin_platform.validator import (
    MAX_PACKAGE_BYTES,
    MAX_PACKAGE_FILES,
    inspect_plugin,
    package_has_symlinks,
)


MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
MAX_ARCHIVE_RATIO = 200


class PluginInstallError(ValueError):
    """A package failed validation or a lifecycle safety check."""


def _require_valid(root: Path, *, data_root: Path):
    inspection = inspect_plugin(root, data_root=data_root)
    if not inspection.valid or inspection.manifest is None:
        messages = [
            item.message for item in inspection.diagnostics if item.severity == "error"
        ]
        raise PluginInstallError("; ".join(messages) or "Plugin is invalid.")
    return inspection


def _version_segment(version: str | None, digest: str) -> str:
    if version:
        normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", version).strip("-.")
        if normalized:
            return normalized[:80]
    return digest[:16]


def _safe_archive_name(name: str) -> PurePosixPath:
    if "\\" in name or name.startswith("/") or not name:
        raise PluginInstallError(f"Unsafe archive path: {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise PluginInstallError(f"Unsafe archive path: {name!r}")
    return path


def _extract_archive(archive: Path, destination: Path) -> Path:
    if archive.stat().st_size > MAX_ARCHIVE_BYTES:
        raise PluginInstallError(
            f"Archive exceeds the {MAX_ARCHIVE_BYTES}-byte compressed limit."
        )
    seen: set[str] = set()
    folded: set[str] = set()
    total = 0
    with zipfile.ZipFile(archive) as bundle:
        infos = bundle.infolist()
        if len(infos) > MAX_PACKAGE_FILES:
            raise PluginInstallError(
                f"Archive exceeds the {MAX_PACKAGE_FILES}-entry limit."
            )
        for info in infos:
            path = _safe_archive_name(info.filename.rstrip("/"))
            normalized = path.as_posix()
            folded_name = normalized.casefold()
            if normalized in seen or folded_name in folded:
                raise PluginInstallError(f"Duplicate archive path: {normalized}")
            seen.add(normalized)
            folded.add(folded_name)
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise PluginInstallError(
                    f"Archive symlinks are not allowed: {normalized}"
                )
            total += info.file_size
            if total > MAX_PACKAGE_BYTES:
                raise PluginInstallError(
                    f"Archive exceeds the {MAX_PACKAGE_BYTES}-byte expanded limit."
                )
            compressed = max(info.compress_size, 1)
            if (
                info.file_size > 1024 * 1024
                and info.file_size / compressed > MAX_ARCHIVE_RATIO
            ):
                raise PluginInstallError(
                    f"Suspicious compression ratio for archive entry: {normalized}"
                )
            target = destination.joinpath(*path.parts)
            try:
                target.absolute().relative_to(destination.absolute())
            except ValueError as exc:
                raise PluginInstallError(
                    f"Archive path escapes staging: {normalized}"
                ) from exc
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(info) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
            # Preserve only the portable executable signal. Never trust archive
            # ownership, setuid, or group/world write bits.
            target.chmod(0o755 if mode & 0o111 else 0o644)
    if not (destination / "plugin.json").is_file():
        raise PluginInstallError("Archive root must contain plugin.json directly.")
    return destination


def _source_root(source: Path, staging: Path) -> Path:
    if source.is_dir():
        return source.resolve()
    if source.is_file() and source.suffix.casefold() in {".evoplugin", ".zip"}:
        return _extract_archive(source, staging / "archive")
    raise PluginInstallError(
        "Source must be a plugin directory or .evoplugin/.zip file."
    )


def link_plugin(source: str | Path, *, enabled: bool = True) -> PluginInstallation:
    root = Path(source).expanduser().resolve()
    installation_id = uuid4().hex
    inspection = _require_valid(root, data_root=plugin_data_root(installation_id))
    assert inspection.manifest is not None and inspection.content_sha256 is not None
    now = datetime.now(UTC).isoformat()
    installation = PluginInstallation(
        id=installation_id,
        name=inspection.manifest.name,
        version=inspection.manifest.version,
        description=inspection.manifest.description,
        root=str(root),
        source_type="linked",
        source_ref=str(root),
        content_sha256=inspection.content_sha256,
        enabled=enabled,
        installed_at=now,
        updated_at=now,
    )
    return add_installation(installation)


def install_plugin(
    source: str | Path,
    *,
    enabled: bool = True,
    source_ref: str | None = None,
) -> PluginInstallation:
    source_path = Path(source).expanduser().absolute()
    installation_id = uuid4().hex
    cache_root = staging_root()
    cache_root.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="install-", dir=cache_root))
    final_path: Path | None = None
    try:
        package_source = _source_root(source_path, temporary)
        inspection = _require_valid(
            package_source,
            data_root=plugin_data_root(installation_id),
        )
        if package_has_symlinks(package_source):
            raise PluginInstallError(
                "Managed installs reject symlinks; use developer link for a contained symlink package."
            )
        assert inspection.manifest is not None and inspection.content_sha256 is not None
        staged_package = temporary / "package"
        shutil.copytree(package_source, staged_package)
        staged_inspection = _require_valid(
            staged_package,
            data_root=plugin_data_root(installation_id),
        )
        if staged_inspection.content_sha256 != inspection.content_sha256:
            raise PluginInstallError("Package changed while it was being staged.")
        version = _version_segment(
            inspection.manifest.version,
            inspection.content_sha256,
        )
        final_path = installed_root() / installation_id / version
        final_path.parent.mkdir(parents=True, exist_ok=True)
        if final_path.exists():
            raise PluginInstallError(f"Install target already exists: {final_path}")
        os.replace(staged_package, final_path)
        now = datetime.now(UTC).isoformat()
        installation = PluginInstallation(
            id=installation_id,
            name=inspection.manifest.name,
            version=inspection.manifest.version,
            description=inspection.manifest.description,
            root=str(final_path),
            source_type="installed",
            source_ref=source_ref or str(source_path.resolve()),
            content_sha256=inspection.content_sha256,
            enabled=enabled,
            installed_at=now,
            updated_at=now,
        )
        try:
            return add_installation(installation)
        except Exception:
            shutil.rmtree(final_path.parent, ignore_errors=True)
            raise
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def uninstall_plugin(
    installation_id: str, *, remove_data: bool = False
) -> PluginInstallation:
    installation = get_installation(installation_id)
    if installation is None:
        raise KeyError(installation_id)
    trashed: Path | None = None
    original: Path | None = None
    if installation.source_type == "installed":
        managed = installed_root().resolve()
        root = Path(installation.root).resolve()
        try:
            owned = root.relative_to(managed)
        except ValueError as exc:
            raise PluginInstallError(
                f"Refusing to delete an unowned install path: {root}"
            ) from exc
        if len(owned.parts) < 2 or owned.parts[0] != installation_id:
            raise PluginInstallError(
                f"Refusing to delete mismatched install path: {root}"
            )
        original = managed / installation_id
        if original.exists():
            trashed = managed / f".uninstall-{installation_id}-{uuid4().hex}"
            os.replace(original, trashed)
    try:
        removed = remove_installation(installation_id)
    except Exception:
        if trashed is not None and original is not None:
            os.replace(trashed, original)
        raise
    if trashed is not None:
        shutil.rmtree(trashed, ignore_errors=True)
    if remove_data:
        data = plugin_data_root(installation_id)
        platform_data = data.parent.resolve()
        resolved = data.resolve()
        try:
            resolved.relative_to(platform_data)
        except ValueError as exc:
            raise PluginInstallError(
                f"Refusing to delete plugin data path: {data}"
            ) from exc
        shutil.rmtree(resolved, ignore_errors=True)
    return removed


def create_plugin(
    destination: str | Path,
    *,
    name: str,
    description: str = "",
    skill_name: str | None = None,
) -> Path:
    root = Path(destination).expanduser().absolute()
    if root.exists():
        raise PluginInstallError(f"Destination already exists: {root}")
    manifest = {
        "$schema": PLUGIN_SCHEMA_ID,
        "name": name,
    }
    if description:
        manifest["description"] = description
    root.mkdir(parents=True)
    try:
        (root / "plugin.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=False) + "\n",
            encoding="utf-8",
        )
        if skill_name:
            skill_dir = root / "skills" / skill_name
            skill_dir.mkdir(parents=True)
            skill_description = (
                description or f"Use {skill_name} for its documented workflow."
            )
            (skill_dir / "SKILL.md").write_text(
                "---\n"
                f"name: {skill_name}\n"
                f"description: {json.dumps(skill_description)}\n"
                "---\n\n"
                f"# {skill_name.replace('-', ' ').title()}\n\n"
                "Describe the workflow, evidence requirements, and stop conditions here.\n",
                encoding="utf-8",
            )
        inspection = inspect_plugin(root)
        invalid_component = any(not skill.valid for skill in inspection.skills)
        if not inspection.valid or invalid_component:
            raise PluginInstallError(
                "; ".join(
                    [
                        item.message
                        for item in inspection.diagnostics
                        if item.severity == "error"
                    ]
                    + [
                        diagnostic.message
                        for skill in inspection.skills
                        for diagnostic in skill.diagnostics
                        if diagnostic.severity == "error"
                    ]
                )
            )
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise
    return root


def pack_plugin(source: str | Path, output: str | Path | None = None) -> Path:
    root = Path(source).expanduser().resolve()
    inspection = _require_valid(root, data_root=root / ".plugin-data-validation")
    if package_has_symlinks(root):
        raise PluginInstallError("Packed .evoplugin archives cannot contain symlinks.")
    assert inspection.manifest is not None
    target = (
        Path(output).expanduser().absolute()
        if output is not None
        else root.parent
        / f"{inspection.manifest.name}-{inspection.manifest.version or 'unversioned'}.evoplugin"
    )
    if target.exists():
        raise PluginInstallError(f"Output already exists: {target}")
    try:
        target.relative_to(root)
    except ValueError:
        pass
    else:
        raise PluginInstallError("Output archive must be outside the plugin root.")
    files = sorted(
        (item for item in root.rglob("*") if item.is_file()),
        key=lambda item: item.relative_to(root).as_posix(),
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for path in files:
            relative = path.relative_to(root).as_posix()
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            mode = 0o755 if path.stat().st_mode & 0o111 else 0o644
            info.external_attr = ((stat.S_IFREG | mode) & 0xFFFF) << 16
            archive.writestr(
                info,
                path.read_bytes(),
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            )
    return target


__all__ = [
    "PluginInstallError",
    "create_plugin",
    "install_plugin",
    "link_plugin",
    "pack_plugin",
    "uninstall_plugin",
]
