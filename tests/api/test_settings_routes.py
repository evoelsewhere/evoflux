"""Tests for app/api/routes/settings.py — sandbox deny-list endpoints."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.agent.sandbox_config import DEFAULT_DENIED_PATTERNS
from app.api.routes import settings as settings_routes
from app.cli.seed import SeedDownloadError, SeedResult
from app.api.routes.settings import router
from app.agent.providers.codex.oauth import CodexOAuth
from app.agent.providers.copilot.oauth import CopilotOAuth
from app.agent.providers.codex import usage as codex_usage
from app.agent.providers.copilot import usage as copilot_usage


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/settings")
    return app


@pytest.fixture
def isolated_config(tmp_path: Path):
    """Point load_config / save_config at a tmp ``sandbox.yaml``."""
    target = tmp_path / "sandbox.yaml"
    with patch("app.agent.sandbox_config.config_path", return_value=target):
        yield target


@pytest.fixture(autouse=True)
def _reset_local_reachable_cache(monkeypatch: pytest.MonkeyPatch):
    """Clear provider caches and avoid live model discovery in tests.

    The cache is module-level state; without resetting it a test that
    happens to ping a daemon successfully (or hit a cached failure)
    would leak that result into unrelated tests. Provider listing also
    checks live model discovery before showing Connected; default that
    probe to a deterministic success so focused tests can opt into
    fallback/unreachable states explicitly.
    """

    async def _available(_entry, **_kwargs):  # type: ignore[no-untyped-def]
        return ["test-model"]

    settings_routes._local_reachable_cache.clear()
    settings_routes._provider_model_cache.clear()
    monkeypatch.setattr(
        "app.agent.providers.model_discovery.discover_provider_models", _available
    )
    yield
    settings_routes._local_reachable_cache.clear()
    settings_routes._provider_model_cache.clear()


def test_connect_conductor_forwards_token_and_returns_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.conductor import conductor_service

    payload = {
        "enabled": True,
        "enrolled": True,
        "state": "connected",
        "installation_id": "installation-1",
    }
    connect = AsyncMock(
        return_value=SimpleNamespace(model_dump=lambda **_kwargs: payload)
    )
    monkeypatch.setattr(conductor_service, "connect", connect)

    response = TestClient(_make_app()).post(
        "/api/settings/conductor/connect",
        json={"enrollment_token": "evc_connection-token"},
    )

    assert response.status_code == 200
    assert response.json() == payload
    connect.assert_awaited_once_with("evc_connection-token")


def test_connect_conductor_preserves_upstream_auth_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.conductor import conductor_service
    from app.conductor.client import ConductorRequestError

    monkeypatch.setattr(
        conductor_service,
        "connect",
        AsyncMock(side_effect=ConductorRequestError(403, "Token scope denied.")),
    )

    response = TestClient(_make_app()).post(
        "/api/settings/conductor/connect",
        json={"enrollment_token": "evc_denied"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Token scope denied."}


def test_connect_conductor_reports_credential_vault_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.conductor import conductor_service
    from app.conductor.client import CredentialStoreError

    monkeypatch.setattr(
        conductor_service,
        "connect",
        AsyncMock(side_effect=CredentialStoreError("Credential vault unavailable.")),
    )

    response = TestClient(_make_app()).post(
        "/api/settings/conductor/connect",
        json={"enrollment_token": "evc_valid"},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Credential vault unavailable."}


def test_disconnect_conductor_clears_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.conductor import conductor_service

    payload = {
        "enabled": True,
        "enrolled": False,
        "state": "disconnected",
        "installation_id": None,
    }
    disconnect = AsyncMock(
        return_value=SimpleNamespace(model_dump=lambda **_kwargs: payload)
    )
    monkeypatch.setattr(conductor_service, "disconnect", disconnect)

    response = TestClient(_make_app()).post("/api/settings/conductor/disconnect")

    assert response.status_code == 200
    assert response.json() == payload
    disconnect.assert_awaited_once_with()


def test_pull_conductor_resource_is_an_explicit_server_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.conductor import conductor_service

    payload = {
        "resource_id": "resource-1",
        "version": "1.2.0",
        "applied_version": "1.2.0",
        "observed_state": "applied",
    }
    pull = AsyncMock(return_value=payload)
    monkeypatch.setattr(conductor_service, "pull_governed_resource", pull)

    response = TestClient(_make_app()).post(
        "/api/settings/conductor/resources/resource-1/pull"
    )

    assert response.status_code == 200
    assert response.json() == payload
    pull.assert_awaited_once_with("resource-1")


def test_get_sandbox_returns_seed_defaults_when_file_missing(
    isolated_config: Path,
) -> None:
    client = TestClient(_make_app())
    response = client.get("/api/settings/sandbox")
    assert response.status_code == 200
    assert response.json() == {
        "denied_patterns": list(DEFAULT_DENIED_PATTERNS),
        "worktree_location": "repository",
        "inherit_shell_environment": False,
        "load_shell_profile": False,
        "outbound_data_policy": "block",
        "outbound_pii_policy": "standard",
        "max_execution_seconds": 600,
        "max_output_bytes": 131072,
    }
    # GET must not write the file.
    assert not isolated_config.exists()


def test_put_sandbox_persists_patterns(isolated_config: Path) -> None:
    client = TestClient(_make_app())
    body = {
        "denied_patterns": ["**/.env", "**/secrets/**"],
        "worktree_location": "user_data",
        "inherit_shell_environment": True,
        "load_shell_profile": True,
        "outbound_data_policy": "block",
        "outbound_pii_policy": "strict",
        "max_execution_seconds": 300,
        "max_output_bytes": 262144,
    }
    response = client.put("/api/settings/sandbox", json=body)
    assert response.status_code == 200
    assert response.json() == body
    assert isolated_config.exists()

    # Round-trip — GET reflects what was saved.
    again = client.get("/api/settings/sandbox")
    assert again.json() == body


def test_put_sandbox_strips_blank_patterns(isolated_config: Path) -> None:
    client = TestClient(_make_app())
    response = client.put(
        "/api/settings/sandbox",
        json={"denied_patterns": ["**/.env", "", "   ", "bar/*"]},
    )
    assert response.status_code == 200
    assert response.json() == {
        "denied_patterns": ["**/.env", "bar/*"],
        "worktree_location": "repository",
        "inherit_shell_environment": False,
        "load_shell_profile": False,
        "outbound_data_policy": "block",
        "outbound_pii_policy": "standard",
        "max_execution_seconds": 600,
        "max_output_bytes": 131072,
    }


def test_put_sandbox_rejects_unknown_field(isolated_config: Path) -> None:
    client = TestClient(_make_app())
    response = client.put(
        "/api/settings/sandbox",
        json={"denied_patterns": [], "extra_field": "nope"},
    )
    assert response.status_code == 422


# ── Providers (Settings → Providers tab) ────────────────────────────────────


def test_list_providers_returns_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /providers returns one entry per catalog row with config state."""
    # Clear every known credential env var so the test is deterministic
    # regardless of the developer's local ``.env``.
    from app.agent.providers.catalog import PROVIDER_KEY_VAR, all_providers

    for var in PROVIDER_KEY_VAR.values():
        monkeypatch.delenv(var, raising=False)
    for entry in all_providers():
        for var in entry.get("env_vars", ()):
            monkeypatch.delenv(var, raising=False)

    # Stub the daemon probe so this test doesn't depend on whether
    # Ollama happens to be running on the developer's machine.
    async def _unreachable(_entry):  # type: ignore[no-untyped-def]
        return False

    monkeypatch.setattr(settings_routes, "_local_provider_reachable", _unreachable)

    app = _make_app()
    client = TestClient(app)
    response = client.get("/api/settings/providers")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data["providers"], list)
    assert len(data["providers"]) > 5  # we ship many
    ids = {p["id"] for p in data["providers"]}
    assert {"googlegenai", "openai", "openrouter", "copilot", "codex"} <= ids
    # Nothing configured → has_any_configured is exactly False.
    assert data["has_any_configured"] is False


