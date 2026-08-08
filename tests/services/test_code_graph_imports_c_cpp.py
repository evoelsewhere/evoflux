"""Tests for EDGE_IMPORTS emission from the C and C++ parsers."""

from __future__ import annotations

from app.services.code_index.parsers.c_family import CParser, CppParser
from app.services.code_index.graph_types import EDGE_IMPORTS


def _import_names(result):
    return [e.dst_name for e in result.edges if e.kind == EDGE_IMPORTS]


def _module_paths(result):
    return [e.module_path for e in result.edges if e.kind == EDGE_IMPORTS]


def test_c_system_include():
    source = b"""#include <stdio.h>
"""
    result = CParser().parse(file_path="main.c", source=source)
    names = _import_names(result)
    assert "stdio.h" in names
    assert "stdio.h" in _module_paths(result)


def test_c_quoted_include_nested_path():
    source = b"""#include "myproject/widget.h"
"""
    result = CParser().parse(file_path="main.c", source=source)
    names = _import_names(result)
    paths = _module_paths(result)
    assert "widget.h" in names
    assert "myproject/widget.h" in paths


def test_c_multiple_includes():
    source = b"""#include <stdio.h>
#include <stdlib.h>
#include "local.h"
"""
    result = CParser().parse(file_path="main.c", source=source)
    names = _import_names(result)
    assert "stdio.h" in names
    assert "stdlib.h" in names
    assert "local.h" in names


def test_cpp_system_include():
    source = b"""#include <vector>
#include <string>
"""
    result = CppParser().parse(file_path="main.cpp", source=source)
    names = _import_names(result)
    assert "vector" in names
    assert "string" in names


def test_cpp_quoted_include():
    source = b"""#include "myproject/widget.h"
"""
    result = CppParser().parse(file_path="main.cpp", source=source)
    names = _import_names(result)
    paths = _module_paths(result)
    assert "widget.h" in names
    assert "myproject/widget.h" in paths
