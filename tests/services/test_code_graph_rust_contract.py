"""Exact behavioral contracts for Rust graph extraction."""

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
    EDGE_REFERENCES,
    NODE_CLASS,
    NODE_ENUM,
    NODE_FUNCTION,
    NODE_INTERFACE,
    NODE_METHOD,
    NODE_MODULE,
    NODE_STRUCT,
    NODE_VARIABLE,
)
from app.services.code_index.parsers.base import Definition
from app.services.code_index.parsers.rust import RustParser, _rust_value_name


@dataclass
class _FakeNode:
    type: str
    start_byte: int = 0
    end_byte: int = 0
    children: list[_FakeNode] = field(default_factory=list)
    fields: dict[str, _FakeNode] = field(default_factory=dict)

    def child_by_field_name(self, name: str) -> _FakeNode | None:
        return self.fields.get(name)


def _descendants(node: Node):
    for child in node.named_children:
        yield child
        yield from _descendants(child)


def _nodes_of_type(parser: RustParser, source: bytes, node_type: str) -> list[Node]:
    root = parser._get_parser().parse(source).root_node
    return [node for node in _descendants(root) if node.type == node_type]


@pytest.mark.parametrize(
    ("source", "node_type", "inside_class", "expected"),
    [
        (b"mod api {}", "mod_item", False, Definition(NODE_MODULE, "api", False)),
        (
            b"struct User;",
            "struct_item",
            False,
            Definition(NODE_STRUCT, "User", True),
        ),
        (
            b"enum State { Idle }",
            "enum_item",
            False,
            Definition(NODE_ENUM, "State", True),
        ),
        (
            b"union Value { integer: i32 }",
            "union_item",
            False,
            Definition(NODE_STRUCT, "Value", True),
        ),
        (
            b"trait Store {}",
            "trait_item",
            False,
            Definition(NODE_INTERFACE, "Store", True),
        ),
        (
            b"impl Trait for User {}",
            "impl_item",
            False,
            Definition(NODE_CLASS, "User", True),
        ),
        (
            b"type Alias = Target;",
            "type_item",
            False,
            Definition(NODE_CLASS, "Alias", False),
        ),
        (
            b"fn run() {}",
            "function_item",
            False,
            Definition(NODE_FUNCTION, "run", False),
        ),
        (
            b"fn run() {}",
            "function_item",
            True,
            Definition(NODE_METHOD, "run", False),
        ),
        (
            b"trait Store { fn load(&self); }",
            "function_signature_item",
            True,
            Definition(NODE_METHOD, "load", False),
        ),
        (
            b"const VALUE: Config = make();",
            "const_item",
            False,
            Definition(NODE_VARIABLE, "VALUE", False),
        ),
        (
            b"static GLOBAL: Registry = Registry::new();",
            "static_item",
            False,
            Definition(NODE_VARIABLE, "GLOBAL", False),
        ),
    ],
)
def test_rust_classification_contract(
    source: bytes,
    node_type: str,
    inside_class: bool,
    expected: Definition,
) -> None:
    parser = RustParser()
    node = _nodes_of_type(parser, source, node_type)[0]

    assert parser.classify(node, source, inside_class=inside_class) == expected


def test_rust_call_targets_keep_static_paths_and_fields() -> None:
    source = b"""fn run() {
 direct();
 crate::module::func();
 super::helper();
 Type::method();
 object.deep.method();
 self.local();
 get().nested();
 println!("x");
}
"""

    result = RustParser().parse(file_path="calls.rs", source=source)
    calls = [
        (edge.dst_name, edge.line) for edge in result.edges if edge.kind == EDGE_CALLS
    ]

    assert calls == [
        ("direct", 2),
        ("crate.module.func", 3),
        ("super.helper", 4),
        ("Type.method", 5),
        ("object.deep.method", 6),
        ("self.local", 7),
        ("nested", 8),
        ("get", 8),
        ("println", 9),
    ]
    assert not any(
        edge.kind == EDGE_REFERENCES and edge.dst_name == "println"
        for edge in result.edges
    )


def test_rust_impl_relations_cover_simple_generic_and_scoped_traits() -> None:
    source = b"""struct User;
impl Trait for User {}
impl Trait<Item> for User {}
impl crate::traits::Other for User {}
impl User {}
"""

    result = RustParser().parse(file_path="impls.rs", source=source)
    implementations = [
        (edge.src_local_id, edge.dst_name, edge.line)
        for edge in result.edges
        if edge.kind == EDGE_IMPLEMENTS
    ]

    assert implementations == [
        ("User#2", "Trait", 2),
        ("User#3", "Trait", 3),
        ("User#4", "Other", 4),
    ]