def test_list_providers_marks_configured_when_env_var_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An env var with a value flips is_configured to True."""
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key-not-real")

    app = _make_app()
    client = TestClient(app)
    response = client.get("/api/settings/providers")
    assert response.status_code == 200
    data = response.json()
    google = next(p for p in data["providers"] if p["id"] == "googlegenai")
    assert google["is_configured"] is True
    assert data["has_any_configured"] is True


def test_list_providers_does_not_connect_to_ollama_automatically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Loading the catalog must not probe or discover models from Ollama."""
    probed: list[str] = []
    discovered: list[str] = []

    async def _reachable(entry):  # type: ignore[no-untyped-def]
        probed.append(entry["id"])
        return True

    async def _discover(entry, **_kwargs):  # type: ignore[no-untyped-def]
        discovered.append(entry["id"])
        return ["test-model"]

    monkeypatch.setattr(settings_routes, "_local_provider_reachable", _reachable)
    monkeypatch.setattr(
        "app.agent.providers.model_discovery.discover_provider_models", _discover
    )

    app = _make_app()
    client = TestClient(app)
    response = client.get("/api/settings/providers")

    assert response.status_code == 200
    ollama = next(p for p in response.json()["providers"] if p["id"] == "ollama")
    assert ollama["is_configured"] is False
    assert "ollama" not in probed
    assert "ollama" not in discovered


def test_list_providers_router9_requires_both_env_var_and_daemon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Local-proxy api_key providers need both a key AND a reachable daemon."""
    monkeypatch.delenv("ROUTER9_API_KEY", raising=False)

    probed: list[str] = []

    async def _spy(entry):  # type: ignore[no-untyped-def]
        probed.append(entry["id"])
        return True

    monkeypatch.setattr(settings_routes, "_local_provider_reachable", _spy)

    app = _make_app()
    client = TestClient(app)
    response = client.get("/api/settings/providers")

    assert response.status_code == 200
    router9 = next(p for p in response.json()["providers"] if p["id"] == "router9")
    # No env var → still not connected, and we never bothered to probe.
    assert router9["is_configured"] is False
    assert "router9" not in probed


def test_list_providers_marks_oauth_file_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OAuth providers persist token files directly under CACHE_DIR."""
    monkeypatch.setattr(settings_routes.settings, "EVOFLUX_CACHE_DIR", str(tmp_path))
    (tmp_path / "codex_oauth.json").write_text("{}", encoding="utf-8")

    app = _make_app()
    client = TestClient(app)
    response = client.get("/api/settings/providers")

    assert response.status_code == 200
    data = response.json()
    codex = next(p for p in data["providers"] if p["id"] == "codex")
    copilot = next(p for p in data["providers"] if p["id"] == "copilot")
    assert codex["is_configured"] is True
    assert copilot["is_configured"] is False


