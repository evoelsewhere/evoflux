"""Shared building blocks for the Office document pipelines."""

from __future__ import annotations

from app.services.office.runtime import (
    ARTIFACT_TOOL_ENTRYPOINT_ENV,
    CHROMIUM_BIN_ENV,
    DEFAULT_WORKER_TIMEOUT_SECONDS,
    DOCUMENT_RUNTIME_DIR_ENV,
    NODE_BIN_ENV,
    DocumentRuntimePaths,
    NodeWorkerRuntime,
    codex_runtime_dependencies,
    document_runtime_diagnostics,
    document_runtime_subprocess_env,
    file_sha256,
    resolve_artifact_tool,
    resolve_chromium_binary,
    resolve_document_runtime,
    resolve_document_runtime_root,
    resolve_executable,
    resolve_node_binary,
)

__all__ = [
    "ARTIFACT_TOOL_ENTRYPOINT_ENV",
    "CHROMIUM_BIN_ENV",
    "DEFAULT_WORKER_TIMEOUT_SECONDS",
    "DOCUMENT_RUNTIME_DIR_ENV",
    "DocumentRuntimePaths",
    "NODE_BIN_ENV",
    "NodeWorkerRuntime",
    "codex_runtime_dependencies",
    "document_runtime_diagnostics",
    "document_runtime_subprocess_env",
    "file_sha256",
    "resolve_artifact_tool",
    "resolve_chromium_binary",
    "resolve_document_runtime",
    "resolve_document_runtime_root",
    "resolve_executable",
    "resolve_node_binary",
]
