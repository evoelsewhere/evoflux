import asyncio
from io import BytesIO
from typing import Annotated, Any, Literal

import httpx
from ddgs import DDGS
from loguru import logger
from pydantic import Field

from app.agent.outbound_redaction import OutboundContext, protect_outbound_text
from app.agent.tools.registry import tool

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
                logger.info(f"Web search succeeded with backend: {backend}")
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

    try:
        async with httpx.AsyncClient(
            follow_redirects=True, verify=True, timeout=timeout_s
        ) as client:
            response = await client.get(url, headers=headers)

            # Cloudflare bot-detection retry with honest UA
            if (
                response.status_code == 403
                and response.headers.get("cf-mitigated") == "challenge"
            ):
                logger.debug("web_fetch_cloudflare_retry")
                response = await client.get(
                    url, headers={**headers, "User-Agent": "opencode"}
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
