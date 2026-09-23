from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class OfficeRuntimeJobResponse(BaseModel):
    phase: Literal["downloading", "verifying", "extracting", "failed"]
    version: str
    bytes_done: int
    bytes_total: int
    started_at: str
    error: str | None


class OfficeRuntimeStatusResponse(BaseModel):
    """Whether exact Office rendering is available, installed or installing."""

    available: bool
    platform: str | None
    version: str | None
    download_bytes: int | None
    installed_version: str | None
    job: OfficeRuntimeJobResponse | None
