"""Tests for P1 (qualified call resolution) and P2 (type aliases + enums)."""

from __future__ import annotations

import os
import tempfile

from app.services.code_graph.indexer import index_files
from app.services.code_graph.parsers.ecmascript import TypeScriptParser
from app.services.code_graph.parsers.go import GoParser
from app.services.code_graph.parsers.python import PythonParser
from app.services.code_graph.parsers.registry import default_registry
from app.services.code_graph.parsers.rust import RustParser
from app.services.code_graph.types import EDGE_CALLS, NODE_CLASS


def _call_names(result):
    return [e.dst_name for e in result.edges if e.kind == EDGE_CALLS]


# ── P2: Type aliases and enums ───────────────────────────────────────────────


def test_ts_type_alias_captured():
    source = b"""type Props = { name: string; age: number };
type Result<T> = T | Error;
"""
    result = TypeScriptParser().parse(file_path="types.ts", source=source)
    classes = [n for n in result.nodes if n.kind == NODE_CLASS]
    names = {c.name for c in classes}
    assert "Props" in names
    assert "Result" in names


def test_ts_enum_captured():
    source = b"""enum Direction { Up, Down, Left, Right }
const enum Status { Active = 1, Inactive = 0 }
"""
    result = TypeScriptParser().parse(file_path="enums.ts", source=source)
    classes = [n for n in result.nodes if n.kind == NODE_CLASS]
    names = {c.name for c in classes}
    assert "Direction" in names
    assert "Status" in names


# ── P1: Qualified call targets ───────────────────────────────────────────────


def test_python_qualified_call():
    source = b"""def run():
    Animal.create("cat")
    helper()
    obj.method()
"""
    result = PythonParser().parse(file_path="main.py", source=source)
    calls = _call_names(result)
    assert "Animal.create" in calls
    assert "helper" in calls
    assert "obj.method" in calls


def test_python_builtin_call_is_not_a_graph_edge():
    source = b"def render(value):\n    return str(value)\n"

    result = PythonParser().parse(file_path="main.py", source=source)

    assert "str" not in _call_names(result)


def test_ts_qualified_call():
    source = b"""function run() {
    Animal.create("cat");
    helper();
    obj.method();
}
"""
    result = TypeScriptParser().parse(file_path="main.ts", source=source)
    calls = _call_names(result)
    assert "Animal.create" in calls
    assert "helper" in calls
    assert "obj.method" in calls


def test_go_qualified_call():
    source = b"""package main

func main() {
    fmt.Println("hello")
    helper()
}
"""
    result = GoParser().parse(file_path="main.go", source=source)
    calls = _call_names(result)
    assert "fmt.Println" in calls
    assert "helper" in calls


def test_rust_qualified_call():
    source = b"""fn main() {
    Animal::new("cat");
    helper();
    obj.run();
}
"""
    result = RustParser().parse(file_path="main.rs", source=source)
    calls = _call_names(result)
    assert "Animal.new" in calls
    assert "helper" in calls
    assert "obj.run" in calls


# ── P1: Qualified resolution in indexer ──────────────────────────────────────


def test_qualified_call_resolves_to_method():
    """Animal.create() resolves to the `create` method inside Animal class."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.makedirs(os.path.join(tmpdir, "pkg"))
        with open(os.path.join(tmpdir, "pkg", "animal.py"), "w") as f:
            f.write("class Animal:\n    def create(self, name):\n        pass\n")
        with open(os.path.join(tmpdir, "pkg", "main.py"), "w") as f:
            f.write("def run():\n    Animal.create('cat')\n")

        result = index_files(
            tmpdir, ["pkg/animal.py", "pkg/main.py"], registry=default_registry()
        )

        call_edges = [e for e in result.edges if e.kind == EDGE_CALLS]
        # Should resolve "Animal.create" → the qualified name "Animal.create"
        assert len(call_edges) >= 1
        resolved_dst_keys = [e.dst_key for e in call_edges]
        assert any("create" in k for k in resolved_dst_keys)


def test_qualified_call_disambiguates():
    """When multiple classes have same method name, qualified call resolves correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with open(os.path.join(tmpdir, "models.py"), "w") as f:
            f.write(
                "class Dog:\n    def run(self):\n        pass\n\n"
                "class Cat:\n    def run(self):\n        pass\n"
            )
        with open(os.path.join(tmpdir, "main.py"), "w") as f:
            f.write("def test():\n    Dog.run()\n")

        result = index_files(
            tmpdir, ["models.py", "main.py"], registry=default_registry()
        )

        call_edges = [e for e in result.edges if e.kind == EDGE_CALLS]
        # "Dog.run" matches qualified_name "Dog.run" — should resolve despite
        # "run" being ambiguous (both Dog.run and Cat.run exist)
        assert len(call_edges) == 1
        assert "Dog" in call_edges[0].dst_key
        assert "run" in call_edges[0].dst_key


def test_simple_call_still_resolves_unique():
    """Simple unique function name still resolves (backward compatible)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with open(os.path.join(tmpdir, "utils.py"), "w") as f:
            f.write("def helper():\n    pass\n")
        with open(os.path.join(tmpdir, "main.py"), "w") as f:
            f.write("def run():\n    helper()\n")

        result = index_files(
            tmpdir, ["utils.py", "main.py"], registry=default_registry()
        )

        call_edges = [e for e in result.edges if e.kind == EDGE_CALLS]
        assert len(call_edges) == 1
        assert "helper" in call_edges[0].dst_key


def test_unscoped_qualified_call_does_not_bind_by_method_name():
    """Receiver-less type inference must not invent a cross-file method edge."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with open(os.path.join(tmpdir, "helpers.py"), "w") as f:
            f.write("def append(value):\n    return value\n")
        with open(os.path.join(tmpdir, "main.py"), "w") as f:
            f.write("def collect(items):\n    items.append(1)\n")

        result = index_files(
            tmpdir, ["helpers.py", "main.py"], registry=default_registry()
        )

        assert [edge for edge in result.edges if edge.kind == EDGE_CALLS] == []


def test_external_import_binding_does_not_fall_back_to_local_name():
    """An unresolved third-party import must not bind to an unrelated symbol."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with open(os.path.join(tmpdir, "helpers.py"), "w") as f:
            f.write("def select(value):\n    return value\n")
        with open(os.path.join(tmpdir, "main.py"), "w") as f:
            f.write("from vendor import select\n\ndef run():\n    return select(1)\n")

        result = index_files(
            tmpdir, ["helpers.py", "main.py"], registry=default_registry()
        )

        assert [edge for edge in result.edges if edge.kind == EDGE_CALLS] == []
