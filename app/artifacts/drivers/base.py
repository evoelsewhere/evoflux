"""Driver contract for native document pipelines."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from app.artifacts.domain import (
    ArtifactDriverContext,
    ArtifactDriverResult,
)


class ArtifactDriver(ABC):
    format: ClassVar[str]
    extension: ClassVar[str]
    media_type: ClassVar[str]
    version: ClassVar[str] = "1"
    protocol_version: ClassVar[int] = 1
    required_extra: ClassVar[str | None] = None

    def lane(self, source_path: Any | None) -> str:
        return "template" if source_path is not None else "new"

    @abstractmethod
    def catalog(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def inspect(self, context: ArtifactDriverContext) -> ArtifactDriverResult:
        raise NotImplementedError

    @abstractmethod
    async def validate(self, context: ArtifactDriverContext) -> ArtifactDriverResult:
        raise NotImplementedError

    @abstractmethod
    async def build(self, context: ArtifactDriverContext) -> ArtifactDriverResult:
        """Build and QA one candidate file. Do not publish it."""

        raise NotImplementedError


__all__ = ["ArtifactDriver"]
