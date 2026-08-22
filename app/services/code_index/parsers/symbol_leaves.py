"""Named leaf-symbol extraction shared by high-volume code-graph parsers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.services.code_index.graph_types import (
    NODE_CLASS,
    NODE_FIELD,
    NODE_FUNCTION,
    NODE_METHOD,
    NODE_PROPERTY,
)
from app.services.code_index.parsers.base import Definition, node_text

if TYPE_CHECKING:
    from tree_sitter import Node


def _static_property_name(node: Node, source: bytes) -> str | None:
    name = node.child_by_field_name("name")
    if name is None:
        return None
    if name.type == "property_identifier":
        return node_text(name, source)
    if name.type == "string":
        literal = node_text(name, source)
        return literal[1:-1]
    return None


def ecmascript_leaf_definition(node: Node, source: bytes) -> Definition | None:
    """Return TypeScript/JavaScript API-surface leaves omitted by declarations."""

    if node.type in {"method_signature", "abstract_method_signature"}:
        name = _static_property_name(node, source)
        return Definition(NODE_METHOD, name) if name else None
    if node.type == "property_signature":
        name = _static_property_name(node, source)
        return Definition(NODE_PROPERTY, name) if name else None
    if node.type == "public_field_definition":
        name = _static_property_name(node, source)
        return Definition(NODE_FIELD, name) if name else None
    if node.type == "enum_assignment":
        name = _static_property_name(node, source)
        return Definition(NODE_PROPERTY, name) if name else None
    if (
        node.type == "property_identifier"
        and node.parent is not None
        and node.parent.type == "enum_body"
    ):
        return Definition(NODE_PROPERTY, node_text(node, source))
    return None


def rust_leaf_definition(node: Node, source: bytes) -> Definition | None:
    """Return Rust fields, variants, associated types, and macro definitions."""

    name_node = node.child_by_field_name("name")
    name = node_text(name_node, source) if name_node is not None else None
    if not name:
        return None
    if node.type == "associated_type":
        return Definition(NODE_CLASS, name)
    if node.type == "field_declaration":
        return Definition(NODE_FIELD, name)
    if node.type == "enum_variant":
        return Definition(NODE_PROPERTY, name)
    if node.type == "macro_definition":
        return Definition(NODE_FUNCTION, name)
    return None


__all__ = ["ecmascript_leaf_definition", "rust_leaf_definition"]
