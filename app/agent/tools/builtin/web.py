import asyncio
import ipaddress
import socket
from io import BytesIO
from typing import Annotated, Any, Literal

import httpx
from ddgs import DDGS
from loguru import logger
from pydantic import Field

from app.agent.outbound_redaction import OutboundContext, protect_outbound_text
from app.agent.tools.registry import tool
from app.core.config import settings

_MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # 5 MB
_DEFAULT_TIMEOUT = 30.0
_MAX_TIMEOUT = 120.0

_ACCEPT_HEADERS: dict[str, str] = {
    "markdown": "text/markdown;q=1.0, text/x-markdown;q=0.9, text/plain;q=0.8, text/html;q=0.7, */*;q=0.1",
    "html": "text/html;q=1.0, application/xhtml+xml;q=0.9, text/plain;q=0.8, */*;q=0.1",
    "text": "text/plain;q=1.0, text/html;q=0.9, */*;q=0.1",
}

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/143.0.0.0 Safari/537.36"
)


# ── SSRF / DNS-rebinding protection ─────────────────────────────────────────


class UnsafeURL(ValueError):
    """Raised when a URL resolves to a non-public address."""


def _is_private_ip(ip: str) -> bool:
    """Return True if *ip* is anything other than a routable public address.

    Fails *closed*: an address we cannot parse is treated as unsafe rather
    than waved through.
    """
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    if addr.is_private or addr.is_loopback or addr.is_reserved:
        return True
    if addr.is_link_local or addr.is_multicast or addr.is_unspecified:
        return True
    # ``::ffff:127.0.0.1`` and friends: judge the embedded v4 address.
    mapped = getattr(addr, "ipv4_mapped", None)
    if mapped is not None:
        return _is_private_ip(str(mapped))
    return False


async def _resolve_public_ip(host: str, port: int, *, allow_private: bool) -> str:
    """Resolve *host* and return one address that passed the policy check.

    The address returned here is the one the caller then connects to
    directly, so validation and connection cannot disagree — that is what
    closes the DNS-rebinding window. Resolving a second time to connect
    would reopen it.
    """
    loop = asyncio.get_running_loop()
    try:
        resolved = await loop.getaddrinfo(
            host, port, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM
        )
    except socket.gaierror:
        raise UnsafeURL(f"DNS resolution failed for {host}") from None

    ips = [info[4][0] for info in resolved]
    if not ips:
        raise UnsafeURL(f"DNS resolution returned no addresses for {host}")

    if allow_private:
        return ips[0]

    for ip in ips:
        if not _is_private_ip(ip):
            return ip
    raise UnsafeURL(
        f"Refusing to fetch {host} — resolved to private IP {ips[0]}. "
        "Set WEB_FETCH_ALLOW_PRIVATE_NETWORK=true to override."
    )


class _PublicOnlyTransport(httpx.AsyncBaseTransport):
    """Policy-check the destination of every outbound connection.

    The check lives in the transport rather than in ``web_fetch`` because
    httpx re-enters the transport once per redirect hop. A 302 pointing at
    ``169.254.169.254`` is therefore refused exactly like the original URL —
    checking only the caller-supplied URL would let one redirect walk
    straight into the metadata service.

    Scope of the guarantee: the address is resolved and checked immediately
    before the connection is handed to httpx, which resolves again itself.
    That leaves a narrow window in which a hostile authoritative server
    could answer differently the second time. Closing it completely needs a
    resolver hook at the socket layer, which httpx does not expose; rewriting
    the URL to the checked IP here would close it but would also bypass TLS
    hostname verification and make the tool untestable against a mocked
    transport. The remaining window is documented rather than papered over.
    """

    def __init__(self, *, allow_private: bool = False) -> None:
        self._allow_private = allow_private
        self._inner = httpx.AsyncHTTPTransport(verify=True)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if not host:
            raise UnsafeURL(f"Invalid URL: no hostname in {request.url}")
        port = request.url.port or (443 if request.url.scheme == "https" else 80)

        await _resolve_public_ip(host, port, allow_private=self._allow_private)
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self._inner.aclose()


# ── Pooled HTTP client ───────────────────────────────────────────────────────
# A single ``httpx.AsyncClient`` is reused across all ``web_fetch`` calls so
# TCP connections are pooled and TLS handshakes are amortised. Connections
# key on the pinned IP, so pooling survives the rewrite above. The client is
# lazily created on first use and torn down via ``close_http_client``.
_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    """Return the shared pooled HTTP client, creating it on first call."""
    global _http_client  # noqa: PLW0603
    if _http_client is None or _http_client.is_closed:
        allow_private = bool(getattr(settings, "WEB_FETCH_ALLOW_PRIVATE_NETWORK", False))
        _http_client = httpx.AsyncClient(
            follow_redirects=True,
            transport=_PublicOnlyTransport(allow_private=allow_private),
        )
    return _http_client


