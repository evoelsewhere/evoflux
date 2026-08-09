from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app.core.config import settings
from app.plugin_platform.credentials import credential_definition, save_credentials
from app.plugin_platform.installer import install_plugin, pack_plugin, uninstall_plugin
from app.plugin_platform.registry import plugin_data_root
from app.plugin_platform.runtime import PluginMCPRuntime
from app.plugin_platform.validator import inspect_plugin
from plugins.jira.backend.evoflux_jira.client import (
    ISSUE_FIELDS,
    JiraClient,
    build_jql,
    normalize_base_url,
)
from plugins.jira.backend.evoflux_jira.config import ConnectionConfig, ConnectionStore
from plugins.jira.backend.evoflux_jira.errors import JiraPluginError


PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "plugins" / "jira"


def _connection(base_url: str = "https://jira.example.test/jira9") -> ConnectionConfig:
    return ConnectionConfig(
        name="default",
        base_url=base_url,
        api_token="fixture-token",
    )


def test_jira_reference_package_is_valid_and_component_complete() -> None:
    inspection = inspect_plugin(PLUGIN_ROOT)

    assert inspection.valid is True
    assert inspection.manifest is not None
    assert inspection.manifest.name == "evoflux-jira"
    assert inspection.manifest.version == "0.1.2"
    assert [skill.name for skill in inspection.skills] == ["jira-task-management"]
    assert [(server.name, server.valid) for server in inspection.mcp_servers] == [
        ("jira", True)
    ]
    definition = credential_definition(inspection)
    assert definition is not None
    assert [(field.key, field.env) for field in definition.fields] == [
        ("base_url", "JIRA_URL"),
        ("api_token", "JIRA_API_TOKEN"),
        ("verify_ssl", "JIRA_VERIFY_SSL"),
    ]


@pytest.mark.parametrize(
    "value",
    [
        "https://user:pass@jira.example.test/jira9",
        "https://jira.example.test/jira9?token=bad",
        "https://jira.example.test/jira9#fragment",
        "file:///tmp/jira",
    ],
)
def test_jira_url_rejects_unsafe_values(value: str) -> None:
    with pytest.raises(JiraPluginError, match="Jira URL"):
        normalize_base_url(value)


def test_jira_url_and_jql_preserve_context_and_escape_filters() -> None:
    assert normalize_base_url("https://jira.example.test/jira9/") == (
        "https://jira.example.test/jira9"
    )
    assert build_jql(
        jql="",
        project_key="opnext88",
        text='broken "login"',
        status="Open",
        assignee="currentUser()",
        priority="",
        issue_type="Bug",
    ) == (
        'project = "OPNEXT88" AND text ~ "broken \\"login\\"" AND '
        'status = "Open" AND issuetype = "Bug" AND assignee = currentUser() '
        "ORDER BY updated DESC"
    )


@pytest.mark.asyncio
async def test_search_uses_bounded_fields_context_path_and_bearer_auth() -> None:
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={
                "startAt": 0,
                "maxResults": 50,
                "total": 1,
                "issues": [
                    {
                        "id": "10001",
                        "key": "OPNEXT88-7",
                        "fields": {
                            "summary": "Fixture issue",
                            "status": {"name": "Open"},
                            "issuetype": {"name": "Bug"},
                            "priority": {"name": "High"},
                            "assignee": {"displayName": "Test User"},
                        },
                    }
                ],
            },
        )

    async with JiraClient(
        _connection(),
        transport=httpx.MockTransport(handler),
    ) as client:
        result = await client.issues_search(project_key="OPNEXT88")

    request = seen[0]
    params = parse_qs(request.url.query.decode())
    assert request.url.path == "/jira9/rest/api/2/search"
    assert request.headers["Authorization"] == "Bearer fixture-token"
    assert params["fields"] == [ISSUE_FIELDS]
    assert params["maxResults"] == ["50"]
    assert result["items"][0]["key"] == "OPNEXT88-7"
    assert result["page"]["is_last"] is True


