from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path


def _load_mcp_apply():
    path = (
        Path(__file__).resolve().parents[3]
        / "app"
        / "agent"
        / "builtin_skills"
        / "mcp-installer"
        / "mcp_apply.py"
    )
    spec = importlib.util.spec_from_file_location("EVOFLUX_mcp_apply", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_parse_http_server_body_supports_headers_and_public_oauth() -> None:
    mcp_apply = _load_mcp_apply()

    body = mcp_apply._parse_server_body(
        argparse.Namespace(
            http="https://mcp.example.com/mcp",
            stdio=None,
            header=[["Authorization=Bearer ${PRIVATE_MCP_TOKEN}"]],
            oauth=True,
            oauth_client_id="public-client-id",
            oauth_client_secret=None,
            args=[],
            env=[],
        )
    )

    assert body == {
        "transport": "http",
        "url": "https://mcp.example.com/mcp",
        "headers": {"Authorization": "Bearer ${PRIVATE_MCP_TOKEN}"},
        "oauth": {"client_id": "public-client-id", "client_secret": None},
    }


def test_fallback_add_stores_oauth_secrets_as_env_refs(tmp_path, monkeypatch) -> None:
    mcp_apply = _load_mcp_apply()
    mcp_json = tmp_path / "mcp.json"
    env_file = tmp_path / ".env"
    monkeypatch.delenv("SLACK_MCP_CLIENT_ID", raising=False)
    monkeypatch.delenv("SLACK_MCP_CLIENT_SECRET", raising=False)

    mcp_apply._fallback_add(
        "slack",
        {
            "transport": "http",
            "url": "https://mcp.slack.com/mcp",
            "headers": {},
            "oauth": {"client_id": "client-id", "client_secret": "client-secret"},
        },
        mcp_json,
        env_file,
    )

    data = json.loads(mcp_json.read_text(encoding="utf-8"))
    assert data["servers"]["slack"]["oauth"] == {
        "client_id": "${SLACK_MCP_CLIENT_ID}",
        "client_secret": "${SLACK_MCP_CLIENT_SECRET}",
    }
    env_text = env_file.read_text(encoding="utf-8")
    assert 'SLACK_MCP_CLIENT_ID="client-id"' in env_text
    assert 'SLACK_MCP_CLIENT_SECRET="client-secret"' in env_text
