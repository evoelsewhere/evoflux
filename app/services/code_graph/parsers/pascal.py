"""Pascal/Delphi/Free Pascal language parser."""

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


class PascalParser(TreeSitterParser):
    name: ClassVar[str] = "pascal"
    extensions: ClassVar[tuple[str, ...]] = (".pas", ".pp", ".dpr", ".lpr")
    grammar: ClassVar[str] = "pascal"

    def classify(
        self, node: Node, source: bytes, *, inside_class: bool
    ) -> Definition | None:
        ntype = node.type
        if ntype == "declClass":
            name = self._type_name(node, source)
            if name:
                return Definition(kind=NODE_CLASS, name=name, is_class=True)
        elif ntype == "declType":
            # Covers class declarations inside type section
            name_node = node.child_by_field_name("name") or self._first_child_type(
                node, "genericTpl"
            )
            if name_node:
                return Definition(
                    kind=NODE_CLASS, name=node_text(name_node, source), is_class=True
                )
        elif ntype == "defProc":
            name = self._proc_name(node, source)
            if name:
                kind = NODE_METHOD if "." in name else NODE_FUNCTION
                return Definition(kind=kind, name=name.split(".")[-1], is_class=False)
        elif ntype == "declProc":
            name = self._proc_name(node, source)
            if name:
                return Definition(kind=NODE_METHOD, name=name, is_class=False)
        return None

    def call_target(self, node: Node, source: bytes) -> str | None:
        if node.type == "exprCall":
            for child in node.children:
                if child.type == "identifier":
                    return node_text(child, source)
                if child.type == "exprDot":
                    for sub in reversed(child.children):
                        if sub.type == "identifier":
                            return node_text(sub, source)
                    break
        return None

    def supertypes(self, node: Node, source: bytes) -> list[SuperType]:
        if node.type not in ("declClass", "declType"):
            return []
        out: list[SuperType] = []
        for child in node.children:
            if child.type == "classParent":
                for sub in child.children:
                    if sub.type == "identifier":
                        out.append(
                            SuperType(
                                name=node_text(sub, source), edge_kind=EDGE_INHERITS
                            )
                        )
        return out

    def docstring(self, node: Node, source: bytes) -> str | None:
        prev = node.prev_named_sibling
        if prev is not None and prev.type == "comment":
            text = node_text(prev, source)
            if text.startswith("{"):
                return text.strip("{}").strip()
            if text.startswith("(*"):
                return text[2:-2].strip() if text.endswith("*)") else text[2:].strip()
        return None

    def _type_name(self, node: Node, source: bytes) -> str | None:
        for child in node.children:
            if child.type == "identifier":
                return node_text(child, source)
            if child.type == "genericTpl":
                for sub in child.children:
                    if sub.type == "identifier":
                        return node_text(sub, source)
        return None

    def _proc_name(self, node: Node, source: bytes) -> str | None:
        for child in node.children:
            if child.type == "moduleName":
                return node_text(child, source)
            if child.type == "identifier":
                return node_text(child, source)
        return None

    def _first_child_type(self, node: Node, ntype: str) -> Node | None:
        for child in node.children:
            if child.type == ntype:
                return child
        return None
