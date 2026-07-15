from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from app.agent.providers.model_discovery import _bedrock_models


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

    assert models == [
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