def test_rust_import_metadata_is_exact() -> None:
    source = b"""use std::io::Result;
use crate::models::{User, Post as Article, nested::Thing};
use crate::service as svc;
use local;
"""

    result = RustParser().parse(file_path="imports.rs", source=source)
    imports = [
        (
            edge.dst_name,
            edge.line,
            edge.module_path,
            edge.local_name,
        )
        for edge in result.edges
        if edge.kind == EDGE_IMPORTS
    ]

    assert imports == [
        ("Result", 1, "std::io", "Result"),
        ("User", 2, "crate::models", "User"),
        ("Post", 2, "crate::models", "Article"),
        ("Thing", 2, "crate::models", "Thing"),
        ("service", 3, "crate::service", "svc"),
        ("local", 4, "", "local"),
    ]


def test_rust_attributes_and_line_block_docs_preserve_order() -> None:
    source = b"""// documentation boundary
/// User docs.
#[derive(Debug)]
#[serde::model]
struct User { field: FieldType }
/** Block docs. */
struct Block;
///First
///Second
struct Lines;
//!Inner docs.
struct Inner;
/*!Inner block.*/
struct InnerBlock;
/* ordinary */
struct Plain;
/**
 *  Multi line
 *Detail
 */
struct Multi;
"""

    result = RustParser().parse(file_path="docs.rs", source=source)
    nodes = {node.qualified_name: node for node in result.nodes}
    decorators = [
        (edge.src_local_id, edge.dst_name)
        for edge in result.edges
        if edge.kind == EDGE_DECORATED_BY
    ]

    assert nodes["User"].docstring == "User docs."
    assert nodes["Block"].docstring == "Block docs."
    assert nodes["Lines"].docstring == "First\nSecond"
    assert nodes["Inner"].docstring == "Inner docs."
    assert nodes["InnerBlock"].docstring == "Inner block."
    assert nodes["Plain"].docstring is None
    assert nodes["Multi"].docstring == "Multi line\nDetail"
    assert decorators == [
        (nodes["User"].local_id, "derive"),
        (nodes["User"].local_id, "model"),
    ]

    at_start = RustParser().parse(
        file_path="start.rs", source=b"///Only\nstruct Solo;\n"
    )
    solo = next(node for node in at_start.nodes if node.qualified_name == "Solo")
    assert solo.docstring == "Only"


def test_rust_type_refs_cover_alias_constants_fields_variants_and_functions() -> None:
    source = b"""type Alias = Target;
const VALUE: Config = make();
static GLOBAL: Registry = Registry::new();
struct User { field: FieldType }
enum Event { Created(Payload), Updated { value: Update } }
trait Store {
  type Error = StoreError;
  type Value: Into<Target>;
  fn load(&self, input: Request) -> Result<Response, Self::Error>;
}
"""

    result = RustParser().parse(file_path="types.rs", source=source)
    node_names = {node.local_id: node.qualified_name for node in result.nodes}
    refs: dict[str, list[str]] = {}
    for edge in result.edges:
        if edge.kind != EDGE_REFERENCES or edge.dst_name is None:
            continue
        refs.setdefault(node_names[edge.src_local_id], []).append(edge.dst_name)

    assert refs["Alias"] == ["Target"]
    assert refs["VALUE"] == ["Config"]
    assert refs["GLOBAL"] == ["Registry"]
    assert refs["User.field"] == ["FieldType"]
    assert refs["Event.Created"] == ["Payload"]
    assert refs["Event.Updated"] == ["Update"]
    assert refs["Store.Error"] == ["StoreError"]
    assert refs["Store.Value"] == ["Into", "Target"]
    assert refs["Store.load"] == ["Request", "Result", "Response", "Error"]


def test_non_matching_rust_nodes_do_not_emit_language_hooks() -> None:
    source = b"let value = 1;"
    parser = RustParser()
    root = parser._get_parser().parse(source).root_node

    assert parser.classify(root, source, inside_class=False) is None
    assert parser.call_target(root, source) is None
    assert parser.supertypes(root, source) == []
    assert parser.import_refs(root, source) == []
    assert parser.decorators(root, source) == []
    assert parser.type_refs(root, source) == []
    assert parser.docstring(root, source) is None


def test_incomplete_scoped_import_is_ignored() -> None:
    name = _FakeNode("identifier", 0, 4)
    scoped = _FakeNode("scoped_identifier", children=[], fields={"name": name})
    declaration = _FakeNode("use_declaration", children=[scoped])

    assert RustParser().import_refs(cast(Node, declaration), b"Name") == []


def test_rust_value_name_handles_incomplete_scoped_and_field_nodes() -> None:
    source = b"owner.member"
    owner = _FakeNode("identifier", 0, 5)
    name = _FakeNode("identifier", 6, 12)

    assert (
        _rust_value_name(
            cast(Node, _FakeNode("scoped_identifier", fields={"name": name})),
            source,
        )
        is None
    )
    assert (
        _rust_value_name(
            cast(Node, _FakeNode("scoped_identifier", fields={"path": owner})),
            source,
        )
        is None
    )
    assert (
        _rust_value_name(
            cast(Node, _FakeNode("field_expression", fields={"field": name})),
            source,
        )
        is None
    )
    assert (
        _rust_value_name(
            cast(Node, _FakeNode("field_expression", fields={"value": owner})),
            source,
        )
        is None
    )
