"""Native provider entrypoints for the trusted Documents plugin."""

from __future__ import annotations


def artifact_drivers() -> tuple[object, ...]:
    # Imports stay behind the provider call so API startup and Plugin Center do
    # not import optional document-engine dependencies in slim installations.
    from app.agent.builtin_plugins.documents.artifacts.docx import DocxArtifactDriver
    from app.agent.builtin_plugins.documents.artifacts.pdf import PdfArtifactDriver
    from app.agent.builtin_plugins.documents.artifacts.pptx import PptxArtifactDriver
    from app.agent.builtin_plugins.documents.artifacts.xlsx import XlsxArtifactDriver

    return (
        DocxArtifactDriver(),
        XlsxArtifactDriver(),
        PptxArtifactDriver(),
        PdfArtifactDriver(),
    )


def preview_provider() -> object:
    from app.agent.builtin_plugins.documents.preview import document_preview_provider

    return document_preview_provider


def api_router() -> object:
    from app.agent.builtin_plugins.documents.routes import router

    return router


__all__ = ["api_router", "artifact_drivers", "preview_provider"]
