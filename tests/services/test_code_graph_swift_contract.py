"""Exact behavioral contracts for Swift graph extraction."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import cast

from tree_sitter import Node

from app.services.code_index.graph_types import (
    EDGE_CALLS,
    EDGE_DECORATED_BY,
    EDGE_IMPLEMENTS,
    EDGE_IMPORTS,
    EDGE_INHERITS,
    EDGE_REFERENCES,
    NODE_CLASS,
    NODE_ENUM,
    NODE_FIELD,
    NODE_INTERFACE,
    NODE_METHOD,
    NODE_PROPERTY,
    NODE_STRUCT,
    NODE_VARIABLE,
)
from app.services.code_index.parsers.swift import (
    SwiftParser,
    _collect_swift_type_ids,
    _inheritance_name,
    _preceding_comment,
    _swift_attr_name,
    _swift_declaration_kind,
    _swift_expression_path,
)


@dataclass
class _FakeNode:
    type: str
    start_byte: int = 0
    end_byte: int = 0
    parent: _FakeNode | None = None
    prev_named_sibling: _FakeNode | None = None
    children: list[_FakeNode] = field(default_factory=list)
    fields: dict[str, _FakeNode] = field(default_factory=dict)

    @property
    def named_children(self) -> list[_FakeNode]:
        return self.children

    def child_by_field_name(self, name: str) -> _FakeNode | None:
        return self.fields.get(name)


def _descendants(node: Node):
    for child in node.named_children:
        yield child
        yield from _descendants(child)


def _nodes_of_type(parser: SwiftParser, source: bytes, node_type: str):
    root = parser._get_parser().parse(source).root_node
    return [node for node in _descendants(root) if node.type == node_type]


def _named_edges(result, kind: str):
    names = {node.local_id: node.qualified_name for node in result.nodes}
    return [
        (names[edge.src_local_id], edge.dst_name)
        for edge in result.edges
        if edge.kind == kind and edge.dst_name is not None
    ]


def test_swift_symbols_types_calls_heritage_docs_and_attributes_are_exact() -> None:
    source = b"""import Foundation
///X Service docs X
///X second line X
@vendor.Service
final class Service<T>: Base, Runner {
 /*X state docs X*/
 @Field var state: State?
 let repo: Repo<T>
 init(repo: Repo<T>) { self.repo = repo }
 deinit {}
 subscript(index: Index) -> Item { get { items[index] } }
 func run(input: Input) -> Result<Output> {
   helper(); client.api.call(); self.local(); super.parent(); Factory.create()
 }
}
protocol Runner: Parent, Logging {
 var state: State { get }
 func run(input: Input) -> Result
}
struct User: Codable { let name: String; var config: Config }
enum State { case ready, done; var label: String { "x" } }
actor Worker: Runnable { func work() {} }
typealias Handler<T> = (T, Input) -> Output
let global: Config = Config()
"""
    result = SwiftParser().parse(file_path="Service.swift", source=source)
    nodes = {node.qualified_name: node for node in result.nodes}

    assert Counter(
        (node.kind, node.qualified_name) for node in result.nodes
    ) == Counter(
        {
            ("file", "Service.swift"): 1,
            (NODE_CLASS, "Service"): 1,
            (NODE_FIELD, "Service.state"): 1,
            (NODE_FIELD, "Service.repo"): 1,
            (NODE_METHOD, "Service.init"): 1,
            (NODE_METHOD, "Service.deinit"): 1,
            (NODE_METHOD, "Service.subscript"): 1,
            (NODE_METHOD, "Service.run"): 1,
            (NODE_INTERFACE, "Runner"): 1,
            (NODE_FIELD, "Runner.state"): 1,
            (NODE_METHOD, "Runner.run"): 1,
            (NODE_STRUCT, "User"): 1,
            (NODE_FIELD, "User.name"): 1,
            (NODE_FIELD, "User.config"): 1,
            (NODE_ENUM, "State"): 1,
            (NODE_PROPERTY, "State.ready"): 1,
            (NODE_PROPERTY, "State.done"): 1,
            (NODE_FIELD, "State.label"): 1,
            (NODE_CLASS, "Worker"): 1,
            (NODE_METHOD, "Worker.work"): 1,
            (NODE_CLASS, "Handler"): 1,
            (NODE_VARIABLE, "global"): 1,
        }
    )
    assert nodes["Service"].docstring == "X Service docs X\nX second line X"
    assert nodes["Service.state"].docstring == "X state docs X"
    assert _named_edges(result, EDGE_IMPORTS) == [("Service.swift", "Foundation")]
    assert _named_edges(result, EDGE_INHERITS) == [
        ("Service", "Base"),
        ("Runner", "Parent"),
        ("Runner", "Logging"),
    ]
    assert _named_edges(result, EDGE_IMPLEMENTS) == [
        ("Service", "Runner"),
        ("User", "Codable"),
        ("Worker", "Runnable"),
    ]
    assert _named_edges(result, EDGE_DECORATED_BY) == [
        ("Service", "Service"),
        ("Service.state", "Field"),
    ]
    assert _named_edges(result, EDGE_REFERENCES) == [
        ("Service.state", "State"),
        ("Service.repo", "Repo"),
        ("Service.init", "Repo"),
        ("Service.subscript", "Index"),
        ("Service.subscript", "Item"),
        ("Service.run", "Input"),
        ("Service.run", "Result"),
        ("Service.run", "Output"),
        ("Runner.state", "State"),
        ("Runner.run", "Input"),
        ("Runner.run", "Result"),
        ("User.config", "Config"),
        ("Handler", "Input"),
        ("Handler", "Output"),
        ("global", "Config"),
    ]
    assert _named_edges(result, EDGE_CALLS) == [
        ("Service.subscript", "items"),
        ("Service.run", "helper"),
        ("Service.run", "client.api.call"),
        ("Service.run", "this.local"),
        ("Service.run", "this.parent"),
        ("Service.run", "Factory.create"),
        ("global", "Config"),
    ]


def test_swift_top_level_symbols_and_generic_type_filtering_are_exact() -> None:
    source = b"""let config: Config = load()
