"""Parser registry — maps file extensions to language parsers.

This is the extension point for new languages: implement a
:class:`~app.services.code_graph.parsers.base.LanguageParser` and register it
here. Nothing else in the pipeline needs to change.
"""

from __future__ import annotations

from pathlib import Path

from app.services.code_graph.parsers.base import LanguageParser
from app.services.code_graph.parsers.c_family import CParser, CppParser
from app.services.code_graph.parsers.csharp import CSharpParser
from app.services.code_graph.parsers.dart import DartParser
from app.services.code_graph.parsers.ecmascript import (
    JavaScriptParser,
    TsxParser,
    TypeScriptParser,
)
from app.services.code_graph.parsers.go import GoParser
from app.services.code_graph.parsers.java import JavaParser
from app.services.code_graph.parsers.kotlin import KotlinParser
from app.services.code_graph.parsers.lua import LuaParser, LuauParser
from app.services.code_graph.parsers.objc import ObjCParser
from app.services.code_graph.parsers.pascal import PascalParser
from app.services.code_graph.parsers.php import PhpParser
from app.services.code_graph.parsers.python import PythonParser
from app.services.code_graph.parsers.r_lang import RParser
from app.services.code_graph.parsers.ruby import RubyParser
from app.services.code_graph.parsers.rust import RustParser
from app.services.code_graph.parsers.scala import ScalaParser
from app.services.code_graph.parsers.swift import SwiftParser
from app.services.code_graph.parsers.web_components import (
    AstroParser,
    LiquidParser,
    SvelteParser,
    VueParser,
)

# Order matters only for ``available_languages`` display.
_BUILTIN_PARSER_TYPES: tuple[type[LanguageParser], ...] = (
    PythonParser,
    TypeScriptParser,
    TsxParser,
    JavaScriptParser,
    GoParser,
    RustParser,
    JavaParser,
    CSharpParser,
    CParser,
    CppParser,
    SwiftParser,
    KotlinParser,
    PhpParser,
    RubyParser,
    ScalaParser,
    DartParser,
    ObjCParser,
    LuaParser,
    LuauParser,
    RParser,
    PascalParser,
    SvelteParser,
    VueParser,
    AstroParser,
    LiquidParser,
)


class ParserRegistry:
    """Resolves the right parser for a given file path."""

    def __init__(self, parsers: list[LanguageParser]) -> None:
        self._by_language: dict[str, LanguageParser] = {}
        self._by_extension: dict[str, LanguageParser] = {}
        for parser in parsers:
            self._by_language[parser.name] = parser
            for ext in parser.extensions:
                self._by_extension[ext.lower()] = parser

    def for_path(self, path: str | Path) -> LanguageParser | None:
        return self._by_extension.get(Path(path).suffix.lower())

    def supported_extensions(self) -> frozenset[str]:
        return frozenset(self._by_extension)

    def languages(self) -> tuple[str, ...]:
        return tuple(self._by_language)


def build_registry(languages: list[str] | None = None) -> ParserRegistry:
    """Build a registry, optionally restricted to ``languages`` by name."""
    parsers: list[LanguageParser] = []
    for parser_type in _BUILTIN_PARSER_TYPES:
        parser = parser_type()
        if languages is None or parser.name in languages:
            parsers.append(parser)
    return ParserRegistry(parsers)


def default_registry() -> ParserRegistry:
    """Registry with every built-in language enabled."""
    return build_registry()
