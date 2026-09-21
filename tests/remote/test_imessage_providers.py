from __future__ import annotations

import httpx
import pytest

from app.remote.imessage.bluebubbles import BlueBubblesProvider
from app.remote.imessage.provider import IMessageProviderError, IMessageProviderFactory


def test_factory_defaults_to_native_imsg() -> None:
    provider = IMessageProviderFactory().create("imsg")
    assert type(provider).__name__ == "IMsgProvider"


def test_factory_requires_bluebubbles_credentials() -> None:
    with pytest.raises(IMessageProviderError, match="requires endpoint"):
        IMessageProviderFactory().create("bluebubbles")


@pytest.mark.asyncio
async def test_bluebubbles_provider_queries_messages_without_exposing_response() -> (
    None
):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"data": [{"guid": "m1", "text": "hello"}]})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://bluebubbles.example.test/",
    )
    provider = BlueBubblesProvider(
        endpoint_url="https://bluebubbles.example.test",
        password="secret",
        client=client,
    )

    page = await provider.query_messages(since_cursor="m0")

    assert page.messages == [{"guid": "m1", "text": "hello"}]
    assert page.next_cursor == "m1"
    assert requests[0].url.params["password"] == "secret"
    await provider.stop()


@pytest.mark.asyncio
async def test_bluebubbles_provider_hides_http_failure_details() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="password leaked by server")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = BlueBubblesProvider(
        endpoint_url="https://bluebubbles.example.test",
        password="secret",
        client=client,
    )

    with pytest.raises(
        IMessageProviderError, match="BlueBubbles request failed"
    ) as exc:
        await provider.status()
    assert "password" not in str(exc.value).lower()
    await provider.stop()


def test_factory_rejects_unknown_provider_kind() -> None:
    with pytest.raises(IMessageProviderError, match="Unsupported iMessage provider"):
        IMessageProviderFactory().create("whatsapp")
