"""Scala language parser."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from app.services.code_graph.parsers.base import (
    Definition,
    SuperType,
    TreeSitterParser,
    node_text,
)
from app.services.code_graph.types import (
    EDGE_INHERITS,
    NODE_CLASS,
    NODE_FUNCTION,
    NODE_INTERFACE,
    NODE_METHOD,
)

if TYPE_CHECKING:
    from tree_sitter import Node


class ScalaParser(TreeSitterParser):
    name: ClassVar[str] = "scala"
    extensions: ClassVar[tuple[str, ...]] = (".scala", ".sc")
    grammar: ClassVar[str] = "scala"

    def classify(
        self, node: Node, source: bytes, *, inside_class: bool
    ) -> Definition | None:
        ntype = node.type
        if ntype == "trait_definition":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_INTERFACE, name=name, is_class=True)
        elif ntype == "class_definition":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_CLASS, name=name, is_class=True)
        elif ntype == "object_definition":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_CLASS, name=name, is_class=True)
        elif ntype == "function_definition":
            name = self._name(node, source)
            if name:
                kind = NODE_METHOD if inside_class else NODE_FUNCTION
                return Definition(kind=kind, name=name, is_class=False)
        elif ntype == "val_definition":
            # Only capture named vals inside classes as properties
            if inside_class:
                name = self._val_name(node, source)
                if name:
                    return Definition(kind=NODE_METHOD, name=name, is_class=False)
        elif ntype == "type_definition":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_CLASS, name=name, is_class=False)
        return None

    def call_target(self, node: Node, source: bytes) -> str | None:
        if node.type == "call_expression":
            func = node.child_by_field_name("function")
            if func is None:
                return None
            if func.type == "identifier":
                return node_text(func, source)
            if func.type == "field_expression":
                field = func.child_by_field_name("field")
                if field is not None:
                    return node_text(field, source)
            if func.type == "generic_function":
                fn = func.child_by_field_name("function")
                if fn is not None and fn.type == "identifier":
                    return node_text(fn, source)
        return None

    def supertypes(self, node: Node, source: bytes) -> list[SuperType]:
        if node.type not in (
            "class_definition",
            "trait_definition",
            "object_definition",
        ):
            return []
        out: list[SuperType] = []
        for child in node.children:
            if child.type == "extends_clause":
                for sub in child.children:
                    name = _scala_type_name(sub, source)
                    if name:
                        out.append(SuperType(name=name, edge_kind=EDGE_INHERITS))
        return out

    def docstring(self, node: Node, source: bytes) -> str | None:
        prev = node.prev_named_sibling
        if prev is not None and prev.type == "comment":
            text = node_text(prev, source)
            if text.startswith("/**"):
                return _strip_scaladoc(text)
        return None

    def _name(self, node: Node, source: bytes) -> str | None:
        name_node = node.child_by_field_name("name")
        if name_node is not None:
            return node_text(name_node, source)
        for child in node.children:
            if child.type == "identifier":
                return node_text(child, source)
        return None

    def _val_name(self, node: Node, source: bytes) -> str | None:
        pattern = node.child_by_field_name("pattern")
        if pattern is not None and pattern.type == "identifier":
            return node_text(pattern, source)
        return None


def _scala_type_name(node: Node, source: bytes) -> str | None:
    if node.type == "type_identifier":
        return node_text(node, source)
    if node.type == "generic_type":
        for child in node.children:
            if child.type == "type_identifier":
                return node_text(child, source)
    return None


def _strip_scaladoc(text: str) -> str:
    s = text.strip()
    if s.startswith("/**"):
        s = s[3:]
    if s.endswith("*/"):
        s = s[:-2]
    lines = [ln.strip().lstrip("* ").strip() for ln in s.split("\n")]
    return "\n".join(ln for ln in lines if ln and not ln.startswith("@"))
