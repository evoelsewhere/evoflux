"""Backend provider wiring shared by tests and scripts.

Lives outside ``conftest.py`` because several folders have their own conftest,
and ``from conftest import ...`` resolves to whichever one was loaded last.
"""

from __future__ import annotations

import httpx

from mock_provider.server import MockProvider

MOCK_MODEL = "mock-model"


def configure_backend_provider(
    client: httpx.Client, mock: MockProvider, *, wire: str = "openai"
) -> None:
    """Register ``mock`` through the settings API the UI uses.

    ``wire`` picks the protocol: ``openai`` is Chat Completions, served to the
    9Router provider (the OpenAI provider itself uses the Responses API);
    ``anthropic`` is the Messages API. ``PUT /api/settings/providers/{id}``
    stores a dummy key and the base URL override, then ``POST /api/settings/seed``
    installs the bundled agents pointed at ``<provider>:mock-model``.
    """
    provider, var, base = {
        "openai": ("router9", "ROUTER9_BASE_URL", f"{mock.base_url}/v1"),
        "anthropic": ("anthropic", "ANTHROPIC_BASE_URL", mock.base_url),
    }[wire]
    saved = client.put(
        f"/api/settings/providers/{provider}",
        json={"api_key": "mock-key", "extra": {var: base}},
    )
    saved.raise_for_status()
    seeded = client.post(
        "/api/settings/seed", json={"provider_model": f"{provider}:{MOCK_MODEL}"}
    )
    seeded.raise_for_status()
