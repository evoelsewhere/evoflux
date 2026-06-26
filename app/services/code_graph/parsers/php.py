"""PHP language parser."""

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


class PhpParser(TreeSitterParser):
    name: ClassVar[str] = "php"
    extensions: ClassVar[tuple[str, ...]] = (".php",)
    grammar: ClassVar[str] = "php"

    def classify(
        self, node: Node, source: bytes, *, inside_class: bool
    ) -> Definition | None:
        ntype = node.type
        if ntype == "class_declaration":
            name = self._field_name(node, source)
            if name:
                return Definition(kind=NODE_CLASS, name=name, is_class=True)
        elif ntype == "interface_declaration":
            name = self._field_name(node, source)
            if name:
                return Definition(kind=NODE_INTERFACE, name=name, is_class=True)
        elif ntype == "trait_declaration":
            name = self._field_name(node, source)
            if name:
                return Definition(kind=NODE_CLASS, name=name, is_class=True)
        elif ntype == "enum_declaration":
            name = self._field_name(node, source)
            if name:
                return Definition(kind=NODE_CLASS, name=name, is_class=True)
        elif ntype == "method_declaration":
            name = self._field_name(node, source)
            if name:
                return Definition(kind=NODE_METHOD, name=name, is_class=False)
        elif ntype == "function_definition":
            name = self._field_name(node, source)
            if name:
                return Definition(kind=NODE_FUNCTION, name=name, is_class=False)
        return None

    def call_target(self, node: Node, source: bytes) -> str | None:
        ntype = node.type
        if ntype == "function_call_expression":
            func = node.child_by_field_name("function")
            if func is not None and func.type == "name":
                return node_text(func, source)
        elif ntype == "member_call_expression":
            name = node.child_by_field_name("name")
            if name is not None:
                return node_text(name, source)
        elif ntype == "scoped_call_expression":
            name = node.child_by_field_name("name")
            if name is not None:
                return node_text(name, source)
        elif ntype == "object_creation_expression":
            for child in node.children:
                if child.type == "name":
                    return node_text(child, source)
                if child.type == "qualified_name":
                    return _last_name(child, source)
        return None

    def supertypes(self, node: Node, source: bytes) -> list[SuperType]:
        if node.type not in ("class_declaration", "interface_declaration"):
            return []
        out: list[SuperType] = []
        for child in node.children:
            if child.type == "base_clause":
                for sub in child.children:
                    if sub.type == "name":
                        out.append(
                            SuperType(
                                name=node_text(sub, source), edge_kind=EDGE_INHERITS
                            )
                        )
                    elif sub.type == "qualified_name":
                        out.append(
                            SuperType(
                                name=_last_name(sub, source) or "",
                                edge_kind=EDGE_INHERITS,
                            )
                        )
            elif child.type == "class_interface_clause":
                for sub in child.children:
                    if sub.type == "name":
                        out.append(
                            SuperType(
                                name=node_text(sub, source), edge_kind=EDGE_IMPLEMENTS
                            )
                        )
                    elif sub.type == "qualified_name":
                        out.append(
                            SuperType(
                                name=_last_name(sub, source) or "",
                                edge_kind=EDGE_IMPLEMENTS,
                            )
                        )
        return out

    def docstring(self, node: Node, source: bytes) -> str | None:
        prev = node.prev_named_sibling
        if prev is not None and prev.type == "comment":
            text = node_text(prev, source)
            if text.startswith("/**"):
                return _strip_phpdoc(text)
        return None

    def _field_name(self, node: Node, source: bytes) -> str | None:
        name_node = node.child_by_field_name("name")
        if name_node is not None:
            return node_text(name_node, source)
        for child in node.children:
            if child.type == "name":
                return node_text(child, source)
        return None


def _last_name(node: Node, source: bytes) -> str | None:
    for child in reversed(node.children):
        if child.type == "name":
            return node_text(child, source)
    return None


def _strip_phpdoc(text: str) -> str:
    s = text.strip()
    if s.startswith("/**"):
        s = s[3:]
    if s.endswith("*/"):
        s = s[:-2]
    lines = [ln.strip().lstrip("* ").strip() for ln in s.split("\n")]
    return "\n".join(ln for ln in lines if ln and not ln.startswith("@"))
