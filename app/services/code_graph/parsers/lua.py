"""Lua and Luau language parser."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from app.services.code_graph.parsers.base import (
    Definition,
    SuperType,
    TreeSitterParser,
    node_text,
)
from app.services.code_graph.types import (
    NODE_CLASS,
    NODE_FUNCTION,
    NODE_METHOD,
)

if TYPE_CHECKING:
    from tree_sitter import Node


class LuaParser(TreeSitterParser):
    name: ClassVar[str] = "lua"
    extensions: ClassVar[tuple[str, ...]] = (".lua",)
    grammar: ClassVar[str] = "lua"

    def classify(
        self, node: Node, source: bytes, *, inside_class: bool
    ) -> Definition | None:
        if node.type != "function_declaration":
            return None
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return None
        ntype = name_node.type
        name = node_text(name_node, source)
        if ntype == "method_index_expression":
            # Animal:run → method
            parts = name.split(":")
            if len(parts) == 2:
                return Definition(
                    kind=NODE_METHOD,
                    name=parts[1],
                    is_class=False,
                    prefix=parts[0],
                )
        elif ntype == "dot_index_expression":
            # Animal.new → class method
            parts = name.split(".")
            if len(parts) == 2:
                return Definition(
                    kind=NODE_METHOD,
                    name=parts[1],
                    is_class=False,
                    prefix=parts[0],
                )
        elif ntype == "identifier":
            return Definition(kind=NODE_FUNCTION, name=name, is_class=False)
        return None

    def call_target(self, node: Node, source: bytes) -> str | None:
        if node.type == "function_call":
            name_node = node.child_by_field_name("name")
            if name_node is None:
                # Some grammars have prefix field
                name_node = node.child_by_field_name("prefix")
            if name_node is None:
                return None
            ntype = name_node.type
            if ntype == "identifier":
                return node_text(name_node, source)
            if ntype in ("dot_index_expression", "method_index_expression"):
                text = node_text(name_node, source)
                parts = text.replace(":", ".").split(".")
                return parts[-1] if parts else None
        return None

    def supertypes(self, node: Node, source: bytes) -> list[SuperType]:
        return []

    def docstring(self, node: Node, source: bytes) -> str | None:
        prev = node.prev_named_sibling
        if prev is not None and prev.type == "comment":
            text = node_text(prev, source)
            if text.startswith("---"):
                lines: list[str] = []
                cur: Node | None = prev
                while cur is not None and cur.type == "comment":
                    t = node_text(cur, source)
                    if t.startswith("---"):
                        lines.append(t[3:].strip())
                    elif t.startswith("--"):
                        lines.append(t[2:].strip())
                    else:
                        break
                    cur = cur.prev_named_sibling
                lines.reverse()
                return "\n".join(ln for ln in lines if ln) or None
        return None


class LuauParser(TreeSitterParser):
    name: ClassVar[str] = "luau"
    extensions: ClassVar[tuple[str, ...]] = (".luau",)
    grammar: ClassVar[str] = "luau"

    def classify(
        self, node: Node, source: bytes, *, inside_class: bool
    ) -> Definition | None:
        if node.type == "type_declaration":
            name = node.child_by_field_name("name")
            if name is not None:
                return Definition(
                    kind=NODE_CLASS, name=node_text(name, source), is_class=True
                )
        if node.type in ("function_declaration", "local_function"):
            name_node = node.child_by_field_name("name")
            if name_node is None:
                return None
            name = node_text(name_node, source)
            if name_node.type == "identifier":
                return Definition(kind=NODE_FUNCTION, name=name, is_class=False)
            if ":" in name:
                parts = name.split(":")
                return Definition(
                    kind=NODE_METHOD, name=parts[-1], is_class=False, prefix=parts[0]
                )
            if "." in name:
                parts = name.split(".")
                return Definition(
                    kind=NODE_METHOD, name=parts[-1], is_class=False, prefix=parts[0]
                )
        return None

    def call_target(self, node: Node, source: bytes) -> str | None:
        if node.type == "function_call":
            name_node = node.child_by_field_name("name") or node.child_by_field_name(
                "prefix"
            )
            if name_node is None:
                return None
            if name_node.type == "identifier":
                return node_text(name_node, source)
            text = node_text(name_node, source)
            parts = text.replace(":", ".").split(".")
            return parts[-1] if parts else None
        return None

    def supertypes(self, node: Node, source: bytes) -> list[SuperType]:
        return []

    def docstring(self, node: Node, source: bytes) -> str | None:
        return None
