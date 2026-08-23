"""Tests for EDGE_IMPORTS emission from the Pascal parser."""

from __future__ import annotations

from app.services.code_index.parsers.pascal import PascalParser
from app.services.code_index.graph_types import EDGE_IMPORTS


def _import_names(result):
    return [e.dst_name for e in result.edges if e.kind == EDGE_IMPORTS]


def _module_paths(result):
    return [e.module_path for e in result.edges if e.kind == EDGE_IMPORTS]


def test_pascal_bare_uses():
    source = b"""program Test;
uses
  SysUtils;

begin
end.
"""
    result = PascalParser().parse(file_path="test.pas", source=source)
    names = _import_names(result)
    assert "SysUtils" in names


def test_pascal_multi_symbol_uses():
    source = b"""program Test;
uses
  SysUtils, Classes, Math;

begin
end.
"""
    result = PascalParser().parse(file_path="test.pas", source=source)
    names = _import_names(result)
    assert "SysUtils" in names
    assert "Classes" in names
    assert "Math" in names


def test_pascal_dotted_unit_name():
    source = b"""program Test;
uses
  MyProject.Utils;

begin
end.
"""
    result = PascalParser().parse(file_path="test.pas", source=source)
    names = _import_names(result)
    paths = _module_paths(result)
    assert "Utils" in names
    assert "MyProject.Utils" in paths


def test_pascal_unit_interface_and_implementation_uses():
    source = b"""unit MyUnit;

interface

uses
  SysUtils, Classes;

implementation

uses
  Math;

end.
"""
    result = PascalParser().parse(file_path="myunit.pas", source=source)
    names = _import_names(result)
    assert "SysUtils" in names
    assert "Classes" in names
    assert "Math" in names


def test_pascal_uppercase_uses_with_explicit_path():
    source = b'''program Test;
USES Vendor.Tools IN 'src/tools.pas';
begin end.
'''
    result = PascalParser().parse(file_path="test.pas", source=source)
    imports = [edge for edge in result.edges if edge.kind == EDGE_IMPORTS]

    assert [(edge.dst_name, edge.module_path) for edge in imports] == [
        ("Tools", "src/tools.pas")
    ]
