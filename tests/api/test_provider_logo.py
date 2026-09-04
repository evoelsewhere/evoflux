"""The provider logo proxy.

models.dev publishes a mark for every provider it lists, which is how a
200-provider picker gets real icons instead of initials. It is proxied
rather than linked so the renderer never talks to a third party, so a
restricted network breaks nothing after the first fetch, and so the icons
keep working offline like the rest of the catalog.

That makes this endpoint a fetcher of remote content, so the tests below
care mostly about what it refuses.
"""

from __future__ import annotations

import httpx
import pytest

from app.api.routes import settings as settings_routes

_SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0h1v1H0z"/></svg>'


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        settings_routes.settings, "EVOFLUX_CACHE_DIR", str(tmp_path / "cache")
    )


class TestSourceResolution:
    def test_a_curated_provider_borrows_its_catalog_mark(self) -> None:
        """Codex is OpenAI's API, so it is OpenAI's mark."""
        assert settings_routes._logo_source_id("codex") == "openai"
        assert settings_routes._logo_source_id("vertexai") == "google-vertex"
        assert settings_routes._logo_source_id("copilot") == "github-copilot"

    def test_a_catalog_provider_uses_its_own_id(self) -> None:
        assert settings_routes._logo_source_id("302ai") == "302ai"

    def test_a_provider_absent_from_the_catalog_has_no_mark(self) -> None:
        """Local daemons are not in models.dev; they keep their own glyph."""
        assert settings_routes._logo_source_id("router9") is None
        assert settings_routes._logo_source_id("ollama") is None

    @pytest.mark.parametrize(
        "provider_id",
        [
            "",
            "nope",
            "../etc/passwd",
            "..",
            "a/b",
            "HTTP://evil.example",
            "x" * 200,
        ],
    )
    def test_unknown_and_malformed_ids_are_refused(self, provider_id: str) -> None:
        """The allowlist is what stops this being a fetch-anything proxy."""
        assert settings_routes._logo_source_id(provider_id) is None


class TestFetchValidation:
    async def _fetch(self, monkeypatch: pytest.MonkeyPatch, response: httpx.Response):
        class _Client:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_exc) -> None:
                return None

            async def get(self, *_args, **_kwargs) -> httpx.Response:
                return response

        monkeypatch.setattr(settings_routes.httpx, "AsyncClient", _Client)
        return await settings_routes._fetch_logo("anthropic")

    async def test_a_plain_svg_is_accepted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        response = httpx.Response(
            200, content=_SVG, headers={"content-type": "image/svg+xml"}
        )
        assert await self._fetch(monkeypatch, response) == _SVG

    async def test_a_non_svg_content_type_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        response = httpx.Response(
            200, content=_SVG, headers={"content-type": "text/html"}
        )
        assert await self._fetch(monkeypatch, response) is None

    async def test_a_non_200_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        response = httpx.Response(404, content=b"nope")
        assert await self._fetch(monkeypatch, response) is None

    @pytest.mark.parametrize(
        "payload",
        [
            b'<svg><script>fetch("//evil")</script></svg>',
            b'<svg><image onload="alert(1)"/></svg>',
            b'<svg><a href="javascript:alert(1)">x</a></svg>',
            b"<svg><foreignObject><iframe/></foreignObject></svg>",
        ],
    )
    async def test_active_svg_content_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, payload: bytes
    ) -> None:
        """An SVG can carry script; a cached one is served back by this API.

        ``<img>`` would not execute it, but the file is also written to disk
        and returned by us, so it is rejected at the door rather than
        trusted to a downstream sandbox.
        """
        response = httpx.Response(
            200, content=payload, headers={"content-type": "image/svg+xml"}
        )
        assert await self._fetch(monkeypatch, response) is None

    async def test_an_oversized_payload_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        oversized = b"<svg>" + b"." * (settings_routes._LOGO_MAX_BYTES + 1) + b"</svg>"
        response = httpx.Response(
            200, content=oversized, headers={"content-type": "image/svg+xml"}
        )
        assert await self._fetch(monkeypatch, response) is None

    async def test_a_transport_error_is_not_fatal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An icon is decoration; failing to fetch one must never raise."""

        class _Client:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_exc) -> None:
                return None

            async def get(self, *_args, **_kwargs):
                raise httpx.ConnectError("offline")

        monkeypatch.setattr(settings_routes.httpx, "AsyncClient", _Client)
        assert await settings_routes._fetch_logo("anthropic") is None


class TestCaching:
    def test_a_cached_logo_is_read_from_disk(self, tmp_path) -> None:
        path = tmp_path / "anthropic.svg"
        path.write_bytes(_SVG)
        assert settings_routes._read_cached_logo(path) == _SVG

    def test_a_missing_cache_file_reads_as_absent(self, tmp_path) -> None:
        assert settings_routes._read_cached_logo(tmp_path / "nope.svg") is None
