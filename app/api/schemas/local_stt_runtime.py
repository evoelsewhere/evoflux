from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class LocalSttRuntimeJobResponse(BaseModel):
    phase: Literal[
        "downloading_runtime",
        "downloading_model",
        "verifying",
        "extracting",
        "checking",
        "failed",
    ]
    runtime_version: str
    model_version: str
    bytes_done: int
    bytes_total: int
    started_at: str
    error: str | None


class LocalSttRuntimeStatusResponse(BaseModel):
    available: bool
    state: Literal[
        "unavailable", "not_installed", "installing", "ready", "needs_repair", "failed"
    ]
    platform: str | None
    model_id: str
    runtime_version: str | None
    model_version: str | None
    download_bytes: int | None
    install_bytes: int | None
    installed_runtime_version: str | None
    installed_model_version: str | None
    healthy: bool
    job: LocalSttRuntimeJobResponse | None