def test_test_provider_returns_404_for_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _make_app()
    client = TestClient(app)
    response = client.post(
        "/api/settings/providers/notreal/test",
        json={"api_key": "x", "model": "y"},
    )
    assert response.status_code == 404


def test_test_provider_reports_failure_without_crashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider chat error → 200 OK with ok=False rather than 500.

    The test endpoint catches every exception so the UI never has to
    distinguish "the test API itself broke" from "your key is wrong."
    """

    # Force a deterministic failure by stubbing build_provider — real
    # provider chat() behaviour varies by SDK version and would make this
    # test flaky against the live network.
    def _explode(*_args: object, **_kwargs: object) -> None:
        raise ValueError("synthetic auth failure")

    monkeypatch.setattr(settings_routes, "build_provider", None, raising=False)
    monkeypatch.setattr(
        "app.agent.providers.factory.build_provider", _explode, raising=True
    )

    app = _make_app()
    client = TestClient(app)
    response = client.post(
        "/api/settings/providers/googlegenai/test",
        json={"api_key": "ignored-because-stub", "model": "gemini-3-flash-preview"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert "synthetic auth failure" in (body["error"] or "")


def test_save_provider_writes_env_and_mutates_environ(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PUT /providers/{id} persists creds and mirrors them into os.environ."""
    # Redirect CONFIG_DIR to a temp dir so the test doesn't touch real config.
    monkeypatch.setattr(settings_routes.settings, "EVOFLUX_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    app = _make_app()
    client = TestClient(app)
    response = client.put(
        "/api/settings/providers/googlegenai",
        json={"api_key": "fresh-key-123"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["saved"] is True
    assert body["is_first_provider"] is True

    # .env should now contain the key.
    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "GOOGLE_API_KEY=fresh-key-123" in env_text

    # os.environ should be mutated so the next build_provider call works
    # without restarting the server.
    import os

    assert os.environ.get("GOOGLE_API_KEY") == "fresh-key-123"

    # A second save flips is_first_provider to False — the user is past
    # the initial setup so the frontend shouldn't trigger seed install
    # again.
    response2 = client.put(
        "/api/settings/providers/googlegenai",
        json={"api_key": "another-key"},
    )
    assert response2.status_code == 200
    assert response2.json()["is_first_provider"] is False


def test_save_provider_persists_base_url_extra(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Daemon providers can set an optional base URL via ``extra``.

    The value is written to ``.env`` alongside the API key and mirrored
    into ``os.environ`` so the next discovery call picks it up without a
    server restart. Clearing the field (empty string) deletes the line.
    """
    monkeypatch.setattr(settings_routes.settings, "EVOFLUX_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("ROUTER9_API_KEY", raising=False)
    monkeypatch.delenv("ROUTER9_BASE_URL", raising=False)

    app = _make_app()
    client = TestClient(app)
    response = client.put(
        "/api/settings/providers/router9",
        json={
            "api_key": "rk-123",
            "extra": {"ROUTER9_BASE_URL": "http://10.0.0.5:20128/v1"},
        },
    )
    assert response.status_code == 200
    assert response.json()["saved"] is True

    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "ROUTER9_API_KEY=rk-123" in env_text
    assert "ROUTER9_BASE_URL=http://10.0.0.5:20128/v1" in env_text

    import os

    assert os.environ.get("ROUTER9_BASE_URL") == "http://10.0.0.5:20128/v1"

    # Clearing the base URL on a subsequent save removes the line from
    # ``.env`` and pops the env var.
    response2 = client.put(
        "/api/settings/providers/router9",
        json={"api_key": "rk-123", "extra": {"ROUTER9_BASE_URL": ""}},
    )
    assert response2.status_code == 200
    env_text2 = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "ROUTER9_BASE_URL" not in env_text2
    assert os.environ.get("ROUTER9_BASE_URL") is None


def test_save_provider_base_url_only_preserves_existing_api_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Editing only the daemon base URL must not wipe a stored API key.

    The Settings UI keeps the key field blank after a successful save and
    re-sends ``api_key: ""`` when the user later changes ROUTER9_BASE_URL /
    CLIPROXY_BASE_URL. Empty used to mean "delete the key line".
    """
    monkeypatch.setattr(settings_routes.settings, "EVOFLUX_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("ROUTER9_API_KEY", raising=False)
    monkeypatch.delenv("ROUTER9_BASE_URL", raising=False)

    app = _make_app()
    client = TestClient(app)
    assert (
        client.put(
            "/api/settings/providers/router9",
            json={
                "api_key": "rk-keep-me",
                "extra": {"ROUTER9_BASE_URL": "http://127.0.0.1:20128/v1"},
            },
        ).status_code
        == 200
    )

    response = client.put(
        "/api/settings/providers/router9",
        json={
            "api_key": "",
            "extra": {"ROUTER9_BASE_URL": "http://10.0.0.5:20128/v1"},
        },
    )
    assert response.status_code == 200
    assert response.json()["saved"] is True

    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "ROUTER9_API_KEY=rk-keep-me" in env_text
    assert "ROUTER9_BASE_URL=http://10.0.0.5:20128/v1" in env_text

    import os

    assert os.environ.get("ROUTER9_API_KEY") == "rk-keep-me"
    assert os.environ.get("ROUTER9_BASE_URL") == "http://10.0.0.5:20128/v1"


def test_save_provider_supports_plugin_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Plugin providers persist declared credential fields, including extras."""
    from app.agent.providers.plugin_registry import clear_provider_plugin_cache

    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / "sample_provider.py").write_text(
        """
from app.agent.providers.base import LLMProviderBase
from app.agent.providers.plugin_api import ProviderPlugin, ProviderCredentialField

class DummyProvider(LLMProviderBase):
    async def chat(self, messages, tools=None, **kwargs):
        raise AssertionError('not used')
    async def stream(self, messages, tools=None, **kwargs):
        if False:
            yield None

provider = ProviderPlugin(
    id='sample',
    label='Sample',
    description='Synthetic provider.',
    kind='api_key',
    credentials=[
        ProviderCredentialField(name='SAMPLE_KEY', label='Sample key'),
        ProviderCredentialField(name='SAMPLE_BASE_URL', label='Base URL', secret=False, required=False),
    ],
    factory=lambda ctx: DummyProvider(),
)
""".lstrip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings_routes.settings, "EVOFLUX_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(
        settings_routes.settings, "EVOFLUX_PLUGINS_DIRS", str(plugin_dir)
    )
    monkeypatch.delenv("SAMPLE_KEY", raising=False)
    monkeypatch.delenv("SAMPLE_BASE_URL", raising=False)
    clear_provider_plugin_cache()

    try:
        client = TestClient(_make_app())
        response = client.put(
            "/api/settings/providers/sample",
            json={
                "api_key": "sk-test",
                "extra": {"SAMPLE_BASE_URL": "https://local.test/v1"},
            },
        )

        assert response.status_code == 200
        assert response.json()["saved"] is True
        env_text = (tmp_path / ".env").read_text(encoding="utf-8")
        assert "SAMPLE_KEY=sk-test" in env_text
        assert "SAMPLE_BASE_URL=https://local.test/v1" in env_text

        listed = client.get("/api/settings/providers")
        sample = next(p for p in listed.json()["providers"] if p["id"] == "sample")
        assert sample["is_configured"] is True
        # The UI can restore safe connection details, but never the API key.
        assert sample["saved_credentials"] == {
            "SAMPLE_BASE_URL": "https://local.test/v1"
        }
        assert [field["name"] for field in sample["credentials"]] == [
            "SAMPLE_KEY",
            "SAMPLE_BASE_URL",
        ]
    finally:
        clear_provider_plugin_cache()


def test_save_provider_404_for_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _make_app()
    client = TestClient(app)
    response = client.put(
        "/api/settings/providers/notreal",
        json={"api_key": "x"},
    )
    assert response.status_code == 404


def test_install_seed_defaults_calls_seed_installer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings_routes.settings, "EVOFLUX_CONFIG_DIR", str(tmp_path))
    install_seed = Mock(
        return_value=SeedResult(
            agents_written=["evoflux.md"],
            skills_written=["self-healing"],
            configs_written=["mcp.json"],
            agents_removed=["consultant.md"],
            source="local",
        )
    )
    monkeypatch.setattr("app.cli.seed.install_seed", install_seed)

    app = _make_app()
    client = TestClient(app)
    response = client.post(
        "/api/settings/seed",
        json={"provider_model": "googlegenai:gemini-3-flash-preview"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "agents_written": ["evoflux.md"],
        "skills_written": ["self-healing"],
        "configs_written": ["mcp.json"],
        "agents_removed": ["consultant.md"],
        "source": "local",
    }
    install_seed.assert_called_once_with(
        tmp_path, provider_model="googlegenai:gemini-3-flash-preview"
    )


def test_install_seed_defaults_reports_download_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings_routes.settings, "EVOFLUX_CONFIG_DIR", str(tmp_path))

    def _fail(*_args: object, **_kwargs: object) -> None:
        raise SeedDownloadError("offline")

    monkeypatch.setattr("app.cli.seed.install_seed", _fail)

    app = _make_app()
    client = TestClient(app)
    response = client.post(
        "/api/settings/seed",
        json={"provider_model": "googlegenai:gemini-3-flash-preview"},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "offline"


@pytest.mark.parametrize("body", [{}, {"provider_model": None}, {"provider_model": ""}])
def test_install_seed_defaults_accepts_empty_model(
    body: dict[str, str | None], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings_routes.settings, "EVOFLUX_CONFIG_DIR", str(tmp_path))
    install_seed = Mock(
        return_value=SeedResult(
            agents_written=[],
            skills_written=[],
            configs_written=[],
            agents_removed=[],
            source="local",
        )
    )
    monkeypatch.setattr("app.cli.seed.install_seed", install_seed)

    app = _make_app()
    client = TestClient(app)
    response = client.post("/api/settings/seed", json=body)

    assert response.status_code == 200
    install_seed.assert_called_once_with(tmp_path, provider_model="__PROVIDER_MODEL__")


def test_install_seed_defaults_rejects_invalid_model() -> None:
    app = _make_app()
    client = TestClient(app)
    response = client.post("/api/settings/seed", json={"provider_model": "gpt-5"})

    assert response.status_code == 422


# ── Daemon reachability probe ───────────────────────────────────────────────


def test_local_provider_reachable_uses_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two probes within the TTL hit the cache instead of re-issuing HTTP."""
    import asyncio

    from app.agent.providers.catalog import find

    entry = find("ollama")
    assert entry is not None

    call_count = 0

    class _FakeResponse:
        status_code = 200

    class _FakeClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _url):
            nonlocal call_count
            call_count += 1
            return _FakeResponse()

    monkeypatch.setattr(settings_routes.httpx, "AsyncClient", _FakeClient)
    monkeypatch.setattr(settings_routes.settings, "OLLAMA_BASE_URL", "http://x:1")

    first = asyncio.get_event_loop().run_until_complete(
        settings_routes._local_provider_reachable(entry)
    )
    second = asyncio.get_event_loop().run_until_complete(
        settings_routes._local_provider_reachable(entry)
    )
    assert first is True
    assert second is True
    assert call_count == 1


def test_local_provider_reachable_swallows_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Connection refused / timeout → False (no exception bubbles up)."""
    import asyncio

    import httpx

    from app.agent.providers.catalog import find

    entry = find("ollama")
    assert entry is not None

    class _BoomClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _url):
            raise httpx.ConnectError("daemon down")

    monkeypatch.setattr(settings_routes.httpx, "AsyncClient", _BoomClient)
    monkeypatch.setattr(settings_routes.settings, "OLLAMA_BASE_URL", "http://x:1")

    result = asyncio.get_event_loop().run_until_complete(
        settings_routes._local_provider_reachable(entry)
    )
    assert result is False


# ── POST /providers/{id}/models ─────────────────────────────────────────────


def test_list_provider_models_returns_404_for_unknown() -> None:
    app = _make_app()
    client = TestClient(app)
    response = client.post(
        "/api/settings/providers/notreal/models",
        json={"api_key": "x"},
    )
    assert response.status_code == 404


def test_list_provider_models_returns_empty_when_discovery_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The settings model-list endpoint should not mask failed live discovery
    with curated fallback models.
    """

    async def _empty(_entry, **_kwargs):  # type: ignore[no-untyped-def]
        return []

    monkeypatch.setattr(
        "app.agent.providers.model_discovery.discover_provider_models", _empty
    )

    app = _make_app()
    client = TestClient(app)
    response = client.post(
        "/api/settings/providers/vertexai/models",
        json={"extra": {"VERTEXAI_API_KEY": "bad-key"}},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "provider"
    assert body["models"] == []


def test_list_provider_models_returns_discovered_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When discovery succeeds, response carries source='provider' with a flat
    list of model IDs (no per-model capability data — see techdebts/model-
    capabilities-registry.md for why)."""

    async def _two_models(_entry, **_kwargs):  # type: ignore[no-untyped-def]
        return ["model-a", "model-b"]

    monkeypatch.setattr(
        "app.agent.providers.model_discovery.discover_provider_models", _two_models
    )

    app = _make_app()
    client = TestClient(app)
    response = client.post(
        "/api/settings/providers/openai/models",
        json={"api_key": "fake"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "openai"
    assert body["source"] == "provider"
    assert body["models"] == ["model-a", "model-b"]


def test_list_provider_models_filters_explicit_non_agent_capabilities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _mixed_models(_entry, **_kwargs):  # type: ignore[no-untyped-def]
        return [
            "gemini-3.5-flash",
            "davinci-002",
            "gpt-audio-mini",
            "veo-3.1-generate-preview",
            "imagen-4",
            "lyria-002",
            "nano-banana",
            "sora-2",
            "gemini-3.1-flash-image-preview",
            "text-embedding-3-small",
        ]

    monkeypatch.setattr(
        "app.agent.providers.model_discovery.discover_provider_models", _mixed_models
    )
    monkeypatch.setattr(
        "app.agent.providers.model_discovery.get_capabilities",
        lambda model_id: SimpleNamespace(
            output=SimpleNamespace(text=model_id.endswith("gemini-3.5-flash"))
        ),
    )
    monkeypatch.setattr(
        "app.agent.providers.model_discovery.get_model_features",
        lambda _model_id: SimpleNamespace(tool_call=None),
    )

    app = _make_app()
    client = TestClient(app)
    response = client.post(
        "/api/settings/providers/googlegenai/models",
        json={"api_key": "fake"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "provider"
    assert body["models"] == ["gemini-3.5-flash"]


def test_list_provider_models_does_not_mutate_os_environ(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The /models endpoint must thread credentials via overrides, not env."""
    import os

    sentinel = "PROBE_ENV_VALUE_BEFORE_REQUEST"
    monkeypatch.setenv("OPENAI_API_KEY", sentinel)

    captured: dict[str, object] = {}

    async def _spy(_entry, **kwargs):  # type: ignore[no-untyped-def]
        captured["overrides"] = kwargs.get("overrides")
        captured["env_during"] = os.environ.get("OPENAI_API_KEY")
        return []

    monkeypatch.setattr(
        "app.agent.providers.model_discovery.discover_provider_models", _spy
    )

    app = _make_app()
    client = TestClient(app)
    response = client.post(
        "/api/settings/providers/openai/models",
        json={"api_key": "candidate-key"},
    )

    assert response.status_code == 200
    # os.environ stayed untouched — only the overrides dict carried the key.
    assert os.environ.get("OPENAI_API_KEY") == sentinel
    assert captured["env_during"] == sentinel
    assert captured["overrides"] == {"OPENAI_API_KEY": "candidate-key"}


def test_get_codex_provider_usage_returns_active_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import time

    oauth = CodexOAuth(
        access_token=SecretStr("chatgpt-token"),
        refresh_token=SecretStr("refresh-token"),
        expires_at=time.time() + 3600,
        account_id="account-123",
    )
    monkeypatch.setattr(
        "app.agent.providers.codex.oauth.CodexOAuth.load", lambda: oauth
    )

    captured: dict[str, object] = {}

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "plan_type": "pro",
                "rate_limit": {
                    "primary_window": {
                        "used_percent": 42,
                        "limit_window_seconds": 3600,
                        "reset_at": 1_735_689_720,
                    },
                    "secondary_window": {
                        "used_percent": 5,
                        "limit_window_seconds": 86400,
                        "reset_at": 1_735_776_000,
                    },
                },
                "credits": {
                    "has_credits": True,
                    "unlimited": False,
                    "balance": "9.99",
                },
                "rate_limit_reached_type": {
                    "type": "workspace_member_usage_limit_reached"
                },
                "additional_rate_limits": [
                    {
                        "limit_name": "codex_other",
                        "metered_feature": "codex_other",
                        "rate_limit": {
                            "primary_window": {
                                "used_percent": 88,
                                "limit_window_seconds": 1800,
                                "reset_at": 1_735_693_200,
                            }
                        },
                    }
                ],
            }

    class _FakeClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url, *, headers):  # type: ignore[no-untyped-def]
            captured["url"] = url
            captured["headers"] = headers
            return _FakeResponse()

    monkeypatch.setattr(codex_usage.httpx, "AsyncClient", _FakeClient)

    client = TestClient(_make_app())
    response = client.get("/api/settings/providers/codex/usage")

    assert response.status_code == 200
    assert captured["url"] == "https://chatgpt.com/backend-api/wham/usage"
    assert captured["headers"] == {
        "Authorization": "Bearer chatgpt-token",
        "Accept": "application/json",
        "User-Agent": "EvoFlux/1.0.0",
        "originator": "EvoFlux",
        "ChatGPT-Account-Id": "account-123",
    }
    body = response.json()
    assert body["provider"] == "codex"
    assert body["limits"][0]["limit_id"] == "codex"
    assert body["limits"][0]["primary"] == {
        "used_percent": 42.0,
        "window_minutes": 60,
        "resets_at": 1_735_689_720,
    }
    assert body["limits"][0]["secondary"]["window_minutes"] == 1440
    assert body["limits"][0]["credits"]["balance"] == "9.99"
    assert (
        body["limits"][0]["rate_limit_reached_type"]
        == "workspace_member_usage_limit_reached"
    )
    assert body["limits"][1]["limit_id"] == "codex_other"
    assert body["limits"][1]["primary"]["used_percent"] == 88.0


def test_get_codex_provider_usage_returns_unlimited_credits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import time

    oauth = CodexOAuth(
        access_token=SecretStr("chatgpt-token"),
        refresh_token=SecretStr("refresh-token"),
        expires_at=time.time() + 3600,
        account_id="account-123",
    )
    monkeypatch.setattr(
        "app.agent.providers.codex.oauth.CodexOAuth.load", lambda: oauth
    )

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "plan_type": "business",
                "rate_limit": None,
                "additional_rate_limits": None,
                "credits": {
                    "has_credits": True,
                    "unlimited": True,
                    "balance": None,
                    "overage_limit_reached": False,
                    "approx_local_messages": None,
                    "approx_cloud_messages": None,
                },
                "rate_limit_reached_type": None,
            }

    class _FakeClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _url, *, headers):  # type: ignore[no-untyped-def]
            return _FakeResponse()

    monkeypatch.setattr(codex_usage.httpx, "AsyncClient", _FakeClient)

    client = TestClient(_make_app())
    response = client.get("/api/settings/providers/codex/usage")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "provider": "codex",
        "limits": [
            {
                "limit_id": "codex",
                "limit_name": None,
                "primary": None,
                "secondary": None,
                "credits": {
                    "has_credits": True,
                    "unlimited": True,
                    "balance": None,
                },
                "plan_type": "business",
                "rate_limit_reached_type": None,
            }
        ],
    }


