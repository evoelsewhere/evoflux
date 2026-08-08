"""Language parsers for the code-context index."""

from __future__ import annotations

from app.services.code_index.parsers.base import LanguageParser
from app.services.code_index.parsers.registry import (
    ParserRegistry,
    build_registry,
    default_registry,
)

__all__ = [
    "LanguageParser",
    "ParserRegistry",
    "build_registry",
    "default_registry",
]
