"""PDF/HTML → text conversion used by read, web_fetch and uploads."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services import document_text
from app.services.document_text import (
    convert_to_text,
    convert_with_timeout,
    html_to_markdown,
    pdf_to_text,
)


def _pdf_with_text(*pages: str) -> bytes:
    """A minimal valid PDF, one Helvetica line per page."""
    count = len(pages)
    kids = " ".join(f"{3 + i * 2} 0 R" for i in range(count))
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {count} >>",
    ]
    font_id = 3 + count * 2
    for index, text in enumerate(pages):
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET"
        objects.append(
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> "
            f"/Contents {4 + index * 2} 0 R >>"
        )
        objects.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
    objects.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n"
    ).encode()
    return bytes(out)


class TestPdf:
    def test_extracts_each_page(self) -> None:
        text = pdf_to_text(_pdf_with_text("First page", "Second page"))
        assert text == "First page\n\nSecond page"

    def test_pdf_without_text_layer_is_none(self) -> None:
        assert pdf_to_text(_pdf_with_text("")) is None

    def test_detected_by_extension_without_mime(self) -> None:
        data = _pdf_with_text("By name")
        assert convert_to_text(data, None, "/files/report.PDF") == "By name"


class TestHtml:
    def test_body_becomes_markdown(self) -> None:
        html = (
            "<html><head><title>T</title><style>p{}</style></head>"
            "<body><h2>Heading</h2><p>Some <b>bold</b> text.</p>"
            "<script>alert(1)</script></body></html>"
        )
        assert html_to_markdown(html) == "## Heading\n\nSome **bold** text."

    def test_javascript_links_and_data_images_are_dropped(self) -> None:
        html = (
            '<p><a href="javascript:void(0)">click</a> '
            '<a href="https://example.com">site</a> '
            '<img src="data:image/png;base64,AAAA" alt="logo"></p>'
        )
        assert html_to_markdown(html) == "click [site](https://example.com) logo"

    def test_empty_body_is_none(self) -> None:
        assert html_to_markdown("<html><body> </body></html>") is None


class TestOtherPayloads:
    def test_text_mime_is_returned(self) -> None:
        assert convert_to_text(b"  plain  ", "text/plain") == "plain"

    def test_untyped_utf8_is_returned(self) -> None:
        assert convert_to_text(b'{"a": 1}', "application/json") == '{"a": 1}'

    def test_binary_is_refused(self) -> None:
        assert convert_to_text(b"\xff\xfe\x00\x81", "image/png") is None


class TestTimeoutWrapper:
    def test_returns_converted_text(self) -> None:
        data = _pdf_with_text("Bounded")
        assert convert_with_timeout(data, "application/pdf", "a.pdf") == "Bounded"

    def test_conversion_error_is_none(self) -> None:
        assert convert_with_timeout(b"not a pdf", "application/pdf", "bad.pdf") is None

    def test_timeout_is_none_and_logged(self) -> None:
        thread = MagicMock()
        thread.is_alive.return_value = True
        with (
            patch.object(document_text.threading, "Thread", return_value=thread),
            patch.object(document_text, "logger") as logger,
        ):
            assert convert_with_timeout(b"x", "application/pdf", "slow.pdf") is None
        thread.join.assert_called_once_with(
            timeout=document_text.CONVERSION_TIMEOUT_SECS
        )
        assert "document_conversion_timeout" in logger.warning.call_args[0][0]
