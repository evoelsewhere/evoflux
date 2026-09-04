from unittest.mock import patch

import httpx
import pytest
import respx

from app.agent.tools.builtin.web import (
    _is_private_ip,
    close_http_client,
    image_search,
    web_fetch,
    web_search,
)


@pytest.mark.asyncio
async def test_web_search_success():
    with patch("app.agent.tools.builtin.web.DDGS") as mock_ddgs_class:
        mock_ddgs = mock_ddgs_class.return_value
        mock_ddgs.text.return_value = [{"title": "t", "href": "h", "body": "b"}]

        result = await web_search("query")
        assert len(result) == 1
        assert result[0]["title"] == "t"


@pytest.mark.asyncio
async def test_web_search_redacts_query_before_search_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.agent.outbound_redaction.load_outbound_data_policy",
        lambda: "redact",
    )
    monkeypatch.setattr(
        "app.agent.outbound_redaction.load_outbound_pii_policy",
        lambda: "off",
    )
    with patch("app.agent.tools.builtin.web.DDGS") as mock_ddgs_class:
        mock_ddgs = mock_ddgs_class.return_value
        mock_ddgs.text.return_value = [{"title": "t", "href": "h", "body": "b"}]

        await web_search("https://example.test/?token=abcdefghijklmnop")

        query = mock_ddgs.text.call_args.args[0]
        assert "abcdefghijklmnop" not in query
        assert "[REDACTED:url-secret]" in query


@pytest.mark.asyncio
async def test_image_search_redacts_query_before_search_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.agent.outbound_redaction.load_outbound_data_policy",
        lambda: "redact",
    )
    monkeypatch.setattr(
        "app.agent.outbound_redaction.load_outbound_pii_policy",
        lambda: "off",
    )
    with patch("app.agent.tools.builtin.web.DDGS") as mock_ddgs_class:
        mock_ddgs = mock_ddgs_class.return_value
        mock_ddgs.images.return_value = [
            {
                "title": "image",
                "image": "https://example.test/image.png",
                "thumbnail": "https://example.test/thumb.png",
                "url": "https://example.test",
                "source": "example",
            }
        ]

        await image_search("token=abcdefghijklmnop")

        query = mock_ddgs.images.call_args.args[0]
        assert "abcdefghijklmnop" not in query
        assert "[REDACTED:secret]" in query


@pytest.mark.asyncio
async def test_web_search_exception_returns_string():
    """When DDGS raises and Exa also fails, web_search returns 'No result found'."""
    with patch("app.agent.tools.builtin.web.DDGS") as mock_ddgs_class:
        mock_ddgs = mock_ddgs_class.return_value
        mock_ddgs.text.side_effect = Exception("network error")

        with respx.mock:
            respx.post("https://mcp.exa.ai/mcp").mock(side_effect=Exception("exa down"))
            result = await web_search("failing query")
        assert result == "No result found"


@pytest.mark.asyncio
async def test_web_search_exa_fallback_with_error():
    """When DDGS fails and Exa returns an error, the error message is returned."""
    with patch("app.agent.tools.builtin.web.DDGS") as mock_ddgs_class:
        mock_ddgs = mock_ddgs_class.return_value
        mock_ddgs.text.return_value = None

        with respx.mock:
            respx.post("https://mcp.exa.ai/mcp").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "error": {"code": -32000, "message": "Invalid query"},
                    },
                )
            )

            result = await web_search("failing query")
            assert "Error:" in result
            assert "Invalid query" in result


@pytest.mark.asyncio
async def test_web_search_exa_fallback_success():
    """When DDGS fails but Exa succeeds, results from Exa are returned."""
    with patch("app.agent.tools.builtin.web.DDGS") as mock_ddgs_class:
        mock_ddgs = mock_ddgs_class.return_value
        mock_ddgs.text.return_value = None

        with respx.mock:
            respx.post("https://mcp.exa.ai/mcp").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": [
                            {"title": "Exa Result", "url": "https://example.com"}
                        ],
                    },
                )
            )

            result = await web_search("test query")
            assert isinstance(result, list)
            assert len(result) == 1
            assert result[0]["title"] == "Exa Result"


