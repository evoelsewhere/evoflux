from __future__ import annotations

import hashlib

import httpx
import pytest

from app.plugin_platform.marketplace import (
    MarketplaceEntry,
    MarketplaceError,
    MarketplaceProvider,
    install_marketplace_plugin,
)


def _entry(content: bytes = b"artifact") -> dict[str, object]:
    return {
        "npmPackage": "@example/plugin",
        "name": "example-plugin",
        "version": "1.0.0",
        "description": "Example marketplace plugin",
        "license": "Apache-2.0",
        "portable": True,
        "portableComponents": ["skills", "mcp"],
        "compatibleClients": ["evoflux", "claude", "codex"],
        "hostCapabilities": [],
        "skills": ["example"],
        "mcpServers": [],
        "connections": [],
        "reportTemplates": [],
        "artifact": {
            "url": "https://registry.example/artifacts/example.evoplugin",
            "sha256": hashlib.sha256(content).hexdigest(),
            "size": len(content),
        },
        "publisher": {"id": "example", "signatureAlgorithm": "ed25519"},
        "verification": {"state": "unverified"},
        "lifecycle": "published",
    }


@pytest.mark.asyncio
async def test_provider_fetches_typed_registry_and_pinned_artifact() -> None:
    content = b"artifact"
    entry = _entry(content)
    index = {"version": 1, "generatedAt": "2026-09-21T00:00:00Z", "plugins": [entry]}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/registry.json":
            return httpx.Response(200, json=index)
        return httpx.Response(200, content=content)

    provider = MarketplaceProvider(
        "https://registry.example/registry.json",
        transport=httpx.MockTransport(handler),
    )

    registry = await provider.fetch_registry()
    artifact = await provider.download_artifact(registry.plugins[0])

    assert registry.plugins[0].name == "example-plugin"
    assert artifact.content == content
    assert artifact.sha256 == entry["artifact"]["sha256"]


@pytest.mark.asyncio
async def test_provider_rejects_non_https_registry() -> None:
    with pytest.raises(MarketplaceError, match="HTTPS"):
        MarketplaceProvider("http://registry.example/registry.json")


@pytest.mark.asyncio
async def test_provider_reports_unavailable_registry_service() -> None:
    provider = MarketplaceProvider(
        "https://registry.example/registry.json",
        transport=httpx.MockTransport(lambda _request: httpx.Response(503)),
    )

    with pytest.raises(MarketplaceError, match="request failed"):
        await provider.fetch_registry()


@pytest.mark.asyncio
async def test_provider_rejects_digest_and_size_mismatch() -> None:
    content = b"artifact"
    entry = _entry(content)
    entry["artifact"] = {
        "url": "https://registry.example/artifacts/example.evoplugin",
        "sha256": "0" * 64,
        "size": len(content) + 1,
    }

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=content)

    provider = MarketplaceProvider(
        "https://registry.example/registry.json",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(MarketplaceError, match="digest mismatch"):
        await provider.download_artifact(MarketplaceEntry.model_validate(entry))


@pytest.mark.asyncio
async def test_provider_rejects_oversized_response() -> None:
    content = b"too-large"

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=content)

    provider = MarketplaceProvider(
        "https://registry.example/registry.json",
        transport=httpx.MockTransport(handler),
        max_registry_bytes=4,
    )

    with pytest.raises(MarketplaceError, match="size limit"):
        await provider.fetch_registry()


@pytest.mark.asyncio
async def test_install_marketplace_plugin_requires_trust_review() -> None:
    provider = MarketplaceProvider(
        "https://registry.example/registry.json",
        transport=httpx.MockTransport(lambda _request: httpx.Response(500)),
    )
    entry = MarketplaceEntry.model_validate(_entry())

    with pytest.raises(MarketplaceError, match="trust review"):
        await install_marketplace_plugin(provider, entry)


@pytest.mark.asyncio
async def test_install_marketplace_plugin_rejects_revoked_even_with_override() -> None:
    provider = MarketplaceProvider(
        "https://registry.example/registry.json",
        transport=httpx.MockTransport(lambda _request: httpx.Response(500)),
    )
    payload = _entry()
    payload["verification"] = {"state": "revoked", "reason": "publisher revoked"}

    with pytest.raises(MarketplaceError, match="cannot be installed"):
        await install_marketplace_plugin(
            provider,
            MarketplaceEntry.model_validate(payload),
            allow_unverified=True,
        )


@pytest.mark.asyncio
async def test_install_marketplace_plugin_stages_verified_bytes(monkeypatch) -> None:
    content = b"artifact"
    payload = _entry(content)
    payload["verification"] = {
        "state": "verified",
        "verifiedAt": "2026-09-21T00:00:00Z",
    }

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=content)

    observed: dict[str, object] = {}

    def fake_install(source, *, enabled, source_ref, provenance):
        observed["content"] = source.read_bytes()
        observed["enabled"] = enabled
        observed["source_ref"] = source_ref
        observed["provenance"] = provenance
        return "installation"

    import app.plugin_platform.installer as installer

    monkeypatch.setattr(installer, "install_plugin", fake_install)
    provider = MarketplaceProvider(
        "https://registry.example/registry.json",
        transport=httpx.MockTransport(handler),
    )

    result = await install_marketplace_plugin(
        provider,
        MarketplaceEntry.model_validate(payload),
        enabled=False,
    )

    assert result == "installation"
    assert observed["content"] == content
    assert observed["enabled"] is False
    assert observed["source_ref"] == payload["artifact"]["url"]
    assert observed["provenance"].verification_state == "verified"
