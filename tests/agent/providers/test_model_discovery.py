from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from app.agent.providers.model_discovery import (
    _bedrock_models,
    _entry_from_openai_catalog_item,
)


def test_model_filter_uses_capabilities_not_name_markers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agent.providers import model_discovery

    monkeypatch.setattr(
        model_discovery,
        "get_capabilities",
        lambda model_id: SimpleNamespace(
            output=SimpleNamespace(text=model_id != "custom:explicit-image")
        ),
    )
    monkeypatch.setattr(
        model_discovery,
        "get_model_features",
        lambda _model_id: SimpleNamespace(tool_call=None),
    )

    result = model_discovery.filter_agent_model_ids(
        "custom",
        ["explicit-image", "unknown-image-name", "chat"],
    )

    assert result == ["unknown-image-name", "chat"]


def test_model_filter_rejects_explicit_no_tool_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agent.providers import model_discovery

    monkeypatch.setattr(
        model_discovery,
        "get_capabilities",
        lambda _model_id: SimpleNamespace(output=SimpleNamespace(text=True)),
    )
    monkeypatch.setattr(
        model_discovery,
        "get_model_features",
        lambda model_id: SimpleNamespace(tool_call=model_id != "custom:completion"),
    )

    assert model_discovery.filter_agent_model_ids(
        "custom", ["completion", "agent"]
    ) == ["agent"]


def test_rich_openai_catalog_item_preserves_provider_contract() -> None:
    model = _entry_from_openai_catalog_item(
        {
            "id": "vendor/reasoning-model",
            "context_length": 200_000,
            "architecture": {
                "input_modalities": ["text", "image"],
                "output_modalities": ["text"],
            },
            "supported_parameters": ["tools", "temperature", "reasoning"],
            "top_provider": {"max_completion_tokens": 64_000},
            "reasoning": {
                "mandatory": False,
                "default_enabled": True,
                "supported_efforts": ["high", "low"],
                "default_effort": "high",
            },
        }
    )

    assert model is not None
    assert model.capabilities["input"]["vision"] is True
    assert model.metadata["limits"] == {
        "context_length": 200_000,
        "max_completion_tokens": 64_000,
    }
    assert model.metadata["thinking"]["levels"] == ["high", "low", "none"]
    assert model.metadata["thinking"]["source"] == "provider_live"


class _BedrockClient:
    def list_foundation_models(self, **kwargs):
        assert kwargs == {"byOutputModality": "TEXT"}
        return {
            "modelSummaries": [
                {"modelId": "anthropic.claude-sonnet-4-6"},
                {"modelId": "amazon.nova-pro-v1:0"},
            ]
        }

    def list_inference_profiles(self, **kwargs):
        assert kwargs["typeEquals"] in {"SYSTEM_DEFINED", "APPLICATION"}
        assert kwargs["maxResults"] == 1000
        if kwargs["typeEquals"] == "SYSTEM_DEFINED":
            return {
                "inferenceProfileSummaries": [
                    {
                        "inferenceProfileId": "global.anthropic.claude-sonnet-4-6",
                        "status": "ACTIVE",
                    }
                ]
            }
        return {
            "inferenceProfileSummaries": [
                {
                    "inferenceProfileId": "my-serverless-profile",
                    "type": "APPLICATION",
                    "status": "ACTIVE",
                },
                {
                    "inferenceProfileId": "inactive-profile",
                    "type": "APPLICATION",
                    "status": "DELETING",
                },
            ]
        }


@pytest.mark.asyncio
async def test_bedrock_models_include_foundation_and_inference_profiles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _BedrockClient()
    monkeypatch.setitem(
        sys.modules,
        "boto3",
        SimpleNamespace(client=lambda *args, **kwargs: client),
    )

    models = await _bedrock_models(
        {"AWS_BEDROCK_REGION": "us-east-1", "AWS_BEDROCK_PROFILE": ""}
    )

    assert [model.id for model in models] == [
        "amazon.nova-pro-v1:0",
        "anthropic.claude-sonnet-4-6",
        "global.anthropic.claude-sonnet-4-6",
        "my-serverless-profile",
    ]


