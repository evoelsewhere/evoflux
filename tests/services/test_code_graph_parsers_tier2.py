"""Tests for C, C++, Swift, Kotlin parsers."""

from __future__ import annotations

from pathlib import Path


from app.services.code_graph.parsers.c_family import CParser, CppParser
from app.services.code_graph.parsers.kotlin import KotlinParser
from app.services.code_graph.parsers.registry import default_registry
from app.services.code_graph.parsers.swift import SwiftParser
from app.services.code_graph.types import (
    EDGE_CALLS,
    EDGE_IMPLEMENTS,
    EDGE_INHERITS,
    NODE_CLASS,
    NODE_FUNCTION,
    NODE_INTERFACE,
    NODE_METHOD,
)


def _by_kind(nodes, kind):
    return [n for n in nodes if n.kind == kind]


# ── C parser ──────────────────────────────────────────────────────────────────


def test_c_parser_extracts_struct_function():
    source = b"""struct Animal {
    char* name;
    int age;
};

void animal_run(struct Animal* a) {
    printf("%s running\\n", a->name);
}

int main() {
    struct Animal a;
    animal_run(&a);
    return 0;
}
"""
    result = CParser().parse(file_path="main.c", source=source)

    classes = _by_kind(result.nodes, NODE_CLASS)
    functions = _by_kind(result.nodes, NODE_FUNCTION)

    assert [c.name for c in classes] == ["Animal"]
    assert "animal_run" in [f.name for f in functions]
    assert "main" in [f.name for f in functions]


def test_c_parser_typedef():
    source = b"""typedef struct { int x; int y; } Point;
typedef enum { NORTH, SOUTH } Direction;
"""
    result = CParser().parse(file_path="types.c", source=source)
    classes = _by_kind(result.nodes, NODE_CLASS)
    names = {c.name for c in classes}
    assert "Point" in names
    assert "Direction" in names


def test_c_parser_calls():
    source = b"""void helper() { printf("hi"); }
int main() { helper(); return 0; }
"""
    result = CParser().parse(file_path="main.c", source=source)
    calls = [e for e in result.edges if e.kind == EDGE_CALLS]
    call_names = {e.dst_name for e in calls}
    assert "printf" in call_names
    assert "helper" in call_names


# ── C++ parser ────────────────────────────────────────────────────────────────


def test_cpp_parser_extracts_class_methods():
    source = b"""class Animal {
public:
    virtual void run() = 0;
    void speak() { helper(); }
    virtual ~Animal() = default;
};
"""
    result = CppParser().parse(file_path="animal.hpp", source=source)

    classes = _by_kind(result.nodes, NODE_CLASS)
    methods = _by_kind(result.nodes, NODE_METHOD)

    assert [c.name for c in classes] == ["Animal"]
    assert "run" in [m.name for m in methods]
    assert "speak" in [m.name for m in methods]
    assert "~Animal" in [m.name for m in methods]


def test_cpp_parser_inheritance():
    source = b"""class Cat : public Animal, public Named {
    void run() override {}
};
"""
    result = CppParser().parse(file_path="cat.cpp", source=source)

    inherits = [e for e in result.edges if e.kind == EDGE_INHERITS]
    names = {e.dst_name for e in inherits}
    assert "Animal" in names
    assert "Named" in names


def test_cpp_parser_calls():
    source = b"""void helper() {}
void test() {
    helper();
    obj.run();
    ptr->method();
    std::make_unique<Cat>();
}
"""
    result = CppParser().parse(file_path="test.cpp", source=source)
    calls = [e for e in result.edges if e.kind == EDGE_CALLS]
    call_names = {e.dst_name for e in calls}
    assert "helper" in call_names
    assert "run" in call_names
    assert "method" in call_names
    assert "make_unique" in call_names


def test_cpp_parser_namespace_function():
    source = b"""namespace utils {
void helper() {}
}
"""
    result = CppParser().parse(file_path="utils.cpp", source=source)
    functions = _by_kind(result.nodes, NODE_FUNCTION)
    assert [f.name for f in functions] == ["helper"]
    assert functions[0].qualified_name == "utils.helper"


def test_cpp_nested_namespace_qualifies_members():
    source = b"""namespace acme::billing {
class Service { public: void run(); };
void top() {}
}
"""
    result = CppParser().parse(file_path="billing.cpp", source=source)
    qualified = {node.name: node.qualified_name for node in result.nodes}

    assert qualified["Service"] == "acme.billing.Service"
    assert qualified["run"] == "acme.billing.Service.run"
    assert qualified["top"] == "acme.billing.top"


# ── Swift parser ──────────────────────────────────────────────────────────────


def test_swift_parser_extracts_protocol_class_struct():
    source = b"""protocol Runner {
    func run()
}

class Animal: Runner {
    var name: String
    init(name: String) { self.name = name }
    func run() { print(name) }
}

struct Point {
    let x: Int
    let y: Int
}

enum Direction {
    case north, south
}
"""
    result = SwiftParser().parse(file_path="main.swift", source=source)

    interfaces = _by_kind(result.nodes, NODE_INTERFACE)
    classes = _by_kind(result.nodes, NODE_CLASS)
    methods = _by_kind(result.nodes, NODE_METHOD)

    assert [i.name for i in interfaces] == ["Runner"]
    assert "Animal" in [c.name for c in classes]
    assert "Point" in [c.name for c in classes]
    assert "Direction" in [c.name for c in classes]
    assert "init" in [m.name for m in methods]
    assert "run" in [m.name for m in methods]


