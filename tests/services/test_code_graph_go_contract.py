"""Exact behavioral contracts for Go graph extraction."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast

import pytest
from tree_sitter import Node

from app.services.code_index.graph_types import (
    EDGE_CALLS,
    EDGE_IMPLEMENTS,
    EDGE_IMPORTS,
    EDGE_REFERENCES,
    NODE_CLASS,
    NODE_FIELD,
    NODE_FUNCTION,
    NODE_INTERFACE,
    NODE_METHOD,
    NODE_STRUCT,
    NODE_VARIABLE,
)
from app.services.code_index.parsers.base import Definition, ImportRef
from app.services.code_index.parsers.go import (
    GoParser,
    _go_string_content,
    _go_value_name,
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

    def child_by_field_name(self, name: str) -> _FakeNode | None:
        return self.fields.get(name)


def _descendants(node: Node):
    for child in node.named_children:
        yield child
        yield from _descendants(child)


def _nodes_of_type(parser: GoParser, source: bytes, node_type: str) -> list[Node]:
    root = parser._get_parser().parse(source).root_node
    return [node for node in _descendants(root) if node.type == node_type]


@pytest.mark.parametrize(
    ("source", "node_type", "inside_class", "expected"),
    [
        (
            b"type User struct{}",
            "type_spec",
            False,
            Definition(NODE_STRUCT, "User", True),
        ),
        (
            b"type Store interface{}",
            "type_spec",
            False,
            Definition(NODE_INTERFACE, "Store", True),
        ),
        (
            b"type ID string",
            "type_spec",
            False,
            Definition(NODE_CLASS, "ID", True),
        ),
        (
            b"type Alias = Target",
            "type_alias",
            False,
            Definition(NODE_CLASS, "Alias"),
        ),
        (
            b"func Run() {}",
            "function_declaration",
            False,
            Definition(NODE_FUNCTION, "Run"),
        ),
        (
            b"type User struct{}\nfunc (u *User) Save() {}",
            "method_declaration",
            False,
            Definition(NODE_METHOD, "Save", prefix="User."),
        ),
        (
            b"type Store interface { Get() error }",
            "method_elem",
            True,
            Definition(NODE_METHOD, "Get"),
        ),
        (
            b"type User struct { Name string }",
            "field_declaration",
            True,
            Definition(NODE_FIELD, "Name"),
        ),
        (
            b"var Value Config",
            "var_spec",
            False,
            Definition(NODE_VARIABLE, "Value"),
        ),
        (
            b"const Value int = 1",
            "const_spec",
            False,
            Definition(NODE_VARIABLE, "Value"),
        ),
    ],
)
def test_go_classification_contract(
    source: bytes,
    node_type: str,
    inside_class: bool,
    expected: Definition,
) -> None:
    parser = GoParser()
    parser.root_prefix(parser._get_parser().parse(source).root_node, source)
    node = _nodes_of_type(parser, source, node_type)[0]

    assert parser.classify(node, source, inside_class=inside_class) == expected


def test_grouped_declarations_keep_every_symbol_and_correct_ownership() -> None:
    source = b"""package demo
// Types docs
type (
 User struct { ID int; Name string; Meta Metadata }
 Store interface { BaseStore; Get(id ID) (User, error) }
 Alias = Target
)
var (
 First Config
 Second = create()
)
const (
 One int = 1
 Two = 2
)
"""

    result = GoParser().parse(file_path="group.go", source=source)
    symbols = {(node.kind, node.qualified_name) for node in result.nodes}
    docs = {node.qualified_name: node.docstring for node in result.nodes}

    assert symbols == {
        ("file", "group.go"),
        (NODE_STRUCT, "demo.User"),
        (NODE_FIELD, "demo.User.ID"),
        (NODE_FIELD, "demo.User.Name"),
        (NODE_FIELD, "demo.User.Meta"),
        (NODE_INTERFACE, "demo.Store"),
        (NODE_METHOD, "demo.Store.Get"),
        (NODE_CLASS, "demo.Alias"),
        (NODE_VARIABLE, "demo.First"),
        (NODE_VARIABLE, "demo.Second"),
        (NODE_VARIABLE, "demo.One"),
        (NODE_VARIABLE, "demo.Two"),
    }
    assert docs["demo.User"] == "Types docs"
    assert docs["demo.Store"] == "Types docs"
    assert docs["demo.Alias"] == "Types docs"


def test_go_calls_receivers_and_type_refs_keep_qualification() -> None:
    source = b"""package demo
type User struct{}
func (u *User) Save(input Request) Response {
  direct()
  service.client.call(input)
  factory().nested()
  return Response{}
}
"""

    result = GoParser().parse(file_path="calls.go", source=source)
    method = next(node for node in result.nodes if node.name == "Save")
    calls = [edge.dst_name for edge in result.edges if edge.kind == EDGE_CALLS]
    refs = [
        edge.dst_name
        for edge in result.edges
        if edge.kind == EDGE_REFERENCES and edge.src_local_id == method.local_id
    ]

    assert method.qualified_name == "demo.User.Save"
    assert calls == ["direct", "service.client.call", "nested", "factory"]
    assert refs[:2] == ["Request", "Response"]

    value_receiver = GoParser().parse(
        file_path="value.go",
        source=b"package demo\ntype User struct{}\nfunc (u User) Load() {}\n",
    )
    assert any(node.qualified_name == "demo.User.Load" for node in value_receiver.nodes)


def test_go_interface_embedding_and_member_types_are_exact() -> None:
    source = b"""package demo
