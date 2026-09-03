"""Exact behavioral contracts for Dart graph extraction."""

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
    NODE_METHOD,
    NODE_PROPERTY,
    NODE_VARIABLE,
)
from app.services.code_index.parsers.dart import (
    DartParser,
    _collect_dart_type_ids,
    _dart_identifier_descendants,
    _dart_local_name,
    _dart_type_name,
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


def _nodes_of_type(parser: DartParser, source: bytes, node_type: str):
    root = parser._get_parser().parse(source).root_node
    return [node for node in _descendants(root) if node.type == node_type]


def _named_edges(result, kind: str):
    names = {node.local_id: node.qualified_name for node in result.nodes}
    return [
        (names[edge.src_local_id], edge.dst_name)
        for edge in result.edges
        if edge.kind == kind and edge.dst_name is not None
    ]


def test_dart_symbols_types_calls_heritage_docs_and_attributes_are_exact() -> None:
    source = b"""import 'package:app/repo.dart' as repo;
///X Service docs X
///X second line X
@Service()
class Service<T> extends Base<T> with Logger implements Runner, Closeable {
 ///X state docs X
 @Primary()
 @Field() final State state;
 final Repo<T> repo;
 final Map<Key, Value> mapping;
 Service(this.repo, {required this.state});
 Result<Output> run(Input input) {
   helper(); client.api.call(); this.local(); super.api.parent(); Factory.create<Item>();
 }
 Config get config => Config();
 set config(Config value) {}
 void finish() { done(); }
}
mixin Logger { void log() {} }
extension ServiceExt on Service { void extra() {} }
enum State { ready, done }
class User { final String name; final Config config; User(this.name, this.config); }
typedef Handler = Output Function(Input);
final Config global = Config();
"""
    result = DartParser().parse(file_path="Service.dart", source=source)
    nodes = {node.qualified_name: node for node in result.nodes}

    assert Counter(
        (node.kind, node.qualified_name) for node in result.nodes
    ) == Counter(
        {
            ("file", "Service.dart"): 1,
            (NODE_CLASS, "Service"): 1,
            (NODE_FIELD, "Service.state"): 1,
            (NODE_FIELD, "Service.repo"): 1,
            (NODE_FIELD, "Service.mapping"): 1,
            (NODE_METHOD, "Service.Service"): 1,
            (NODE_METHOD, "Service.run"): 1,
            (NODE_METHOD, "Service.config"): 2,
            (NODE_METHOD, "Service.finish"): 1,
            (NODE_CLASS, "Logger"): 1,
            (NODE_METHOD, "Logger.log"): 1,
            (NODE_CLASS, "ServiceExt"): 1,
            (NODE_METHOD, "ServiceExt.extra"): 1,
            (NODE_ENUM, "State"): 1,
            (NODE_PROPERTY, "State.ready"): 1,
            (NODE_PROPERTY, "State.done"): 1,
            (NODE_CLASS, "User"): 1,
            (NODE_FIELD, "User.name"): 1,
            (NODE_FIELD, "User.config"): 1,
            (NODE_METHOD, "User.User"): 1,
            (NODE_CLASS, "Handler"): 1,
            (NODE_VARIABLE, "global"): 1,
        }
    )
    assert nodes["Service"].docstring == "X Service docs X\nX second line X"
    assert nodes["Service.state"].docstring == "X state docs X"
    assert _named_edges(result, EDGE_IMPORTS) == [("Service.dart", "repo")]
    assert _named_edges(result, EDGE_INHERITS) == [("Service", "Base")]
    assert _named_edges(result, EDGE_IMPLEMENTS) == [
        ("Service", "Logger"),
        ("Service", "Runner"),
        ("Service", "Closeable"),
    ]
    assert _named_edges(result, EDGE_DECORATED_BY) == [
        ("Service", "Service"),
        ("Service.state", "Primary"),
        ("Service.state", "Field"),
    ]
    assert _named_edges(result, EDGE_REFERENCES) == [
        ("Service.state", "State"),
        ("Service.repo", "Repo"),
        ("Service.mapping", "Key"),
        ("Service.mapping", "Value"),
        ("Service.run", "Result"),
        ("Service.run", "Output"),
        ("Service.run", "Input"),
        ("Service.config", "Config"),
        ("Service.config", "Config"),
        ("User.config", "Config"),
        ("Handler", "Output"),
        ("Handler", "Input"),
        ("global", "Config"),
    ]
    assert _named_edges(result, EDGE_CALLS) == [
        ("Service.run", "helper"),
        ("Service.run", "client.api.call"),
        ("Service.run", "this.local"),
        ("Service.run", "this.api.parent"),
        ("Service.run", "Factory.create"),
        ("Service.config", "Config"),
        ("Service.finish", "done"),
        ("global", "Config"),
    ]


def test_dart_top_level_function_and_generic_type_filtering_are_exact() -> None:
    source = b"""Result<R> execute<T, R>(Input<T> input) { return service.run(); }
final Config config = load();
"""
    parser = DartParser()
    result = parser.parse(file_path="script.dart", source=source)
    assert {(node.kind, node.qualified_name) for node in result.nodes} == {
        ("file", "script.dart"),
        ("function", "execute"),
        (NODE_VARIABLE, "config"),
    }
    assert _named_edges(result, EDGE_REFERENCES) == [
        ("execute", "Result"),
        ("execute", "Input"),
        ("config", "Config"),
    ]
    assert _named_edges(result, EDGE_CALLS) == [
        ("execute", "service.run"),
        ("config", "load"),
    ]


def test_dart_type_and_uri_helpers_are_exact() -> None:
    source = b"Result<Vendor.Models.Input>? value;"
    parser = DartParser()
    type_node = _nodes_of_type(parser, source, "type_identifier")[0]
    generic = _nodes_of_type(parser, source, "type_arguments")[0]
    root = parser._get_parser().parse(source).root_node
    out: list[str] = []
    _collect_dart_type_ids(generic, source, out)
    descendant_names = [
        source[node.start_byte : node.end_byte].decode()
        for node in _dart_identifier_descendants(generic)
    ]

    assert _dart_type_name(type_node, source) == "Result"
    assert _dart_type_name(root, source) == "Result"
    assert out == ["Input"]
    assert descendant_names == ["Vendor", "Models", "Input"]
    assert _dart_local_name("package:pkg/deep/file.dart") == "file"
    assert _dart_local_name("dart:async") == "async"
    assert _dart_local_name("plain") == "plain"
    assert _dart_local_name("scheme:part:leaf") == "leaf"


def test_dart_non_matching_nodes_do_not_emit_language_hooks() -> None:
    parser = DartParser()
    source = b"print(1);"
    root = parser._get_parser().parse(source).root_node
    assert parser.classify(root, source, inside_class=False) is None
    assert parser.call_target(root, source) is None
    assert parser.supertypes(root, source) == []
    assert parser.import_refs(root, source) == []
    assert parser.decorators(root, source) == []
    assert parser.type_refs(root, source) == []
    assert parser.docstring(root, source) is None
    assert parser.identifier_reference_targets(root, source) == []


def test_dart_malformed_import_fails_closed() -> None:
    parser = DartParser()
    malformed = _FakeNode("library_import")
    assert parser.import_refs(cast(Node, malformed), b"") == []
