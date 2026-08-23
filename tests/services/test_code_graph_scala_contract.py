"""Exact behavioral contracts for Scala graph extraction."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import cast

from tree_sitter import Node

from app.services.code_index.graph_types import (
    EDGE_CALLS,
    EDGE_DECORATED_BY,
    EDGE_IMPLEMENTS,
    EDGE_INHERITS,
    EDGE_REFERENCES,
    NODE_CLASS,
    NODE_ENUM,
    NODE_FIELD,
    NODE_INTERFACE,
    NODE_METHOD,
    NODE_NAMESPACE,
    NODE_PROPERTY,
    NODE_VARIABLE,
)
from app.services.code_index.parsers.scala import (
    ScalaParser,
    _collect_scala_type_ids,
    _scala_annotation_name,
    _scala_expression_path,
    _scala_type_name,
    _strip_scaladoc,
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


def _nodes_of_type(parser: ScalaParser, source: bytes, node_type: str):
    root = parser._get_parser().parse(source).root_node
    return [node for node in _descendants(root) if node.type == node_type]


def _named_edges(result, kind: str):
    names = {node.local_id: node.qualified_name for node in result.nodes}
    return [
        (names[edge.src_local_id], edge.dst_name)
        for edge in result.edges
        if edge.kind == kind and edge.dst_name is not None
    ]


def test_scala_symbols_types_calls_heritage_docs_and_annotations_are_exact() -> None:
    source = b'''package demo.core
/** Service docs */
@Service
case class Service[T](repo: Repo[T], config: Config) extends Base[T] with Runner {
 /** State docs */
 @Field val state: State = State.Ready
 var count: Count = Count()
 def run(input: Input): Result[Output] = {
   helper(); client.api.call(); this.local(); super.parent(); Factory.create[Item]()
 }
}
trait Runner extends Parent { def run(input: Input): Result }
object Registry extends Runner { val item: Item = Item() }
enum State { case Ready, Done }
type Handler[T] = T => Output
val global: Config = Config()
'''
    result = ScalaParser().parse(file_path="Service.scala", source=source)
    nodes = {node.qualified_name: node for node in result.nodes}

    assert Counter((node.kind, node.qualified_name) for node in result.nodes) == Counter(
        {
            ("file", "Service.scala"): 1,
            (NODE_NAMESPACE, "demo.core"): 1,
            (NODE_CLASS, "demo.core.Service"): 1,
            (NODE_FIELD, "demo.core.Service.repo"): 1,
            (NODE_FIELD, "demo.core.Service.config"): 1,
            (NODE_FIELD, "demo.core.Service.state"): 1,
            (NODE_FIELD, "demo.core.Service.count"): 1,
            (NODE_METHOD, "demo.core.Service.run"): 1,
            (NODE_INTERFACE, "demo.core.Runner"): 1,
            (NODE_METHOD, "demo.core.Runner.run"): 1,
            (NODE_CLASS, "demo.core.Registry"): 1,
            (NODE_FIELD, "demo.core.Registry.item"): 1,
            (NODE_ENUM, "demo.core.State"): 1,
            (NODE_PROPERTY, "demo.core.State.Ready"): 1,
            (NODE_PROPERTY, "demo.core.State.Done"): 1,
            (NODE_CLASS, "demo.core.Handler"): 1,
            (NODE_VARIABLE, "demo.core.global"): 1,
        }
    )
    assert nodes["demo.core.Service"].docstring == "Service docs"
    assert nodes["demo.core.Service.state"].docstring == "State docs"
    assert _named_edges(result, EDGE_INHERITS) == [
        ("demo.core.Service", "Base"),
        ("demo.core.Runner", "Parent"),
    ]
    assert _named_edges(result, EDGE_IMPLEMENTS) == [
        ("demo.core.Service", "Runner"),
        ("demo.core.Registry", "Runner"),
    ]
    assert _named_edges(result, EDGE_DECORATED_BY) == [
        ("demo.core.Service", "Service"),
        ("demo.core.Service.state", "Field"),
    ]
    assert _named_edges(result, EDGE_REFERENCES) == [
        ("demo.core.Service.repo", "Repo"),
        ("demo.core.Service.config", "Config"),
        ("demo.core.Service.state", "State"),
        ("demo.core.Service.state", "Ready"),
        ("demo.core.Service.count", "Count"),
        ("demo.core.Service.run", "Input"),
        ("demo.core.Service.run", "Result"),
        ("demo.core.Service.run", "Output"),
        ("demo.core.Runner.run", "Input"),
        ("demo.core.Runner.run", "Result"),
        ("demo.core.Registry.item", "Item"),
        ("demo.core.Handler", "Output"),
        ("demo.core.global", "Config"),
    ]
    assert _named_edges(result, EDGE_CALLS) == [
        ("demo.core.Service.count", "Count"),
        ("demo.core.Service.run", "helper"),
        ("demo.core.Service.run", "client.api.call"),
        ("demo.core.Service.run", "this.local"),
        ("demo.core.Service.run", "this.parent"),
        ("demo.core.Service.run", "Factory.create"),
        ("demo.core.Registry.item", "Item"),
        ("demo.core.global", "Config"),
    ]


def test_scala_top_level_function_and_generic_type_filtering_are_exact() -> None:
    source = b'''val config: Config = load()
def execute[T, R](input: Input[T]): Result[R] = service.run()
'''
    parser = ScalaParser()
    result = parser.parse(file_path="script.sc", source=source)
    assert {(node.kind, node.qualified_name) for node in result.nodes} == {
        ("file", "script.sc"),
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


def test_scala_expression_type_and_scaladoc_helpers_are_exact() -> None:
    source = b'''/**
 * X docs X
 * @param input ignored
 * second line
 */
def run(input: Vendor.Input): Vendor.Result = client.api.run()
'''
    parser = ScalaParser()
    function = _nodes_of_type(parser, source, "function_definition")[0]
    field = _nodes_of_type(parser, source, "field_expression")[0]
    generic_source = b"val value: Repo[Item] = ???"
    generic = _nodes_of_type(parser, generic_source, "generic_type")[0]
    type_id = _nodes_of_type(parser, source, "type_identifier")[0]
    root = parser._get_parser().parse(source).root_node
    out: list[str] = []
    _collect_scala_type_ids(generic, generic_source, out)

    assert _scala_expression_path(field, source) == "client.api.run"
    assert _scala_expression_path(root, source) is None
    assert _scala_type_name(type_id, source) == "Input"
    assert _scala_type_name(root, source) is None
    assert out == ["Repo", "Item"]
    assert _strip_scaladoc(
        "/**\n * X docs X\n * @param input ignored\n * second line\n */"
    ) == "X docs X\nsecond line"
    assert _strip_scaladoc("/**X compact X*/") == "X compact X"
    assert function is not None


def test_scala_import_metadata_is_exact() -> None:
    source = b'''import alpha.beta.gamma.Target
import tools.syntax._
import source.pkg.{Original => Alias}
'''
    result = ScalaParser().parse(file_path="Imports.scala", source=source)
    assert [
        (edge.dst_name, edge.module_path, edge.local_name)
        for edge in result.edges
        if edge.kind == "imports"
    ] == [
        ("Target", "alpha.beta.gamma.Target", "Target"),
        ("*", "tools.syntax.*", "*"),
        ("Original", "source.pkg", "Alias"),
    ]


def test_scala_braced_package_never_becomes_a_root_prefix() -> None:
    source = b"package demo { class Box }"
    parser = ScalaParser()
    root = parser._get_parser().parse(source).root_node
    assert parser.root_prefix(root, source) == ""
    result = parser.parse(file_path="Box.scala", source=source)
    assert {(node.kind, node.qualified_name) for node in result.nodes} == {
        ("file", "Box.scala"),
        (NODE_NAMESPACE, "demo"),
        (NODE_CLASS, "demo.Box"),
    }


def test_scala_non_matching_nodes_do_not_emit_language_hooks() -> None:
    parser = ScalaParser()
    source = b"println(1)"
    root = parser._get_parser().parse(source).root_node
    assert parser.classify(root, source, inside_class=False) is None
    assert parser.call_target(root, source) is None
    assert parser.supertypes(root, source) == []
    assert parser.import_refs(root, source) == []
    assert parser.decorators(root, source) == []
    assert parser.type_refs(root, source) == []
    assert parser.docstring(root, source) is None


def test_scala_malformed_hook_inputs_fail_closed() -> None:
    parser = ScalaParser()
    package = _FakeNode("package_clause")
    fake_root = _FakeNode("compilation_unit", children=[package])
    function = _FakeNode("function_definition")
    wrong_pattern = _FakeNode("pattern")
    value = _FakeNode("val_definition", fields={"pattern": wrong_pattern})
    annotation = _FakeNode("annotation")

    assert parser.root_prefix(cast(Node, fake_root), b"") == ""
    assert parser.type_refs(cast(Node, function), b"") == []
    assert parser._val_name(cast(Node, value), b"") is None
    assert _scala_annotation_name(cast(Node, annotation), b"") is None
