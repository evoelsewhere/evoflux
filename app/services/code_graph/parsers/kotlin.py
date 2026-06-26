"""Kotlin language parser."""

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
    NODE_INTERFACE,
    NODE_METHOD,
)

if TYPE_CHECKING:
    from tree_sitter import Node


class KotlinParser(TreeSitterParser):
    name: ClassVar[str] = "kotlin"
    extensions: ClassVar[tuple[str, ...]] = (".kt", ".kts")
    grammar: ClassVar[str] = "kotlin"

    def classify(
        self, node: Node, source: bytes, *, inside_class: bool
    ) -> Definition | None:
        ntype = node.type
        if ntype == "class_declaration":
            name = self._class_name(node, source)
            if name:
                kind = NODE_INTERFACE if _is_interface(node) else NODE_CLASS
                return Definition(kind=kind, name=name, is_class=True)
        elif ntype == "object_declaration":
            name = self._class_name(node, source)
            if name:
                return Definition(kind=NODE_CLASS, name=name, is_class=True)
        elif ntype == "function_declaration":
            name = self._func_name(node, source)
            if name:
                kind = NODE_METHOD if inside_class else NODE_FUNCTION
                return Definition(kind=kind, name=name, is_class=False)
        elif ntype == "property_declaration" and inside_class:
            name = self._property_name(node, source)
            if name:
                return Definition(kind=NODE_METHOD, name=name, is_class=False)
        return None

    def call_target(self, node: Node, source: bytes) -> str | None:
        if node.type != "call_expression":
            return None
        # Kotlin call_expression: first child is callee, then call_suffix
        for child in node.children:
            if child.type == "simple_identifier":
                return node_text(child, source)
            if child.type == "navigation_expression":
                return _nav_expr_name(child, source)
            if child.type == "call_suffix":
                break
        return None

    def supertypes(self, node: Node, source: bytes) -> list[SuperType]:
        if node.type != "class_declaration":
            return []
        out: list[SuperType] = []
        is_interface = _is_interface(node)
        for child in node.children:
            if child.type == "delegation_specifier":
                name = _delegation_name(child, source)
                if name:
                    if is_interface:
                        edge = EDGE_INHERITS
                    elif _looks_like_interface_kt(name):
                        edge = EDGE_IMPLEMENTS
                    else:
                        edge = EDGE_INHERITS
                    out.append(SuperType(name=name, edge_kind=edge))
        return out

    def docstring(self, node: Node, source: bytes) -> str | None:
        return _preceding_comment(node, source)

    def _class_name(self, node: Node, source: bytes) -> str | None:
        for child in node.children:
            if child.type == "type_identifier":
                return node_text(child, source)
        return None

    def _func_name(self, node: Node, source: bytes) -> str | None:
        for child in node.children:
            if child.type == "simple_identifier":
                return node_text(child, source)
        return None

    def _property_name(self, node: Node, source: bytes) -> str | None:
        for child in node.children:
            if child.type == "variable_declaration":
                for sub in child.children:
                    if sub.type == "simple_identifier":
                        return node_text(sub, source)
            if child.type == "simple_identifier":
                return node_text(child, source)
        return None


def _is_interface(node: Node) -> bool:
    """Check if a class_declaration is an interface (has 'interface' keyword)."""
    for child in node.children:
        if child.type == "interface":
            return True
    return False


def _nav_expr_name(node: Node, source: bytes) -> str | None:
    """Extract the final member name from a navigation_expression."""
    for child in reversed(node.children):
        if child.type == "navigation_suffix":
            for sub in child.children:
                if sub.type == "simple_identifier":
                    return node_text(sub, source)
    return None


def _delegation_name(node: Node, source: bytes) -> str | None:
    """Extract type name from a delegation_specifier."""
    for child in node.children:
        if child.type == "user_type":
            for sub in child.children:
                if sub.type == "type_identifier":
                    return node_text(sub, source)
                if sub.type == "simple_identifier":
                    return node_text(sub, source)
        if child.type == "type_identifier":
            return node_text(child, source)
        if child.type == "simple_identifier":
            return node_text(child, source)
    return None


def _looks_like_interface_kt(name: str) -> bool:
    """Heuristic: Kotlin interfaces often start with uppercase but so do classes.

    Without type resolution we can't distinguish, so we treat all as INHERITS
    unless the name clearly follows interface naming conventions.
    """
    # Conservative: only 'I' prefix pattern (less common in Kotlin than C#)
    return False


def _preceding_comment(node: Node, source: bytes) -> str | None:
    """Extract KDoc (/** ... */) or // comments preceding a node."""
    prev = node.prev_named_sibling
    if prev is None:
        return None
    if prev.type == "multiline_comment":
        text = node_text(prev, source)
        if text.startswith("/**"):
            text = text[3:]
        elif text.startswith("/*"):
            text = text[2:]
        if text.endswith("*/"):
            text = text[:-2]
        lines = [ln.strip().lstrip("* ").strip() for ln in text.split("\n")]
        return "\n".join(ln for ln in lines if ln) or None
    return None
