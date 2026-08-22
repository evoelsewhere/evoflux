"""Exact behavioral contracts for C and C++ graph extraction."""

from __future__ import annotations

from collections import Counter

from tree_sitter import Node

from app.services.code_index.graph_types import (
    EDGE_CALLS,
    EDGE_DECORATED_BY,
    EDGE_IMPORTS,
    EDGE_INHERITS,
    EDGE_REFERENCES,
    NODE_CLASS,
    NODE_ENUM,
    NODE_FIELD,
    NODE_FUNCTION,
    NODE_METHOD,
    NODE_NAMESPACE,
    NODE_PROPERTY,
    NODE_STRUCT,
    NODE_VARIABLE,
)
from app.services.code_index.parsers.c_family import (
    CParser,
    CppParser,
    _collect_c_type_ids,
    _contains_node_type,
    _looks_like_class_scope,
    _same_node,
    _simple_c_type_name,
)


def _descendants(node: Node):
    for child in node.named_children:
        yield child
        yield from _descendants(child)


def _nodes_of_type(parser: CParser | CppParser, source: bytes, node_type: str):
    root = parser._get_parser().parse(source).root_node
    return [node for node in _descendants(root) if node.type == node_type]


def _named_edges(result, kind: str):
    names = {node.local_id: node.qualified_name for node in result.nodes}
    return [
        (names[edge.src_local_id], edge.dst_name)
        for edge in result.edges
        if edge.kind == kind and edge.dst_name is not None
    ]


def test_c_symbols_ownership_types_calls_and_docs_are_exact() -> None:
    source = b'''#include <stdio.h>
/** Point docs */
typedef struct Point { int x, y; } Point;
typedef struct { /** Value docs */ Config value; } Box;
typedef int Count;
typedef int *CountPtr;
typedef void (*Callback)(Config);
/** Union docs */
typedef union Value { int integer; float decimal; } Value;
typedef union { int integer; } Any;
typedef enum { Auto, Manual } Mode;
/** Tagged docs */
typedef enum Tagged { On, Off } Tagged;
/** State docs */
enum State { Idle, Running = 2 };
enum { Anonymous };
/** Global docs */
static Config global;
int first, second = 2;
Result process(struct Repo *repo, Config config);
void inspect(union Value value, enum State state);
Result process(struct Repo *repo, Config config) {
  int local;
  helper();
  repo->save();
}
'''
    result = CParser().parse(file_path="sample.c", source=source)
    nodes = {node.qualified_name: node for node in result.nodes}

    assert Counter((node.kind, node.qualified_name) for node in result.nodes) == Counter(
        {
            ("file", "sample.c"): 1,
            (NODE_STRUCT, "Point"): 1,
            (NODE_FIELD, "Point.x"): 1,
            (NODE_FIELD, "Point.y"): 1,
            (NODE_STRUCT, "Box"): 1,
            (NODE_FIELD, "Box.value"): 1,
            (NODE_CLASS, "Count"): 1,
            (NODE_CLASS, "CountPtr"): 1,
            (NODE_CLASS, "Callback"): 1,
            (NODE_STRUCT, "Value"): 1,
            (NODE_FIELD, "Value.integer"): 1,
            (NODE_FIELD, "Value.decimal"): 1,
            (NODE_STRUCT, "Any"): 1,
            (NODE_FIELD, "Any.integer"): 1,
            (NODE_ENUM, "Mode"): 1,
            (NODE_PROPERTY, "Mode.Auto"): 1,
            (NODE_PROPERTY, "Mode.Manual"): 1,
            (NODE_ENUM, "Tagged"): 1,
            (NODE_PROPERTY, "Tagged.On"): 1,
            (NODE_PROPERTY, "Tagged.Off"): 1,
            (NODE_ENUM, "State"): 1,
            (NODE_PROPERTY, "State.Idle"): 1,
            (NODE_PROPERTY, "State.Running"): 1,
            (NODE_VARIABLE, "global"): 1,
            (NODE_VARIABLE, "first"): 1,
            (NODE_VARIABLE, "second"): 1,
            (NODE_FUNCTION, "process"): 2,
            (NODE_FUNCTION, "inspect"): 1,
        }
    )
    assert "local" not in nodes
    assert nodes["Point"].docstring == "Point docs"
    assert nodes["Box.value"].docstring == "Value docs"
    assert nodes["Value"].docstring == "Union docs"
    assert nodes["State"].docstring == "State docs"
    assert nodes["Tagged"].docstring == "Tagged docs"
    assert nodes["global"].docstring == "Global docs"
    assert _named_edges(result, EDGE_IMPORTS) == [("sample.c", "stdio.h")]
    assert _named_edges(result, EDGE_REFERENCES) == [
        ("Box.value", "Config"),
        ("Callback", "Config"),
        ("global", "Config"),
        ("process", "Result"),
        ("process", "Repo"),
        ("process", "Config"),
        ("inspect", "Value"),
        ("inspect", "State"),
        ("process", "Result"),
        ("process", "Repo"),
        ("process", "Config"),
    ]
    assert _named_edges(result, EDGE_CALLS) == [
        ("process", "helper"),
        ("process", "repo.save"),
    ]


