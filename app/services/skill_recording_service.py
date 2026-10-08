"""Bounded, app-local storage for selected-application skill demonstrations."""

from __future__ import annotations

import base64
import binascii
import json
import os
import shutil
import stat
import struct
import uuid
import zlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, AsyncIterable, Sequence

from app.agent.tools.builtin.filesystem._atomic import atomic_write_bytes
from app.core.paths import skill_recordings_dir

MAX_EVENT_BYTES = 128 * 1024
MAX_SCREENSHOT_BASE64_BYTES = 3 * 1024 * 1024
MAX_SCREENSHOT_BYTES = 9 * 1024 * 1024 // 4
MAX_BATCH_EVENTS = 64
MAX_SESSION_BYTES = 32 * 1024 * 1024
MAX_SESSION_EVENTS = 20_000
MAX_VIDEO_BYTES = 512 * 1024 * 1024
SESSION_TTL = timedelta(hours=1)
_MANIFEST_SCHEMA_VERSION = 2
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_KINDS = {
    "click",
    "double_click",
    "scroll",
    "window_change",
    "focus",
    "invoked",
    "selected",
    "value_changed",
    "state_change",
    "window_opened",
    "window_closed",
    "gap",
    "screenshot",
}
_VALUE_STATES = {"not_captured", "captured", "omitted_secure", "unavailable"}


class SkillRecordingError(Exception):
    """Base error for local skill recording operations."""


class SkillRecordingNotFoundError(SkillRecordingError):
    """A session or artifact does not exist."""


class SkillRecordingConflictError(SkillRecordingError):
    """An operation conflicts with the session's current state."""


class SkillRecordingValidationError(SkillRecordingError):
    """A recording or event violates the bounded storage contract."""


class SkillRecordingPathError(SkillRecordingError):
    """A session path is unsafe or no longer contained in its storage root."""


def _now() -> datetime:
    return datetime.now(UTC)


