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
    names = _import_names(result)
    edges = _import_edges(result)
    assert "DBFacade" in names
    assert ("DBFacade", "Illuminate\\Support\\Facades\\DB") in edges


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
    names = _import_names(result)
    edges = _import_edges(result)
    assert "S" in names
    assert "Arr" in names
    assert ("S", "Illuminate\\Support\\Str") in edges


def test_php_leading_backslash_import():
    source = rb"""<?php
use \GlobalName;
"""
    result = PhpParser().parse(file_path="sample.php", source=source)
    names = _import_names(result)
    edges = _import_edges(result)
    assert "GlobalName" in names
    assert ("GlobalName", "\\GlobalName") in edges
