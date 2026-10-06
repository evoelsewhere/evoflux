"""Bounded, read-only package review helpers."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import ValidationError

from app.plugin_platform.models import MCP_SERVER_ADAPTER
from app.plugin_platform.validator import redact_mcp_server_config

_MAX_FILES = 500
_MAX_SCANNED_FILES = 2_000
_MAX_FILE_BYTES = 2 * 1024 * 1024
_MAX_TOTAL_BYTES = 16 * 1024 * 1024
_MAX_TEXT_BYTES = 512 * 1024
_SENSITIVE_NAMES = {
    ".env",
    ".env.local",
    "credentials.json",
    "secrets.json",
    "id_rsa",
    "id_ed25519",
    ".npmrc",
    ".pypirc",
}
_SECRET_KEY = re.compile(
    r'(?i)(["\']?(?:password|token|secret|api[_-]?key|authorization|proxy-authorization|client_secret)["\']?\s*[:=]\s*)(["\']?)([^\s,"\'};]+)'
)
_ENV_VALUE = re.compile(
    r"(?im)^(\s*(?:export\s+)?[A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|KEY|AUTH|CREDENTIAL)[A-Z0-9_]*\s*=\s*)(.*)$"
)
_AUTH_VALUE = re.compile(
    r"""(?i)(["']?(?:authorization|proxy-authorization)["']?\s*:\s*)(["'])(.*?)(\2)"""
)
_AUTH_LINE = re.compile(
    r"(?im)^(\s*(?:authorization|proxy-authorization)\s*:\s*)(?:(?:bearer|basic)\s+)?(.*)$"
)


_SECRET_FIELD = re.compile(
    r"(?i)(?:token|secret|password|api[_-]?key|authorization|credential|auth)"
)
_URL_FIELDS = {"url", "uri", "endpoint"}
_MCP_CONFIG_NAMES = {"mcp.json", ".mcp.json"}


def _redact_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        if not parsed.scheme or not hostname:
            return "[REDACTED]"
        host = f"[{hostname}]" if ":" in hostname else hostname
        if parsed.port is not None:
            host = f"{host}:{parsed.port}"
        query = urlencode(
            [
                (name, "[REDACTED]")
                for name, _ in parse_qsl(parsed.query, keep_blank_values=True)
            ]
        )
        return urlunsplit((parsed.scheme, host, parsed.path, query, ""))
    except ValueError:
        return "[REDACTED]"


def _redact_json(value: object, *, key: str = "") -> object:
    if key.casefold() in {"env", "headers"}:
        if isinstance(value, dict):
            return {field: "[REDACTED]" for field in value}
        return "[REDACTED]"
    if isinstance(value, dict):
        redacted: dict[str, object] = {}
        for raw_key, item in value.items():
            field = str(raw_key)
            normalized = field.casefold()
            if normalized == "mcpservers" and isinstance(item, dict):
                servers: dict[str, object] = {}
                for name, config in item.items():
                    try:
                        server = MCP_SERVER_ADAPTER.validate_python(config)
                        servers[str(name)] = redact_mcp_server_config(server)
                    except (ValidationError, TypeError, ValueError):
                        servers[str(name)] = _redact_json(config)
                redacted[field] = servers
            elif _SECRET_FIELD.search(field):
                redacted[field] = "[REDACTED]"
            elif normalized in _URL_FIELDS and isinstance(item, str):
                redacted[field] = _redact_url(item)
            else:
                redacted[field] = _redact_json(item, key=field)
        return redacted
    if isinstance(value, list):
        return [_redact_json(item, key=key) for item in value]
    if isinstance(value, str) and key.casefold() in _URL_FIELDS:
        return _redact_url(value)
    return value


def _safe_files(root: Path) -> tuple[list[tuple[Path, int]], bool]:
    resolved = root.resolve(strict=True)
    rows: list[tuple[Path, int]] = []
    total = 0
    scanned = 0
    truncated = False
    for base, directories, filenames in os.walk(resolved, followlinks=False):
        base_path = Path(base)
        directories[:] = sorted(
            name for name in directories if not (base_path / name).is_symlink()
        )
        for filename in sorted(filenames):
            scanned += 1
            if scanned > _MAX_SCANNED_FILES:
                return rows, True
            candidate = base_path / filename
            if candidate.is_symlink() or not candidate.is_file():
                continue
            try:
                real = candidate.resolve(strict=True)
                real.relative_to(resolved)
                relative = candidate.relative_to(resolved)
                size = candidate.stat().st_size
            except (OSError, ValueError):
                continue
            if any(
                part.lower() in _SENSITIVE_NAMES
                or part.lower().startswith(".env")
                or part.lower().endswith((".pem", ".p12", ".pfx", ".key"))
                for part in relative.parts
            ):
                continue
            if size > _MAX_FILE_BYTES or total + size > _MAX_TOTAL_BYTES:
                truncated = True
                continue
            if len(rows) >= _MAX_FILES:
                return rows, True
            total += size
            rows.append((relative, size))
    return rows, truncated


def list_package_files(root: str | Path) -> dict[str, object]:
    rows, truncated = _safe_files(Path(root))
    files = []
    for path, size in rows:
        candidate = Path(root).resolve(strict=True).joinpath(*path.parts)
        try:
            raw = candidate.read_bytes()
            raw.decode("utf-8")
            kind = "binary" if b"\x00" in raw else "text"
        except (OSError, UnicodeDecodeError):
            kind = "binary"
        files.append({"path": path.as_posix(), "kind": kind, "size": size})
    readme_path = next(
        (path.as_posix() for path, _ in rows if path.name.lower().startswith("readme")),
        None,
    )
    readme: dict[str, object] | None = None
    if readme_path is not None:
        try:
            readme = read_package_file(root, readme_path)
        except ValueError:
            readme = {"path": readme_path}
    return {
        "files": files,
        "truncated": truncated,
        "readme": readme,
    }


def read_package_file(root: str | Path, requested: str) -> dict[str, object]:
    if not requested or "\\" in requested or "\x00" in requested:
        raise ValueError("Invalid package file path.")
    relative = Path(requested)
    if relative.is_absolute() or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        raise ValueError("Invalid package file path.")
    rows, _ = _safe_files(Path(root))
    allowed = {path.as_posix(): size for path, size in rows}
    if requested not in allowed:
        raise FileNotFoundError(requested)
    root_path = Path(root).resolve(strict=True)
    target = root_path.joinpath(*relative.parts)
    try:
        current = root_path
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise ValueError("Symbolic links are not reviewable.")
        target.resolve(strict=True).relative_to(root_path)
        raw = target.read_bytes()
    except ValueError:
        raise
    except OSError as exc:
        raise FileNotFoundError(requested) from exc
    if b"\x00" in raw:
        raise ValueError("Binary files are not reviewable.")
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Binary files are not reviewable.") from exc
    try:
        parsed_json = json.loads(content)
    except json.JSONDecodeError as exc:
        if Path(requested).name.casefold() in _MCP_CONFIG_NAMES or re.search(
            r"(?i)mcpservers", content
        ):
            raise ValueError("MCP configuration cannot be safely reviewed.") from exc
    else:
        content = json.dumps(_redact_json(parsed_json), ensure_ascii=False, indent=2)
    content = _AUTH_VALUE.sub(r"\1\2[REDACTED]\4", content)
    content = _AUTH_LINE.sub(r"\1[REDACTED]", content)
    content = _ENV_VALUE.sub(r"\1[REDACTED]", content)
    content = _SECRET_KEY.sub(r"\1\2[REDACTED]", content)
    truncated = len(content.encode("utf-8")) > _MAX_TEXT_BYTES
    if truncated:
        content = content.encode("utf-8")[:_MAX_TEXT_BYTES].decode(
            "utf-8", errors="ignore"
        )
    return {"path": requested, "content": content, "truncated": truncated}


__all__ = ["list_package_files", "read_package_file"]
