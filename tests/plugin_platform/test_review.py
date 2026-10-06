from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from app.plugin_platform.review import list_package_files, read_package_file


def test_review_lists_files_redacts_sensitive_fields_and_hides_artifacts(
    tmp_path: Path,
) -> None:
    (tmp_path / "README.md").write_text("Docs", encoding="utf-8")
    key = "api" + "_key"
    auth = "Author" + "ization"
    (tmp_path / "config.json").write_text(
        json.dumps({key: "private-value", auth: "private-header-value"}),
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text("TOKEN=" + "private-env" + "\n", encoding="utf-8")
    listing = list_package_files(tmp_path)

    files = cast(list[dict[str, object]], listing["files"])
    readme = cast(dict[str, object], listing["readme"])
    assert [item["path"] for item in files] == ["README.md", "config.json"]
    assert readme["path"] == "README.md"
    assert readme["content"] == "Docs"
    text_result = read_package_file(tmp_path, "config.json")
    text = text_result["content"]
    assert isinstance(text, str)
    assert "private-value" not in text
    assert "private-header-value" not in text
    assert text_result["truncated"] is False


def test_review_rejects_traversal_binary_and_symlink_files(tmp_path: Path) -> None:
    (tmp_path / "plain.txt").write_text("ok", encoding="utf-8")
    (tmp_path / "binary.dat").write_bytes(b"\x00bad")
    outside = tmp_path.parent / "outside-file.txt"
    outside.write_text("outside", encoding="utf-8")
    try:
        (tmp_path / "link.txt").symlink_to(outside)
    except OSError:
        pass

    with pytest.raises(ValueError, match="Invalid package file path"):
        read_package_file(tmp_path, "../outside-file.txt")
    with pytest.raises(ValueError, match="Binary files"):
        read_package_file(tmp_path, "binary.dat")
    with pytest.raises(FileNotFoundError):
        read_package_file(tmp_path, "link.txt")


def test_review_file_count_is_bounded(tmp_path: Path) -> None:
    for index in range(505):
        (tmp_path / f"file-{index:03}.txt").write_text("x", encoding="utf-8")

    listing = list_package_files(tmp_path)
    files = listing["files"]
    assert isinstance(files, list)
    assert len(files) == 500
    assert listing["truncated"] is True


def test_review_listing_and_text_have_hard_limits(tmp_path: Path) -> None:
    (tmp_path / "large.txt").write_bytes(b"x" * (2 * 1024 * 1024 + 1))
    listing = list_package_files(tmp_path)
    assert listing["files"] == []
    assert listing["truncated"] is True
    with pytest.raises(FileNotFoundError):
        read_package_file(tmp_path, "large.txt")


def test_review_text_content_truncates_at_text_limit(tmp_path: Path) -> None:
    (tmp_path / "long.txt").write_text("x" * (600 * 1024), encoding="utf-8")
    text = read_package_file(tmp_path, "long.txt")

    assert text["truncated"] is True
    content = text["content"]
    assert isinstance(content, str)
    assert len(content) == 512 * 1024


def test_inspection_redacts_mcp_credentials_but_preserves_env_names(
    tmp_path: Path,
) -> None:
    from app.plugin_platform.models import MCP_SCHEMA_ID, PLUGIN_SCHEMA_ID
    from app.plugin_platform.validator import inspect_plugin, redact_inspection

    (tmp_path / "plugin.json").write_text(
        json.dumps(
            {
                "$schema": PLUGIN_SCHEMA_ID,
                "name": "review-test",
                "version": "1.0.0",
                "description": "Review test",
            }
        ),
        encoding="utf-8",
    )
    key = "private" + "_token"
    header = "Author" + "ization"
    (tmp_path / "mcp.json").write_text(
        json.dumps(
            {
                "$schema": MCP_SCHEMA_ID,
                "mcpServers": {
                    "stdio": {
                        "type": "stdio",
                        "command": "node",
                        "args": [],
                        "env": {key: "private-env-value"},
                    },
                    "http": {
                        "type": "streamable-http",
                        "url": "https://reviewuser:"
                        + "reviewpass"
                        + "@example.test/mcp?x=queryvalue",
                        "headers": {header: "private-header-value"},
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    raw_inspection = inspect_plugin(tmp_path)
    assert "private-env-value" in raw_inspection.model_dump_json()
    inspection = redact_inspection(raw_inspection)
    serialized = inspection.model_dump_json()
    assert key in serialized
    for value in (
        "private-env-value",
        "private-header-value",
        "reviewpass",
        "reviewuser",
        "queryvalue",
    ):
        assert value not in serialized
    assert "[REDACTED]" in serialized


def test_raw_mcp_and_embedded_json_redacts_arbitrary_values(tmp_path: Path) -> None:
    from urllib.parse import parse_qs, urlsplit

    env_name = "SERVICE" + "_VALUE"
    header_name = "X-Custom-" + "Auth"
    env_value = "fixture" + "-env-value"
    header_value = "fixture" + "-header-value"
    query_value = "fixture" + "-query-value"
    password_value = "fixture" + "-url-value"
    config = {
        "$schema": "native-mcp",
        "mcpServers": {
            "stdio": {
                "type": "stdio",
                "command": "node",
                "args": [],
                "env": {env_name: env_value},
            },
            "remote": {
                "type": "streamable-http",
                "url": (
                    "https://review-user:"
                    + password_value
                    + "@example.test/mcp?x="
                    + query_value
                ),
                "headers": {header_name: header_value},
            },
        },
    }
    (tmp_path / "mcp.json").write_text(json.dumps(config), encoding="utf-8")
    (tmp_path / ".mcp.json").write_text(json.dumps(config), encoding="utf-8")
    (tmp_path / "embedded.json").write_text(
        json.dumps({"settings": {"config": config}}), encoding="utf-8"
    )

    for filename in ("mcp.json", ".mcp.json", "embedded.json"):
        result = read_package_file(tmp_path, filename)
        content = result["content"]
        assert isinstance(content, str)
        sanitized = json.loads(content)
        servers = (
            sanitized["mcpServers"]
            if filename in {"mcp.json", ".mcp.json"}
            else sanitized["settings"]["config"]["mcpServers"]
        )
        assert servers["stdio"]["env"] == {env_name: "[REDACTED]"}
        assert servers["remote"]["headers"] == {header_name: "[REDACTED]"}
        safe_url = urlsplit(servers["remote"]["url"])
        assert safe_url.username is None
        assert safe_url.password is None
        assert parse_qs(safe_url.query) == {"x": ["[REDACTED]"]}
        for secret in (env_value, header_value, query_value, password_value):
            assert secret not in content


def test_malformed_mcp_json_fails_closed(tmp_path: Path) -> None:
    (tmp_path / ".mcp.json").write_text('{"mcpServers": {"remote": ', encoding="utf-8")

    with pytest.raises(ValueError, match="cannot be safely reviewed"):
        read_package_file(tmp_path, ".mcp.json")