@pytest.mark.asyncio
@respx.mock
async def test_web_fetch_html_converted_via_markitdown():
    """HTML responses are converted to Markdown via MarkItDown."""
    url = "https://example.com"
    respx.get(url).mock(
        return_value=httpx.Response(
            200,
            text="<html><body><h1>Hello</h1></body></html>",
            headers={"content-type": "text/html"},
        )
    )

    with patch("markitdown.MarkItDown") as mock_mid_class:
        mock_mid = mock_mid_class.return_value
        mock_mid.convert_stream.return_value.markdown = "# Hello"

        result = await web_fetch(url)
        assert result == "# Hello"
        mock_mid.convert_stream.assert_called_once()


@pytest.mark.asyncio
@respx.mock
async def test_web_fetch_native_markdown_returned_asis():
    """Responses with text/markdown MIME type are returned as-is without MarkItDown."""
    url = "https://example.com/readme.md"
    respx.get(url).mock(
        return_value=httpx.Response(
            200,
            text="# Native Markdown",
            headers={"content-type": "text/markdown"},
        )
    )

    with patch("markitdown.MarkItDown") as mock_mid_class:
        result = await web_fetch(url)
        assert result == "# Native Markdown"
        mock_mid_class.return_value.convert_stream.assert_not_called()


@pytest.mark.asyncio
@respx.mock
async def test_web_fetch_no_scheme_prefixed():
    """URL without scheme gets https:// prepended."""
    respx.get("https://example.com").mock(
        return_value=httpx.Response(
            200,
            text="<html><body>Test</body></html>",
            headers={"content-type": "text/html"},
        )
    )

    with patch("markitdown.MarkItDown") as mock_mid_class:
        mock_mid = mock_mid_class.return_value
        mock_mid.convert_stream.return_value.markdown = "Test"

        result = await web_fetch("example.com")
        assert result == "Test"


@pytest.mark.asyncio
@respx.mock
async def test_web_fetch_format_html_uses_markitdown():
    """format='html' still uses MarkItDown for conversion."""
    url = "https://example.com"
    respx.get(url).mock(
        return_value=httpx.Response(
            200,
            text="<html><body>Raw</body></html>",
            headers={"content-type": "text/html"},
        )
    )

    with patch("markitdown.MarkItDown") as mock_mid_class:
        mock_mid = mock_mid_class.return_value
        mock_mid.convert_stream.return_value.markdown = "Raw"

        result = await web_fetch(url, format="html")
        assert result == "Raw"
        mock_mid.convert_stream.assert_called_once()


@pytest.mark.asyncio
@respx.mock
async def test_web_fetch_http_error_returns_error_string():
    """Non-2xx response returns an error string."""
    url = "https://nonexistent-url.com"
    respx.get(url).mock(return_value=httpx.Response(404))

    result = await web_fetch(url)
    assert "Error fetching or converting" in result


@pytest.mark.asyncio
@respx.mock
async def test_web_fetch_blocks_url_secret_before_http_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.agent.outbound_redaction.load_outbound_data_policy",
        lambda: "block",
    )
    monkeypatch.setattr(
        "app.agent.outbound_redaction.load_outbound_pii_policy",
        lambda: "off",
    )
    route = respx.get("https://example.test/?token=abcdefghijklmnop").mock(
        return_value=httpx.Response(200, text="should not be fetched")
    )

    with pytest.raises(PermissionError):
        await web_fetch("https://example.test/?token=abcdefghijklmnop")

    assert not route.called


@pytest.mark.asyncio
@respx.mock
async def test_web_fetch_content_length_too_large():
    """Responses with content-length > 5MB are rejected."""
    url = "https://example.com/bigfile"
    respx.get(url).mock(
        return_value=httpx.Response(
            200,
            text="x",
            headers={
                "content-type": "text/plain",
                "content-length": str(6 * 1024 * 1024),
            },
        )
    )

    result = await web_fetch(url)
    assert "too large" in result


