"""Tests for local skill demonstration trace storage."""

from __future__ import annotations

import base64
import json
import struct
import zlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.core.config import settings
from app.services import skill_recording_service as recordings


@pytest.fixture
def recording_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config = tmp_path / "config"
    config.mkdir()
    monkeypatch.setattr(settings, "EVOFLUX_CONFIG_DIR", str(config))
    return config / "skill-recordings"


def event(sequence: int, *, kind: str = "focus", screenshot: str | None = None) -> dict:
    return {
        "sequence": sequence,
        "elapsed_ms": sequence * 10,
        "kind": kind,
        "target": None,
        "value_state": "not_captured",
        "value": None,
        "screenshot": screenshot,
    }


def png_fixture() -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    pixels = zlib.compress(b"\x00\xff\x00\x00\xff")
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", pixels)
        + chunk(b"IEND", b"")
    )


def test_create_session_uses_uuid_directory_and_manifest(recording_root: Path) -> None:
    session = recordings.create_session()

    assert (recording_root / session["id"] / "manifest.json").is_file()
    manifest = json.loads(
        (recording_root / session["id"] / "manifest.json").read_text()
    )
    assert manifest["id"] == session["id"]
    assert manifest["status"] == "recording"
    assert manifest["schema_version"] == 2
    assert manifest["video_artifacts"] == []


def test_append_assigns_persistent_order_and_roundtrips_events(
    recording_root: Path,
) -> None:
    session = recordings.create_session()

    result = recordings.append_events(session["id"], [event(20), event(21)])
    stored = recordings.get_session(session["id"])

    assert result["appended"] == 2
    assert [row["sequence"] for row in stored["events"]] == [1, 2]
    assert [row["source_sequence"] for row in stored["events"]] == [20, 21]
    assert (recording_root / session["id"] / "events.jsonl").read_text().count(
        "\n"
    ) == 2


def test_pointer_actions_roundtrip_coordinates_and_button(recording_root: Path) -> None:
    session_id = recordings.create_session()["id"]
    rows = [
        {
            **event(1, kind="click"),
            "point": {"x": -120, "y": 340, "display_id": "DISPLAY1"},
            "button": "left",
        },
        {
            **event(2, kind="double_click"),
            "point": {"x": 12, "y": 34, "display_id": None},
            "button": "right",
        },
        {
            **event(3, kind="scroll"),
            "point": {"x": 12, "y": 34, "display_id": "DISPLAY1"},
            "scroll_delta": {"x": 0, "y": -120},
        },
    ]

    recordings.append_events(session_id, rows)
    stored = recordings.get_session(session_id)["events"]

    assert stored[0]["point"] == {"x": -120, "y": 340, "display_id": "DISPLAY1"}
    assert stored[0]["button"] == "left"
    assert stored[1]["button"] == "right"
    assert stored[2]["scroll_delta"] == {"x": 0, "y": -120}


@pytest.mark.parametrize(
    "pointer_fields",
    [
        {"point": {"x": True, "y": 0}, "button": "left"},
        {"point": {"x": 32768, "y": 0}, "button": "left"},
        {"point": {"x": 0, "y": 0}, "button": "keyboard"},
        {"point": {"x": 0, "y": 0}, "scroll_delta": {"x": False, "y": 0}},
    ],
)
def test_invalid_pointer_payload_is_rejected_atomically(
    recording_root: Path, pointer_fields: dict
) -> None:
    session_id = recordings.create_session()["id"]
    kind = "scroll" if "scroll_delta" in pointer_fields else "click"

    with pytest.raises(recordings.SkillRecordingValidationError):
        recordings.append_events(
            session_id, [{**event(1, kind=kind), **pointer_fields}]
        )

    assert recordings.get_session(session_id)["events"] == []


def test_pause_rejects_appends_resume_accepts_and_stop_is_idempotent(
    recording_root: Path,
) -> None:
    session_id = recordings.create_session()["id"]

    recordings.pause_session(session_id)
    with pytest.raises(recordings.SkillRecordingConflictError):
        recordings.append_events(session_id, [event(1)])
    recordings.resume_session(session_id)
    recordings.append_events(session_id, [event(1)])
    recordings.stop_session(session_id)
    recordings.stop_session(session_id)
    with pytest.raises(recordings.SkillRecordingConflictError):
        recordings.append_events(session_id, [event(2)])
    assert recordings.get_session(session_id)["status"] == "stopped"


