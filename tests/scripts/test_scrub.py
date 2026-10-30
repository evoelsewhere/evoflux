import subprocess
import sys
from pathlib import Path


def test_scrub_removes_api_keys_and_home_paths(tmp_path: Path) -> None:
    recording = tmp_path / "recording.jsonl"
    recording.write_text(
        "sk-abcdefghijklmnopqrstuvwxyz123456 user@example.com /home/alice/private C:\\Users\\Alice\\private",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "scripts/migration/scrub.py", str(recording)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    scrubbed = recording.read_text(encoding="utf-8")
    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in scrubbed
    assert "user@example.com" not in scrubbed
    assert "/home/alice" not in scrubbed
    assert "C:\\Users\\Alice" not in scrubbed
    assert "<user>" in scrubbed


def test_scrub_keeps_json_lines_valid(tmp_path: Path) -> None:
    recording = tmp_path / "recording.jsonl"
    recording.write_text(
        '{"path":"C:\\\\Users\\\\Alice\\\\x","key":"sk-ant-api03-abcdefghijklmnopqrstuvwxyz"}\n',
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "scripts/migration/scrub.py", str(recording)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    import json

    row = json.loads(recording.read_text(encoding="utf-8"))
    assert "Alice" not in row["path"]
    assert "abcdefghijklmnopqrstuvwxyz" not in row["key"]


def test_scrub_missing_file_exits_nonzero(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "scripts/migration/scrub.py", str(tmp_path / "nope.jsonl")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0


def test_scrub_removes_percent_encoded_token_keys(tmp_path: Path) -> None:
    recording = tmp_path / "recording.jsonl"
    recording.write_text(
        '{"path":"/a?x=1&%5Ftoken=SECRET1&_%74oken=SECRET2&_token=SECRET3"}\n',
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "scripts/migration/scrub.py", str(recording)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    scrubbed = recording.read_text(encoding="utf-8")
    for secret in ("SECRET1", "SECRET2", "SECRET3"):
        assert secret not in scrubbed
    assert "x=1" in scrubbed