def test_get_copilot_provider_usage_returns_premium_quota_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oauth = CopilotOAuth(github_token=SecretStr("github-token"))
    monkeypatch.setattr(
        "app.agent.providers.copilot.oauth.CopilotOAuth.load", lambda: oauth
    )

    captured: dict[str, object] = {}

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "copilot_plan": "individual",
                "quota_reset_date_utc": "2026-06-01T00:00:00.000Z",
                "quota_snapshots": {
                    "chat": {
                        "quota_id": "chat",
                        "percent_remaining": 100.0,
                        "remaining": 0,
                        "entitlement": 0,
                        "unlimited": True,
                        "quota_reset_at": 0,
                    },
                    "premium_interactions": {
                        "quota_id": "premium_interactions",
                        "percent_remaining": 85.6,
                        "remaining": 257,
                        "entitlement": 300,
                        "unlimited": False,
                        "quota_reset_at": 0,
                    },
                },
            }

    class _FakeClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url, *, headers):  # type: ignore[no-untyped-def]
            captured["url"] = url
            captured["headers"] = headers
            return _FakeResponse()

    monkeypatch.setattr(copilot_usage.httpx, "AsyncClient", _FakeClient)

    client = TestClient(_make_app())
    response = client.get("/api/settings/providers/copilot/usage")

    assert response.status_code == 200
    assert captured["url"] == "https://api.github.com/copilot_internal/user"
    assert captured["headers"] == {
        "Authorization": "token github-token",
        "Accept": "application/json",
        "User-Agent": "EvoFlux/1.0.0",
    }
    body = response.json()
    assert body["provider"] == "copilot"
    assert body["limits"][0] == {
        "limit_id": "premium_interactions",
        "limit_name": "Premium requests",
        "primary": {
            "used_percent": pytest.approx(14.4),
            "window_minutes": None,
            "resets_at": 1780272000,
        },
        "secondary": None,
        "credits": {"has_credits": True, "unlimited": False, "balance": "257/300"},
        "plan_type": "individual",
        "rate_limit_reached_type": None,
    }


