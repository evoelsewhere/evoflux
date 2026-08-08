"""Tests for EDGE_IMPORTS emission from the Dart parser."""

from __future__ import annotations

from app.services.code_index.parsers.dart import DartParser
from app.services.code_index.graph_types import EDGE_IMPORTS


def _import_names(result):
    return [e.dst_name for e in result.edges if e.kind == EDGE_IMPORTS]


def _import_edges(result):
    return {e.dst_name: e.module_path for e in result.edges if e.kind == EDGE_IMPORTS}


def test_dart_bare_package_import():
    source = b"""import 'package:my_pkg/my_pkg.dart';
"""
    result = DartParser().parse(file_path="lib/main.dart", source=source)
    edges = _import_edges(result)
    assert "my_pkg" in edges
    assert edges["my_pkg"] == "package:my_pkg/my_pkg.dart"


def test_dart_aliased_import():
    source = b"""import 'package:shared/src/utils.dart' as sharedUtils;
"""
    result = DartParser().parse(file_path="lib/main.dart", source=source)
    edge = next(edge for edge in result.edges if edge.kind == EDGE_IMPORTS)
    assert edge.dst_name == "utils"
    assert edge.local_name == "sharedUtils"
    assert edge.module_path == "package:shared/src/utils.dart"


def test_dart_sdk_import():
    source = b"""import 'dart:core';
import 'dart:async';
"""
    result = DartParser().parse(file_path="lib/main.dart", source=source)
    edges = _import_edges(result)
    assert "core" in edges
    assert edges["core"] == "dart:core"
    assert "async" in edges
    assert edges["async"] == "dart:async"


def test_dart_relative_import():
    source = b"""import 'src/local_file.dart';
"""
    result = DartParser().parse(file_path="lib/main.dart", source=source)
    edges = _import_edges(result)
    assert "local_file" in edges
    assert edges["local_file"] == "src/local_file.dart"


def test_dart_multi_symbol_show_combinator_import():
    source = b"""import 'package:flutter/material.dart' show Widget, State;
"""
    result = DartParser().parse(file_path="lib/main.dart", source=source)
    names = _import_names(result)
    edges = _import_edges(result)
    assert "material" in names
    assert edges["material"] == "package:flutter/material.dart"


def test_dart_export_treated_as_import_like_edge():
    source = b"""export 'package:shared/src/utils.dart';
"""
    result = DartParser().parse(file_path="lib/main.dart", source=source)
    edges = _import_edges(result)
    assert "utils" in edges
    assert edges["utils"] == "package:shared/src/utils.dart"


def test_dart_multiple_imports_in_one_file():
    source = b"""import 'package:my_pkg/my_pkg.dart';
import 'package:shared/src/utils.dart' as utils;
import 'dart:core';
import 'src/local_file.dart';

class Foo {}
"""
    result = DartParser().parse(file_path="lib/main.dart", source=source)
    names = _import_names(result)
    assert names == ["my_pkg", "utils", "core", "local_file"]