@pytest.mark.asyncio
async def test_redirect_and_html_permission_errors_are_sanitized() -> None:
    responses = iter(
        [
            httpx.Response(302, headers={"location": "https://evil.test/steal"}),
            httpx.Response(
                403,
                headers={"content-type": "text/html"},
                text="<html>internal firewall details</html>",
            ),
        ]
    )

    async def handler(_: httpx.Request) -> httpx.Response:
        return next(responses)

    async with JiraClient(
        _connection(),
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(JiraPluginError) as redirect:
            await client.projects_list()
        with pytest.raises(JiraPluginError) as forbidden:
            await client.projects_list()

    assert redirect.value.code == "endpoint_unavailable"
    assert forbidden.value.code == "permission_denied"
    assert "firewall" not in forbidden.value.message


def test_connection_store_masks_token_and_uses_private_permissions(
    tmp_path: Path,
) -> None:
    path = tmp_path / "connections.json"
    store = ConnectionStore(path)
    store.save(_connection())

    assert store.get().api_token == "fixture-token"
    assert store.list_public() == [
        {
            "name": "default",
            "base_url": "https://jira.example.test/jira9",
            "verify_ssl": True,
            "has_api_token": True,
        }
    ]
    assert path.stat().st_mode & 0o777 == 0o600
    assert "fixture-token" not in json.dumps(store.list_public())


def test_connection_store_accepts_host_injected_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PLUGIN_DATA", str(tmp_path))
    monkeypatch.setenv("JIRA_URL", "https://jira.example.test/jira9")
    monkeypatch.setenv("JIRA_API_TOKEN", "host-secret")
    monkeypatch.setenv("JIRA_VERIFY_SSL", "false")

    store = ConnectionStore.from_environment()

    assert store.get() == ConnectionConfig(
        name="default",
        base_url="https://jira.example.test/jira9",
        api_token="host-secret",
        verify_ssl=False,
    )
    assert store.list_public()[0]["has_api_token"] is True
    assert not (tmp_path / "connections.json").exists()


class _FixtureJiraHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        payloads = {
            "/jira9/rest/api/2/serverInfo": {
                "serverTitle": "Fixture Jira",
                "version": "10.3.23",
            },
            "/jira9/rest/api/2/myself": {
                "displayName": "Fixture User",
                "name": "fixture.user",
            },
            "/jira9/rest/api/2/project": [{"id": "101", "key": "DEMO", "name": "Demo"}],
        }
        payload = payloads.get(path)
        if (
            payload is None
            or self.headers.get("Authorization") != "Bearer fixture-token"
        ):
            self.send_response(404)
            payload = {"errorMessages": ["Not found"]}
        else:
            self.send_response(200)
        body = json.dumps(payload).encode()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        del format, args
        return


@pytest.mark.asyncio
async def test_jira_plugin_pack_install_start_and_call_tool_end_to_end(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "EVOFLUX_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(settings, "EVOFLUX_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(settings, "EVOFLUX_CONFIG_DIR", str(tmp_path / "config"))
    fixture = ThreadingHTTPServer(("127.0.0.1", 0), _FixtureJiraHandler)
    thread = threading.Thread(target=fixture.serve_forever, daemon=True)
    thread.start()
    runtime = PluginMCPRuntime(watch_interval=60)
    installation = None
    try:
        archive = pack_plugin(PLUGIN_ROOT, tmp_path / "evoflux-jira.evoplugin")
        installation = install_plugin(archive)
        inspection = inspect_plugin(
            installation.root,
            data_root=plugin_data_root(installation.id),
        )
        credential_state = save_credentials(
            installation.id,
            inspection,
            {
                "base_url": f"http://127.0.0.1:{fixture.server_port}/jira9",
                "api_token": "fixture-token",
                "verify_ssl": True,
            },
        )
        assert credential_state.configured is True
        assert (
            next(
                field for field in credential_state.fields if field.key == "api_token"
            ).value
            == "********"
        )

        await runtime.refresh()
        await runtime._manager.wait_until_ready(timeout=10)
        statuses = runtime.list_status()
        assert len(statuses) == 1
        assert statuses[0]["state"] == "ready"

        tools = runtime.get_tools_dict()
        tool = next(
            value for name, value in tools.items() if name.endswith("_connection_test")
        )
        result = await tool.arun(connection="default")
        assert "Fixture Jira" in result
        assert "fixture-token" not in result
    finally:
        await runtime.stop()
        if installation is not None:
            uninstall_plugin(installation.id, remove_data=True)
        fixture.shutdown()
        fixture.server_close()
        await asyncio.to_thread(thread.join, 2)