def test_cpp_symbols_scoped_methods_templates_calls_and_heritage_are_exact() -> None:
    source = b'''#include "service.hpp"
namespace demo::core {
/// Service docs
class Service : public Base, private ns::Mixin {
 public:
  Service();
  ~Service();
  virtual Result<Item> run(const Request& request) = 0;
  int count;
  Config config;
};
Config global{};
extern "C" { Config linked; }
Result Outer::Inner::later(Config value);
Result<Item> Service::run(const Request& request) {
  client.api().call();
  Base::create();
  make<Item>();
  new Widget();
}
}
'''
    result = CppParser().parse(file_path="sample.cpp", source=source)
    nodes = {node.qualified_name: node for node in result.nodes}

    assert Counter((node.kind, node.qualified_name) for node in result.nodes) == Counter(
        {
            ("file", "sample.cpp"): 1,
            (NODE_NAMESPACE, "demo.core"): 1,
            (NODE_CLASS, "demo.core.Service"): 1,
            (NODE_METHOD, "demo.core.Service.Service"): 1,
            (NODE_METHOD, "demo.core.Service.~Service"): 1,
            (NODE_METHOD, "demo.core.Service.run"): 2,
            (NODE_FIELD, "demo.core.Service.count"): 1,
            (NODE_FIELD, "demo.core.Service.config"): 1,
            (NODE_VARIABLE, "demo.core.global"): 1,
            (NODE_VARIABLE, "demo.core.linked"): 1,
            (NODE_METHOD, "demo.core.Outer.Inner.later"): 1,
        }
    )
    assert nodes["demo.core.Service"].docstring == "Service docs"
    assert _named_edges(result, EDGE_INHERITS) == [
        ("demo.core.Service", "Base"),
        ("demo.core.Service", "ns.Mixin"),
    ]
    assert _named_edges(result, EDGE_REFERENCES) == [
        ("demo.core.Service.run", "Result"),
        ("demo.core.Service.run", "Item"),
        ("demo.core.Service.run", "Request"),
        ("demo.core.Service.config", "Config"),
        ("demo.core.global", "Config"),
        ("demo.core.linked", "Config"),
        ("demo.core.Outer.Inner.later", "Result"),
        ("demo.core.Outer.Inner.later", "Config"),
        ("demo.core.Service.run", "Result"),
        ("demo.core.Service.run", "Item"),
        ("demo.core.Service.run", "Request"),
    ]
    assert _named_edges(result, EDGE_CALLS) == [
        ("demo.core.Service.run", "client.api.call"),
        ("demo.core.Service.run", "client.api"),
        ("demo.core.Service.run", "Base.create"),
        ("demo.core.Service.run", "make"),
        ("demo.core.Service.run", "Widget"),
    ]


def test_c_and_cpp_multiline_docs_and_attributes_are_exact() -> None:
    c_source = b'''/// First line
/// Second line
__attribute__((cold, aligned(16))) Result work(Config input) { return helper(); }
'''
    cpp_source = b'''/**
 * Build docs
 * second line
 */
[[deprecated, nodiscard]] Result build(Config input) { return Result{}; }
__declspec(noinline) void win();
'''
    c_result = CParser().parse(file_path="docs.c", source=c_source)
    cpp_result = CppParser().parse(file_path="docs.cpp", source=cpp_source)
    c_node = next(node for node in c_result.nodes if node.name == "work")
    cpp_node = next(node for node in cpp_result.nodes if node.name == "build")

    assert c_node.docstring == "First line\nSecond line"
    assert cpp_node.docstring == "Build docs\nsecond line"
    assert _named_edges(c_result, EDGE_DECORATED_BY) == [
        ("work", "cold"),
        ("work", "aligned"),
    ]
    assert _named_edges(cpp_result, EDGE_DECORATED_BY) == [
        ("build", "deprecated"),
        ("build", "nodiscard"),
        ("win", "noinline"),
    ]


def test_c_family_include_delimiters_and_deep_paths_are_exact() -> None:
    source = b'''#include <XvectorX>
#include "one/two/widget.h"
'''
    result = CppParser().parse(file_path="includes.cpp", source=source)
    assert [
        (edge.dst_name, edge.module_path)
        for edge in result.edges
        if edge.kind == EDGE_IMPORTS
    ] == [("XvectorX", "XvectorX"), ("widget.h", "one/two/widget.h")]