def test_get_provider_usage_rejects_unsupported_provider() -> None:
    client = TestClient(_make_app())
    response = client.get("/api/settings/providers/openai/usage")
    assert response.status_code == 404


def test_provider_configuration_reads_saved_config_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.agent.providers.catalog import find

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(settings_routes.settings, "EVOFLUX_CONFIG_DIR", str(tmp_path))
    (tmp_path / ".env").write_text("OPENAI_API_KEY=saved-key\n", encoding="utf-8")

    entry = find("openai")
    assert entry is not None
    assert settings_routes._provider_is_configured(entry) is True


def test_save_provider_visible_models_writes_runtime_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(settings_routes.settings, "EVOFLUX_CONFIG_DIR", str(tmp_path))

    app = _make_app()
    client = TestClient(app)
    response = client.put(
        "/api/settings/providers/openai/visible-models",
        json={"models": ["gpt-5.1", "gpt-5.1-mini", "gpt-5.1"]},
    )

    assert response.status_code == 200
    assert response.json() == {
        "provider": "openai",
        "visible_models": ["gpt-5.1", "gpt-5.1-mini"],
    }
    assert "visible_models" in (tmp_path / "settings.yaml").read_text(encoding="utf-8")


def test_version_control_settings_round_trip(tmp_path, monkeypatch):
    from app.api.app import create_app
    from app.core.config import settings

    monkeypatch.setattr(settings, "EVOFLUX_CONFIG_DIR", str(tmp_path))
    client = TestClient(create_app())
    defaults = client.get("/api/settings/version-control")

    assert defaults.status_code == 200
    assert defaults.json()["default_pull_strategy"] == "ff_only"
    assert defaults.json()["allow_force_push"] is False

    payload = {
        **defaults.json(),
        "network_timeout_seconds": 240,
        "default_pull_strategy": "rebase",
        "allow_force_push": True,
        "review_retry_attempts": 3,
        "review_max_concurrent_repositories": 6,
    }
    updated = client.put("/api/settings/version-control", json=payload)

    assert updated.status_code == 200
    assert updated.json() == payload
    written = (tmp_path / "settings.yaml").read_text(encoding="utf-8")
    assert "default_pull_strategy: rebase" in written
    assert "max_concurrent_repositories: 6" in written


