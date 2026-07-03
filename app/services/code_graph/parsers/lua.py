"""Lua and Luau language parser."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from app.services.code_graph.parsers.base import (
    Definition,
    ImportRef,
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

    def import_refs(self, node: Node, source: bytes) -> list[ImportRef]:
        return _require_refs(node, source)

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

    def import_refs(self, node: Node, source: bytes) -> list[ImportRef]:
        return _require_refs(node, source)

    def supertypes(self, node: Node, source: bytes) -> list[SuperType]:
        return []

    def type_refs(self, node: Node, source: bytes) -> list[str]:
        if node.type not in {"function_declaration", "local_function"}:
            return []
        out: list[str] = []
        params = node.child_by_field_name("parameters")
        if params is not None:
            for param in params.children:
                if param.type == "parameter":
                    type_node = param.child_by_field_name("type")
                    if type_node is not None:
                        _collect_luau_type_ids(type_node, source, out)
        ret = node.child_by_field_name("return_type")
        if ret is not None:
            _collect_luau_type_ids(ret, source, out)
        return out

    def docstring(self, node: Node, source: bytes) -> str | None:
        return None


def _require_refs(node: Node, source: bytes) -> list[ImportRef]:
    """Lua/Luau have no import grammar node — ``require(...)`` is an ordinary
    call, e.g. ``local socket = require("socket.http")`` or the bare-string
    call form ``require "mypkg.utils"``.
    """
    if node.type != "function_call":
        return []
    name_node = node.child_by_field_name("name")
    if name_node is None or name_node.type != "identifier":
        return []
    if node_text(name_node, source) != "require":
        return []
    args_node = node.child_by_field_name("arguments")
    if args_node is None:
        return []
    # The `arguments` node wraps a single string for both call styles —
    # parenthesized (`require("x")`) and the bare-string call form
    # (`require "x"`, no parens, still an `arguments` wrapper).
    arg = _first_arg(args_node)
    if arg is None:
        return []
    module_path = (
        _string_content(arg, source) if arg.type == "string" else node_text(arg, source)
    )
    if not module_path:
        return []
    return [
        ImportRef(name=_bound_name(node, module_path, source), module_path=module_path)
    ]


def _first_arg(args_node: Node) -> Node | None:
    for child in args_node.children:
        if child.type not in ("(", ")", ","):
            return child
    return None


def _string_content(string_node: Node, source: bytes) -> str | None:
    for child in string_node.children:
        if child.type == "string_content":
            return node_text(child, source)
    return None


def _bound_name(call_node: Node, module_path: str, source: bytes) -> str:
    """Locally-used name: the first identifier assigned in an enclosing
    `local x = require(...)` / `x = require(...)`, else the last dotted
    segment of the module path (e.g. bare statement-level `require "x.y"`).
    """
    parent = call_node.parent
    if parent is not None and parent.type == "expression_list":
        grandparent = parent.parent
        if grandparent is not None and grandparent.type == "assignment_statement":
            var_list = next(
                (c for c in grandparent.children if c.type == "variable_list"), None
            )
            if var_list is not None:
                for child in var_list.children:
                    if child.type in ("identifier", "dot_index_expression"):
                        return node_text(child, source).split(".")[-1]
    return module_path.split(".")[-1]


_LUAU_BUILTIN_TYPES = frozenset(
    {
        "boolean",
        "number",
        "string",
        "nil",
        "thread",
        "userdata",
        "buffer",
        "any",
        "unknown",
        "never",
        "none",
    }
)


def _collect_luau_type_ids(node: Node, source: bytes, out: list[str]) -> None:
    """Recursively collect user-defined type identifiers from Luau type nodes."""
    if node.type == "type_identifier":
        name = node_text(node, source)
        if name not in _LUAU_BUILTIN_TYPES:
            out.append(name)
        return
    if node.type in (
        "generic_type",
        "nullable_type",
        "type_intersection",
        "type_union",
    ):
        for child in node.children:
            _collect_luau_type_ids(child, source, out)
        return
    for child in node.children:
        _collect_luau_type_ids(child, source, out)
