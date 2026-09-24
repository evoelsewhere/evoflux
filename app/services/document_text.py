"""Turn PDF and HTML bytes into text an agent can read.

PDFs go through PDFium (``pypdfium2``) for plain text, one block per page.
HTML goes through BeautifulSoup and ``markdownify`` for Markdown, with
scripts, styles, ``javascript:`` links and inline ``data:`` images dropped.
Anything else is returned as-is when it is text, and refused when binary.

Every entry point returns ``None`` instead of raising: callers treat "no
text" as one outcome and choose their own fallback.
"""

from __future__ import annotations

import threading

from loguru import logger

CONVERSION_TIMEOUT_SECS = 30

# PDFium is not thread-safe, and conversions run on worker threads.
_PDFIUM_LOCK = threading.Lock()


def is_pdf(mime: str | None, filename: str = "") -> bool:
    return mime == "application/pdf" or filename.lower().endswith(".pdf")


def is_html(mime: str | None, filename: str = "") -> bool:
    return mime in ("text/html", "application/xhtml+xml") or filename.lower().endswith(
        (".html", ".htm", ".xhtml")
    )


def pdf_to_text(data: bytes) -> str | None:
    """Extract the text layer of a PDF, pages separated by a blank line."""
    import pypdfium2 as pdfium

    pages: list[str] = []
    with _PDFIUM_LOCK:
        pdf = pdfium.PdfDocument(data)
        try:
            for page in pdf:
                textpage = page.get_textpage()
                try:
                    text = textpage.get_text_bounded().strip()
                finally:
                    textpage.close()
                    page.close()
                if text:
                    pages.append(text)
        finally:
            pdf.close()
    joined = "\n\n".join(pages).replace("\r\n", "\n")
    return joined or None


def html_to_markdown(data: bytes | str) -> str | None:
    """Convert an HTML page's body to Markdown."""
    from bs4 import BeautifulSoup, Tag
    from markdownify import ATX, MarkdownConverter

    soup = BeautifulSoup(data, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    for link in soup.find_all("a"):
        href = str(link.get("href") or "") if isinstance(link, Tag) else ""
        if href.strip().lower().startswith("javascript:"):
            link.unwrap()
    for image in soup.find_all("img"):
        src = str(image.get("src") or "") if isinstance(image, Tag) else ""
        if src.startswith("data:"):
            image.replace_with(str(image.get("alt") or ""))
    root = soup.find("body") or soup
    markdown = MarkdownConverter(heading_style=ATX).convert_soup(root).strip()
    return markdown or None


def convert_to_text(data: bytes, mime: str | None, filename: str = "") -> str | None:
    """Convert a PDF, HTML page, or text payload; ``None`` when nothing usable."""
    if is_pdf(mime, filename):
        return pdf_to_text(data)
    if is_html(mime, filename):
        return html_to_markdown(data)
    if mime and mime.startswith("text/"):
        text = data.decode("utf-8", errors="replace")
    else:
        # Untyped or non-text payload: only accept it if it really is text.
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return None
    return text.strip() or None


def convert_with_timeout(
    data: bytes, mime: str | None, filename: str = ""
) -> str | None:
    """:func:`convert_to_text` on a daemon thread, bounded by a timeout.

    A pathological file must not hold up the turn, so a conversion that
    overruns is abandoned (its thread finishes on its own) and reads as
    ``None``, as does any conversion error.
    """
    result: list[str | None] = [None]
    error: list[BaseException | None] = [None]

    def _run() -> None:
        try:
            result[0] = convert_to_text(data, mime, filename)
        except Exception as exc:
            error[0] = exc

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=CONVERSION_TIMEOUT_SECS)

    if thread.is_alive():
        logger.warning(
            "document_conversion_timeout filename={} mime={} timeout={}s",
            filename,
            mime,
            CONVERSION_TIMEOUT_SECS,
        )
        return None
    if error[0] is not None:
        logger.debug(
            "document_conversion_failed filename={} mime={} error={}",
            filename,
            mime,
            error[0],
        )
        return None
    return result[0]