def test_webbridge_settings_round_trip(tmp_path, monkeypatch):
    from app.api.app import create_app
    from app.core.config import settings

    monkeypatch.setattr(settings, "EVOFLUX_CONFIG_DIR", str(tmp_path))
    client = TestClient(create_app())
    defaults = client.get("/api/settings/webbridge")

    assert defaults.status_code == 200
    assert defaults.json()["enabled"] is True
    assert defaults.json()["allow_evaluate"] is True

    payload = {"enabled": False, "allow_evaluate": False}
    updated = client.put("/api/settings/webbridge", json=payload)

    assert updated.status_code == 200
    assert updated.json() == payload
    written = (tmp_path / "settings.yaml").read_text(encoding="utf-8")
    assert "enabled: false" in written
    assert "allow_evaluate: false" in written

    reread = client.get("/api/settings/webbridge")
    assert reread.status_code == 200
    assert reread.json() == payload


def test_save_provider_visible_models_rejects_unknown_provider() -> None:
    app = _make_app()
    client = TestClient(app)
    response = client.put(
        "/api/settings/providers/notreal/visible-models",
        json={"models": ["x"]},
    )

    assert response.status_code == 404


# ── /agents/registry — concurrent + cached discovery ────────────────────────


def test_registry_skips_unconfigured_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    """Discovery only runs for providers the user has actually configured."""
    from fastapi import FastAPI

    from app.api.routes.agents import router as agents_router

    # Force every provider to look unconfigured.
    monkeypatch.setattr(
        "app.api.routes.settings._provider_is_configured", lambda _entry: False
    )

    call_count = 0

    async def _spy(_entry, **_kwargs):  # type: ignore[no-untyped-def]
        nonlocal call_count
        call_count += 1
        return []

    monkeypatch.setattr("app.api.routes.agents.discover_provider_models", _spy)

    app = FastAPI()
    app.include_router(agents_router, prefix="/api/agents")
    client = TestClient(app)
    response = client.get("/api/agents/registry")

    assert response.status_code == 200
    assert call_count == 0


