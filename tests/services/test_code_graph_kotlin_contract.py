"""Exact behavioral contracts for Kotlin graph extraction."""

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
    NODE_VARIABLE,
)
from app.services.code_index.parsers.kotlin import (
    KotlinParser,
    _collect_kt_type_ids,
    _kt_annotation_name,
    _kt_declared_type,
    _kt_expression_path,
    _preceding_comment,
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


def _nodes_of_type(parser: KotlinParser, source: bytes, node_type: str):
    root = parser._get_parser().parse(source).root_node
    return [node for node in _descendants(root) if node.type == node_type]


def _named_edges(result, kind: str):
    names = {node.local_id: node.qualified_name for node in result.nodes}
    return [
        (names[edge.src_local_id], edge.dst_name)
        for edge in result.edges
        if edge.kind == kind and edge.dst_name is not None
    ]


def test_kotlin_symbols_types_calls_heritage_docs_and_attributes_are_exact() -> None:
    source = b'''package demo.core
import vendor.Repo as R
/** Service docs */
@vendor.Service()
class Service<T>(private val repo: Repo<T>, var config: Config?) : Base<T>(), Runner {
 /** State docs */
 @Field val state: State = State.Ready
 fun run(input: Input): Result<Output> {
   helper()
   client.api.call()
   this.local()
   super.parent()
   Factory.create<Item>()
 }
}
interface Runner : Parent { fun run(input: Input): Result }
enum class State { Ready, Done }
data class User(val name: String, val config: Config)
typealias Handler = (Input) -> Output
val global: Config = Config()
object Registry { val item: Item = Item() }
class Delegating(val closeable: Closeable) : Closeable by closeable
class Plain(input: Input)
'''
    result = KotlinParser().parse(file_path="Service.kt", source=source)
    nodes = {node.qualified_name: node for node in result.nodes}

    assert Counter((node.kind, node.qualified_name) for node in result.nodes) == Counter(
        {
            ("file", "Service.kt"): 1,
            (NODE_CLASS, "demo.core.Service"): 1,
            (NODE_FIELD, "demo.core.Service.repo"): 1,
            (NODE_FIELD, "demo.core.Service.config"): 1,
            (NODE_FIELD, "demo.core.Service.state"): 1,
            (NODE_METHOD, "demo.core.Service.run"): 1,
            (NODE_INTERFACE, "demo.core.Runner"): 1,
            (NODE_METHOD, "demo.core.Runner.run"): 1,
            (NODE_ENUM, "demo.core.State"): 1,
            (NODE_PROPERTY, "demo.core.State.Ready"): 1,
            (NODE_PROPERTY, "demo.core.State.Done"): 1,
            (NODE_CLASS, "demo.core.User"): 1,
            (NODE_FIELD, "demo.core.User.name"): 1,
            (NODE_FIELD, "demo.core.User.config"): 1,
            (NODE_CLASS, "demo.core.Handler"): 1,
            (NODE_VARIABLE, "demo.core.global"): 1,
            (NODE_CLASS, "demo.core.Registry"): 1,
            (NODE_FIELD, "demo.core.Registry.item"): 1,
            (NODE_CLASS, "demo.core.Delegating"): 1,
            (NODE_FIELD, "demo.core.Delegating.closeable"): 1,
            (NODE_CLASS, "demo.core.Plain"): 1,
        }
    )
    assert nodes["demo.core.Service"].docstring == "Service docs"
    assert nodes["demo.core.Service.state"].docstring == "State docs"
    assert _named_edges(result, EDGE_IMPORTS) == [("Service.kt", "Repo")]
    assert _named_edges(result, EDGE_INHERITS) == [
        ("demo.core.Service", "Base"),
        ("demo.core.Runner", "Parent"),
    ]
    assert _named_edges(result, EDGE_IMPLEMENTS) == [
        ("demo.core.Service", "Runner"),
        ("demo.core.Delegating", "Closeable"),
    ]
    assert _named_edges(result, EDGE_DECORATED_BY) == [
        ("demo.core.Service", "Service"),
        ("demo.core.Service.state", "Field"),
    ]
    assert _named_edges(result, EDGE_REFERENCES) == [
        ("demo.core.Service.repo", "Repo"),
        ("demo.core.Service.config", "Config"),
        ("demo.core.Service.state", "State"),
        ("demo.core.Service.run", "Input"),
        ("demo.core.Service.run", "Result"),
        ("demo.core.Service.run", "Output"),
        ("demo.core.Runner.run", "Input"),
        ("demo.core.Runner.run", "Result"),
        ("demo.core.User.config", "Config"),
        ("demo.core.Handler", "Input"),
        ("demo.core.Handler", "Output"),
        ("demo.core.global", "Config"),
        ("demo.core.Registry.item", "Item"),
        ("demo.core.Delegating.closeable", "Closeable"),
    ]
    assert _named_edges(result, EDGE_CALLS) == [
        ("demo.core.Service.run", "helper"),
        ("demo.core.Service.run", "client.api.call"),
        ("demo.core.Service.run", "this.local"),
        ("demo.core.Service.run", "this.parent"),
        ("demo.core.Service.run", "Factory.create"),
        ("demo.core.global", "Config"),
        ("demo.core.Registry.item", "Item"),
    ]


def test_kotlin_top_level_functions_and_properties_stay_outside_classes() -> None:
    source = b'''/** file docs */
package scripts
val config: Config = load()
fun execute(input: Input?): Result = service.run(input)
'''
    result = KotlinParser().parse(file_path="build.kts", source=source)
    assert {(node.kind, node.qualified_name) for node in result.nodes} == {
        ("file", "build.kts"),
        (NODE_VARIABLE, "scripts.config"),
        ("function", "scripts.execute"),
    }
    assert _named_edges(result, EDGE_REFERENCES) == [
        ("scripts.config", "Config"),
        ("scripts.execute", "Input"),
        ("scripts.execute", "Result"),
    ]
    assert _named_edges(result, EDGE_CALLS) == [
        ("scripts.config", "load"),
        ("scripts.execute", "service.run"),
    ]


def test_kotlin_type_hooks_filter_builtins_and_enclosing_type_parameters() -> None:
    source = b'''class Box<T>(val value: T, val repo: Repo<T>) {
 fun <R> map(input: Input<R>): Result<T> = TODO()
}
'''
    parser = KotlinParser()
    fields = _nodes_of_type(parser, source, "class_parameter")
    method = _nodes_of_type(parser, source, "function_declaration")[0]
    assert parser.type_refs(fields[0], source) == []
    assert parser.type_refs(fields[1], source) == ["Repo"]
    assert parser.type_refs(method, source) == ["Input", "Result"]


def test_kotlin_expression_type_and_comment_helpers_are_exact() -> None:
    source = b'''/**
 * X docs X
 * second line
 */
fun run(input: Vendor.Input): Vendor.Result = client.api.run()
/*X regular X*/
fun regular(): Result = helper()
'''
    parser = KotlinParser()
    function = _nodes_of_type(parser, source, "function_declaration")[0]
    regular = _nodes_of_type(parser, source, "function_declaration")[1]
    navigation = _nodes_of_type(parser, source, "navigation_expression")[0]
    user_type = _nodes_of_type(parser, source, "user_type")[0]
    root = parser._get_parser().parse(source).root_node
    out: list[str] = []
    _collect_kt_type_ids(user_type, source, out)

    assert _kt_expression_path(navigation, source) == "client.api.run"
    assert _kt_expression_path(root, source) is None
    assert out == ["Input"]
    assert _preceding_comment(function, source) == "X docs X\nsecond line"
    assert _preceding_comment(regular, source) == "X regular X"


def test_kotlin_non_matching_nodes_do_not_emit_language_hooks() -> None:
    parser = KotlinParser()
    source = b"println(1)"
    root = parser._get_parser().parse(source).root_node
    assert parser.root_prefix(root, source) == ""
    assert parser.classify(root, source, inside_class=False) is None
    assert parser.call_target(root, source) is None
    assert parser.supertypes(root, source) == []
    assert parser.import_refs(root, source) == []
    assert parser.decorators(root, source) == []
    assert parser.type_refs(root, source) == []
    assert parser.docstring(root, source) is None


def test_kotlin_malformed_hook_inputs_fail_closed() -> None:
    parser = KotlinParser()
    package = _FakeNode("package_header")
    fake_root = _FakeNode("source_file", children=[_FakeNode("comment"), package])
    object_literal = _FakeNode("object_literal")
    malformed_object = _FakeNode("infix_expression", children=[object_literal])
    import_header = _FakeNode("import_header")
    path = _FakeNode("identifier", start_byte=0, end_byte=3)
    alias = _FakeNode("import_alias")
    malformed_alias = _FakeNode("import_header", children=[path, alias])
    property_node = _FakeNode("property_declaration")
    navigation = _FakeNode("navigation_expression")
    receiver = _FakeNode("simple_identifier", start_byte=0, end_byte=3)
    empty_suffix = _FakeNode("navigation_suffix")
    partial_navigation = _FakeNode(
        "navigation_expression", children=[receiver, empty_suffix]
    )
    annotation = _FakeNode("annotation")

    assert parser.root_prefix(cast(Node, fake_root), b"") == ""
    assert parser.classify(
        cast(Node, malformed_object), b"", inside_class=False
    ) is None
    assert parser.import_refs(cast(Node, import_header), b"") == []
    assert parser.import_refs(cast(Node, malformed_alias), b"foo")[0].local_name is None
    assert parser.type_refs(cast(Node, property_node), b"") == []
    assert parser._property_name(cast(Node, property_node), b"") is None
    assert _kt_expression_path(cast(Node, navigation), b"") is None
    assert _kt_expression_path(cast(Node, partial_navigation), b"foo") == "foo"
    assert _kt_declared_type(cast(Node, property_node)) is None
    assert _kt_annotation_name(cast(Node, annotation), b"") is None
