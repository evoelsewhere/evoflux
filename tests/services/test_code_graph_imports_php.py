"""Tests for EDGE_IMPORTS emission from the PHP parser."""

from __future__ import annotations

from app.services.code_graph.parsers.php import PhpParser
from app.services.code_graph.types import EDGE_IMPORTS


def _import_names(result):
    return [e.dst_name for e in result.edges if e.kind == EDGE_IMPORTS]


def _import_edges(result):
    return [(e.dst_name, e.module_path) for e in result.edges if e.kind == EDGE_IMPORTS]


def test_php_bare_import():
    source = rb"""<?php
namespace App;

use Illuminate\Support\Str;

class Foo {}
"""
    result = PhpParser().parse(file_path="sample.php", source=source)
    names = _import_names(result)
    edges = _import_edges(result)
    assert "Str" in names
    assert ("Str", "Illuminate\\Support\\Str") in edges


def test_php_aliased_import():
    source = rb"""<?php
namespace App;

use Illuminate\Support\Facades\DB as DBFacade;
"""
    result = PhpParser().parse(file_path="sample.php", source=source)
    edge = next(edge for edge in result.edges if edge.kind == EDGE_IMPORTS)
    assert edge.dst_name == "DB"
    assert edge.local_name == "DBFacade"
    assert edge.module_path == "Illuminate\\Support\\Facades\\DB"


def test_php_grouped_import():
    source = rb"""<?php
namespace App;

use Illuminate\Support\{Str, Arr};
"""
    result = PhpParser().parse(file_path="sample.php", source=source)
    names = _import_names(result)
    edges = _import_edges(result)
    assert "Str" in names
    assert "Arr" in names
    assert ("Str", "Illuminate\\Support\\Str") in edges
    assert ("Arr", "Illuminate\\Support\\Arr") in edges


def test_php_grouped_import_with_alias():
    source = rb"""<?php
namespace App;

use Illuminate\Support\{Str as S, Arr};
"""
    result = PhpParser().parse(file_path="sample.php", source=source)
    edges = [edge for edge in result.edges if edge.kind == EDGE_IMPORTS]
    aliased = next(edge for edge in edges if edge.local_name == "S")
    assert aliased.dst_name == "Str"
    assert aliased.module_path == "Illuminate\\Support\\Str"
    assert any(edge.dst_name == "Arr" for edge in edges)


def test_php_leading_backslash_import():
    source = rb"""<?php
use \GlobalName;
"""
    result = PhpParser().parse(file_path="sample.php", source=source)
    names = _import_names(result)
    edges = _import_edges(result)
    assert "GlobalName" in names
    assert ("GlobalName", "\\GlobalName") in edges