def test_manual_ollama_connection_populates_registry_without_reconnecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the explicit model-list request may contact local Ollama."""
    from fastapi import FastAPI

    from app.api.routes import agents as agents_module
    from app.api.routes.agents import router as agents_router

    settings_routes._provider_model_cache.clear()
    agents_module._registry_model_cache.clear()
    calls: list[str] = []

    async def _discover(entry, **_kwargs):  # type: ignore[no-untyped-def]
        calls.append(entry["id"])
        return ["llama3.2"]

    monkeypatch.setattr(
        "app.agent.providers.model_discovery.discover_provider_models", _discover
    )
    monkeypatch.setattr(agents_module, "discover_provider_models", _discover)
    monkeypatch.setattr(
        settings_routes,
        "_provider_is_configured",
        lambda entry: entry["id"] == "ollama",
    )

    app = FastAPI()
    app.include_router(router, prefix="/api/settings")
    app.include_router(agents_router, prefix="/api/agents")
    client = TestClient(app)

    initial_registry = client.get("/api/agents/registry")
    assert initial_registry.status_code == 200
    assert calls == []

    listed = client.post("/api/settings/providers/ollama/models", json={})
    registry = client.get("/api/agents/registry")

    assert listed.status_code == 200
    assert registry.status_code == 200
    assert calls == ["ollama"]
    assert "ollama:llama3.2" in {m["id"] for m in registry.json()["models"]}


def test_registry_caches_discovery_within_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two calls in the same TTL window invoke discovery just once per provider."""
    from fastapi import FastAPI

    from app.api.routes import agents as agents_module
    from app.api.routes.agents import router as agents_router

    # Reset the module-level cache so prior tests don't taint the count.
    agents_module._registry_model_cache.clear()

    monkeypatch.setattr(
        "app.api.routes.settings._provider_is_configured",
        lambda entry: entry["id"] == "openai",
    )

    call_count = 0

    async def _spy(_entry, **_kwargs):  # type: ignore[no-untyped-def]
        nonlocal call_count
        call_count += 1
        return ["only-model"]

    monkeypatch.setattr("app.api.routes.agents.discover_provider_models", _spy)

    app = FastAPI()
    app.include_router(agents_router, prefix="/api/agents")
    client = TestClient(app)

    client.get("/api/agents/registry")
    client.get("/api/agents/registry")

    assert call_count == 1


