"""Local runtime model overrides for Conductor-managed Agents.

Managed Agent bundles remain immutable on an EvoFlux installation.  The
selected model is an installation preference, so it is stored separately and
addressed by the stable Conductor project/resource identity instead of by the
bundle slug.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Mapping

from loguru import logger


AGENT_SETTINGS_FILENAME = "agent-settings.json"
AGENT_SETTINGS_VERSION = 1
MAX_AGENT_SETTINGS_BYTES = 1024 * 1024
MAX_AGENT_SETTINGS_RECORDS = 5_000
MAX_AGENT_RUNTIME_ADDITIONS = 200
MAX_AGENT_RUNTIME_ADDITION_LENGTH = 128

_PROCESS_WRITE_LOCK = threading.Lock()


class AgentSettingsError(ValueError):
    """Raised when an Agent runtime override cannot be persisted safely."""


@dataclass(frozen=True)
class AgentRuntimeSettings:
    model: str | None = None
    extra_tools: tuple[str, ...] = ()
    extra_skills: tuple[str, ...] = ()
    extra_mcp: tuple[str, ...] = ()


def agent_settings_path() -> Path:
    from app.core.config import settings

    return Path(settings.EVOFLUX_CONFIG_DIR) / AGENT_SETTINGS_FILENAME


def agent_settings_id(*, project_id: str, resource_id: str) -> str:
    material = f"{project_id}\0{resource_id}".encode("utf-8")
    return f"agent_{hashlib.sha256(material).hexdigest()[:32]}"


def agent_settings_signature(path: Path | None = None) -> tuple[int, int, int]:
    target = path or agent_settings_path()
    try:
        metadata = target.stat()
        with target.open("rb") as handle:
            payload = handle.read(MAX_AGENT_SETTINGS_BYTES + 1)
    except OSError:
        return (0, 0, 0)
    digest = hashlib.blake2b(payload, digest_size=8).digest()
    return (metadata.st_mtime_ns, metadata.st_size, int.from_bytes(digest, "big"))


def _empty_payload() -> dict:
    return {"version": AGENT_SETTINGS_VERSION, "agents": {}}


def _read_payload(path: Path, *, strict: bool) -> dict:
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_AGENT_SETTINGS_BYTES + 1)
    except FileNotFoundError:
        return _empty_payload()
    except OSError as exc:
        if strict:
            raise AgentSettingsError(f"Could not read {path}: {exc}") from exc
        logger.warning("agent_settings_read_failed path={} error={}", path, exc)
        return _empty_payload()

    if len(raw) > MAX_AGENT_SETTINGS_BYTES:
        message = f"{path} exceeds the {MAX_AGENT_SETTINGS_BYTES}-byte limit."
        if strict:
            raise AgentSettingsError(message)
        logger.warning("agent_settings_too_large path={}", path)
        return _empty_payload()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        if strict:
            raise AgentSettingsError(f"{path} is not valid JSON: {exc}") from exc
        logger.warning("agent_settings_invalid_json path={} error={}", path, exc)
        return _empty_payload()
    if not isinstance(payload, dict):
        message = f"{path} must contain a JSON object."
        if strict:
            raise AgentSettingsError(message)
        logger.warning("agent_settings_invalid_root path={}", path)
        return _empty_payload()
    records = payload.get("agents")
    if payload.get("version") != AGENT_SETTINGS_VERSION or not isinstance(
        records, dict
    ):
        message = f"{path} has an unsupported Agent settings format."
        if strict:
            raise AgentSettingsError(message)
        logger.warning("agent_settings_invalid_format path={}", path)
        return _empty_payload()
    if len(records) > MAX_AGENT_SETTINGS_RECORDS:
        message = (
            f"{path}.agents exceeds the {MAX_AGENT_SETTINGS_RECORDS}-record limit."
        )
        if strict:
            raise AgentSettingsError(message)
        logger.warning("agent_settings_record_limit path={}", path)
        return _empty_payload()
    return payload


def _parse_settings(payload: Mapping) -> dict[str, AgentRuntimeSettings]:
    records = payload.get("agents")
    if not isinstance(records, dict):
        return {}
    parsed: dict[str, AgentRuntimeSettings] = {}
    for settings_id, value in records.items():
        if not isinstance(settings_id, str) or not isinstance(value, dict):
            continue
        model = value.get("model")
        if not isinstance(model, str) or ":" not in model:
            model = None
        parsed[settings_id] = AgentRuntimeSettings(
            model=model,
            extra_tools=_parse_additions(value.get("extra_tools")),
            extra_skills=_parse_additions(value.get("extra_skills")),
            extra_mcp=_parse_additions(value.get("extra_mcp")),
        )
    return parsed


def _parse_additions(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    selected: list[str] = []
    for item in value[:MAX_AGENT_RUNTIME_ADDITIONS]:
        if (
            isinstance(item, str)
            and item
            and len(item) <= MAX_AGENT_RUNTIME_ADDITION_LENGTH
            and item not in selected
        ):
            selected.append(item)
    return tuple(selected)


@lru_cache(maxsize=8)
def _read_cached(
    path_string: str, signature: tuple[int, int, int]
) -> dict[str, AgentRuntimeSettings]:
    del signature
    return _parse_settings(_read_payload(Path(path_string), strict=False))


def read_agent_runtime_model(*, project_id: str, resource_id: str) -> str | None:
    return read_agent_runtime_settings(
        project_id=project_id,
        resource_id=resource_id,
    ).model


def read_agent_runtime_settings(
    *, project_id: str, resource_id: str
) -> AgentRuntimeSettings:
    path = agent_settings_path()
    records = _read_cached(str(path), agent_settings_signature(path))
    record = records.get(
        agent_settings_id(project_id=project_id, resource_id=resource_id)
    )
    return record or AgentRuntimeSettings()


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    try:
        temporary.chmod(0o600)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def _settings_write_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.lock")
    with _PROCESS_WRITE_LOCK, lock_path.open("a+b") as handle:
        try:
            lock_path.chmod(0o600)
        except OSError:
            pass
        try:
            import fcntl as file_lock
        except ImportError:  # pragma: no cover - Windows fallback
            yield
            return
        file_lock.flock(handle.fileno(), file_lock.LOCK_EX)
        try:
            yield
        finally:
            file_lock.flock(handle.fileno(), file_lock.LOCK_UN)


def write_agent_runtime_model(
    *, project_id: str, resource_id: str, name: str, model: str
) -> AgentRuntimeSettings:
    current = read_agent_runtime_settings(
        project_id=project_id,
        resource_id=resource_id,
    )
    return write_agent_runtime_settings(
        project_id=project_id,
        resource_id=resource_id,
        name=name,
        model=model,
        extra_tools=current.extra_tools,
        extra_skills=current.extra_skills,
        extra_mcp=current.extra_mcp,
    )


def write_agent_runtime_settings(
    *,
    project_id: str,
    resource_id: str,
    name: str,
    model: str | None,
    extra_tools: tuple[str, ...] | list[str] = (),
    extra_skills: tuple[str, ...] | list[str] = (),
    extra_mcp: tuple[str, ...] | list[str] = (),
) -> AgentRuntimeSettings:
    if not project_id or not resource_id:
        raise AgentSettingsError("Managed Agent identity is incomplete.")
    if model is not None and (not model or ":" not in model):
        raise AgentSettingsError("Agent model must use the provider:model format.")
    normalized_tools = _validate_additions("extra_tools", extra_tools)
    normalized_skills = _validate_additions("extra_skills", extra_skills)
    normalized_mcp = _validate_additions("extra_mcp", extra_mcp)
    path = agent_settings_path()
    settings_id = agent_settings_id(project_id=project_id, resource_id=resource_id)
    with _settings_write_lock(path):
        payload = _read_payload(path, strict=True)
        records = payload["agents"]
        if settings_id not in records and len(records) >= MAX_AGENT_SETTINGS_RECORDS:
            raise AgentSettingsError(
                f"{path}.agents reached the {MAX_AGENT_SETTINGS_RECORDS}-record limit."
            )
        record = {
            "project_id": project_id,
            "resource_id": resource_id,
            "name": name,
            "extra_tools": list(normalized_tools),
            "extra_skills": list(normalized_skills),
            "extra_mcp": list(normalized_mcp),
        }
        if model is not None:
            record["model"] = model
        records[settings_id] = record
        content = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        if len(content.encode("utf-8")) > MAX_AGENT_SETTINGS_BYTES:
            raise AgentSettingsError(
                f"{path} would exceed the {MAX_AGENT_SETTINGS_BYTES}-byte limit."
            )
        _atomic_write(path, content)
    _read_cached.cache_clear()
    return AgentRuntimeSettings(
        model=model,
        extra_tools=normalized_tools,
        extra_skills=normalized_skills,
        extra_mcp=normalized_mcp,
    )


def _validate_additions(
    field: str, values: tuple[str, ...] | list[str]
) -> tuple[str, ...]:
    if len(values) > MAX_AGENT_RUNTIME_ADDITIONS:
        raise AgentSettingsError(
            f"{field} may contain at most {MAX_AGENT_RUNTIME_ADDITIONS} entries."
        )
    normalized: list[str] = []
    for value in values:
        if (
            not isinstance(value, str)
            or not value
            or len(value) > MAX_AGENT_RUNTIME_ADDITION_LENGTH
        ):
            raise AgentSettingsError(f"{field} contains an invalid name.")
        if value not in normalized:
            normalized.append(value)
    return tuple(normalized)


def delete_agent_runtime_model(*, project_id: str, resource_id: str) -> bool:
    path = agent_settings_path()
    settings_id = agent_settings_id(project_id=project_id, resource_id=resource_id)
    with _settings_write_lock(path):
        payload = _read_payload(path, strict=True)
        records = payload["agents"]
        raw_record = records.get(settings_id)
        if not isinstance(raw_record, dict) or "model" not in raw_record:
            return False
        del raw_record["model"]
        has_additions = any(
            raw_record.get(field)
            for field in ("extra_tools", "extra_skills", "extra_mcp")
        )
        if not has_additions:
            del records[settings_id]
        if records:
            _atomic_write(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")
        else:
            path.unlink(missing_ok=True)
    _read_cached.cache_clear()
    return True


__all__ = [
    "AGENT_SETTINGS_FILENAME",
    "AgentRuntimeSettings",
    "AgentSettingsError",
    "agent_settings_id",
    "agent_settings_path",
    "agent_settings_signature",
    "delete_agent_runtime_model",
    "read_agent_runtime_model",
    "read_agent_runtime_settings",
    "write_agent_runtime_settings",
    "write_agent_runtime_model",
]