def test_total_event_count_is_bounded(
    recording_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(recordings, "MAX_SESSION_EVENTS", 1)
    session_id = recordings.create_session()["id"]

    with pytest.raises(recordings.SkillRecordingValidationError):
        recordings.append_events(session_id, [event(1), event(2)])

    assert recordings.get_session(session_id)["events"] == []


@pytest.mark.parametrize("session_id", ["..", "../outside", "a/b", "not-a-uuid"])
def test_invalid_session_id_cannot_escape_storage_root(
    recording_root: Path, session_id: str
) -> None:
    with pytest.raises(recordings.SkillRecordingNotFoundError):
        recordings.get_session(session_id)
    assert not (recording_root.parent / "outside").exists()


def test_screenshot_is_saved_as_contained_artifact_and_jsonl_has_no_base64(
    recording_root: Path,
) -> None:
    session_id = recordings.create_session()["id"]
    png = png_fixture()
    encoded = base64.b64encode(png).decode("ascii")

    recordings.append_events(
        session_id, [event(3, kind="screenshot", screenshot=encoded)]
    )
    stored = recordings.get_session(session_id)
    event_row = stored["events"][0]
    artifact = recording_root / session_id / event_row["screenshot"]

    assert artifact.is_file()
    assert artifact.read_bytes() == png
    assert encoded not in (recording_root / session_id / "events.jsonl").read_text()


def test_bad_screenshot_base64_rejected_without_partial_event(
    recording_root: Path,
) -> None:
    session_id = recordings.create_session()["id"]

    with pytest.raises(recordings.SkillRecordingValidationError):
        recordings.append_events(session_id, [event(1, screenshot="not-base64!")])

    assert recordings.get_session(session_id)["events"] == []
    assert not list((recording_root / session_id / "screenshots").glob("*"))


def test_delete_removes_only_the_owned_recording_directory(
    recording_root: Path,
) -> None:
    session_id = recordings.create_session()["id"]
    recordings.append_events(session_id, [event(1)])

    recordings.delete_session(session_id)

    assert not (recording_root / session_id).exists()
    assert recording_root.is_dir()


def test_symlinked_session_directory_is_rejected(
    tmp_path: Path, recording_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_id = recordings.create_session()["id"]
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "manifest.json").write_text("{}")
    session_dir = recording_root / session_id
    original_is_symlink = Path.is_symlink
    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda path: path == session_dir or original_is_symlink(path),
    )

    with pytest.raises(recordings.SkillRecordingPathError):
        recordings.get_session(session_id)
    assert (outside / "manifest.json").read_text() == "{}"


def test_stop_sets_one_hour_expiry(
    recording_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime(2026, 10, 8, 3, 0, tzinfo=UTC)
    monkeypatch.setattr(recordings, "_now", lambda: now)
    session = recordings.create_session()

    stopped = recordings.stop_session(session["id"])

    assert datetime.fromisoformat(stopped["expires_at"]) == now + timedelta(hours=1)


@pytest.mark.asyncio
async def test_video_artifact_is_streamed_to_a_contained_file(
    recording_root: Path,
) -> None:
    session_id = recordings.create_session()["id"]
    recordings.stop_session(session_id)

    async def chunks():
        yield b"webm-header"
        yield b"-webm-frame"

    uploaded = await recordings.store_video(session_id, chunks())
    session = recordings.get_session(session_id)
    artifact = recording_root / session_id / "video.webm"

    assert uploaded["byte_length"] == 22
    assert artifact.read_bytes() == b"webm-header-webm-frame"
    assert session["video_artifacts"] == [
        {
            "id": "video",
            "path": "video.webm",
            "media_type": "video/webm",
            "byte_length": 22,
        }
    ]


@pytest.mark.asyncio
async def test_video_limit_rejects_partial_artifact_and_manifest_update(
    recording_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(recordings, "MAX_VIDEO_BYTES", 8)
    session_id = recordings.create_session()["id"]
    recordings.stop_session(session_id)

    async def chunks():
        yield b"12345678"
        yield b"9"

    with pytest.raises(recordings.SkillRecordingValidationError):
        await recordings.store_video(session_id, chunks())

    assert not (recording_root / session_id / "video.webm").exists()
    assert recordings.get_session(session_id)["video_artifacts"] == []


def test_schema_v1_manifest_is_migrated_without_losing_events(
    recording_root: Path,
) -> None:
    session = recordings.create_session()
    recordings.append_events(session["id"], [event(1)])
    manifest_path = recording_root / session["id"] / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["schema_version"] = 1
    manifest.pop("video_artifacts", None)
    manifest.pop("expires_at", None)
    manifest_path.write_text(json.dumps(manifest))

    migrated = recordings.get_session(session["id"])

    assert migrated["schema_version"] == 2
    assert migrated["video_artifacts"] == []
    assert [row["source_sequence"] for row in migrated["events"]] == [1]
    assert json.loads(manifest_path.read_text())["schema_version"] == 2


def test_expired_session_cannot_be_read_and_cleanup_deletes_all_artifacts(
    recording_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime(2026, 10, 8, 3, 0, tzinfo=UTC)
    monkeypatch.setattr(recordings, "_now", lambda: now)
    session_id = recordings.create_session()["id"]
    png = base64.b64encode(png_fixture()).decode("ascii")
    recordings.append_events(session_id, [event(1, kind="screenshot", screenshot=png)])
    recordings.stop_session(session_id)
    session_dir = recording_root / session_id
    (session_dir / "video.webm").write_bytes(b"webm")
    manifest_path = session_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["video_artifacts"] = [
        {
            "id": "video",
            "path": "video.webm",
            "media_type": "video/webm",
            "byte_length": 4,
        }
    ]
    manifest["artifact_bytes"] += 4
    manifest["expires_at"] = (now - timedelta(seconds=1)).isoformat()
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(recordings.SkillRecordingNotFoundError):
        recordings.get_session(session_id)
    with pytest.raises(recordings.SkillRecordingNotFoundError):
        recordings.video_path(session_id)

    assert recordings.cleanup_expired_sessions() == 1
    assert not session_dir.exists()


def test_startup_recovers_interrupted_session_with_one_hour_review_window(
    recording_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 10, 8, 3, 0, tzinfo=UTC)
    monkeypatch.setattr(recordings, "_now", lambda: now)
    session_id = recordings.create_session()["id"]
    recordings.append_events(session_id, [event(1)])

    assert recordings.cleanup_expired_sessions(recover_interrupted=True) == 0
    recovered = recordings.get_session(session_id)

    assert recovered["status"] == "stopped"
    assert datetime.fromisoformat(recovered["expires_at"]) == now + timedelta(hours=1)
    assert [row["source_sequence"] for row in recovered["events"]] == [1]