func execute<T, R>(input: Input<T>) -> Result<R> { service.run() }
"""
    parser = SwiftParser()
    result = parser.parse(file_path="Script.swift", source=source)
    assert {(node.kind, node.qualified_name) for node in result.nodes} == {
        ("file", "Script.swift"),
        (NODE_VARIABLE, "config"),
        ("function", "execute"),
    }
    assert _named_edges(result, EDGE_REFERENCES) == [
        ("config", "Config"),
        ("execute", "Input"),
        ("execute", "Result"),
    ]
    assert _named_edges(result, EDGE_CALLS) == [
        ("config", "load"),
        ("execute", "service.run"),
    ]


def test_swift_expression_type_and_comment_helpers_are_exact() -> None:
    source = b"""/**
 * X docs X
 * second line
 */
func run(input: Vendor.Input) -> Vendor.Result { client.api.run() }
"""
    parser = SwiftParser()
    function = _nodes_of_type(parser, source, "function_declaration")[0]
    navigation = _nodes_of_type(parser, source, "navigation_expression")[0]
    user_type = _nodes_of_type(parser, source, "user_type")[0]
    root = parser._get_parser().parse(source).root_node
    out: list[str] = []
    _collect_swift_type_ids(user_type, source, out)

    assert _swift_expression_path(navigation, source) == "client.api.run"
    assert _swift_expression_path(root, source) is None
    assert out == ["Input"]
    assert _preceding_comment(function, source) == "X docs X\nsecond line"


def test_swift_first_line_doc_and_deep_scoped_import_are_exact() -> None:
    source = b"""///X first X
func first() {}
import struct UIKit.Components.View
"""
    parser = SwiftParser()
    function = _nodes_of_type(parser, source, "function_declaration")[0]
    result = parser.parse(file_path="First.swift", source=source)
    assert _preceding_comment(function, source) == "X first X"
    assert _named_edges(result, EDGE_IMPORTS) == [("First.swift", "View")]


def test_swift_non_matching_nodes_do_not_emit_language_hooks() -> None:
    parser = SwiftParser()
    source = b"print(1)"
    root = parser._get_parser().parse(source).root_node
    assert parser.classify(root, source, inside_class=False) is None
    assert parser.synthetic_definitions(root, source, inside_class=False) == []
    assert parser.call_target(root, source) is None
    assert parser.supertypes(root, source) == []
    assert parser.import_refs(root, source) == []
    assert parser.decorators(root, source) == []
    assert parser.type_refs(root, source) == []
    assert parser.docstring(root, source) is None


def test_swift_malformed_hook_inputs_fail_closed() -> None:
    parser = SwiftParser()
    import_node = _FakeNode("import_declaration")
    function = _FakeNode("function_declaration")
    empty_pattern = _FakeNode("pattern")
    property_node = _FakeNode("property_declaration", children=[empty_pattern])
    target = _FakeNode("simple_identifier", start_byte=0, end_byte=3)
    suffix = _FakeNode("navigation_suffix")
    navigation = _FakeNode(
        "navigation_expression",
        children=[target, suffix],
        fields={"target": target, "suffix": suffix},
    )
    unknown = _FakeNode("unknown")

    assert parser.import_refs(cast(Node, import_node), b"") == []
    assert parser.classify(cast(Node, function), b"", inside_class=False) is None
    assert parser.classify(cast(Node, property_node), b"", inside_class=True) is None
    assert parser.type_refs(cast(Node, property_node), b"") == []
    assert _swift_expression_path(cast(Node, navigation), b"foo") == "foo"
    assert _swift_declaration_kind(cast(Node, unknown)) == "class"
    assert _inheritance_name(cast(Node, unknown), b"") is None
    assert _swift_attr_name(cast(Node, unknown), b"") is None
