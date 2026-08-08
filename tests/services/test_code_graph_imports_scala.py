"""Tests for EDGE_IMPORTS emission from the Scala parser."""

from __future__ import annotations

from app.services.code_index.parsers.scala import ScalaParser
from app.services.code_index.graph_types import EDGE_IMPORTS


def _import_names(result):
    return [e.dst_name for e in result.edges if e.kind == EDGE_IMPORTS]


def test_scala_bare_import():
    source = b"""import com.example.baz.Qux
"""
    result = ScalaParser().parse(file_path="Main.scala", source=source)
    names = _import_names(result)
    assert "Qux" in names


def test_scala_multi_symbol_import():
    source = b"""import com.example.baz.{Qux, Quux}
"""
    result = ScalaParser().parse(file_path="Main.scala", source=source)
    names = _import_names(result)
    assert "Qux" in names
    assert "Quux" in names

    import_edges = [e for e in result.edges if e.kind == EDGE_IMPORTS]
    module_paths = {e.dst_name: e.module_path for e in import_edges}
    assert module_paths["Qux"] == "com.example.baz"
    assert module_paths["Quux"] == "com.example.baz"


def test_scala_renamed_import():
    source = b"""import com.example.baz.{Qux => AliasQux}
"""
    result = ScalaParser().parse(file_path="Main.scala", source=source)
    names = _import_names(result)
    # We record the original name, not the alias
    assert "Qux" in names
    assert "AliasQux" not in names
    edge = next(edge for edge in result.edges if edge.kind == EDGE_IMPORTS)
    assert edge.local_name == "AliasQux"


def test_scala_wildcard_import_scala2():
    source = b"""import com.example.util._
"""
    result = ScalaParser().parse(file_path="Main.scala", source=source)
    names = _import_names(result)
    assert "*" in names


def test_scala_wildcard_import_scala3():
    source = b"""import com.example.util.*
"""
    result = ScalaParser().parse(file_path="Main.scala", source=source)
    names = _import_names(result)
    assert "*" in names


def test_scala_comma_separated_imports():
    source = b"""import a.b.C, d.e.F
"""
    result = ScalaParser().parse(file_path="Main.scala", source=source)
    names = _import_names(result)
    assert "C" in names
    assert "F" in names
