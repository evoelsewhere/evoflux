"""Language parsers for the code knowledge graph."""

from __future__ import annotations

from app.services.code_graph.parsers.base import LanguageParser
from app.services.code_graph.parsers.registry import (
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