class _FakeFoundryResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeFoundryClient:
    """Serves the legacy deployments route; 404s everything else."""

    calls: list[tuple[str, dict | None, dict | None]] = []

    def __init__(self, *_args, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get(self, url, params=None, headers=None):
        import httpx

        type(self).calls.append((url, params, headers))
        if url.endswith("/openai/deployments"):
            return _FakeFoundryResponse(
                {
                    "object": "list",
                    "data": [
                        {"id": "claude-sonnet-5", "object": "deployment"},
                        {"id": "my-gpt-deploy", "object": "deployment"},
                    ],
                }
            )
        raise httpx.HTTPStatusError("404", request=None, response=None)


class _FakeFoundryCatalogOnlyClient(_FakeFoundryClient):
    """Deployments route retired — only the v1 catalog answers."""

    calls: list[tuple[str, dict | None, dict | None]] = []

    async def get(self, url, params=None, headers=None):
        import httpx

        type(self).calls.append((url, params, headers))
        if url.endswith("/openai/v1/models"):
            return _FakeFoundryResponse(
                {"object": "list", "data": [{"id": "gpt-5.1"}, {"id": "grok-4.3"}]}
            )
        raise httpx.HTTPStatusError("404", request=None, response=None)


class _FakeCodexModelsClient:
    def __init__(self, *_args, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get(self, url, params=None, headers=None):
        assert url == "https://chatgpt.com/backend-api/codex/models"
        assert params == {"client_version": "1.0.0"}
        assert headers["Authorization"] == "Bearer test-token"
        return _FakeFoundryResponse(
            {
                "models": [
                    {
                        "slug": "gpt-5.6-sol",
                        "visibility": "list",
                        "supported_in_api": True,
                        "context_window": 272_000,
                        "max_context_window": 272_000,
                        "input_modalities": ["text", "image"],
                        "default_reasoning_level": "medium",
                        "supports_parallel_tool_calls": True,
                        "supported_reasoning_levels": [
                            {"effort": "low"},
                            {"effort": "medium"},
                            {"effort": "high"},
                            {"effort": "xhigh"},
                            {"effort": "max"},
                            {"effort": "ultra"},
                        ],
                    },
                    {
                        "slug": "gpt-5.6-luna",
                        "visibility": "list",
                        "supported_in_api": True,
                        "context_window": 272_000,
                        "input_modalities": ["text", "image"],
                        "default_reasoning_level": "medium",
                        "supports_parallel_tool_calls": True,
                        "supported_reasoning_levels": [
                            {"effort": "low"},
                            {"effort": "medium"},
                            {"effort": "high"},
                            {"effort": "xhigh"},
                            {"effort": "max"},
                        ],
                    },
                    {
                        "slug": "codex-auto-review",
                        "visibility": "hide",
                        "supported_in_api": True,
                        "context_window": 272_000,
                        "input_modalities": ["text", "image"],
                        "supported_reasoning_levels": [{"effort": "medium"}],
                    },
                    {
                        "slug": "retired-codex-model",
                        "visibility": "list",
                        "supported_in_api": False,
                        "context_window": 272_000,
                        "input_modalities": ["text"],
                        "supported_reasoning_levels": [{"effort": "medium"}],
                    },
                ]
            }
        )


@pytest.mark.asyncio
async def test_codex_discovery_registers_live_reasoning_levels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agent.providers import model_discovery
    from app.agent.providers.catalog import find
    from app.agent.providers.codex.oauth import CodexOAuth
    from app.agent.providers.model_metadata import (
        clear_runtime_model_metadata,
        get_model_limits,
        get_model_metadata,
        get_model_thinking_levels,
        has_runtime_model_metadata,
        set_runtime_model_metadata,
    )
    from app.agent.providers.capabilities import (
        clear_runtime_model_capabilities,
        get_capabilities,
    )

    oauth = SimpleNamespace(
        access_token=SimpleNamespace(get_secret_value=lambda: "test-token"),
        account_id="account-1",
        is_expired=lambda: False,
    )
    monkeypatch.setattr(CodexOAuth, "load", classmethod(lambda _cls: oauth))
    monkeypatch.setattr(model_discovery.httpx, "AsyncClient", _FakeCodexModelsClient)
    monkeypatch.setattr(model_discovery, "is_agent_model_id", lambda *_args: True)
    entry = find("codex")
    assert entry is not None

    clear_runtime_model_metadata()
    try:
        set_runtime_model_metadata(
            "codex:removed-model", {"thinking": {"levels": ["high"]}}
        )
        models = await model_discovery.discover_provider_model_entries(entry)

        assert [model.id for model in models] == ["gpt-5.6-luna", "gpt-5.6-sol"]
        assert has_runtime_model_metadata("codex:removed-model") is False
        assert get_model_thinking_levels("codex:gpt-5.6-sol") == (
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
            "ultra",
        )
        assert get_model_thinking_levels("codex:gpt-5.6-luna") == (
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
        )
        assert get_model_limits("codex:gpt-5.6-sol").context_length == 272_000
        assert (
            get_model_metadata("codex:gpt-5.6-sol").thinking.default_level == "medium"
        )
        assert get_model_metadata("codex:gpt-5.6-sol").features.tool_call is True
        assert get_capabilities("codex:gpt-5.6-sol").input.vision is True
    finally:
        clear_runtime_model_metadata()
        clear_runtime_model_capabilities()


@pytest.mark.asyncio
async def test_foundry_models_prefer_deployments_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agent.providers import model_discovery
    from app.agent.providers.catalog import find

    _FakeFoundryClient.calls = []
    monkeypatch.setattr(model_discovery.httpx, "AsyncClient", _FakeFoundryClient)
    entry = find("foundry")
    assert entry is not None

    models = await model_discovery.discover_provider_models(
        entry,
        overrides={"FOUNDRY_API_KEY": "key-123", "FOUNDRY_RESOURCE_NAME": "myres"},
    )

    assert models == ["claude-sonnet-5", "my-gpt-deploy"]
    url, params, headers = _FakeFoundryClient.calls[0]
    assert url == "https://myres.services.ai.azure.com/openai/deployments"
    assert params == {"api-version": "2023-03-15-preview"}
    assert headers == {"Authorization": "Bearer key-123", "api-key": "key-123"}


@pytest.mark.asyncio
async def test_foundry_models_fall_back_to_v1_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agent.providers import model_discovery
    from app.agent.providers.catalog import find

    _FakeFoundryCatalogOnlyClient.calls = []
    monkeypatch.setattr(
        model_discovery.httpx, "AsyncClient", _FakeFoundryCatalogOnlyClient
    )
    entry = find("foundry")
    assert entry is not None

    models = await model_discovery.discover_provider_models(
        entry,
        overrides={"FOUNDRY_API_KEY": "key-123", "FOUNDRY_RESOURCE_NAME": "myres"},
    )

    assert models == ["gpt-5.1", "grok-4.3"]
    urls = [call[0] for call in _FakeFoundryCatalogOnlyClient.calls]
    assert urls == [
        "https://myres.services.ai.azure.com/openai/deployments",
        "https://myres.services.ai.azure.com/openai/v1/models",
    ]


@pytest.mark.asyncio
async def test_foundry_models_missing_credentials_return_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agent.providers import model_discovery
    from app.agent.providers.catalog import find

    monkeypatch.setattr(model_discovery.httpx, "AsyncClient", _FakeFoundryClient)
    entry = find("foundry")
    assert entry is not None

    models = await model_discovery.discover_provider_models(
        entry,
        overrides={"FOUNDRY_API_KEY": "", "FOUNDRY_RESOURCE_NAME": ""},
    )

    assert models == []
