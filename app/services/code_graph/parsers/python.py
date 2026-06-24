"""Python language parser."""

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
    NODE_METHOD,
)

if TYPE_CHECKING:
    from tree_sitter import Node


class PythonParser(TreeSitterParser):
    name: ClassVar[str] = "python"
    extensions: ClassVar[tuple[str, ...]] = (".py", ".pyi")
    grammar: ClassVar[str] = "python"

    def classify(
        self, node: Node, source: bytes, *, inside_class: bool
    ) -> Definition | None:
        if node.type == "class_definition":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_CLASS, name=name, is_class=True)
        elif node.type == "function_definition":
            name = self._name(node, source)
            if name:
                kind = NODE_METHOD if inside_class else NODE_FUNCTION
                return Definition(kind=kind, name=name, is_class=False)
        return None

    def call_target(self, node: Node, source: bytes) -> str | None:
        if node.type != "call":
            return None
        func = node.child_by_field_name("function")
        if func is None:
            return None
        if func.type == "identifier":
            return node_text(func, source)
        if func.type == "attribute":
            attr = func.child_by_field_name("attribute")
            if attr is not None:
                return node_text(attr, source)
        return None

    def supertypes(self, node: Node, source: bytes) -> list[SuperType]:
        supers = node.child_by_field_name("superclasses")
        if supers is None:
            return []
        out: list[SuperType] = []
        for child in supers.children:
            if child.type == "identifier":
                out.append(
                    SuperType(name=node_text(child, source), edge_kind=EDGE_INHERITS)
                )
            elif child.type == "attribute":
                attr = child.child_by_field_name("attribute")
                if attr is not None:
                    out.append(
                        SuperType(name=node_text(attr, source), edge_kind=EDGE_INHERITS)
                    )
        return out

    def docstring(self, node: Node, source: bytes) -> str | None:
        body = node.child_by_field_name("body")
        if body is None:
            return None
        for child in body.children:
            # A class/module body exposes the docstring as a bare ``string``;
            # a function body wraps it in an ``expression_statement``.
            if child.type == "string":
                return _strip_py_string(node_text(child, source))
            if child.type == "expression_statement":
                inner = child.children[0] if child.children else None
                if inner is not None and inner.type == "string":
                    return _strip_py_string(node_text(inner, source))
                break
            if child.type == "comment":
                continue
            # Only the first statement can be a docstring.
            break
        return None

    def _name(self, node: Node, source: bytes) -> str | None:
        name = node.child_by_field_name("name")
        return node_text(name, source) if name is not None else None


def _strip_py_string(text: str) -> str:
    """Strip quotes/prefixes from a Python string literal, best effort."""
    s = text.strip()
    # Drop string prefixes (r, b, f, u and combinations).
    while s and s[0] in "rRbBuUfF":
        s = s[1:]
    for quote in ('"""', "'''", '"', "'"):
        if s.startswith(quote) and s.endswith(quote) and len(s) >= 2 * len(quote):
            s = s[len(quote) : len(s) - len(quote)]
            break
    return s.strip()