def test_registry_discovery_uses_saved_config_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from fastapi import FastAPI

    from app.api.routes import agents as agents_module
    from app.api.routes.agents import router as agents_router

    agents_module._registry_model_cache.clear()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(settings_routes.settings, "EVOFLUX_CONFIG_DIR", str(tmp_path))
    (tmp_path / ".env").write_text("OPENAI_API_KEY=saved-key\n", encoding="utf-8")
    monkeypatch.setattr(
        "app.api.routes.settings._provider_is_configured",
        lambda entry: entry["id"] == "openai",
    )

    captured: dict[str, object] = {}

    async def _spy(_entry, **kwargs):  # type: ignore[no-untyped-def]
        captured["overrides"] = kwargs.get("overrides")
        return ["saved-model"]

    monkeypatch.setattr("app.api.routes.agents.discover_provider_models", _spy)

    app = FastAPI()
    app.include_router(agents_router, prefix="/api/agents")
    client = TestClient(app)

    response = client.get("/api/agents/registry")

    assert response.status_code == 200
    assert captured["overrides"] == {"OPENAI_API_KEY": "saved-key"}
    assert "openai:saved-model" in {m["id"] for m in response.json()["models"]}


def test_registry_filters_provider_visible_models(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from fastapi import FastAPI

    from app.api.routes import agents as agents_module
    from app.api.routes.agents import router as agents_router
    from app.core.runtime_settings import RuntimeSettings, save_runtime_settings

    agents_module._registry_model_cache.clear()
    monkeypatch.setattr(settings_routes.settings, "EVOFLUX_CONFIG_DIR", str(tmp_path))
    save_runtime_settings(
        RuntimeSettings(providers={"openai": {"visible_models": ["shown"]}})
    )
    monkeypatch.setattr(
        "app.api.routes.settings._provider_is_configured",
        lambda entry: entry["id"] == "openai",
    )

    async def _spy(_entry, **_kwargs):  # type: ignore[no-untyped-def]
        return ["shown", "hidden"]

    monkeypatch.setattr("app.api.routes.agents.discover_provider_models", _spy)

    app = FastAPI()
    app.include_router(agents_router, prefix="/api/agents")
    client = TestClient(app)
    response = client.get("/api/agents/registry")

    assert response.status_code == 200
    ids = {m["id"] for m in response.json()["models"]}
    assert "openai:shown" in ids
    assert "openai:hidden" not in ids


def test_registry_survives_discovery_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """A discovery exception per provider must not break the whole registry."""
    from fastapi import FastAPI

    from app.api.routes import agents as agents_module
    from app.api.routes.agents import router as agents_router

    agents_module._registry_model_cache.clear()

    monkeypatch.setattr(
        "app.api.routes.settings._provider_is_configured", lambda _entry: True
    )

    async def _raise(_entry, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("provider unreachable")

    monkeypatch.setattr("app.api.routes.agents.discover_provider_models", _raise)

    app = FastAPI()
    app.include_router(agents_router, prefix="/api/agents")
    client = TestClient(app)
    response = client.get("/api/agents/registry")

    # Registry endpoint stays healthy even when every provider's discovery raises.
    # Failed discovery is not masked by catalog fallbacks, so no provider models
    # are added without a working live discovery call.
    assert response.status_code == 200
    assert response.json()["models"] == []


def test_build_overrides_skips_blank_candidate_values() -> None:
    """A blank form field must not clobber a saved credential.

    The cloud_creds UI echoes non-secret values but leaves saved secrets
    empty; discovery merges these overrides over the saved ones, so empty
    strings would erase the saved API key and fail verification.
    """
    from app.agent.providers.catalog import find

    entry = find("foundry")
    assert entry is not None

    overrides = settings_routes._build_overrides(
        entry, "", {"FOUNDRY_RESOURCE_NAME": "evollm", "FOUNDRY_API_KEY": ""}
    )

    assert overrides == {"FOUNDRY_RESOURCE_NAME": "evollm"}