async def close_http_client() -> None:
    """Shut down the shared HTTP client (called on app teardown)."""
    global _http_client  # noqa: PLW0603
    if _http_client is not None and not _http_client.is_closed:
        await _http_client.aclose()
    _http_client = None


@tool(
    name="web_search",
    concurrency_safe=True,
    read_only=True,
    deferred=True,
    deferred_summary="Search the public web for current information and sources.",
    search_aliases=(
        "google",
        "internet",
        "online",
        "news",
        "latest",
        "recent",
        "research",
        "documentation",
        "docs",
    ),
)
async def web_search(
    query: Annotated[
        str,
        Field(description="Search query string."),
    ],
    max_results: Annotated[
        int,
        Field(description="Number of results (default 5, max 20)."),
    ] = 5,
    page: Annotated[
        int,
        Field(description="Page number (default 1)."),
    ] = 1,
    safesearch: Annotated[
        Literal["on", "moderate", "off"],
        Field(description="Safe search level (default 'moderate')."),
    ] = "moderate",
) -> list[dict[str, Any]] | str:
    """Search the web. Returns [{title, href, body}]."""
    # Search providers receive the query verbatim, so protect it before both
    # the primary backend and the Exa fallback. This covers a common covert
    # egress path that is outside the model-provider boundary.
    query, report = protect_outbound_text(
        query,
        context=OutboundContext(channel="web", destination="search"),
    )
    if report.matches:
        logger.warning(
            "web_search_outbound_sensitive_data_protected matches={} "
            "secret_matches={} pii_matches={} categories={}",
            report.matches,
            report.secret_matches,
            report.pii_matches,
            ",".join(report.categories),
        )
    results = None
    backends = ["auto", "brave", "wikipedia", "mojeek"]
    for backend in backends:
        try:
            loop = asyncio.get_running_loop()
            results = await loop.run_in_executor(
                None,
                lambda b=backend: DDGS().text(
                    query,
                    max_results=max_results,
                    page=page,
                    safesearch=safesearch,
                    backend=b,
                ),
            )
            if results:
                logger.debug("web_search_succeeded backend={}", backend)
                break
        except Exception as e:
            logger.debug(f"Web search failed with backend {backend}: {str(e)}")

    if results:
        return results

    logger.debug(
        "DDGS search failed or returned no results, falling back to Exa search"
    )
    # Fallback to Exa search tool if DDGS fails or returns no results
    url = "https://mcp.exa.ai/mcp"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    data = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "search",
            "arguments": {"query": query, "numResults": max_results},
        },
    }
    try:
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
            response = await client.post(url, headers=headers, json=data)
            response.raise_for_status()
            result = response.json()
            if "error" in result:
                logger.debug(f"Exa search error: {result['error']}")
                return f"Error: {result['error']}"
            return result.get("result", [])
    except Exception as e:
        logger.debug(f"Error during Exa search: {str(e)}")
        return "No result found"