def test_swift_parser_inheritance():
    source = b"""class Cat: Animal, Runner {
    func run() {}
}
"""
    result = SwiftParser().parse(file_path="cat.swift", source=source)

    edges = [e for e in result.edges if e.kind in (EDGE_INHERITS, EDGE_IMPLEMENTS)]
    names = {e.dst_name for e in edges}
    assert "Animal" in names
    assert "Runner" in names


def test_swift_parser_calls():
    source = b"""func test() {
    let a = Animal(name: "cat")
    a.run()
    helper()
}
"""
    result = SwiftParser().parse(file_path="test.swift", source=source)

    calls = [e for e in result.edges if e.kind == EDGE_CALLS]
    call_names = {e.dst_name for e in calls}
    assert "Animal" in call_names
    assert "run" in call_names
    assert "helper" in call_names


def test_swift_parser_properties():
    source = b"""class Foo {
    var name: String
    let count: Int
}
"""
    result = SwiftParser().parse(file_path="foo.swift", source=source)
    methods = _by_kind(result.nodes, NODE_METHOD)
    names = {m.name for m in methods}
    assert "name" in names
    assert "count" in names


# ── Kotlin parser ─────────────────────────────────────────────────────────────


def test_kotlin_parser_extracts_interface_class():
    source = b"""interface Runner {
    fun run()
}

class Animal(val name: String) : Runner {
    override fun run() { println(name) }
}

data class Point(val x: Int, val y: Int)

enum class Direction { NORTH, SOUTH }
"""
    result = KotlinParser().parse(file_path="main.kt", source=source)

    interfaces = _by_kind(result.nodes, NODE_INTERFACE)
    classes = _by_kind(result.nodes, NODE_CLASS)
    methods = _by_kind(result.nodes, NODE_METHOD)

    assert [i.name for i in interfaces] == ["Runner"]
    assert "Animal" in [c.name for c in classes]
    assert "Point" in [c.name for c in classes]
    assert "Direction" in [c.name for c in classes]
    assert "run" in [m.name for m in methods]


def test_kotlin_parser_inheritance():
    source = b"""interface Runner { fun run() }
class Animal(val name: String) : Runner {
    override fun run() {}
}
"""
    result = KotlinParser().parse(file_path="main.kt", source=source)

    inherits = [e for e in result.edges if e.kind == EDGE_INHERITS]
    assert any(e.dst_name == "Runner" for e in inherits)


def test_kotlin_parser_calls():
    source = b"""fun test() {
    val a = Animal("cat")
    a.run()
    helper()
    println("hi")
}
"""
    result = KotlinParser().parse(file_path="test.kt", source=source)

    calls = [e for e in result.edges if e.kind == EDGE_CALLS]
    call_names = {e.dst_name for e in calls}
    assert "Animal" in call_names
    assert "run" in call_names
    assert "helper" in call_names
    assert "println" in call_names


def test_kotlin_parser_top_level_function():
    source = b"""fun topLevel() { println("hello") }
"""
    result = KotlinParser().parse(file_path="util.kt", source=source)
    functions = _by_kind(result.nodes, NODE_FUNCTION)
    assert [f.name for f in functions] == ["topLevel"]


def test_kotlin_package_qualifies_top_level_and_class_members():
    source = b"""package com.acme.billing
class Service { fun run() {} }
fun top() {}
"""
    result = KotlinParser().parse(file_path="Service.kt", source=source)
    qualified = {node.name: node.qualified_name for node in result.nodes}

    assert qualified["Service"] == "com.acme.billing.Service"
    assert qualified["run"] == "com.acme.billing.Service.run"
    assert qualified["top"] == "com.acme.billing.top"


# ── Registry integration ──────────────────────────────────────────────────────


def test_registry_resolves_c_cpp_swift_kotlin():
    registry = default_registry()
    assert registry.for_path("main.c").name == "c"
    assert registry.for_path("lib.h").name == "c"
    assert registry.for_path("main.cpp").name == "cpp"
    assert registry.for_path("lib.hpp").name == "cpp"
    assert registry.for_path("main.cc").name == "cpp"
    assert registry.for_path("main.swift").name == "swift"
    assert registry.for_path("main.kt").name == "kotlin"
    assert registry.for_path("script.kts").name == "kotlin"


# ── Cross-file indexing ───────────────────────────────────────────────────────


def test_cpp_cross_file_indexing(tmp_path: Path):
    from app.services.code_graph.indexer import index_workspace

    (tmp_path / "animal.hpp").write_bytes(
        b"class Animal { public: virtual void run() = 0; };\n"
    )
    (tmp_path / "main.cpp").write_bytes(
        b"void test() { Animal* a; a->run(); }\n"
    )
    idx = index_workspace(tmp_path)
    call_edges = [e for e in idx.edges if e.kind == "calls" and e.dst_key is not None]
    resolved_targets = {e.dst_key for e in call_edges}
    run_node = next((n for n in idx.nodes if n.name == "run"), None)
    assert run_node is not None
    assert run_node.key in resolved_targets


def test_swift_cross_file_indexing(tmp_path: Path):
    from app.services.code_graph.indexer import index_workspace

    (tmp_path / "animal.swift").write_bytes(
        b"class Animal { func run() {} }\n"
    )
    (tmp_path / "main.swift").write_bytes(
        b"func test() { let a = Animal(); a.run() }\n"
    )
    idx = index_workspace(tmp_path)
    call_edges = [e for e in idx.edges if e.kind == "calls" and e.dst_key is not None]
    resolved_targets = {e.dst_key for e in call_edges}
    run_node = next((n for n in idx.nodes if n.name == "run"), None)
    assert run_node is not None
    assert run_node.key in resolved_targets
