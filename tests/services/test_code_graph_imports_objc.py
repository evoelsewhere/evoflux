"""Tests for EDGE_IMPORTS emission from the Objective-C parser."""

from __future__ import annotations

from app.services.code_graph.parsers.objc import ObjCParser
from app.services.code_graph.types import EDGE_IMPORTS


def _import_names(result):
    return [e.dst_name for e in result.edges if e.kind == EDGE_IMPORTS]


def _import_edges(result):
    return {e.dst_name: e.module_path for e in result.edges if e.kind == EDGE_IMPORTS}


def test_objc_framework_qualified_import():
    source = b"""#import <Foundation/Foundation.h>
"""
    result = ObjCParser().parse(file_path="AppDelegate.m", source=source)
    edges = _import_edges(result)
    assert "Foundation" in edges
    assert edges["Foundation"] == "Foundation/Foundation.h"


def test_objc_quoted_local_import():
    source = b"""#import "MyHeader.h"
"""
    result = ObjCParser().parse(file_path="AppDelegate.m", source=source)
    edges = _import_edges(result)
    assert "MyHeader.h" in edges
    assert edges["MyHeader.h"] == "MyHeader.h"


def test_objc_clang_module_import():
    source = b"""@import SomeModule;
"""
    result = ObjCParser().parse(file_path="AppDelegate.m", source=source)
    edges = _import_edges(result)
    assert "SomeModule" in edges
    assert edges["SomeModule"] == "SomeModule"


def test_objc_dotted_submodule_import():
    source = b"""@import Foo.Bar;
"""
    result = ObjCParser().parse(file_path="AppDelegate.m", source=source)
    edges = _import_edges(result)
    assert "Bar" in edges
    assert edges["Bar"] == "Foo.Bar"


def test_objc_multiple_imports_in_one_file():
    source = b"""#import <Foundation/Foundation.h>
#import "MyHeader.h"
#include <stdio.h>

@interface Foo : NSObject
@end
"""
    result = ObjCParser().parse(file_path="AppDelegate.m", source=source)
    names = _import_names(result)
    assert names == ["Foundation", "MyHeader.h", "stdio.h"]
