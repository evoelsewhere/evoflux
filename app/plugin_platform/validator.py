"""Agent Plugins v1 directory inspection and validation.

The normative prose has a few failure boundaries JSON Schema cannot express:
unknown root manifest fields and a non-object ``extensions`` value are
reported and ignored, while other manifest failures are fatal. MCP top-level
failures disable MCP only, and server entries fail independently.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import urllib.parse
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import ValidationError

from app.agent.skills.discovery import parse_frontmatter
from app.plugin_platform.models import (
    MCP_SCHEMA_ID,
    MCP_SERVER_ADAPTER,
    PLUGIN_SCHEMA_ID,
    SKILL_NAME_RE,
    PluginDiagnostic,
    PluginInspection,
    PluginManifest,
    PluginMCPComponent,
    PluginSkillComponent,
    PortableHttpServer,
    PortableStdioServer,
)


MAX_MANIFEST_BYTES = 512 * 1024
MAX_SKILL_BYTES = 512 * 1024
MAX_MCP_BYTES = 2 * 1024 * 1024
MAX_PACKAGE_FILES = 2_000
MAX_PACKAGE_BYTES = 200 * 1024 * 1024
_MANIFEST_FIELDS = {
    "$schema",
    "name",
    "version",
    "description",
    "author",
    "homepage",
    "repository",
    "license",
    "keywords",
    "extensions",
}
_HTTP_FIELD_NAME_RE = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")


def _diagnostic(
    severity: str,
    code: str,
    message: str,
    *,
    scope: str = "package",
) -> PluginDiagnostic:
    return PluginDiagnostic(
        severity="error" if severity == "error" else "warning",
        code=code,
        message=message,
        scope=scope,
    )


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _read_bounded_json(path: Path, limit: int) -> Any:
    size = path.stat().st_size
    if size > limit:
        raise ValueError(f"file exceeds the {limit}-byte limit")
    with path.open("rb") as handle:
        payload = handle.read(limit + 1)
    if len(payload) > limit:
        raise ValueError(f"file exceeds the {limit}-byte limit")
    try:
        return json.loads(payload.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError("file is not valid UTF-8") from exc
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc


def _package_digest(root: Path) -> str:
    digest = hashlib.sha256()
    count = 0
    total = 0
    for base, dirs, files in os.walk(root, followlinks=False):
        dirs.sort()
        files.sort()
        base_path = Path(base)
        for name in dirs:
            path = base_path / name
            mode = path.lstat().st_mode
            if not stat.S_ISLNK(mode):
                continue
            count += 1
            if count > MAX_PACKAGE_FILES:
                raise ValueError(f"package exceeds the {MAX_PACKAGE_FILES}-file limit")
            relative = path.relative_to(root).as_posix()
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0link\0")
            digest.update(
                os.readlink(path).encode("utf-8", errors="surrogateescape")
            )
        for name in files:
            path = base_path / name
            count += 1
            if count > MAX_PACKAGE_FILES:
                raise ValueError(f"package exceeds the {MAX_PACKAGE_FILES}-file limit")
            relative = path.relative_to(root).as_posix()
            digest.update(relative.encode("utf-8"))
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                target = os.readlink(path)
                digest.update(b"\0link\0")
                digest.update(target.encode("utf-8", errors="surrogateescape"))
                continue
            if not stat.S_ISREG(mode):
                raise ValueError(f"unsupported package entry type: {relative}")
            size = path.stat().st_size
            total += size
            if total > MAX_PACKAGE_BYTES:
                raise ValueError(f"package exceeds the {MAX_PACKAGE_BYTES}-byte limit")
            digest.update(b"\0file\0")
            digest.update(b"x" if mode & 0o111 else b"-")
            with path.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    digest.update(chunk)
    return digest.hexdigest()


def _inspect_links(root: Path) -> list[PluginDiagnostic]:
    diagnostics: list[PluginDiagnostic] = []
    seen = 0
    for base, dirs, files in os.walk(root, followlinks=False):
        entries = [
            *(Path(base) / item for item in dirs),
            *(Path(base) / item for item in files),
        ]
        for path in entries:
            seen += 1
            if seen > MAX_PACKAGE_FILES:
                diagnostics.append(
                    _diagnostic(
                        "error",
                        "package-entry-limit",
                        f"Package exceeds the {MAX_PACKAGE_FILES}-entry limit.",
                    )
                )
                return diagnostics
            try:
                mode = path.lstat().st_mode
            except OSError as exc:
                diagnostics.append(
                    _diagnostic(
                        "error",
                        "package-entry-unreadable",
                        f"Could not inspect {path.relative_to(root).as_posix()}: {exc}",
                    )
                )
                continue
            if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode) or stat.S_ISLNK(mode)):
                diagnostics.append(
                    _diagnostic(
                        "error",
                        "package-entry-type",
                        f"Unsupported package entry type: {path.relative_to(root).as_posix()}",
                    )
                )
                continue
            if not stat.S_ISLNK(mode):
                continue
            if not _inside(path, root):
                diagnostics.append(
                    _diagnostic(
                        "error",
                        "escaping-symlink",
                        f"Symlink escapes the plugin root: {path.relative_to(root).as_posix()}",
                    )
                )
    return diagnostics


def _load_manifest(
    root: Path, diagnostics: list[PluginDiagnostic]
) -> PluginManifest | None:
    manifest_path = root / "plugin.json"
    if not manifest_path.exists():
        diagnostics.append(
            _diagnostic("error", "manifest-missing", "plugin.json is required.")
        )
        return None
    if not manifest_path.is_file() or not _inside(manifest_path, root):
        diagnostics.append(
            _diagnostic(
                "error",
                "manifest-invalid-path",
                "plugin.json must be a regular file contained by the plugin root.",
            )
        )
        return None
    try:
        raw = _read_bounded_json(manifest_path, MAX_MANIFEST_BYTES)
    except (OSError, ValueError) as exc:
        diagnostics.append(
            _diagnostic("error", "manifest-unreadable", f"plugin.json: {exc}")
        )
        return None
    if not isinstance(raw, dict):
        diagnostics.append(
            _diagnostic(
                "error", "manifest-not-object", "plugin.json must be a JSON object."
            )
        )
        return None

    filtered = dict(raw)
    for field in sorted(set(raw) - _MANIFEST_FIELDS):
        diagnostics.append(
            _diagnostic(
                "warning",
                "manifest-unknown-field",
                f"Unknown plugin.json field was ignored: {field}",
                scope="manifest",
            )
        )
        filtered.pop(field, None)
    if "extensions" in filtered and not isinstance(filtered["extensions"], dict):
        diagnostics.append(
            _diagnostic(
                "warning",
                "manifest-invalid-extensions",
                "Non-object extensions value was ignored.",
                scope="manifest",
            )
        )
        filtered.pop("extensions", None)

    try:
        return PluginManifest.model_validate(filtered)
    except ValidationError as exc:
        diagnostics.append(
            _diagnostic(
                "error",
                "manifest-schema-invalid",
                f"plugin.json does not conform to {PLUGIN_SCHEMA_ID}: {exc}",
                scope="manifest",
            )
        )
        return None


def _inspect_skills(
    root: Path,
) -> tuple[list[PluginSkillComponent], list[PluginDiagnostic]]:
    skills: list[PluginSkillComponent] = []
    diagnostics: list[PluginDiagnostic] = []
    skills_root = root / "skills"
    if not skills_root.exists():
        return skills, diagnostics
    if not skills_root.is_dir() or not _inside(skills_root, root):
        diagnostics.append(
            _diagnostic(
                "error",
                "skills-location-invalid",
                "skills must be a directory contained by the plugin root.",
                scope="skills",
            )
        )
        return skills, diagnostics

    try:
        children = sorted(skills_root.iterdir(), key=lambda item: item.name)
    except OSError as exc:
        diagnostics.append(
            _diagnostic(
                "error",
                "skills-unreadable",
                f"Could not read skills/: {exc}",
                scope="skills",
            )
        )
        return skills, diagnostics

    for child in children:
        if not child.is_dir():
            continue
        skill_file = child / "SKILL.md"
        if not skill_file.is_file():
            continue
        component_diagnostics: list[PluginDiagnostic] = []
        scope = f"skill:{child.name}"
        if not _inside(child, root) or not _inside(skill_file, root):
            component_diagnostics.append(
                _diagnostic(
                    "error",
                    "skill-path-escapes-root",
                    "Skill directory or SKILL.md resolves outside the plugin root.",
                    scope=scope,
                )
            )
            skills.append(
                PluginSkillComponent(
                    name=child.name,
                    path=f"skills/{child.name}/SKILL.md",
                    valid=False,
                    diagnostics=component_diagnostics,
                )
            )
            continue
        name = child.name
        description = ""
        try:
            if skill_file.stat().st_size > MAX_SKILL_BYTES:
                raise ValueError(f"SKILL.md exceeds {MAX_SKILL_BYTES} bytes")
            with skill_file.open("rb") as handle:
                payload = handle.read(MAX_SKILL_BYTES + 1)
            if len(payload) > MAX_SKILL_BYTES:
                raise ValueError(f"SKILL.md exceeds {MAX_SKILL_BYTES} bytes")
            text = payload.decode("utf-8")
            metadata, body = parse_frontmatter(text)
            raw_name = metadata.get("name")
            raw_description = metadata.get("description")
            if not isinstance(raw_name, str) or not raw_name:
                raise ValueError("frontmatter requires a non-empty name")
            name = raw_name
            if name != child.name:
                raise ValueError(
                    f"frontmatter name {name!r} must match directory {child.name!r}"
                )
            if len(name) > 64 or not SKILL_NAME_RE.fullmatch(name):
                raise ValueError(
                    "name is not portable lowercase-hyphenated Agent Skills format"
                )
            if not isinstance(raw_description, str) or not raw_description.strip():
                raise ValueError("frontmatter requires a non-empty description")
            description = raw_description.strip()
            if len(description) > 1024:
                raise ValueError("description exceeds 1024 characters")
            if not body:
                raise ValueError("instruction body is empty")
        except (OSError, UnicodeError, ValueError) as exc:
            component_diagnostics.append(
                _diagnostic("error", "skill-invalid", str(exc), scope=scope)
            )
        skills.append(
            PluginSkillComponent(
                name=name,
                description=description,
                path=f"skills/{child.name}/SKILL.md",
                valid=not component_diagnostics,
                diagnostics=component_diagnostics,
            )
        )
    return skills, diagnostics


def _validate_stdio(
    server: PortableStdioServer,
    *,
    root: Path,
    data_root: Path,
    scope: str,
) -> list[PluginDiagnostic]:
    diagnostics: list[PluginDiagnostic] = []
    command = server.command
    if command.startswith("./"):
        if not _inside(root / PurePosixPath(command[2:]), root):
            diagnostics.append(
                _diagnostic(
                    "error",
                    "mcp-command-escapes-root",
                    "command escapes the plugin root.",
                    scope=scope,
                )
            )
    elif "/" in command or "\\" in command or command.startswith("."):
        diagnostics.append(
            _diagnostic(
                "error",
                "mcp-command-invalid",
                "command must be a bare executable name or begin with './'.",
                scope=scope,
            )
        )
    if "PLUGIN_ROOT" in server.env or "PLUGIN_DATA" in server.env:
        diagnostics.append(
            _diagnostic(
                "error",
                "mcp-reserved-env",
                "env must not define PLUGIN_ROOT or PLUGIN_DATA.",
                scope=scope,
            )
        )
    if server.cwd is not None:
        value = server.cwd
        if value.startswith("./"):
            candidate = root / PurePosixPath(value[2:])
            allowed = root
        elif value == "${PLUGIN_ROOT}" or value.startswith("${PLUGIN_ROOT}/"):
            suffix = value.removeprefix("${PLUGIN_ROOT}").lstrip("/")
            candidate = root / PurePosixPath(suffix)
            allowed = root
        elif value == "${PLUGIN_DATA}" or value.startswith("${PLUGIN_DATA}/"):
            suffix = value.removeprefix("${PLUGIN_DATA}").lstrip("/")
            candidate = data_root / PurePosixPath(suffix)
            allowed = data_root
        else:
            candidate = root
            allowed = Path("/__invalid_plugin_cwd__")
            diagnostics.append(
                _diagnostic(
                    "error",
                    "mcp-cwd-invalid",
                    "cwd must be plugin-relative, PLUGIN_ROOT-rooted, or PLUGIN_DATA-rooted.",
                    scope=scope,
                )
            )
        if not _inside(candidate, allowed):
            diagnostics.append(
                _diagnostic(
                    "error",
                    "mcp-cwd-escapes-root",
                    "cwd escapes its allowed root.",
                    scope=scope,
                )
            )
    return diagnostics


def _is_loopback(host: str | None) -> bool:
    if host is None:
        return False
    normalized = host.strip("[]").casefold()
    if normalized == "localhost":
        return True
    try:
        import ipaddress

        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _validate_http(server: PortableHttpServer, *, scope: str) -> list[PluginDiagnostic]:
    diagnostics: list[PluginDiagnostic] = []
    try:
        parsed = urllib.parse.urlsplit(server.url)
        hostname = parsed.hostname
        parsed.port
    except ValueError as exc:
        diagnostics.append(
            _diagnostic(
                "error", "mcp-url-invalid", f"Invalid HTTP(S) URL: {exc}", scope=scope
            )
        )
        return diagnostics
    if parsed.scheme not in {"http", "https"} or not hostname:
        diagnostics.append(
            _diagnostic(
                "error",
                "mcp-url-invalid",
                "url must be an absolute HTTP(S) URL.",
                scope=scope,
            )
        )
    if parsed.username is not None or parsed.password is not None or parsed.fragment:
        diagnostics.append(
            _diagnostic(
                "error",
                "mcp-url-unsafe",
                "url must not contain user information or a fragment.",
                scope=scope,
            )
        )
    if parsed.scheme == "http" and not _is_loopback(hostname):
        diagnostics.append(
            _diagnostic(
                "error",
                "mcp-url-insecure",
                "Non-loopback MCP endpoints must use HTTPS.",
                scope=scope,
            )
        )
    lowered: set[str] = set()
    for key, value in server.headers.items():
        normalized = key.casefold()
        if normalized in lowered:
            diagnostics.append(
                _diagnostic(
                    "error",
                    "mcp-header-duplicate",
                    f"Duplicate case-insensitive header: {key}",
                    scope=scope,
                )
            )
        lowered.add(normalized)
        invalid_value = any(
            ord(character) == 127 or (ord(character) < 32 and character != "\t")
            for character in value
        )
        if _HTTP_FIELD_NAME_RE.fullmatch(key) is None or invalid_value:
            diagnostics.append(
                _diagnostic(
                    "error",
                    "mcp-header-invalid",
                    f"Invalid HTTP header: {key!r}",
                    scope=scope,
                )
            )
    return diagnostics


def _inspect_mcp(
    root: Path,
    *,
    data_root: Path,
) -> tuple[list[PluginMCPComponent], list[PluginDiagnostic]]:
    components: list[PluginMCPComponent] = []
    diagnostics: list[PluginDiagnostic] = []
    path = root / "mcp.json"
    if not path.exists():
        return components, diagnostics
    if not path.is_file() or not _inside(path, root):
        diagnostics.append(
            _diagnostic(
                "error",
                "mcp-location-invalid",
                "mcp.json must be a regular file contained by the plugin root.",
                scope="mcp",
            )
        )
        return components, diagnostics
    try:
        raw = _read_bounded_json(path, MAX_MCP_BYTES)
    except (OSError, ValueError) as exc:
        diagnostics.append(
            _diagnostic("error", "mcp-invalid", f"mcp.json: {exc}", scope="mcp")
        )
        return components, diagnostics
    if not isinstance(raw, dict):
        diagnostics.append(
            _diagnostic(
                "error",
                "mcp-not-object",
                "mcp.json must be a JSON object.",
                scope="mcp",
            )
        )
        return components, diagnostics
    if set(raw) != {"$schema", "mcpServers"}:
        diagnostics.append(
            _diagnostic(
                "error",
                "mcp-top-level-invalid",
                "mcp.json must contain exactly $schema and mcpServers.",
                scope="mcp",
            )
        )
        return components, diagnostics
    if raw.get("$schema") != MCP_SCHEMA_ID:
        diagnostics.append(
            _diagnostic(
                "error",
                "mcp-schema-unsupported",
                f"Unsupported MCP schema: {raw.get('$schema')!r}",
                scope="mcp",
            )
        )
        return components, diagnostics
    servers = raw.get("mcpServers")
    if not isinstance(servers, dict):
        diagnostics.append(
            _diagnostic(
                "error",
                "mcp-servers-invalid",
                "mcpServers must be an object.",
                scope="mcp",
            )
        )
        return components, diagnostics

    for name, server_raw in servers.items():
        scope = f"mcp:{name}"
        entry_diagnostics: list[PluginDiagnostic] = []
        if not isinstance(name, str) or not name:
            entry_diagnostics.append(
                _diagnostic(
                    "error",
                    "mcp-server-name-invalid",
                    "Server names must be non-empty strings.",
                    scope=scope,
                )
            )
            components.append(
                PluginMCPComponent(
                    name=str(name),
                    transport="unknown",
                    valid=False,
                    diagnostics=entry_diagnostics,
                )
            )
            continue
        try:
            server = MCP_SERVER_ADAPTER.validate_python(server_raw)
        except ValidationError as exc:
            entry_diagnostics.append(
                _diagnostic("error", "mcp-server-invalid", str(exc), scope=scope)
            )
            transport = (
                server_raw.get("type", "unknown")
                if isinstance(server_raw, dict)
                else "unknown"
            )
            components.append(
                PluginMCPComponent(
                    name=name,
                    transport=str(transport),
                    valid=False,
                    diagnostics=entry_diagnostics,
                )
            )
            continue
        if isinstance(server, PortableStdioServer):
            entry_diagnostics.extend(
                _validate_stdio(server, root=root, data_root=data_root, scope=scope)
            )
        else:
            entry_diagnostics.extend(_validate_http(server, scope=scope))
            if server.type == "sse":
                entry_diagnostics.append(
                    _diagnostic(
                        "warning",
                        "mcp-transport-unsupported",
                        "Legacy SSE is valid but not supported by EvoFlux; this server will be skipped.",
                        scope=scope,
                    )
                )
        components.append(
            PluginMCPComponent(
                name=name,
                transport=server.type,
                valid=not any(item.severity == "error" for item in entry_diagnostics),
                config=server.model_dump(mode="json"),
                diagnostics=entry_diagnostics,
            )
        )
    return components, diagnostics


def inspect_plugin(
    root: str | Path,
    *,
    data_root: str | Path | None = None,
) -> PluginInspection:
    """Inspect one unpacked Agent Plugins directory without executing it."""

    package_root = Path(root).expanduser().absolute()
    diagnostics: list[PluginDiagnostic] = []
    if not package_root.is_dir():
        diagnostics.append(
            _diagnostic(
                "error",
                "plugin-root-invalid",
                f"Not a plugin directory: {package_root}",
            )
        )
        return PluginInspection(
            root=str(package_root), valid=False, diagnostics=diagnostics
        )
    try:
        resolved_root = package_root.resolve(strict=True)
    except OSError as exc:
        diagnostics.append(_diagnostic("error", "plugin-root-unreadable", str(exc)))
        return PluginInspection(
            root=str(package_root), valid=False, diagnostics=diagnostics
        )

    diagnostics.extend(_inspect_links(resolved_root))
    manifest = _load_manifest(resolved_root, diagnostics)
    if manifest is None:
        return PluginInspection(
            root=str(resolved_root), valid=False, diagnostics=diagnostics
        )

    plugin_data = (
        Path(data_root).expanduser().absolute()
        if data_root is not None
        else resolved_root / ".plugin-data-validation"
    )
    skills, skill_diagnostics = _inspect_skills(resolved_root)
    diagnostics.extend(skill_diagnostics)
    mcp_servers, mcp_diagnostics = _inspect_mcp(resolved_root, data_root=plugin_data)
    diagnostics.extend(mcp_diagnostics)
    try:
        digest = _package_digest(resolved_root)
    except (OSError, ValueError) as exc:
        diagnostics.append(_diagnostic("error", "package-digest-failed", str(exc)))
        digest = None

    package_errors = any(
        item.severity == "error" and item.scope in {"package", "manifest"}
        for item in diagnostics
    )
    return PluginInspection(
        root=str(resolved_root),
        valid=not package_errors,
        manifest=manifest,
        diagnostics=diagnostics,
        skills=skills,
        mcp_servers=mcp_servers,
        extension_namespaces=sorted(manifest.extensions),
        content_sha256=digest,
    )


def package_has_symlinks(root: Path) -> bool:
    for base, dirs, files in os.walk(root, followlinks=False):
        for name in [*dirs, *files]:
            path = Path(base) / name
            try:
                mode = path.lstat().st_mode
            except OSError:
                return True
            if stat.S_ISLNK(mode):
                return True
    return False


__all__ = [
    "MAX_PACKAGE_BYTES",
    "MAX_PACKAGE_FILES",
    "inspect_plugin",
    "package_has_symlinks",
]
