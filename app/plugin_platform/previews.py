"""Format-neutral document preview provider registry."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable

from app.plugin_platform.native import iter_builtin_native_providers


DOCUMENT_PREVIEW_CSP = (
    "default-src 'none'; "
    "base-uri 'none'; "
    "connect-src 'none'; "
    "font-src data:; "
    "form-action 'none'; "
    "frame-src 'none'; "
    "img-src data: blob:; "
    "media-src data: blob:; "
    "object-src 'none'; "
    "script-src 'none'; "
    "style-src 'unsafe-inline'"
)


class DocumentPreviewError(RuntimeError):
    """A trusted provider could not render an otherwise supported document."""


class DocumentPreviewUnsupportedError(DocumentPreviewError):
    """No trusted bundled provider accepts the requested file format."""


@dataclass(frozen=True, slots=True)
class DocumentPreviewProvider:
    name: str
    extensions: frozenset[str]
    render: Callable[[Path], Path]


@lru_cache(maxsize=1)
def document_preview_providers() -> tuple[DocumentPreviewProvider, ...]:
    providers: list[DocumentPreviewProvider] = []
    for plugin_name, factory in iter_builtin_native_providers("preview_provider"):
        provider = factory()
        if not isinstance(provider, DocumentPreviewProvider):
            raise TypeError(
                f"preview provider from {plugin_name} returned an invalid contract"
            )
        providers.append(provider)
    return tuple(providers)


def render_document_preview(source: Path) -> Path:
    suffix = source.suffix.casefold()
    for provider in document_preview_providers():
        if suffix in provider.extensions:
            return provider.render(source)
    raise DocumentPreviewUnsupportedError(
        f"{suffix or 'This file type'} is not supported for document preview."
    )


__all__ = [
    "DOCUMENT_PREVIEW_CSP",
    "DocumentPreviewError",
    "DocumentPreviewProvider",
    "DocumentPreviewUnsupportedError",
    "document_preview_providers",
    "render_document_preview",
]