def test_c_family_compact_and_regular_block_docs_preserve_boundary_text() -> None:
    source = b'''/**XdocsX*/
void compact();
/*YplainY*/
void plain();
///XlineX
void line();
'''
    result = CParser().parse(file_path="compact.c", source=source)
    docs = {node.name: node.docstring for node in result.nodes}
    assert docs["compact"] == "XdocsX"
    assert docs["plain"] == "YplainY"
    assert docs["line"] == "XlineX"


def test_c_family_non_matching_nodes_do_not_emit_language_hooks() -> None:
    parser = CppParser()
    source = b"class Empty {};"
    root = parser._get_parser().parse(source).root_node

    assert parser.classify(root, source, inside_class=False) is None
    assert parser.call_target(root, source) is None
    assert parser.supertypes(root, source) == []
    assert parser.import_refs(root, source) == []
    assert parser.decorators(root, source) == []
    assert parser.type_refs(root, source) == []
    assert parser.docstring(root, source) is None


def test_c_family_direct_type_hooks_cover_fields_prototypes_and_templates() -> None:
    source = b'''namespace demo {
class Service {
  ns::Result<Item> run(const Request& request);
  Config field;
  std::array<int, N> values;
};
}
'''
    parser = CppParser()
    field = next(
        node
        for node in _nodes_of_type(parser, source, "field_identifier")
        if source[node.start_byte : node.end_byte] == b"field"
    )
    method = next(
        node
        for node in _nodes_of_type(parser, source, "field_declaration")
        if b"run" in source[node.start_byte : node.end_byte]
    )
    values = next(
        node
        for node in _nodes_of_type(parser, source, "field_identifier")
        if source[node.start_byte : node.end_byte] == b"values"
    )

    assert parser.type_refs(field, source) == ["Config"]
    assert parser.type_refs(values, source) == ["array", "N"]
    assert parser.type_refs(method, source) == ["Result", "Item", "Request"]


def test_c_inline_aggregate_type_refs_do_not_leak_member_types() -> None:
    source = b"union Inline { Config nested; } inline_value;"
    parser = CParser()
    variable = next(
        node
        for node in _nodes_of_type(parser, source, "identifier")
        if source[node.start_byte : node.end_byte] == b"inline_value"
    )
    assert parser.type_refs(variable, source) == ["Inline"]


def test_c_family_helper_boundaries_are_exact() -> None:
    source = b'''Config global{};
int *pointer;
std::vector<Item> items;
struct Shape *shape;
union Payload *payload;
enum State state;
void run();
void create() { make<Item>(); new ns::Widget(); }
'''
    parser = CppParser()
    root = parser._get_parser().parse(source).root_node
    init = _nodes_of_type(parser, source, "init_declarator")[0]
    global_name = next(
        node
        for node in _nodes_of_type(parser, source, "identifier")
        if source[node.start_byte : node.end_byte] == b"global"
    )
    pointer = _nodes_of_type(parser, source, "pointer_declarator")[0]
    pointer_name = next(
        node
        for node in _nodes_of_type(parser, source, "identifier")
        if source[node.start_byte : node.end_byte] == b"pointer"
    )
    function_declarator = _nodes_of_type(parser, source, "function_declarator")[0]
    qualified = _nodes_of_type(parser, source, "qualified_identifier")[0]
    template_type = _nodes_of_type(parser, source, "template_type")[0]
    template_function = _nodes_of_type(parser, source, "template_function")[0]
    struct_type = _nodes_of_type(parser, source, "struct_specifier")[0]
    union_type = _nodes_of_type(parser, source, "union_specifier")[0]
    enum_type = _nodes_of_type(parser, source, "enum_specifier")[0]

    assert not _same_node(global_name, init)
    assert not _same_node(pointer_name, pointer)
    assert _same_node(global_name, global_name)
    assert not _same_node(None, global_name)
    assert _contains_node_type(function_declarator, "identifier")
    assert not _contains_node_type(function_declarator, "enumerator")
    assert not _contains_node_type(None, "identifier")
    assert _simple_c_type_name(global_name, source) == "global"
    assert _simple_c_type_name(qualified, source) == "vector"
    assert _simple_c_type_name(template_type, source) == "vector"
    assert _simple_c_type_name(template_function, source) == "make"
    assert _simple_c_type_name(struct_type, source) == "Shape"
    assert _simple_c_type_name(union_type, source) == "Payload"
    assert _simple_c_type_name(enum_type, source) == "State"
    assert _simple_c_type_name(root, source) is None
    collected: list[str] = []
    _collect_c_type_ids(global_name, source, collected)
    assert collected == ["global"]

    assert _looks_like_class_scope("Service")
    assert _looks_like_class_scope("outer.Inner")
    assert not _looks_like_class_scope("service")
    assert not _looks_like_class_scope("outer.inner")
    assert not _looks_like_class_scope("")