def _fallback_convert(content_bytes: bytes, mime: str | None) -> str:
    """Minimal HTML/text conversion when markitdown is unavailable (onnxruntime DLL issue)."""
    if mime and mime.startswith("text/") and mime != "text/html":
        return content_bytes.decode("utf-8", errors="replace")

    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(content_bytes, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        return text
    except Exception:
        return content_bytes.decode("utf-8", errors="replace")


@tool(
    name="web_fetch",
    concurrency_safe=True,
    read_only=True,
    deferred=True,
    deferred_summary="Fetch a web URL as Markdown, HTML, or plain text.",
    search_aliases=(
        "url",
        "link",
        "website",
        "scrape",
        "download",
        "http",
        "https",
        "article",
        "documentation",
        "docs",
    ),
)
async def web_fetch(
    url: Annotated[
        str,
        Field(description="URL to fetch. https:// prepended if no scheme."),
    ],
    format: Annotated[  # noqa: A002
        Literal["markdown", "html", "text"],
        Field(description="Response format (default 'markdown')."),
    ] = "markdown",
    timeout: Annotated[
        int | None,
        Field(description="Timeout in seconds (default 30, max 120)."),
    ] = None,
) -> str:
    """Fetch a URL and return its content. Handles HTML, PDF, and plain text."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    url, report = protect_outbound_text(
        url,
        context=OutboundContext(channel="web", destination="fetch"),
    )
    if report.matches:
        logger.warning(
            "web_fetch_outbound_sensitive_data_protected matches={} "
            "secret_matches={} pii_matches={} categories={}",
            report.matches,
            report.secret_matches,
            report.pii_matches,
            ",".join(report.categories),
        )

    timeout_s = min(float(timeout) if timeout else _DEFAULT_TIMEOUT, _MAX_TIMEOUT)

    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": _ACCEPT_HEADERS[format],
        "Accept-Language": "en-US,en;q=0.9",
    }

    # SSRF/DNS-rebinding policy is enforced inside the client's transport, so
    # it covers the initial request and every redirect hop alike.
    try:
        client = _get_http_client()
        response = await client.get(url, headers=headers, timeout=timeout_s)

        # Cloudflare bot-detection retry with honest UA
        if (
            response.status_code == 403
            and response.headers.get("cf-mitigated") == "challenge"
        ):
            logger.debug("web_fetch_cloudflare_retry")
            response = await client.get(
                url,
                headers={**headers, "User-Agent": "opencode"},
                timeout=timeout_s,
            )

        response.raise_for_status()

        content_length = response.headers.get("content-length")
        if content_length and int(content_length) > _MAX_RESPONSE_BYTES:
            return f"Error: Response too large (content-length {content_length} exceeds 5 MB limit)"

        content_bytes = response.content
        if len(content_bytes) > _MAX_RESPONSE_BYTES:
            return f"Error: Response too large ({len(content_bytes)} bytes exceeds 5 MB limit)"

        content_type = response.headers.get("content-type", "")

        mime = content_type.split(";")[0].strip().lower() or None

        # If the response is already markdown, return it as-is
        if mime in ("text/markdown", "text/x-markdown"):
            return content_bytes.decode("utf-8", errors="replace")

        # For all other types (html, text, pdf, etc.) let MarkItDown convert.
        # ``markitdown`` is imported lazily because it pulls native libraries
        # (``onnxruntime`` via ``magika``) whose DLL load can fail on some
        # Windows hosts. Keeping the import inside the tool body means the
        # backend always starts; only ``web_fetch`` calls that actually need
        # conversion are affected when the native runtime is missing.
        def _convert() -> str:
            try:
                from markitdown import MarkItDown, StreamInfo

                md = MarkItDown()
                result = md.convert_stream(
                    BytesIO(content_bytes),
                    stream_info=StreamInfo(url=url, mimetype=mime),
                )
                return result.markdown
            except (ImportError, OSError):
                logger.debug("web_fetch_markitdown_fallback")
                return _fallback_convert(content_bytes, mime)

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _convert)

    except UnsafeURL as e:
        return f"Error: {e}"
    except TypeError as e:
        # A bad call into httpx is our bug, not a fetch failure — surface it
        # loudly instead of returning a string the agent reads as "site down".
        logger.exception("web_fetch_internal_error")
        raise RuntimeError(f"web_fetch internal error: {e}") from e
    except Exception as e:
        return f"Error fetching or converting: {str(e)}"


@tool(
    name="image_search",
    concurrency_safe=True,
    read_only=True,
    deferred=True,
    deferred_summary="Search the web for usable photos, illustrations, icons, or backgrounds.",
    search_aliases=(
        "image",
        "images",
        "picture",
        "photo",
        "stock",
        "logo",
        "asset",
        "wallpaper",
        "graphic",
        "thumbnail",
    ),
)
async def image_search(
    query: Annotated[
        str,
        Field(
            description="Search query for images (e.g. 'modern office teamwork', 'abstract blue gradient background')."
        ),
    ],
    max_results: Annotated[
        int,
        Field(description="Number of images to return (default 5, max 20)."),
    ] = 5,
    size: Annotated[
        Literal["small", "medium", "large", "wallpaper"] | None,
        Field(description="Filter by image size. None for any size."),
    ] = None,
    layout: Annotated[
        Literal["square", "tall", "wide"] | None,
        Field(description="Filter by aspect ratio. None for any layout."),
    ] = None,
    license_image: Annotated[
        Literal[
            "any",
            "Public",
            "Share",
            "ShareCommercially",
            "Modify",
            "ModifyCommercially",
        ]
        | None,
        Field(
            description="License filter. 'Public' = public domain, 'ShareCommercially' = free for commercial use. None for any license."
        ),
    ] = None,
) -> list[dict[str, str]] | str:
    """Search for images on the web. Returns [{title, image, thumbnail, url, source}].

    Use this to find stock photos, illustrations, icons, or backgrounds
    for presentations, documents, or design work. Download images via
    shell (curl/wget) using the returned 'image' URL.
    """
    query, report = protect_outbound_text(
        query,
        context=OutboundContext(channel="web", destination="image-search"),
    )
    if report.matches:
        logger.warning(
            "image_search_outbound_sensitive_data_protected matches={} "
            "secret_matches={} pii_matches={} categories={}",
            report.matches,
            report.secret_matches,
            report.pii_matches,
            ",".join(report.categories),
        )
    max_results = max(1, min(max_results, 20))

    try:
        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(
            None,
            lambda: DDGS().images(
                query,
                max_results=max_results,
                size=size,
                layout=layout,
                license_image=license_image,
                safesearch="moderate",
            ),
        )
    except Exception as e:
        logger.debug("image_search_failed err={}", e)
        return f"Image search failed: {e}"

    if not results:
        return "No images found for this query. Try different keywords."

    return [
        {
            "title": r.get("title", ""),
            "image": r.get("image", ""),
            "thumbnail": r.get("thumbnail", ""),
            "url": r.get("url", ""),
            "source": r.get("source", ""),
        }
        for r in results
    ]
