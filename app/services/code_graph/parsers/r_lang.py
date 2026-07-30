"""R language parser."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from app.services.code_graph.parsers.base import (
    Definition,
    ImportRef,
    SuperType,
    TreeSitterParser,
    node_text,
)
from app.services.code_graph.types import NODE_FUNCTION

if TYPE_CHECKING:
    from tree_sitter import Node

_LOADER_CALLS = frozenset({"library", "require", "loadNamespace", "requireNamespace"})


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
            if func is not None and func.type == "extract_operator":
                member = func.child_by_field_name("rhs")
                if member is not None and member.type in {"identifier", "string"}:
                    return node_text(member, source).strip("'\"")
            if func is not None and func.type == "string":
                return node_text(func, source).strip("'\"")
        return None

    def supertypes(self, node: Node, source: bytes) -> list[SuperType]:
        return []

    def import_refs(self, node: Node, source: bytes) -> list[ImportRef]:
        # R has no import statement; packages are loaded via library(pkg)/
        # require(pkg) calls, or referenced inline via a pkg::fun namespace
        # operator (call_target already extracts the function half of that
        # for EDGE_CALLS — here we extract the package half for EDGE_IMPORTS).
        if node.type == "call":
            func = node.child_by_field_name("function")
            if func is not None and func.type == "identifier":
                fname = node_text(func, source)
                if fname in _LOADER_CALLS:
                    pkg = self._first_call_arg_text(node, source)
                    if pkg:
                        return [ImportRef(name=pkg, module_path=pkg)]
                if fname == "source":
                    path = self._first_call_string(node, source)
                    if path:
                        return [
                            ImportRef(name=_source_ref_name(path), module_path=path)
                        ]
            return []
        if node.type == "namespace_operator":
            lhs = node.child_by_field_name("lhs")
            if lhs is not None and lhs.type == "identifier":
                pkg = node_text(lhs, source)
                return [ImportRef(name=pkg, module_path=pkg)]
        return []

    def _first_call_arg_text(self, node: Node, source: bytes) -> str | None:
        arguments = node.child_by_field_name("arguments")
        if arguments is None:
            return None
        for child in arguments.children:
            if child.type == "argument":
                value = child.child_by_field_name("value")
                if value is None:
                    continue
                if value.type == "identifier":
                    return node_text(value, source)
                if value.type == "string":
                    content = value.child_by_field_name("content")
                    if content is not None:
                        return node_text(content, source)
        return None

    def _first_call_string(self, node: Node, source: bytes) -> str | None:
        arguments = node.child_by_field_name("arguments")
        if arguments is None:
            return None
        for child in arguments.children:
            if child.type != "argument":
                continue
            value = child.child_by_field_name("value")
            if value is None or value.type != "string":
                return None
            content = value.child_by_field_name("content")
            return node_text(content, source) if content is not None else None
        return None

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
        operator = node.child_by_field_name("operator")
        if (
            rhs.type == "identifier"
            and operator is not None
            and node_text(operator, source) in {"->", "->>"}
            and _unwrap_r_function(lhs) is not None
        ):
            return Definition(
                kind=NODE_FUNCTION, name=node_text(rhs, source), is_class=False
            )
        return None


def _unwrap_r_function(node: Node) -> Node | None:
    if node.type == "function_definition":
        return node
    if node.type not in {"parenthesized_expression", "braced_expression"}:
        return None
    for child in node.named_children:
        function = _unwrap_r_function(child)
        if function is not None:
            return function
    return None


def _source_ref_name(path: str) -> str:
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    return name[:-2] if name.lower().endswith(".r") else name
