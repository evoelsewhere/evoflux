"""Trusted user overrides for skill runtime visibility.

Portable skill bundles own their workflow and provider metadata.  EvoFlux UI
preferences must not rewrite those files, especially when a bundle comes from
the application, an administrator, or a symlinked compatibility root.  This
module stores the three user-facing runtime switches in one bounded config
file and addresses the exact discovered bundle variant with an opaque ID.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Mapping, Sequence

from loguru import logger

from app.core.skill_scope import ALL_SKILL_MODES, SkillMode, normalize_skill_modes


SKILL_SETTINGS_FILENAME = "skill-settings.json"
MAX_SKILL_SETTINGS_BYTES = 1024 * 1024
MAX_SKILL_SETTINGS_RECORDS = 5_000
SKILL_SETTINGS_VERSION = 1

_SETTINGS_ID_RE = re.compile(r"^skill_[0-9a-f]{32}$")
_PATH_SCOPED_SOURCES = {
    "project-EvoFlux",
    "project-agents",
    "project-claude",
    "project-opencode",
    "custom",
    "unknown",
}
_PROCESS_WRITE_LOCK = threading.Lock()


class SkillSettingsError(ValueError):
    """Raised when persisted settings cannot be updated safely."""


@dataclass(frozen=True)
class SkillRuntimeSettings:
    """One complete runtime-settings override."""

    modes: tuple[SkillMode, ...]
    allow_implicit_invocation: bool
    user_invocable: bool


def skill_settings_path() -> Path:
    """Return the user-owned settings overlay path."""

    from app.core.config import settings

    return Path(settings.EVOFLUX_CONFIG_DIR) / SKILL_SETTINGS_FILENAME


def skill_settings_id(*, source: str, root: Path, stem: str) -> str:
    """Return a stable opaque ID for one discovered bundle variant.

    Built-in, admin, and named global roots use their stable source namespace,
    so upgrades that move installation files keep the user's preference.
    Project/custom roots include their canonical root because two repositories
    may intentionally provide different implementations with the same name.
    """

    root_identity = ""
    if source in _PATH_SCOPED_SOURCES:
        # Address the configured link/root location, not a resolved symlink
        # target. A link replacement is still the same catalog slot; a skill
        # with the same name in another repository is not.
        root_identity = os.path.normcase(str(root.absolute()))
    material = f"{source}\0{root_identity}\0{stem}".encode("utf-8")
    return f"skill_{hashlib.sha256(material).hexdigest()[:32]}"


def skill_settings_signature(path: Path | None = None) -> tuple[int, int, int]:
    """Return an mtime/size/content fingerprint for discovery cache keys."""

    target = path or skill_settings_path()
    try:
        metadata = target.stat()
        with target.open("rb") as handle:
            payload = handle.read(MAX_SKILL_SETTINGS_BYTES + 1)
    except OSError:
        return (0, 0, 0)
    digest = hashlib.blake2b(payload, digest_size=8).digest()
    return (metadata.st_mtime_ns, metadata.st_size, int.from_bytes(digest, "big"))


def _read_payload(path: Path, *, strict: bool) -> dict:
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_SKILL_SETTINGS_BYTES + 1)
    except FileNotFoundError:
        return {"version": SKILL_SETTINGS_VERSION, "skills": {}}
    except OSError as exc:
        if strict:
            raise SkillSettingsError(f"Could not read {path}: {exc}") from exc
        logger.warning("skill_settings_read_failed path={} error={}", path, exc)
        return {"version": SKILL_SETTINGS_VERSION, "skills": {}}

    if len(raw) > MAX_SKILL_SETTINGS_BYTES:
        message = f"{path} exceeds the {MAX_SKILL_SETTINGS_BYTES}-byte runtime limit."
        if strict:
            raise SkillSettingsError(message)
        logger.warning("skill_settings_too_large path={}", path)
        return {"version": SKILL_SETTINGS_VERSION, "skills": {}}
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        if strict:
            raise SkillSettingsError(f"{path} is not valid JSON: {exc}") from exc
        logger.warning("skill_settings_invalid_json path={} error={}", path, exc)
        return {"version": SKILL_SETTINGS_VERSION, "skills": {}}
    if not isinstance(payload, dict):
        message = f"{path} must contain a JSON object."
        if strict:
            raise SkillSettingsError(message)
        logger.warning("skill_settings_invalid_root path={}", path)
        return {"version": SKILL_SETTINGS_VERSION, "skills": {}}
    if payload.get("version") != SKILL_SETTINGS_VERSION:
        message = (
            f"{path} has an unsupported version; expected {SKILL_SETTINGS_VERSION}."
        )
        if strict:
            raise SkillSettingsError(message)
        logger.warning("skill_settings_invalid_version path={}", path)
        return {"version": SKILL_SETTINGS_VERSION, "skills": {}}
    skills = payload.get("skills")
    if not isinstance(skills, dict):
        message = f"{path}.skills must contain a JSON object."
        if strict:
            raise SkillSettingsError(message)
        logger.warning("skill_settings_invalid_records path={}", path)
        return {"version": SKILL_SETTINGS_VERSION, "skills": {}}
    if len(skills) > MAX_SKILL_SETTINGS_RECORDS:
        message = (
            f"{path}.skills exceeds the {MAX_SKILL_SETTINGS_RECORDS}-record limit."
        )
        if strict:
            raise SkillSettingsError(message)
        logger.warning("skill_settings_record_limit path={}", path)
        return {"version": SKILL_SETTINGS_VERSION, "skills": {}}
    return payload


def _parse_settings(
    payload: Mapping,
) -> tuple[dict[str, SkillRuntimeSettings], dict[str, str]]:
    raw_records = payload.get("skills")
    if not isinstance(raw_records, dict):
        return {}, {}
    parsed: dict[str, SkillRuntimeSettings] = {}
    diagnostics: dict[str, str] = {}
    for settings_id, value in raw_records.items():
        if (
            not isinstance(settings_id, str)
            or _SETTINGS_ID_RE.fullmatch(settings_id) is None
        ):
            continue
        if not isinstance(value, dict):
            diagnostics[settings_id] = (
                "The user runtime override is not a JSON object; bundle defaults "
                "remain active."
            )
            continue
        raw_modes = value.get("modes")
        implicit = value.get("allow_implicit_invocation")
        invocable = value.get("user_invocable")
        if (
            not isinstance(raw_modes, list)
            or not raw_modes
            or len(set(map(str, raw_modes))) != len(raw_modes)
            or any(mode not in ALL_SKILL_MODES for mode in raw_modes)
            or not isinstance(implicit, bool)
            or not isinstance(invocable, bool)
        ):
            diagnostics[settings_id] = (
                "The user runtime override is invalid; expected unique work/coding/aim "
                "modes and boolean invocation switches. Bundle defaults remain active."
            )
            continue
        parsed[settings_id] = SkillRuntimeSettings(
            modes=normalize_skill_modes(raw_modes),
            allow_implicit_invocation=implicit,
            user_invocable=invocable,
        )
    return parsed, diagnostics


@lru_cache(maxsize=8)
def _read_skill_runtime_settings_cached(
    path_string: str,
    signature: tuple[int, int, int],
) -> tuple[dict[str, SkillRuntimeSettings], dict[str, str]]:
    del signature  # cache-key only
    return _parse_settings(_read_payload(Path(path_string), strict=False))


def read_skill_runtime_settings_snapshot() -> tuple[
    dict[str, SkillRuntimeSettings], dict[str, str]
]:
    """Read settings and diagnostics together with one bounded fingerprint."""

    path = skill_settings_path()
    return _read_skill_runtime_settings_cached(
        str(path), skill_settings_signature(path)
    )


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
        # Runtime visibility is trusted user configuration. Tighten legacy or
        # manually-created permissive files on every successful rewrite.
        temporary.chmod(0o600)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def _settings_write_lock(path: Path):
    """Serialize read-modify-write in-process and across POSIX workers."""

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


def write_skill_runtime_settings(
    settings_id: str,
    *,
    name: str,
    source: str,
    modes: Sequence[SkillMode],
    allow_implicit_invocation: bool,
    user_invocable: bool,
) -> SkillRuntimeSettings:
    """Atomically replace one exact variant's complete runtime override."""

    if _SETTINGS_ID_RE.fullmatch(settings_id) is None:
        raise SkillSettingsError("Invalid skill settings ID.")
    raw_modes = list(modes)
    normalized_modes = normalize_skill_modes(raw_modes)
    if (
        not raw_modes
        or len(raw_modes) != len(set(raw_modes))
        or len(normalized_modes) != len(raw_modes)
    ):
        raise SkillSettingsError(
            "Skill modes must contain work, coding, and/or aim once."
        )

    path = skill_settings_path()
    with _settings_write_lock(path):
        payload = _read_payload(path, strict=True)
        raw_records = payload["skills"]
        if not isinstance(raw_records, dict):  # narrowed by strict reader
            raise SkillSettingsError(f"{path}.skills must contain a JSON object.")
        if (
            settings_id not in raw_records
            and len(raw_records) >= MAX_SKILL_SETTINGS_RECORDS
        ):
            raise SkillSettingsError(
                f"{path}.skills reached the {MAX_SKILL_SETTINGS_RECORDS}-record limit."
            )
        raw_records[settings_id] = {
            "name": name,
            "source": source,
            "modes": list(normalized_modes),
            "allow_implicit_invocation": allow_implicit_invocation,
            "user_invocable": user_invocable,
        }
        content = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        if len(content.encode("utf-8")) > MAX_SKILL_SETTINGS_BYTES:
            raise SkillSettingsError(
                f"{path} would exceed the {MAX_SKILL_SETTINGS_BYTES}-byte limit."
            )
        _atomic_write(path, content)
    _read_skill_runtime_settings_cached.cache_clear()
    return SkillRuntimeSettings(
        modes=normalized_modes,
        allow_implicit_invocation=allow_implicit_invocation,
        user_invocable=user_invocable,
    )