type Store interface {
  BaseStore
  external.RemoteStore
  Get(id ID) (User, error)
}
type User struct { Meta Metadata }
type Alias = Target
var Current Config
const Default Option = 1
"""

    result = GoParser().parse(file_path="types.go", source=source)
    names = {node.local_id: node.qualified_name for node in result.nodes}
    implements = [
        edge.dst_name for edge in result.edges if edge.kind == EDGE_IMPLEMENTS
    ]
    refs: dict[str, list[str]] = {}
    for edge in result.edges:
        if edge.kind == EDGE_REFERENCES and edge.dst_name is not None:
            refs.setdefault(names[edge.src_local_id], []).append(edge.dst_name)

    assert implements == ["BaseStore", "RemoteStore"]
    assert refs["demo.Store.Get"] == ["ID", "User"]
    assert refs["demo.User.Meta"] == ["Metadata"]
    assert refs["demo.Alias"] == ["Target"]
    assert refs["demo.Current"] == ["Config"]
    assert refs["demo.Default"] == ["Option"]


def test_go_import_metadata_supports_alias_blank_dot_and_raw_paths() -> None:
    source = b"""package demo
import (
 alias "example.com/deep/pkg"
 _ "example.com/side"
 . `example.com/dot`
)
"""

    result = GoParser().parse(file_path="imports.go", source=source)
    imports = [
        (edge.dst_name, edge.module_path, edge.local_name)
        for edge in result.edges
        if edge.kind == EDGE_IMPORTS
    ]

    assert imports == [
        ("pkg", "example.com/deep/pkg", "alias"),
        ("side", "example.com/side", "_"),
        ("dot", "example.com/dot", "."),
    ]

    single_source = b'package demo\nimport "example.com/single"\n'
    parser = GoParser()
    declaration = _nodes_of_type(parser, single_source, "import_declaration")[0]
    assert parser.import_refs(declaration, single_source) == [
        ImportRef(name="single", module_path="example.com/single")
    ]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (b'"example.com/pkg"', "example.com/pkg"),
        (b"`example.com/pkg`", "example.com/pkg"),
        (b"unquoted", "unquoted"),
        (b'"mismatch`', '"mismatch`'),
        (b'""', ""),
        (b"``", ""),
    ],
)
def test_go_import_string_content_only_strips_matching_delimiters(
    raw: bytes, expected: str
) -> None:
    node = _FakeNode("interpreted_string_literal", 0, len(raw))
    assert _go_string_content(cast(Node, node), raw) == expected


def test_go_value_name_handles_nested_and_incomplete_selectors() -> None:
    source = b"service.client.call"
    service = _FakeNode("identifier", 0, 7)
    client = _FakeNode("field_identifier", 8, 14)
    call = _FakeNode("field_identifier", 15, 19)
    inner = _FakeNode(
        "selector_expression",
        fields={"operand": service, "field": client},
    )
    outer = _FakeNode(
        "selector_expression",
        fields={"operand": inner, "field": call},
    )

    assert _go_value_name(cast(Node, outer), source) == "service.client.call"
    assert (
        _go_value_name(
            cast(Node, _FakeNode("selector_expression", fields={"field": call})),
            source,
        )
        is None
    )
    assert (
        _go_value_name(
            cast(Node, _FakeNode("selector_expression", fields={"operand": service})),
            source,
        )
        is None
    )


def test_go_docs_keep_compact_and_multiple_comment_lines() -> None:
    source = b"""package demo
//First
//Second
func Run() {}
/*Block*/
type User struct{}
"""

    result = GoParser().parse(file_path="docs.go", source=source)
    nodes = {node.qualified_name: node for node in result.nodes}

    assert nodes["demo.Run"].docstring == "First\nSecond"
    assert nodes["demo.User"].docstring == "Block"


def test_go_helpers_reject_incomplete_root_and_non_field_nodes() -> None:
    parser = GoParser()
    root = _FakeNode("source_file")
    unknown = _FakeNode("unknown", fields={"name": _FakeNode("identifier", 0, 4)})

    assert parser.root_prefix(cast(Node, root), b"") == ""
    empty_clause = _FakeNode("package_clause")
    root_with_clause = _FakeNode("source_file", children=[empty_clause])
    assert parser.root_prefix(cast(Node, root_with_clause), b"") == ""
    assert parser.classify(cast(Node, unknown), b"Name", inside_class=True) is None
    path = _FakeNode("interpreted_string_literal", 0, 5)
    invalid_name = _FakeNode("identifier", 0, 0)
    spec = _FakeNode(
        "import_spec",
        fields={"path": path, "name": invalid_name},
    )
    assert parser._import_spec(cast(Node, spec), b'"pkg"') == [
        ImportRef(name="pkg", module_path="pkg")
    ]
    malformed_comment = _FakeNode("comment", 0, 8)
    declaration = _FakeNode(
        "function_declaration", prev_named_sibling=malformed_comment
    )
    assert _preceding_comment(cast(Node, declaration), b"/*broken") == "/*broken"


def test_non_matching_go_nodes_do_not_emit_language_hooks() -> None:
    source = b"package demo\nfunc run() {}"
    parser = GoParser()
    root = parser._get_parser().parse(source).root_node

    assert parser.classify(root, source, inside_class=False) is None
    assert parser.call_target(root, source) is None
    assert parser.supertypes(root, source) == []
    assert parser.import_refs(root, source) == []
    assert parser.type_refs(root, source) == []
    assert parser.docstring(root, source) is None
