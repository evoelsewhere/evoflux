"""Exact behavioral contracts for C# graph extraction."""

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
    NODE_FUNCTION,
    NODE_INTERFACE,
    NODE_METHOD,
    NODE_NAMESPACE,
    NODE_PROPERTY,
    NODE_STRUCT,
)
from app.services.code_index.parsers.base import Definition, node_text
from app.services.code_index.parsers.csharp import (
    CSharpParser,
    _looks_like_interface,
    _simple_type_name,
    _strip_xml_tags,
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


def _nodes_of_type(parser: CSharpParser, source: bytes, node_type: str) -> list[Node]:
    root = parser._get_parser().parse(source).root_node
    return [node for node in _descendants(root) if node.type == node_type]


@pytest.mark.parametrize(
    ("source", "node_type", "inside_class", "expected"),
    [
        (b"namespace Demo {}", "namespace_declaration", False, Definition(NODE_NAMESPACE, "Demo")),
        (b"namespace Demo;", "file_scoped_namespace_declaration", False, Definition(NODE_NAMESPACE, "Demo", prefix="")),
        (b"class Service {}", "class_declaration", False, Definition(NODE_CLASS, "Service", True)),
        (b"interface IService {}", "interface_declaration", False, Definition(NODE_INTERFACE, "IService", True)),
        (b"struct Value {}", "struct_declaration", False, Definition(NODE_STRUCT, "Value", True)),
        (b"enum State { Idle }", "enum_declaration", False, Definition(NODE_ENUM, "State", True)),
        (b"record User(string Name);", "record_declaration", False, Definition(NODE_CLASS, "User", True)),
        (b"class Service { void Run() {} }", "method_declaration", True, Definition(NODE_METHOD, "Run")),
        (b"class Service { Service() {} }", "constructor_declaration", True, Definition(NODE_METHOD, "Service")),
        (b"class Service { Config Item { get; } }", "property_declaration", True, Definition(NODE_PROPERTY, "Item")),
        (b"class Service { void Run() { void Local() {} } }", "local_function_statement", False, Definition(NODE_FUNCTION, "Local")),
        (b"delegate Result Handler(Input value);", "delegate_declaration", False, Definition(NODE_FUNCTION, "Handler")),
        (b"class Service { Config field; }", "variable_declarator", True, Definition(NODE_FIELD, "field")),
        (b"record User(Config Config);", "parameter", True, Definition(NODE_FIELD, "Config")),
        (b"enum State { Idle }", "enum_member_declaration", True, Definition(NODE_PROPERTY, "Idle")),
    ],
)
def test_csharp_classification_contract(
    source: bytes, node_type: str, inside_class: bool, expected: Definition
) -> None:
    parser = CSharpParser()
    node = _nodes_of_type(parser, source, node_type)[0]
    assert parser.classify(node, source, inside_class=inside_class) == expected


def test_csharp_records_fields_properties_enums_and_ownership_are_exact() -> None:
    source = b'''namespace Demo;
/// <summary>User docs</summary>
public record User(string Name, Config Config) : IIdentified;
class Service : Base, IDisposable {
 /// <summary>Repo field</summary>
 [Inject] private readonly IRepository<User> _repo;
 private int count, total;
 public Result<User> Item { get; set; }
 public Response Load(Request req, Config cfg) => client.Api.Call(req);
}
enum State { Idle, Running }
'''
    result = CSharpParser().parse(file_path="Demo.cs", source=source)
    nodes = {node.qualified_name: node for node in result.nodes}
    assert {(node.kind, node.qualified_name) for node in result.nodes} == {
        ("file", "Demo.cs"),
        (NODE_NAMESPACE, "Demo"),
        (NODE_CLASS, "Demo.User"),
        (NODE_FIELD, "Demo.User.Name"),
        (NODE_FIELD, "Demo.User.Config"),
        (NODE_CLASS, "Demo.Service"),
        (NODE_FIELD, "Demo.Service._repo"),
        (NODE_FIELD, "Demo.Service.count"),
        (NODE_FIELD, "Demo.Service.total"),
        (NODE_PROPERTY, "Demo.Service.Item"),
        (NODE_METHOD, "Demo.Service.Load"),
        (NODE_ENUM, "Demo.State"),
        (NODE_PROPERTY, "Demo.State.Idle"),
        (NODE_PROPERTY, "Demo.State.Running"),
    }
    assert nodes["Demo.User"].docstring == "User docs"
    assert nodes["Demo.Service._repo"].docstring == "Repo field"


def test_csharp_heritage_di_attributes_and_recursive_type_refs_are_exact() -> None:
    source = b'''namespace Demo;
record User(Config Config) : IIdentified;
class Service : Base, IDisposable {
 [Inject] private readonly IRepository<User> _repo;
 public Result<User> Item { get; set; }
 public Response Load(Request req, Map<Key, Value> mapping) => default;
}
interface IService : IParent, IOther {}
'''
    result = CSharpParser().parse(file_path="Types.cs", source=source)
    names = {node.local_id: node.qualified_name for node in result.nodes}
    assert [
        (names[e.src_local_id], e.kind, e.dst_name)
        for e in result.edges if e.kind in {EDGE_INHERITS, EDGE_IMPLEMENTS}
    ] == [
        ("Demo.User", EDGE_IMPLEMENTS, "IIdentified"),
        ("Demo.Service", EDGE_INHERITS, "Base"),
        ("Demo.Service", EDGE_IMPLEMENTS, "IDisposable"),
        ("Demo.IService", EDGE_INHERITS, "IParent"),
        ("Demo.IService", EDGE_INHERITS, "IOther"),
    ]
    refs: dict[str, list[str]] = {}
    for edge in result.edges:
        if edge.kind == EDGE_REFERENCES and edge.dst_name is not None:
            refs.setdefault(names[edge.src_local_id], []).append(edge.dst_name)
    assert refs["Demo.User.Config"] == ["Config"]
    assert refs["Demo.Service._repo"] == ["IRepository", "User"]
    assert refs["Demo.Service.Item"] == ["Result", "User"]
    assert refs["Demo.Service.Load"] == ["Response", "Request", "Map", "Key", "Value"]
    assert any(e.kind == EDGE_DECORATED_BY and names[e.src_local_id] == "Demo.Service._repo" and e.dst_name == "Inject" for e in result.edges)
    assert any(e.kind == EDGE_USES and names[e.src_local_id] == "Demo.Service" and e.dst_name == "IRepository" for e in result.edges)
    service_id = next(local_id for local_id, name in names.items() if name == "Demo.Service")
    assert not any(
        e.kind == EDGE_REFERENCES and e.src_local_id == service_id
        for e in result.edges
    )


def test_csharp_calls_and_object_creation_keep_qualification() -> None:
    source = b'''class Service {
 void Run(Request req) {
   Direct();
   client.Api.Call(req);
   this.Local();
   base.Parent();
   new Demo.Widget();
 }
}
'''
    result = CSharpParser().parse(file_path="Calls.cs", source=source)
    assert [e.dst_name for e in result.edges if e.kind == EDGE_CALLS] == [
        "Direct", "client.Api.Call", "this.Local", "this.Parent", "Widget"
    ]


def test_csharp_using_metadata_is_exact() -> None:
    source = b'''using Simple;
using Demo.Deep.Service;
global using System.Text;
using Alias = Demo.Deep.Service;
using static System.Math;
'''
    result = CSharpParser().parse(file_path="Usings.cs", source=source)
    assert [
        (e.dst_name, e.module_path, e.local_name)
        for e in result.edges if e.kind == EDGE_IMPORTS
    ] == [
        ("Simple", "Simple", "Simple"),
        ("Service", "Demo.Deep.Service", "Service"),
        ("Text", "System.Text", "Text"),
        ("Service", "Demo.Deep.Service", "Alias"),
        ("Math", "System.Math", "Math"),
    ]


def test_csharp_language_hooks_handle_missing_structural_children() -> None:
    parser = CSharpParser()
    using = _FakeNode("using_directive")
    modifier = _FakeNode("modifier", start_byte=0, end_byte=8)
    field_node = _FakeNode("field_declaration", children=[modifier])
    assert parser.import_refs(cast(Node, using), b"") == []
    assert parser.uses_target(cast(Node, field_node), b"readonly") is None


def test_csharp_multiline_docs_stay_attached_to_the_exact_declaration() -> None:
    source = b'''/// <summary>Class docs</summary>
class Service {
 /// <summary>First line</summary>
 /// <remarks>Second line</remarks>
 void Run() {}
}
'''
    result = CSharpParser().parse(file_path="Docs.cs", source=source)
    nodes = {node.qualified_name: node for node in result.nodes}
    assert nodes["Service"].docstring == "Class docs"
    assert nodes["Service.Run"].docstring == "First line\nSecond line"


def test_csharp_doc_comments_do_not_require_a_space_after_slashes() -> None:
    source = b"///<summary>Compact docs</summary>\nclass Compact {}"
    result = CSharpParser().parse(file_path="Compact.cs", source=source)
    node = next(node for node in result.nodes if node.qualified_name == "Compact")
    assert node.docstring == "Compact docs"


def test_csharp_decorators_scan_past_non_attribute_children() -> None:
    source = b"Inject"
    name = _FakeNode("identifier", start_byte=0, end_byte=len(source))
    attribute = _FakeNode("attribute", children=[name], fields={"name": name})
    attribute_list = _FakeNode("attribute_list", children=[attribute])
    owner = _FakeNode(
        "field_declaration",
        children=[_FakeNode("modifier"), attribute_list],
    )
    assert CSharpParser().decorators(cast(Node, owner), source) == ["Inject"]


def test_csharp_type_hooks_resolve_parameters_returns_and_qualified_generics() -> None:
    source = b'''class Service {
 Demo.Result<Demo.Item> Load(Map<Key, Value> input) => default;
 Demo.Result<Demo.Item> Item { get; }
 void Reset(int count) {}
}
'''
    parser = CSharpParser()
    method, reset = _nodes_of_type(parser, source, "method_declaration")
    property_node = _nodes_of_type(parser, source, "property_declaration")[0]
    parameter, builtin_parameter = _nodes_of_type(parser, source, "parameter")
    generic = _nodes_of_type(parser, source, "generic_name")[0]
    qualified = _nodes_of_type(parser, source, "qualified_name")[0]

    assert parser.type_refs(method, source) == [
        "Result",
        "Item",
        "Map",
        "Key",
        "Value",
    ]
    assert parser.type_refs(property_node, source) == ["Result", "Item"]
    assert parser.type_refs(parameter, source) == ["Map", "Key", "Value"]
    assert parser.type_refs(reset, source) == []
    assert parser.type_refs(builtin_parameter, source) == []
    assert _simple_type_name(generic, source) == "Result"
    assert _simple_type_name(qualified, source) == "Result"


def test_csharp_di_positive_negative_and_builtin_cases() -> None:
    source = b'''class Service {
 [Inject] Repo injected = new();
 readonly Config required;
 readonly Config initialized = new();
 string optional;
 [Inject] string builtin;
}
'''
    parser = CSharpParser()
    fields = _nodes_of_type(parser, source, "field_declaration")
    assert {node_text(node, source): parser.uses_target(node, source) for node in fields} == {
        "[Inject] Repo injected = new();": "Repo",
        "readonly Config required;": "Config",
        "readonly Config initialized = new();": None,
        "string optional;": None,
        "[Inject] string builtin;": None,
    }


@pytest.mark.parametrize(("name", "expected"), [
    ("IService", True), ("IO", True), ("Item", False), ("I", False), ("service", False),
])
def test_interface_name_heuristic(name: str, expected: bool) -> None:
    assert _looks_like_interface(name) is expected


@pytest.mark.parametrize(("raw", "expected"), [
    ("<summary>Docs</summary>", "Docs"),
    ("<summary>First <see cref=\"T\"/> second</summary>", "First  second"),
    ("plain", "plain"),
    ("<broken", "<broken"),
])
def test_xml_doc_tag_stripping(raw: str, expected: str) -> None:
    assert _strip_xml_tags(raw) == expected


def test_csharp_helpers_reject_incomplete_types_and_roots() -> None:
    parser = CSharpParser()
    root = _FakeNode("compilation_unit")
    unknown = _FakeNode("unknown")
    assert parser.root_prefix(cast(Node, root), b"") == ""
    assert parser.classify(cast(Node, unknown), b"", inside_class=True) is None
    assert _simple_type_name(cast(Node, unknown), b"") is None


def test_non_matching_csharp_nodes_do_not_emit_language_hooks() -> None:
    source = b"class Service {}"
    parser = CSharpParser()
    root = parser._get_parser().parse(source).root_node
    assert parser.classify(root, source, inside_class=False) is None
    assert parser.call_target(root, source) is None
    assert parser.supertypes(root, source) == []
    assert parser.import_refs(root, source) == []
    assert parser.decorators(root, source) == []
    assert parser.type_refs(root, source) == []
    assert parser.docstring(root, source) is None
