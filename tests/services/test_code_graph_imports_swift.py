"""Tests for EDGE_IMPORTS emission from the Swift parser."""

from __future__ import annotations

from app.services.code_index.parsers.swift import SwiftParser
from app.services.code_index.graph_types import EDGE_IMPORTS


def _import_names(result):
    return [e.dst_name for e in result.edges if e.kind == EDGE_IMPORTS]


def _import_edges(result):
    return {e.dst_name: e.module_path for e in result.edges if e.kind == EDGE_IMPORTS}


def test_swift_bare_module_import():
    source = b"""import Foundation
"""
    result = SwiftParser().parse(file_path="main.swift", source=source)
    edges = _import_edges(result)
    assert "Foundation" in edges
    assert edges["Foundation"] == "Foundation"


def test_swift_scoped_symbol_import():
    source = b"""import struct Foundation.Date
"""
    result = SwiftParser().parse(file_path="main.swift", source=source)
    edges = _import_edges(result)
    assert "Date" in edges
    assert edges["Date"] == "Foundation.Date"


def test_swift_testable_attribute_import():
    source = b"""@testable import MyAppCore
"""
    result = SwiftParser().parse(file_path="MyAppCoreTests.swift", source=source)
    edges = _import_edges(result)
    assert "MyAppCore" in edges
    assert edges["MyAppCore"] == "MyAppCore"


def test_swift_multiple_imports_in_one_file():
    source = b"""import Foundation
import UIKit
import class UIKit.UIView

class Foo {}
"""
    result = SwiftParser().parse(file_path="main.swift", source=source)
    names = _import_names(result)
    assert names == ["Foundation", "UIKit", "UIView"]
