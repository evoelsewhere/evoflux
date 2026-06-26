"""Ruby language parser."""

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
    NODE_MODULE,
)

if TYPE_CHECKING:
    from tree_sitter import Node


class RubyParser(TreeSitterParser):
    name: ClassVar[str] = "ruby"
    extensions: ClassVar[tuple[str, ...]] = (".rb",)
    grammar: ClassVar[str] = "ruby"

    def classify(
        self, node: Node, source: bytes, *, inside_class: bool
    ) -> Definition | None:
        ntype = node.type
        if ntype == "class":
            name = self._class_name(node, source)
            if name:
                return Definition(kind=NODE_CLASS, name=name, is_class=True)
        elif ntype == "module":
            name = self._module_name(node, source)
            if name:
                return Definition(kind=NODE_MODULE, name=name, is_class=True)
        elif ntype == "method":
            name = node.child_by_field_name("name")
            if name is not None:
                kind = NODE_METHOD if inside_class else NODE_FUNCTION
                return Definition(
                    kind=kind, name=node_text(name, source), is_class=False
                )
        elif ntype == "singleton_method":
            name = node.child_by_field_name("name")
            if name is not None:
                return Definition(
                    kind=NODE_METHOD, name=node_text(name, source), is_class=False
                )
        return None

    def call_target(self, node: Node, source: bytes) -> str | None:
        if node.type == "call":
            method = node.child_by_field_name("method")
            if method is not None:
                return node_text(method, source)
        elif node.type == "method_call":
            method = node.child_by_field_name("method")
            if method is not None:
                return node_text(method, source)
        return None

    def supertypes(self, node: Node, source: bytes) -> list[SuperType]:
        if node.type != "class":
            return []
        sup = node.child_by_field_name("superclass")
        if sup is None:
            return []
        # superclass node contains '< ClassName'
        for child in sup.children:
            if child.type == "constant":
                return [
                    SuperType(name=node_text(child, source), edge_kind=EDGE_INHERITS)
                ]
            if child.type == "scope_resolution":
                for sub in reversed(child.children):
                    if sub.type == "constant":
                        return [
                            SuperType(
                                name=node_text(sub, source), edge_kind=EDGE_INHERITS
                            )
                        ]
        return []

    def docstring(self, node: Node, source: bytes) -> str | None:
        prev = node.prev_named_sibling
        if prev is not None and prev.type == "comment":
            lines: list[str] = []
            cur: Node | None = prev
            while cur is not None and cur.type == "comment":
                lines.append(node_text(cur, source))
                cur = cur.prev_named_sibling
            lines.reverse()
            cleaned = [ln.lstrip("#").strip() for ln in lines]
            return "\n".join(ln for ln in cleaned if ln) or None
        return None

    def _class_name(self, node: Node, source: bytes) -> str | None:
        for child in node.children:
            if child.type == "constant":
                return node_text(child, source)
        return None

    def _module_name(self, node: Node, source: bytes) -> str | None:
        for child in node.children:
            if child.type == "constant":
                return node_text(child, source)
        return None
