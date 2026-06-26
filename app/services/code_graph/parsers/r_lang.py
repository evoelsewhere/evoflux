"""R language parser."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from app.services.code_graph.parsers.base import (
    Definition,
    SuperType,
    TreeSitterParser,
    node_text,
)
from app.services.code_graph.types import NODE_FUNCTION

if TYPE_CHECKING:
    from tree_sitter import Node


class RParser(TreeSitterParser):
    name: ClassVar[str] = "r"
    extensions: ClassVar[tuple[str, ...]] = (".r", ".R")
    grammar: ClassVar[str] = "r"

    def classify(
        self, node: Node, source: bytes, *, inside_class: bool
    ) -> Definition | None:
        # R has `name <- function(...)` or `name = function(...)`
        if node.type in ("binary_operator", "left_assignment"):
            return self._check_function_assign(node, source)
        # Alternative: equals assignment
        if node.type == "equals_assignment":
            return self._check_function_assign(node, source)
        return None

    def call_target(self, node: Node, source: bytes) -> str | None:
        if node.type == "call":
            func = node.child_by_field_name("function")
            if func is not None and func.type == "identifier":
                return node_text(func, source)
            if func is not None and func.type == "namespace_operator":
                # pkg::func or pkg:::func
                for child in reversed(func.children):
                    if child.type == "identifier":
                        return node_text(child, source)
        return None

    def supertypes(self, node: Node, source: bytes) -> list[SuperType]:
        return []

    def docstring(self, node: Node, source: bytes) -> str | None:
        prev = node.prev_named_sibling
        if prev is not None and prev.type == "comment":
            lines: list[str] = []
            cur: Node | None = prev
            while cur is not None and cur.type == "comment":
                text = node_text(cur, source)
                if text.startswith("#'"):
                    lines.append(text[2:].strip())
                else:
                    break
                cur = cur.prev_named_sibling
            if lines:
                lines.reverse()
                return "\n".join(lines)
        return None

    def _check_function_assign(self, node: Node, source: bytes) -> Definition | None:
        """Check if node is `name <- function(...)` pattern."""
        lhs = node.child_by_field_name("lhs")
        rhs = node.child_by_field_name("rhs")
        if lhs is None or rhs is None:
            return None
        if rhs.type == "function_definition":
            if lhs.type == "identifier":
                return Definition(
                    kind=NODE_FUNCTION, name=node_text(lhs, source), is_class=False
                )
        return None