def delete_skill_runtime_settings(settings_id: str) -> bool:
    """Remove one override and restore inheritance from the selected bundle."""

    if _SETTINGS_ID_RE.fullmatch(settings_id) is None:
        raise SkillSettingsError("Invalid skill settings ID.")
    path = skill_settings_path()
    with _settings_write_lock(path):
        payload = _read_payload(path, strict=True)
        raw_records = payload["skills"]
        if not isinstance(raw_records, dict):  # narrowed by strict reader
            raise SkillSettingsError(f"{path}.skills must contain a JSON object.")
        if settings_id not in raw_records:
            return False
        del raw_records[settings_id]
        if raw_records:
            _atomic_write(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")
        else:
            path.unlink(missing_ok=True)
    _read_skill_runtime_settings_cached.cache_clear()
    return True


__all__ = [
    "MAX_SKILL_SETTINGS_BYTES",
    "MAX_SKILL_SETTINGS_RECORDS",
    "SKILL_SETTINGS_FILENAME",
    "SkillRuntimeSettings",
    "SkillSettingsError",
    "delete_skill_runtime_settings",
    "read_skill_runtime_settings_snapshot",
    "skill_settings_id",
    "skill_settings_path",
    "skill_settings_signature",
    "write_skill_runtime_settings",
]
