"""Exact behavioral contracts for Java graph extraction."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast

import pytest
from tree_sitter import Node

from app.services.code_index.graph_types import (
    EDGE_CALLS,
    EDGE_DECORATED_BY,
    EDGE_IMPLEMENTS,
    EDGE_IMPORTS,
    EDGE_INHERITS,
    EDGE_REFERENCES,
    EDGE_USES,
    NODE_CLASS,
    NODE_ENUM,
    NODE_FIELD,
    NODE_INTERFACE,
    NODE_METHOD,
    NODE_PROPERTY,
)
from app.services.code_index.parsers.base import Definition, ImportRef, node_text
from app.services.code_index.parsers.java import (
    JavaParser,
    _simple_type_name,
    _strip_javadoc,
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

    def child_by_field_name(self, name: str) -> _FakeNode | None:
        return self.fields.get(name)


def _descendants(node: Node):
    for child in node.named_children:
        yield child
        yield from _descendants(child)


def _nodes_of_type(parser: JavaParser, source: bytes, node_type: str) -> list[Node]:
    root = parser._get_parser().parse(source).root_node
    return [node for node in _descendants(root) if node.type == node_type]


@pytest.mark.parametrize(
    ("source", "node_type", "inside_class", "expected"),
    [
        (b"class Service {}", "class_declaration", False, Definition(NODE_CLASS, "Service", True)),
        (b"interface Service {}", "interface_declaration", False, Definition(NODE_INTERFACE, "Service", True)),
        (b"enum State { IDLE }", "enum_declaration", False, Definition(NODE_ENUM, "State", True)),
        (b"record User(String name) {}", "record_declaration", False, Definition(NODE_CLASS, "User", True)),
        (b"@interface Marker {}", "annotation_type_declaration", False, Definition(NODE_INTERFACE, "Marker", True)),
        (b"class Service { Result run() { return null; } }", "method_declaration", True, Definition(NODE_METHOD, "run")),
        (b"class Service { Service() {} }", "constructor_declaration", True, Definition(NODE_METHOD, "Service")),
        (b"class Service { Config field; }", "variable_declarator", True, Definition(NODE_FIELD, "field")),
        (b"record User(Config config) {}", "formal_parameter", True, Definition(NODE_FIELD, "config")),
        (b"enum State { IDLE }", "enum_constant", True, Definition(NODE_PROPERTY, "IDLE")),
        (b"@interface Marker { Custom value(); }", "annotation_type_element_declaration", True, Definition(NODE_METHOD, "value")),
    ],
)
def test_java_classification_contract(
    source: bytes, node_type: str, inside_class: bool, expected: Definition
) -> None:
    parser = JavaParser()
    node = _nodes_of_type(parser, source, node_type)[0]
    assert parser.classify(node, source, inside_class=inside_class) == expected


def test_java_fields_records_enums_annotations_and_ownership_are_exact() -> None:
    source = b'''package com.example;
/** User docs */
public record User(String name, Config config) implements Identified {}
class Service extends Base implements First, pkg.Second {
 /** field docs */
 @Inject private final Repository<User> repository;
 private int count, total;
 public Result<User> load(Request req, Config cfg) { return client.api.call(req); }
}
enum State { IDLE, RUNNING }
@interface Marker { Custom value(); }
'''
    result = JavaParser().parse(file_path="Demo.java", source=source)
    nodes = {node.qualified_name: node for node in result.nodes}
    assert {(node.kind, node.qualified_name) for node in result.nodes} == {
        ("file", "Demo.java"),
        (NODE_CLASS, "com.example.User"),
        (NODE_FIELD, "com.example.User.name"),
        (NODE_FIELD, "com.example.User.config"),
        (NODE_CLASS, "com.example.Service"),
        (NODE_FIELD, "com.example.Service.repository"),
        (NODE_FIELD, "com.example.Service.count"),
        (NODE_FIELD, "com.example.Service.total"),
        (NODE_METHOD, "com.example.Service.load"),
        (NODE_ENUM, "com.example.State"),
        (NODE_PROPERTY, "com.example.State.IDLE"),
        (NODE_PROPERTY, "com.example.State.RUNNING"),
        (NODE_INTERFACE, "com.example.Marker"),
        (NODE_METHOD, "com.example.Marker.value"),
    }
    assert nodes["com.example.User"].docstring == "User docs"
    assert nodes["com.example.Service.repository"].docstring == "field docs"
    assert not any(edge.kind == EDGE_REFERENCES and edge.dst_name == "com" for edge in result.edges)

    ordinary = JavaParser().parse(
        file_path="Ordinary.java",
        source=b"/* ordinary */\nclass Ordinary {}\n",
    )
    ordinary_node = next(node for node in ordinary.nodes if node.name == "Ordinary")
    assert ordinary_node.docstring is None


def test_java_heritage_decorators_di_and_generic_type_refs_are_exact() -> None:
    source = b'''package com.example;
record User(Config config) implements Identified {}
class Service extends Base implements First, pkg.Second {
 @Inject private final Repository<User> repository;
 public Result<User> load(Request req, Map<Key, Value> mapping) { return null; }
}
interface API extends Parent, pkg.Other {}
'''
    result = JavaParser().parse(file_path="Types.java", source=source)
    names = {node.local_id: node.qualified_name for node in result.nodes}
    assert [
        (names[e.src_local_id], e.kind, e.dst_name)
        for e in result.edges
        if e.kind in {EDGE_INHERITS, EDGE_IMPLEMENTS}
    ] == [
        ("com.example.User", EDGE_IMPLEMENTS, "Identified"),
        ("com.example.Service", EDGE_INHERITS, "Base"),
        ("com.example.Service", EDGE_IMPLEMENTS, "First"),
        ("com.example.Service", EDGE_IMPLEMENTS, "Second"),
        ("com.example.API", EDGE_INHERITS, "Parent"),
        ("com.example.API", EDGE_INHERITS, "Other"),
    ]
    refs: dict[str, list[str]] = {}
    for edge in result.edges:
        if edge.kind == EDGE_REFERENCES and edge.dst_name is not None:
            refs.setdefault(names[edge.src_local_id], []).append(edge.dst_name)
    assert refs["com.example.User.config"] == ["Config"]
    assert refs["com.example.Service.repository"] == ["Repository", "User"]
    assert refs["com.example.Service.load"] == ["Result", "User", "Request", "Map", "Key", "Value"]
    assert any(e.kind == EDGE_DECORATED_BY and names[e.src_local_id] == "com.example.Service.repository" and e.dst_name == "Inject" for e in result.edges)
    assert any(e.kind == EDGE_USES and names[e.src_local_id] == "com.example.Service" and e.dst_name == "Repository" for e in result.edges)


def test_java_calls_and_object_creation_keep_qualification() -> None:
    source = b'''class Service {
 void run(Request req) {
   direct();
   client.api.call(req);
   this.local();
   super.parent();
   new pkg.Widget();
 }
}
'''
    result = JavaParser().parse(file_path="Calls.java", source=source)
    assert [e.dst_name for e in result.edges if e.kind == EDGE_CALLS] == [
        "direct", "client.api.call", "this.local", "this.parent", "Widget"
    ]


def test_java_import_metadata_is_exact() -> None:
    source = b'''import com.example.User;
import static com.example.Helper.doThing;
import com.example.models.*;
'''
    result = JavaParser().parse(file_path="Imports.java", source=source)
    assert [
        (e.dst_name, e.module_path, e.local_name)
        for e in result.edges if e.kind == EDGE_IMPORTS
    ] == [
        ("User", "com.example.User", "User"),
        ("doThing", "com.example.Helper.doThing", "doThing"),
        ("*", "com.example.models.*", "*"),
    ]

    single = b"import User;"
    parser = JavaParser()
    declaration = _nodes_of_type(parser, single, "import_declaration")[0]
    assert parser.import_refs(declaration, single) == [
        ImportRef(name="User", module_path="User")
    ]


@pytest.mark.parametrize(("raw", "expected"), [
    ("/**Docs*/", "Docs"),
    ("/**\n * First\n *Second\n */", "First\nSecond"),
    ("/*ordinary*/", "ordinary"),
    ("/**/", ""),
    ("/**broken", "/**broken"),
])
def test_javadoc_normalization(raw: str, expected: str) -> None:
    assert _strip_javadoc(raw) == expected


def test_java_helpers_reject_incomplete_types_and_roots() -> None:
    parser = JavaParser()
    root = _FakeNode("program")
    unknown = _FakeNode("unknown")
    assert parser.root_prefix(cast(Node, root), b"") == ""
    package = b"package demo;"
    package_root = parser._get_parser().parse(package).root_node
    assert parser.root_prefix(package_root, package) == "demo."
    assert parser.classify(cast(Node, unknown), b"", inside_class=True) is None
    assert _simple_type_name(cast(Node, unknown), b"") is None


def test_java_di_and_type_hooks_cover_positive_negative_and_scoped_cases() -> None:
    source = b'''class Service {
 @Inject Repo injected = make();
 final Config required;
 final Config initialized = make();
 String optional;
 @Inject String builtin;
 final int count;
 pkg.External external;
 java.lang.String scopedBuiltin;
 Service(Config config) {}
}
@interface Marker { Custom value(); }
'''
    parser = JavaParser()
    fields = _nodes_of_type(parser, source, "field_declaration")
    uses = {node_text(node, source): parser.uses_target(node, source) for node in fields}
    assert uses == {
        "@Inject Repo injected = make();": "Repo",
        "final Config required;": "Config",
        "final Config initialized = make();": None,
        "String optional;": None,
        "@Inject String builtin;": None,
        "final int count;": None,
        "pkg.External external;": None,
        "java.lang.String scopedBuiltin;": None,
    }
    result = parser.parse(file_path="Hooks.java", source=source)
    names = {node.local_id: node.qualified_name for node in result.nodes}
    refs: dict[str, list[str]] = {}
    for edge in result.edges:
        if edge.kind == EDGE_REFERENCES and edge.dst_name is not None:
            refs.setdefault(names[edge.src_local_id], []).append(edge.dst_name)
    assert refs["Service.external"] == ["External"]
    assert "Service.scopedBuiltin" not in refs
    assert refs["Service.Service"] == ["Config"]
    assert refs["Marker.value"] == ["Custom"]

    modifiers = _FakeNode("modifiers", children=[_FakeNode("final")])
    malformed_field = _FakeNode("field_declaration", children=[modifiers])
    assert parser.uses_target(cast(Node, malformed_field), b"") is None
    malformed_import = _FakeNode("import_declaration")
    assert parser.import_refs(cast(Node, malformed_import), b"") == []


def test_non_matching_java_nodes_do_not_emit_language_hooks() -> None:
    source = b"class Service {}"
    parser = JavaParser()
    root = parser._get_parser().parse(source).root_node
    assert parser.classify(root, source, inside_class=False) is None
    assert parser.call_target(root, source) is None
    assert parser.supertypes(root, source) == []
    assert parser.import_refs(root, source) == []
    assert parser.decorators(root, source) == []
    assert parser.type_refs(root, source) == []
    assert parser.docstring(root, source) is None
