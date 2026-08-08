"""Tests for EDGE_IMPORTS emission from the Kotlin parser."""

from __future__ import annotations

from app.services.code_index.parsers.kotlin import KotlinParser
from app.services.code_index.graph_types import EDGE_IMPORTS


def _import_names(result):
    return [e.dst_name for e in result.edges if e.kind == EDGE_IMPORTS]


def test_kotlin_bare_import():
    source = b"""import com.example.foo.Bar
"""
    result = KotlinParser().parse(file_path="Main.kt", source=source)
    names = _import_names(result)
    assert "Bar" in names


def test_kotlin_aliased_import():
    source = b"""import com.example.foo.Bar as AliasBar
"""
    result = KotlinParser().parse(file_path="Main.kt", source=source)
    names = _import_names(result)
    # We record the original name, not the alias
    assert "Bar" in names
    edge = next(edge for edge in result.edges if edge.kind == EDGE_IMPORTS)
    assert edge.local_name == "AliasBar"


def test_kotlin_wildcard_import():
    source = b"""import com.example.foo.*
"""
    result = KotlinParser().parse(file_path="Main.kt", source=source)
    names = _import_names(result)
    assert "*" in names


def test_kotlin_multiple_imports():
    source = b"""import com.example.foo.Bar
import com.example.foo.Bar as AliasBar
import com.example.util.*
"""
    result = KotlinParser().parse(file_path="Main.kt", source=source)
    names = _import_names(result)
    assert "Bar" in names
    assert "*" in names

    import_edges = [e for e in result.edges if e.kind == EDGE_IMPORTS]
    module_paths = {e.module_path for e in import_edges}
    assert "com.example.foo.Bar" in module_paths
    assert "com.example.util.*" in module_paths