@pytest.mark.asyncio
@respx.mock
async def test_web_fetch_cloudflare_retry():
    """403 with cf-mitigated=challenge retries with 'opencode' User-Agent."""
    url = "https://example.com"
    call_count = 0

    def side_effect(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(403, headers={"cf-mitigated": "challenge"})
        return httpx.Response(
            200,
            text="<p>OK</p>",
            headers={"content-type": "text/html"},
        )

    respx.get(url).mock(side_effect=side_effect)

    with patch("markitdown.MarkItDown") as mock_mid_class:
        mock_mid = mock_mid_class.return_value
        mock_mid.convert_stream.return_value.markdown = "OK"

        result = await web_fetch(url)
        assert result == "OK"
        assert call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_web_fetch_body_too_large_without_content_length():
    """Responses where body exceeds 5MB (no content-length header) are rejected.

    Covers web_tools.py:107 — the body-size check after reading content.
    """
    url = "https://example.com/bigbody"
    # Serve a body larger than _MAX_RESPONSE_BYTES (5 MB).
    # Build the httpx.Response manually and strip the content-length header so
    # that only the body-size check (line 107) is reached, not the header check.
    big_body = b"x" * (5 * 1024 * 1024 + 1)
    response = httpx.Response(
        200,
        content=big_body,
        headers={"content-type": "text/plain"},
    )
    # Remove the auto-set content-length so the header branch is skipped
    response.headers.pop("content-length", None)
    respx.get(url).mock(return_value=response)

    result = await web_fetch(url)
    assert "too large" in result
    assert "bytes exceeds" in result


@pytest.mark.asyncio
@respx.mock
async def test_web_fetch_timeout_capped_at_120():
    """timeout > 120 is capped to 120 seconds."""
    url = "https://example.com"
    respx.get(url).mock(
        return_value=httpx.Response(
            200, text="<p>hi</p>", headers={"content-type": "text/html"}
        )
    )

    with patch("markitdown.MarkItDown") as mock_mid_class:
        mock_mid = mock_mid_class.return_value
        mock_mid.convert_stream.return_value.markdown = "hi"

        result = await web_fetch(url, timeout=9999)
        assert result == "hi"


# ── SSRF / private-network policy ────────────────────────────────────────────
# Regression cover for the DNS-rebinding hardening: the guard must block
# private destinations, must re-check every redirect hop, and must not break
# ordinary fetches (it previously passed an unsupported ``transport`` kwarg to
# ``AsyncClient.get``, which failed every single call).


@pytest.mark.asyncio
async def test_web_fetch_rejects_private_destination():
    """A hostname resolving into a private range is refused by default."""
    await close_http_client()
    result = await web_fetch("http://127.0.0.1:1/")
    assert result.startswith("Error:")
    assert "private IP" in result
    await close_http_client()


@pytest.mark.asyncio
async def test_web_fetch_rejects_cloud_metadata_endpoint():
    """The link-local metadata address is refused."""
    await close_http_client()
    result = await web_fetch("http://169.254.169.254/latest/meta-data")
    assert "169.254.169.254" in result
    assert "private IP" in result
    await close_http_client()


@pytest.mark.asyncio
async def test_web_fetch_allows_private_when_setting_enabled(monkeypatch):
    """WEB_FETCH_ALLOW_PRIVATE_NETWORK opts out of the private-range guard."""
    from app.core.config import settings

    await close_http_client()
    monkeypatch.setattr(settings, "WEB_FETCH_ALLOW_PRIVATE_NETWORK", True)
    # Port 1 refuses the connection; reaching a connection error proves the
    # policy let the destination through rather than short-circuiting it.
    result = await web_fetch("http://127.0.0.1:1/")
    assert "private IP" not in result
    await close_http_client()


@pytest.mark.asyncio
@respx.mock
async def test_web_fetch_redirect_hop_is_revalidated():
    """A redirect into a private range is refused even when hop 1 is public."""
    await close_http_client()
    respx.get("https://example.com/open").mock(
        return_value=httpx.Response(
            302, headers={"location": "http://169.254.169.254/latest/meta-data"}
        )
    )

    result = await web_fetch("https://example.com/open")
    assert "private IP" in result
    await close_http_client()


def test_is_private_ip_fails_closed_on_garbage():
    """An unparseable address is treated as unsafe, not waved through."""
    assert _is_private_ip("not-an-ip") is True
    assert _is_private_ip("10.0.0.1") is True
    assert _is_private_ip("::ffff:127.0.0.1") is True
    assert _is_private_ip("93.184.216.34") is False
