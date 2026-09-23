"""User on/off switches for discovered Agent Skills.

Skill bundles own their content and metadata. The only user preference EvoFlux
stores outside a bundle is whether a Skill is enabled, so built-in, plugin and
read-only bundles can be turned off without rewriting their files. The store is
one small JSON document keyed by Skill name::

    {"version": 2, "disabled": ["pdf", "xlsx"]}
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import threading
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from loguru import logger


SKILL_SETTINGS_FILENAME = "skill-settings.json"
SKILL_SETTINGS_VERSION = 2
# A name is at most 64 characters, so this bounds the file far above any
# realistic number of installed Skills while keeping reads cheap.
MAX_SKILL_SETTINGS_BYTES = 1024 * 1024
MAX_DISABLED_SKILLS = 5_000

_PROCESS_WRITE_LOCK = threading.Lock()


class SkillSettingsError(ValueError):
    """Raised when the settings file cannot be updated safely."""


def skill_settings_path() -> Path:
    from app.core.config import settings

    return Path(settings.EVOFLUX_CONFIG_DIR) / SKILL_SETTINGS_FILENAME


def _signature(path: Path) -> tuple[int, int, int]:
    try:
        metadata = path.stat()
        with path.open("rb") as handle:
            payload = handle.read(MAX_SKILL_SETTINGS_BYTES + 1)
    except OSError:
        return (0, 0, 0)
    digest = hashlib.blake2b(payload, digest_size=8).digest()
    return (metadata.st_mtime_ns, metadata.st_size, int.from_bytes(digest, "big"))


def skill_settings_signature() -> tuple[int, int, int]:
    """Return a content fingerprint used in discovery cache keys."""

    return _signature(skill_settings_path())


def _read_disabled(path: Path, *, strict: bool) -> list[str]:
    """Return the disabled list; malformed files fail open unless *strict*."""

    def reject(message: str) -> list[str]:
        if strict:
            raise SkillSettingsError(message)
        logger.warning("skill_settings_ignored path={} reason={}", path, message)
        return []

    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_SKILL_SETTINGS_BYTES + 1)
    except FileNotFoundError:
        return []
    except OSError as exc:
        return reject(f"Could not read {path}: {exc}")
    if len(raw) > MAX_SKILL_SETTINGS_BYTES:
        return reject(f"{path} exceeds {MAX_SKILL_SETTINGS_BYTES} bytes.")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        return reject(f"{path} is not valid JSON: {exc}")
    if (
        not isinstance(payload, dict)
        or payload.get("version") != SKILL_SETTINGS_VERSION
    ):
        # An older or foreign document carries no switches this version
        # understands. Reads ignore it; the next write replaces it.
        return []
    disabled = payload.get("disabled")
    if not isinstance(disabled, list) or not all(
        isinstance(item, str) for item in disabled
    ):
        return reject(f"{path}.disabled must be a list of Skill names.")
    return sorted({item for item in disabled if isinstance(item, str)})


@lru_cache(maxsize=8)
def _disabled_cached(
    path_string: str, signature: tuple[int, int, int]
) -> frozenset[str]:
    del signature  # cache key only
    return frozenset(_read_disabled(Path(path_string), strict=False))


def disabled_skill_names() -> frozenset[str]:
    """Return the names the user turned off."""

    path = skill_settings_path()
    return _disabled_cached(str(path), _signature(path))


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
def _write_lock(path: Path):
    """Serialize read-modify-write in-process and across POSIX workers."""

    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.lock")
    with _PROCESS_WRITE_LOCK, lock_path.open("a+b") as handle:
        try:
            import fcntl as file_lock
        except ImportError:  # pragma: no cover - Windows
            yield
            return
        file_lock.flock(handle.fileno(), file_lock.LOCK_EX)
        try:
            yield
        finally:
            file_lock.flock(handle.fileno(), file_lock.LOCK_UN)


def set_skill_enabled(name: str, enabled: bool) -> None:
    """Persist one Skill's on/off switch."""

    path = skill_settings_path()
    with _write_lock(path):
        disabled = set(_read_disabled(path, strict=True))
        if enabled:
            disabled.discard(name)
        else:
            disabled.add(name)
        if len(disabled) > MAX_DISABLED_SKILLS:
            raise SkillSettingsError(
                f"At most {MAX_DISABLED_SKILLS} Skills can be disabled."
            )
        if disabled:
            payload = {"version": SKILL_SETTINGS_VERSION, "disabled": sorted(disabled)}
            _atomic_write(path, json.dumps(payload, indent=2) + "\n")
        else:
            path.unlink(missing_ok=True)
    _disabled_cached.cache_clear()


__all__ = [
    "SKILL_SETTINGS_FILENAME",
    "SkillSettingsError",
    "disabled_skill_names",
    "set_skill_enabled",
    "skill_settings_path",
    "skill_settings_signature",
]