def _root(*, create: bool) -> Path:
    root = skill_recordings_dir().expanduser()
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _validated_session_dir(session_id: str, *, create_root: bool = False) -> Path:
    try:
        parsed = uuid.UUID(session_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise SkillRecordingNotFoundError("Recording session not found.") from exc
    if str(parsed) != session_id.lower():
        raise SkillRecordingNotFoundError("Recording session not found.")
    root = _root(create=create_root)
    path = root / str(parsed)
    if path.is_symlink():
        raise SkillRecordingPathError("Recording session path may not be a symlink.")
    resolved = path.resolve(strict=False)
    if resolved.parent != root:
        raise SkillRecordingPathError("Recording session escaped its storage root.")
    if not resolved.is_dir():
        raise SkillRecordingNotFoundError("Recording session not found.")
    for directory, dirs, files in os.walk(resolved, followlinks=False):
        current = Path(directory)
        if any((current / name).is_symlink() for name in [*dirs, *files]):
            raise SkillRecordingPathError(
                "Recording tree contains an unexpected symlink."
            )
    return resolved


def _regular_file(path: Path, *, required: bool) -> Path:
    if path.is_symlink():
        raise SkillRecordingPathError("Recording files may not be symlinks.")
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as exc:
        if required:
            raise SkillRecordingNotFoundError("Recording file not found.") from exc
        return path
    if not stat.S_ISREG(mode):
        raise SkillRecordingPathError("Recording file is not a regular file.")
    return path


def _read_manifest(session_dir: Path) -> dict[str, Any]:
    path = _regular_file(session_dir / "manifest.json", required=True)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SkillRecordingPathError("Recording manifest is unreadable.") from exc
    if not isinstance(data, dict) or data.get("id") != session_dir.name:
        raise SkillRecordingPathError(
            "Recording manifest does not match its directory."
        )
    version = data.get("schema_version")
    if version == 1:
        # Preserve recordings created by the selected-window recorder while
        # adding media-artifact and expiry metadata.
        data["schema_version"] = _MANIFEST_SCHEMA_VERSION
        data.setdefault("video_artifacts", [])
        data.setdefault("expires_at", None)
        _write_manifest(session_dir, data)
    elif version != _MANIFEST_SCHEMA_VERSION:
        raise SkillRecordingPathError("Recording manifest version is unsupported.")
    return data


def _write_manifest(session_dir: Path, manifest: dict[str, Any]) -> None:
    payload = (
        json.dumps(manifest, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    atomic_write_bytes(session_dir / "manifest.json", payload)


def create_session() -> dict[str, Any]:
    cleanup_expired_sessions()
    root = _root(create=True)
    session_id = str(uuid.uuid4())
    session_dir = root / session_id
    now = _now().isoformat()
    try:
        session_dir.mkdir(mode=0o700)
        manifest = {
            "schema_version": _MANIFEST_SCHEMA_VERSION,
            "id": session_id,
            "status": "recording",
            "created_at": now,
            "updated_at": now,
            "expires_at": None,
            "event_count": 0,
            "artifact_bytes": 0,
            "video_artifacts": [],
        }
        _write_manifest(session_dir, manifest)
    except Exception:
        if session_dir.exists() and not session_dir.is_symlink():
            shutil.rmtree(session_dir, ignore_errors=True)
        raise
    return manifest


def _read_events(session_dir: Path) -> tuple[bytes, list[dict[str, Any]]]:
    path = _regular_file(session_dir / "events.jsonl", required=False)
    if not path.exists():
        return b"", []
    raw = path.read_bytes()
    if len(raw) > MAX_SESSION_BYTES:
        raise SkillRecordingValidationError("Recording exceeded its storage limit.")
    try:
        events = [json.loads(line) for line in raw.splitlines() if line]
    except json.JSONDecodeError as exc:
        raise SkillRecordingPathError("Recording event stream is unreadable.") from exc
    return raw, events


def _is_bounded_png(image: bytes) -> bool:
    if not image.startswith(_PNG_SIGNATURE):
        return False
    offset = len(_PNG_SIGNATURE)
    saw_header = saw_data = saw_end = False
    while offset + 12 <= len(image):
        length = struct.unpack_from(">I", image, offset)[0]
        end = offset + 12 + length
        if end > len(image):
            return False
        kind = image[offset + 4 : offset + 8]
        data = image[offset + 8 : offset + 8 + length]
        crc = struct.unpack_from(">I", image, offset + 8 + length)[0]
        if zlib.crc32(kind + data) & 0xFFFFFFFF != crc:
            return False
        if not saw_header:
            if kind != b"IHDR" or length != 13:
                return False
            width, height = struct.unpack_from(">II", data)
            if width < 1 or height < 1 or width * height > 33_554_432:
                return False
            saw_header = True
        elif kind == b"IHDR":
            return False
        if kind == b"IDAT":
            saw_data = True
        if kind == b"IEND":
            if length != 0 or not saw_data or end != len(image):
                return False
            saw_end = True
            break
        offset = end
    return saw_header and saw_data and saw_end


def _normalize_event(
    raw: dict[str, Any], sequence: int
) -> tuple[dict[str, Any], bytes | None]:
    if not isinstance(raw, dict):
        raise SkillRecordingValidationError("Each event must be an object.")
    try:
        source_sequence = int(raw["sequence"])
        elapsed_ms = int(raw["elapsed_ms"])
        kind = str(raw["kind"])
        value_state = str(raw.get("value_state", "not_captured"))
    except (KeyError, TypeError, ValueError) as exc:
        raise SkillRecordingValidationError(
            "Event sequence, timing, or kind is invalid."
        ) from exc
    if source_sequence < 1 or elapsed_ms < 0 or kind not in _KINDS:
        raise SkillRecordingValidationError(
            "Event sequence, timing, or kind is invalid."
        )
    if value_state not in _VALUE_STATES:
        raise SkillRecordingValidationError("Event value state is invalid.")
    value = raw.get("value")
    if value is not None and (
        not isinstance(value, str) or len(value.encode("utf-8")) > MAX_EVENT_BYTES
    ):
        raise SkillRecordingValidationError("Event value is too large or malformed.")
    if value_state != "captured" and value is not None:
        raise SkillRecordingValidationError(
            "An uncaptured or secure event cannot contain a value."
        )
    if kind != "value_changed" and value is not None:
        raise SkillRecordingValidationError(
            "Only value-change events may contain a value."
        )

    point = raw.get("point")
    button = raw.get("button")
    scroll_delta = raw.get("scroll_delta")
    pointer_kind = kind in {"click", "double_click", "scroll"}
    if not pointer_kind and any(
        field is not None for field in (point, button, scroll_delta)
    ):
        raise SkillRecordingValidationError(
            "Pointer fields are only valid on pointer events."
        )
    if pointer_kind:
        if not isinstance(point, dict) or set(point) - {"x", "y", "display_id"}:
            raise SkillRecordingValidationError("Pointer coordinates are malformed.")
        if type(point.get("x")) is not int or type(point.get("y")) is not int:
            raise SkillRecordingValidationError("Pointer coordinates are malformed.")
        if any(point[key] < -32768 or point[key] > 32767 for key in ("x", "y")):
            raise SkillRecordingValidationError(
                "Pointer coordinates are out of bounds."
            )
        display_id = point.get("display_id")
        if display_id is not None and (
            not isinstance(display_id, str) or len(display_id) > 128
        ):
            raise SkillRecordingValidationError(
                "Pointer display identifier is malformed."
            )
        point = {"x": point["x"], "y": point["y"], "display_id": display_id}
        if kind in {"click", "double_click"}:
            if button not in {"left", "middle", "right"} or scroll_delta is not None:
                raise SkillRecordingValidationError(
                    "Click event details are malformed."
                )
        else:
            if button is not None or not isinstance(scroll_delta, dict):
                raise SkillRecordingValidationError(
                    "Scroll event details are malformed."
                )
            if set(scroll_delta) != {"x", "y"} or any(
                type(scroll_delta[key]) is not int or abs(scroll_delta[key]) > 100_000
                for key in ("x", "y")
            ):
                raise SkillRecordingValidationError("Scroll delta is malformed.")
            scroll_delta = {"x": scroll_delta["x"], "y": scroll_delta["y"]}

    target = raw.get("target")
    if target is not None:
        if not isinstance(target, dict):
            raise SkillRecordingValidationError("Event target is malformed.")
        target = {
            key: target.get(key) for key in ("automation_id", "control_type", "name")
        }
        for key, text in target.items():
            if text is not None and (not isinstance(text, str) or len(text) > 2048):
                raise SkillRecordingValidationError(
                    "Event target is too large or malformed."
                )
        if kind == "focus" or (target.get("control_type") or "").lower() in {
            "edit",
            "text",
            "pane",
        }:
            target["name"] = None

    screenshot = raw.get("screenshot")
    screenshot_bytes = None
    if screenshot is not None:
        if kind != "screenshot" or not isinstance(screenshot, str):
            raise SkillRecordingValidationError(
                "Screenshots are only valid on checkpoint events."
            )
        if len(screenshot) > MAX_SCREENSHOT_BASE64_BYTES:
            raise SkillRecordingValidationError(
                "Screenshot exceeds the capture size limit."
            )
        try:
            screenshot_bytes = base64.b64decode(screenshot, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise SkillRecordingValidationError(
                "Screenshot is not valid base64."
            ) from exc
        if len(screenshot_bytes) > MAX_SCREENSHOT_BYTES or not _is_bounded_png(
            screenshot_bytes
        ):
            raise SkillRecordingValidationError(
                "Screenshot must be a bounded PNG checkpoint."
            )
        screenshot = f"screenshots/{sequence:06d}.png"
    elif kind == "screenshot":
        raise SkillRecordingValidationError("Screenshot checkpoint has no image.")

    event = {
        "sequence": sequence,
        "source_sequence": source_sequence,
        "elapsed_ms": elapsed_ms,
        "kind": kind,
        "point": point,
        "button": button,
        "scroll_delta": scroll_delta,
        "target": target,
        "value_state": value_state,
        "value": value,
        "screenshot": screenshot,
    }
    encoded_size = len(
        json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
    if encoded_size > MAX_EVENT_BYTES:
        raise SkillRecordingValidationError("Event exceeds the storage limit.")
    return event, screenshot_bytes


def append_events(session_id: str, events: Sequence[dict[str, Any]]) -> dict[str, int]:
    if not events or len(events) > MAX_BATCH_EVENTS:
        raise SkillRecordingValidationError(
            f"Event batch must contain 1 to {MAX_BATCH_EVENTS} events."
        )
    session_dir = _validated_session_dir(session_id)
    manifest = _read_manifest(session_dir)
    _ensure_session_live(manifest)
    if manifest["status"] != "recording":
        raise SkillRecordingConflictError("Recording is not accepting events.")
    old_bytes, old_events = _read_events(session_dir)
    if manifest.get("event_count") != len(old_events):
        raise SkillRecordingPathError(
            "Recording manifest and event stream do not match."
        )
    base_sequence = len(old_events)
    if base_sequence + len(events) > MAX_SESSION_EVENTS:
        raise SkillRecordingValidationError("Recording exceeded its event limit.")
    normalized: list[dict[str, Any]] = []
    screenshots: list[tuple[Path, bytes]] = []
    for offset, raw in enumerate(events, start=1):
        row, image = _normalize_event(raw, base_sequence + offset)
        normalized.append(row)
        if image is not None:
            screenshots.append((session_dir / row["screenshot"], image))
    new_bytes = old_bytes + b"".join(
        (json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
        for row in normalized
    )
    artifact_bytes = int(manifest.get("artifact_bytes", 0)) + sum(
        len(image) for _, image in screenshots
    )
    video_bytes = sum(
        int(artifact.get("byte_length", 0))
        for artifact in manifest.get("video_artifacts", [])
    )
    if (
        len(new_bytes) + artifact_bytes + video_bytes
        > MAX_SESSION_BYTES + MAX_VIDEO_BYTES
    ):
        raise SkillRecordingValidationError("Recording exceeded its storage limit.")

    created: list[Path] = []
    try:
        for path, image in screenshots:
            if path.exists() or path.is_symlink():
                raise SkillRecordingPathError("Screenshot artifact already exists.")
            path.parent.mkdir(parents=True, exist_ok=True)
            if (
                path.parent.is_symlink()
                or path.parent.resolve().parent != session_dir.resolve()
            ):
                raise SkillRecordingPathError(
                    "Screenshot directory escaped its recording."
                )
            atomic_write_bytes(path, image)
            created.append(path)
        atomic_write_bytes(session_dir / "events.jsonl", new_bytes)
        manifest["event_count"] = base_sequence + len(normalized)
        manifest["artifact_bytes"] = artifact_bytes
        manifest["updated_at"] = datetime.now(UTC).isoformat()
        _write_manifest(session_dir, manifest)
    except Exception:
        atomic_write_bytes(session_dir / "events.jsonl", old_bytes) if old_bytes else (
            session_dir / "events.jsonl"
        ).unlink(missing_ok=True)
        for path in created:
            path.unlink(missing_ok=True)
        raise
    return {
        "appended": len(normalized),
        "first_sequence": base_sequence + 1,
        "last_sequence": base_sequence + len(normalized),
    }


def _set_status(session_id: str, status: str) -> dict[str, Any]:
    session_dir = _validated_session_dir(session_id)
    manifest = _read_manifest(session_dir)
    _ensure_session_live(manifest)
    current = manifest["status"]
    if status == "stopped" and current == "stopped":
        return manifest
    if current == "stopped":
        raise SkillRecordingConflictError("Recording has already stopped.")
    if status == "paused" and current != "recording":
        raise SkillRecordingConflictError("Recording is not active.")
    if status == "recording" and current != "paused":
        raise SkillRecordingConflictError("Recording is not paused.")
    manifest["status"] = status
    now = _now()
    manifest["updated_at"] = now.isoformat()
    if status == "stopped":
        manifest["expires_at"] = (now + SESSION_TTL).isoformat()
    elif status == "paused":
        manifest["expires_at"] = (now + SESSION_TTL).isoformat()
    else:
        manifest["expires_at"] = None
    _write_manifest(session_dir, manifest)
    return manifest


def pause_session(session_id: str) -> dict[str, Any]:
    return _set_status(session_id, "paused")


def resume_session(session_id: str) -> dict[str, Any]:
    return _set_status(session_id, "recording")


def stop_session(session_id: str) -> dict[str, Any]:
    return _set_status(session_id, "stopped")


def get_session(session_id: str) -> dict[str, Any]:
    session_dir = _validated_session_dir(session_id)
    manifest = _read_manifest(session_dir)
    _ensure_session_live(manifest)
    _, events = _read_events(session_dir)
    if manifest.get("event_count") != len(events):
        raise SkillRecordingPathError(
            "Recording manifest and event stream do not match."
        )
    return {**manifest, "events": events}


def read_screenshot(session_id: str, sequence: int) -> bytes:
    if sequence < 1:
        raise SkillRecordingNotFoundError("Screenshot not found.")
    session_dir = _validated_session_dir(session_id)
    _ensure_session_live(_read_manifest(session_dir))
    path = session_dir / "screenshots" / f"{sequence:06d}.png"
    _regular_file(path, required=True)
    resolved = path.resolve()
    if session_dir not in resolved.parents:
        raise SkillRecordingPathError("Screenshot escaped its recording directory.")
    return path.read_bytes()


def delete_session(session_id: str) -> None:
    session_dir = _validated_session_dir(session_id)
    for directory, dirs, files in os.walk(session_dir, followlinks=False):
        current = Path(directory)
        if any((current / name).is_symlink() for name in [*dirs, *files]):
            raise SkillRecordingPathError(
                "Recording tree contains an unexpected symlink."
            )
    shutil.rmtree(session_dir)


def _expiry_time(manifest: dict[str, Any]) -> datetime | None:
    expiry = manifest.get("expires_at")
    if expiry:
        try:
            parsed = datetime.fromisoformat(str(expiry))
        except ValueError as exc:
            raise SkillRecordingPathError(
                "Recording expiry metadata is invalid."
            ) from exc
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed
    if manifest.get("status") in {"paused", "stopped"}:
        timestamp = manifest.get("updated_at") or manifest.get("created_at")
        try:
            parsed = datetime.fromisoformat(str(timestamp))
        except (TypeError, ValueError) as exc:
            raise SkillRecordingPathError(
                "Recording timestamp metadata is invalid."
            ) from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed + SESSION_TTL
    return None


def _ensure_session_live(manifest: dict[str, Any]) -> None:
    expiry = _expiry_time(manifest)
    if expiry is not None and expiry <= _now():
        raise SkillRecordingNotFoundError("Recording session has expired.")


def cleanup_expired_sessions(*, recover_interrupted: bool = False) -> int:
    """Expire old sessions and optionally finalize sessions left active at exit."""
    root = _root(create=False)
    if not root.exists():
        return 0
    removed = 0
    for child in root.iterdir():
        if child.is_symlink() or not child.is_dir():
            continue
        try:
            session_dir = _validated_session_dir(child.name)
            manifest = _read_manifest(session_dir)
            expiry = _expiry_time(manifest)
            if expiry is not None and expiry <= _now():
                delete_session(child.name)
                removed += 1
            elif recover_interrupted and manifest.get("status") in {
                "recording",
                "paused",
            }:
                now = _now()
                manifest["status"] = "stopped"
                manifest["updated_at"] = now.isoformat()
                manifest["expires_at"] = (now + SESSION_TTL).isoformat()
                _write_manifest(session_dir, manifest)
        except (SkillRecordingError, OSError):
            # Invalid or inaccessible entries are preserved for inspection.
            continue
    return removed


async def store_video(session_id: str, chunks: AsyncIterable[bytes]) -> dict[str, Any]:
    """Stream a stopped session's WebM into its UUID-owned artifact directory."""
    session_dir = _validated_session_dir(session_id)
    manifest = _read_manifest(session_dir)
    _ensure_session_live(manifest)
    if manifest.get("status") != "stopped":
        raise SkillRecordingConflictError("Stop the recording before saving video.")
    if manifest.get("video_artifacts"):
        raise SkillRecordingConflictError("A video artifact already exists.")

    destination = session_dir / "video.webm"
    temporary = session_dir / f".video-{uuid.uuid4().hex}.tmp"
    if destination.exists() or destination.is_symlink():
        raise SkillRecordingPathError("Video artifact already exists on disk.")

    total = 0
    try:
        with temporary.open("xb") as stream:
            async for chunk in chunks:
                if not isinstance(chunk, bytes):
                    raise SkillRecordingValidationError(
                        "Video stream contained an invalid chunk."
                    )
                total += len(chunk)
                if total > MAX_VIDEO_BYTES:
                    raise SkillRecordingValidationError(
                        "Video exceeds the recording size limit."
                    )
                if chunk:
                    stream.write(chunk)
            if total < 1:
                raise SkillRecordingValidationError("Video artifact is empty.")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        artifact = {
            "id": "video",
            "path": "video.webm",
            "media_type": "video/webm",
            "byte_length": total,
        }
        manifest["video_artifacts"] = [artifact]
        manifest["artifact_bytes"] = int(manifest.get("artifact_bytes", 0)) + total
        manifest["updated_at"] = _now().isoformat()
        try:
            _write_manifest(session_dir, manifest)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return {
        "recording_id": session_id,
        "artifact_id": "video",
        "media_type": "video/webm",
        "byte_length": total,
        "expires_at": manifest.get("expires_at"),
    }


def video_path(session_id: str) -> Path:
    """Return a validated, unexpired video artifact path for streaming reads."""
    session_dir = _validated_session_dir(session_id)
    manifest = _read_manifest(session_dir)
    _ensure_session_live(manifest)
    artifacts = manifest.get("video_artifacts", [])
    if not any(
        artifact.get("id") == "video"
        and artifact.get("path") == "video.webm"
        and artifact.get("media_type") == "video/webm"
        for artifact in artifacts
        if isinstance(artifact, dict)
    ):
        raise SkillRecordingNotFoundError("Video artifact not found.")
    path = _regular_file(session_dir / "video.webm", required=True)
    if path.resolve().parent != session_dir.resolve():
        raise SkillRecordingPathError("Video artifact escaped its recording directory.")
    return path
