"""Tests for EDGE_IMPORTS emission from the C# parser."""

from __future__ import annotations

from app.services.code_graph.parsers.csharp import CSharpParser
from app.services.code_graph.types import EDGE_IMPORTS


def _import_names(result):
    return [e.dst_name for e in result.edges if e.kind == EDGE_IMPORTS]


def _import_edges(result):
    return [e for e in result.edges if e.kind == EDGE_IMPORTS]


def test_csharp_bare_using():
    source = b"""using System;
using System.Collections.Generic;

namespace MyApp {
    class Program {}
}
"""
    result = CSharpParser().parse(file_path="Program.cs", source=source)
    names = _import_names(result)
    assert "System" in names
    assert "Generic" in names
    edges = {e.dst_name: e.module_path for e in _import_edges(result)}
    assert edges["Generic"] == "System.Collections.Generic"


def test_csharp_aliased_using():
    source = b"""using Json = Newtonsoft.Json.Linq;

namespace MyApp {
    class Program {}
}
"""
    result = CSharpParser().parse(file_path="Program.cs", source=source)
    names = _import_names(result)
    assert "Json" in names
    edges = {e.dst_name: e.module_path for e in _import_edges(result)}
    assert edges["Json"] == "Newtonsoft.Json.Linq"


def test_csharp_multi_using():
    source = b"""using System;
using MyOrg.Payments.Client;
using static System.Math;

namespace MyApp {
    class Program {}
}
"""
    result = CSharpParser().parse(file_path="Program.cs", source=source)
    names = _import_names(result)
    assert "System" in names
    assert "Client" in names
    assert "Math" in names
    edges = {e.dst_name: e.module_path for e in _import_edges(result)}
    assert edges["Client"] == "MyOrg.Payments.Client"
    assert edges["Math"] == "System.Math"


def test_csharp_global_using():
    source = b"""global using System.Text;

namespace MyApp {
    class Program {}
}
"""
    result = CSharpParser().parse(file_path="Program.cs", source=source)
    names = _import_names(result)
    assert "Text" in names
    edges = {e.dst_name: e.module_path for e in _import_edges(result)}
    assert edges["Text"] == "System.Text"
