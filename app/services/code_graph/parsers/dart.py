"""Dart language parser."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from app.services.code_graph.parsers.base import (
    Definition,
    SuperType,
    TreeSitterParser,
    node_text,
)
from app.services.code_graph.types import (
    EDGE_IMPLEMENTS,
    EDGE_INHERITS,
    NODE_CLASS,
    NODE_FUNCTION,
    NODE_METHOD,
)

if TYPE_CHECKING:
    from tree_sitter import Node


class DartParser(TreeSitterParser):
    name: ClassVar[str] = "dart"
    extensions: ClassVar[tuple[str, ...]] = (".dart",)
    grammar: ClassVar[str] = "dart"

    def classify(
        self, node: Node, source: bytes, *, inside_class: bool
    ) -> Definition | None:
        ntype = node.type
        if ntype == "class_definition":
            name = node.child_by_field_name("name")
            if name is not None:
                return Definition(
                    kind=NODE_CLASS, name=node_text(name, source), is_class=True
                )
        elif ntype == "enum_declaration":
            name = node.child_by_field_name("name")
            if name is not None:
                return Definition(
                    kind=NODE_CLASS, name=node_text(name, source), is_class=True
                )
        elif ntype == "mixin_declaration":
            name = node.child_by_field_name("name")
            if name is not None:
                return Definition(
                    kind=NODE_CLASS, name=node_text(name, source), is_class=True
                )
        elif ntype == "extension_declaration":
            name = node.child_by_field_name("name")
            if name is not None:
                return Definition(
                    kind=NODE_CLASS, name=node_text(name, source), is_class=True
                )
        elif ntype == "method_signature":
            name = node.child_by_field_name("name")
            if name is not None:
                return Definition(
                    kind=NODE_METHOD, name=node_text(name, source), is_class=False
                )
        elif ntype == "function_signature":
            name = node.child_by_field_name("name")
            if name is not None:
                kind = NODE_METHOD if inside_class else NODE_FUNCTION
                return Definition(
                    kind=kind, name=node_text(name, source), is_class=False
                )
        elif ntype == "getter_signature":
            name = node.child_by_field_name("name")
            if name is not None:
                return Definition(
                    kind=NODE_METHOD, name=node_text(name, source), is_class=False
                )
        elif ntype == "setter_signature":
            name = node.child_by_field_name("name")
            if name is not None:
                return Definition(
                    kind=NODE_METHOD, name=node_text(name, source), is_class=False
                )
        elif ntype == "constructor_signature":
            name = node.child_by_field_name("name")
            if name is not None:
                return Definition(
                    kind=NODE_METHOD, name=node_text(name, source), is_class=False
                )
        return None

    def call_target(self, node: Node, source: bytes) -> str | None:
        # Dart doesn't have a straightforward call_expression in all grammars.
        # Look for identifiers in selector chains.
        if node.type == "identifier":
            # Handled by parent walk
            pass
        return None

    def supertypes(self, node: Node, source: bytes) -> list[SuperType]:
        if node.type != "class_definition":
            return []
        out: list[SuperType] = []
        for child in node.children:
            if child.type == "superclass":
                name = _dart_type_name(child, source)
                if name:
                    out.append(SuperType(name=name, edge_kind=EDGE_INHERITS))
            elif child.type == "interfaces":
                for sub in child.children:
                    name = _dart_type_name(sub, source)
                    if name:
                        out.append(SuperType(name=name, edge_kind=EDGE_IMPLEMENTS))
            elif child.type == "mixins":
                for sub in child.children:
                    name = _dart_type_name(sub, source)
                    if name:
                        out.append(SuperType(name=name, edge_kind=EDGE_IMPLEMENTS))
        return out

    def docstring(self, node: Node, source: bytes) -> str | None:
        prev = node.prev_named_sibling
        if prev is not None and prev.type == "comment":
            text = node_text(prev, source)
            if text.startswith("///"):
                lines: list[str] = []
                cur: Node | None = prev
                while cur is not None and cur.type == "comment":
                    t = node_text(cur, source)
                    if t.startswith("///"):
                        lines.append(t[3:].strip())
                    else:
                        break
                    cur = cur.prev_named_sibling
                lines.reverse()
                return "\n".join(lines) if lines else None
        return None


def _dart_type_name(node: Node, source: bytes) -> str | None:
    if node.type == "identifier":
        return node_text(node, source)
    if node.type == "type_identifier":
        return node_text(node, source)
    for child in node.children:
        if child.type == "identifier" or child.type == "type_identifier":
            return node_text(child, source)
    return None
