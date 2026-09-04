"""Lua and Luau language parser."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from app.services.code_index.parsers.base import (
    Definition,
    ImportRef,
    SuperType,
    TreeSitterParser,
    node_text,
)
from app.services.code_index.graph_types import (
    NODE_CLASS,
    NODE_FUNCTION,
    NODE_METHOD,
    NODE_VARIABLE,
)

if TYPE_CHECKING:
    from tree_sitter import Node


class LuaParser(TreeSitterParser):
    name: ClassVar[str] = "lua"
    extensions: ClassVar[tuple[str, ...]] = (".lua",)
    grammar: ClassVar[str] = "lua"

    def identifier_reference_targets(self, node: Node, source: bytes) -> list[str]:
        # Lua's grammar uses ordinary identifiers for selector fields,
        # declaration names, and assignment targets. The shared fallback
        # consequently reports syntactic fragments (``client``, ``api``,
        # ``call``) as independent references. Calls/imports below are exact;
        # Lua has no static type syntax from which to derive other references.
        return []

    def classify(
        self, node: Node, source: bytes, *, inside_class: bool
    ) -> Definition | None:
        if node.type == "assignment_statement":
            return _assigned_definition(node, source)
        if node.type == "function_declaration":
            name_node = next(
                child
                for index, child in enumerate(node.children)
                if node.field_name_for_child(index) == "name"
            )
            return _lua_function_definition(name_node, source)
        return None

    def call_target(self, node: Node, source: bytes) -> str | None:
        return _lua_call_target(node, source)

    def import_refs(self, node: Node, source: bytes) -> list[ImportRef]:
        return _require_refs(node, source)

    def supertypes(self, node: Node, source: bytes) -> list[SuperType]:
        return []

    def docstring(self, node: Node, source: bytes) -> str | None:
        return _lua_docstring(node, source)


class LuauParser(TreeSitterParser):
    name: ClassVar[str] = "luau"
    extensions: ClassVar[tuple[str, ...]] = (".luau",)
    grammar: ClassVar[str] = "luau"

    def identifier_reference_targets(self, node: Node, source: bytes) -> list[str]:
        # Luau shares Lua's ambiguous identifier grammar. Precise type_refs,
        # call, and import hooks provide the trustworthy relations instead of
        # emitting selector/type/declaration fragments as runtime references.
        return []

    def classify(
        self, node: Node, source: bytes, *, inside_class: bool
    ) -> Definition | None:
        if node.type == "type_definition":
            name = next(
                child
                for index, child in enumerate(node.children)
                if node.field_name_for_child(index) == "name"
            )
            if name.type == "generic_type":
                name = name.named_children[0]
            return Definition(kind=NODE_CLASS, name=node_text(name, source))
        if node.type == "assignment_statement":
            return _assigned_definition(node, source)
        if node.type == "function_declaration":
            name_node = next(
                child
                for index, child in enumerate(node.children)
                if node.field_name_for_child(index) == "name"
            )
            return _lua_function_definition(name_node, source)
        return None

    def call_target(self, node: Node, source: bytes) -> str | None:
        return _lua_call_target(node, source)

    def import_refs(self, node: Node, source: bytes) -> list[ImportRef]:
        return _require_refs(node, source)

    def supertypes(self, node: Node, source: bytes) -> list[SuperType]:
        return []

    def type_refs(self, node: Node, source: bytes) -> list[str]:
        out: list[str] = []
        if node.type == "type_definition":
            name = next(
                child
                for index, child in enumerate(node.children)
                if node.field_name_for_child(index) == "name"
            )
            excluded: set[str] = set()
            if name.type == "generic_type":
                excluded.update(
                    node_text(child, source)
                    for child in name.named_children[1:]
                    if child.type == "identifier"
                )
            value = next(
                child for child in reversed(node.named_children) if child != name
            )
            _collect_luau_type_ids(value, source, out, excluded=excluded)
        elif node.type == "function_declaration":
            _collect_luau_function_type_ids(node, source, out)
        elif node.type == "assignment_statement":
            variable_list = next(
                child for child in node.children if child.type == "variable_list"
            )
            for index, child in enumerate(variable_list.children[:-1]):
                if child.type != ":":
                    continue
                annotation = variable_list.children[index + 1]
                if annotation.is_named:
                    _collect_luau_type_ids(annotation, source, out)
            expression_list = next(
                child for child in node.children if child.type == "expression_list"
            )
            for expression in expression_list.named_children:
                if expression.type == "function_definition":
                    _collect_luau_function_type_ids(expression, source, out)
        return list(dict.fromkeys(out))

    def docstring(self, node: Node, source: bytes) -> str | None:
        return _lua_docstring(node, source)


def _lua_call_target(node: Node, source: bytes) -> str | None:
    if node.type != "function_call":
        return None
    name_node = next(
        child
        for index, child in enumerate(node.children)
        if node.field_name_for_child(index) == "name"
    )
    name = _static_lua_name(name_node, source)
    # Package loading is represented by its path-aware EDGE_IMPORTS relation,
    # not a misleading runtime call to a user-defined function named require.
    return None if name == "require" else name


def _static_lua_name(node: Node, source: bytes) -> str | None:
    """Return a statically resolvable identifier/member path."""
    if node.type == "identifier":
        return node_text(node, source)
    if node.type not in {"dot_index_expression", "method_index_expression"}:
        return None
    owner_node = node.child_by_field_name("table")
    member_node = node.child_by_field_name("field") or node.child_by_field_name(
        "method"
    )
    if member_node is None:
        return None
    member = node_text(member_node, source)
    owner = _static_lua_name(owner_node, source) if owner_node is not None else None
    return f"{owner}.{member}" if owner else member


def _require_refs(node: Node, source: bytes) -> list[ImportRef]:
    """Lua/Luau have no import grammar node — ``require(...)`` is an ordinary
    call, e.g. ``local socket = require("socket.http")`` or the bare-string
    call form ``require "mypkg.utils"``.
    """
    if node.type != "function_call":
        return []
    name_node = next(
        child
        for index, child in enumerate(node.children)
        if node.field_name_for_child(index) == "name"
    )
    if name_node.type != "identifier":
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


def _lua_function_definition(name_node: Node, source: bytes) -> Definition | None:
    name = _static_lua_name(name_node, source)
    if name is None:
        return None
    if name_node.type == "identifier":
        return Definition(kind=NODE_FUNCTION, name=name)
    if name_node.type in {"dot_index_expression", "method_index_expression"}:
        owner, separator, leaf = name.rpartition(".")
        if separator:
            return Definition(
                kind=NODE_METHOD,
                name=leaf,
                prefix=f"{owner}.",
            )
    return None


def _assigned_definition(node: Node, source: bytes) -> Definition | None:
    variable_list = next(
        child for child in node.children if child.type == "variable_list"
    )
    expression_list = next(
        child for child in node.children if child.type == "expression_list"
    )
    targets = [
        child
        for index, child in enumerate(variable_list.children)
        if variable_list.field_name_for_child(index) == "name"
    ]
    values = [
        child
        for index, child in enumerate(expression_list.children)
        if expression_list.field_name_for_child(index) == "value"
    ]
    if len(targets) != 1 or len(values) != 1:
        return None
    if values[0].type == "function_definition":
        return _lua_function_definition(targets[0], source)
    if not _is_module_assignment(node):
        return None
    name = _static_lua_name(targets[0], source)
    if name is None:
        return None
    owner, separator, leaf = name.rpartition(".")
    return Definition(
        kind=NODE_VARIABLE,
        name=leaf if separator else name,
        prefix=f"{owner}." if separator else None,
    )


def _is_module_assignment(node: Node) -> bool:
    ancestor = node.parent
    while ancestor is not None:
        if ancestor.type in {"function_declaration", "function_definition"}:
            return False
        ancestor = ancestor.parent
    return True


def _lua_docstring(node: Node, source: bytes) -> str | None:
    prev = node.prev_named_sibling
    if prev is None or prev.type != "comment":
        return None
    lines: list[str] = []
    cur: Node | None = prev
    while cur is not None and cur.type == "comment":
        text = node_text(cur, source)
        if text.startswith("---"):
            lines.append(text[3:].strip())
        else:
            break
        cur = cur.prev_named_sibling
    lines.reverse()
    return "\n".join(line for line in lines if line) or None


def _first_arg(args_node: Node) -> Node | None:
    return args_node.named_children[0] if args_node.named_children else None


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
    fallback = module_path.rsplit(".")[-1]
    parent: Node = call_node.parent  # ty: ignore[invalid-assignment]
    if parent.type != "expression_list":
        return fallback
    grandparent: Node = parent.parent  # ty: ignore[invalid-assignment]
    if grandparent.type != "assignment_statement":
        return fallback
    variable_list = next(
        child for child in grandparent.children if child.type == "variable_list"
    )
    target = next(
        child
        for index, child in enumerate(variable_list.children)
        if variable_list.field_name_for_child(index) == "name"
    )
    name = _static_lua_name(target, source)
    return name.rsplit(".")[-1] if name is not None else fallback


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


def _collect_luau_function_type_ids(node: Node, source: bytes, out: list[str]) -> None:
    generic_parameters = next(
        (child for child in node.named_children if child.type == "generic_type_list"),
        None,
    )
    excluded = (
        {
            node_text(child, source)
            for child in generic_parameters.named_children
            if child.type == "identifier"
        }
        if generic_parameters is not None
        else set()
    )
    params = next(child for child in node.children if child.type == "parameters")
    for param in params.named_children:
        if param.type != "parameter":
            continue
        for annotation in param.named_children[1:]:
            _collect_luau_type_ids(annotation, source, out, excluded=excluded)

    body = node.child_by_field_name("body")
    return_type = params.next_named_sibling
    if return_type is not None and return_type != body:
        _collect_luau_type_ids(return_type, source, out, excluded=excluded)


def _collect_luau_type_ids(
    node: Node,
    source: bytes,
    out: list[str],
    *,
    excluded: set[str] | None = None,
) -> None:
    """Recursively collect user-defined type identifiers from Luau type nodes."""
    excluded = excluded or set()
    if node.type == "identifier":
        name = node_text(node, source)
        if name not in _LUAU_BUILTIN_TYPES and name not in excluded:
            out.append(name)
        return
    if node.type == "object_type":
        for index, child in enumerate(node.children):
            if not child.is_named:
                continue
            next_child = node.children[index + 1]
            if child.type == "identifier" and next_child.type == ":":
                continue
            _collect_luau_type_ids(child, source, out, excluded=excluded)
        return
    for child in node.named_children:
        _collect_luau_type_ids(child, source, out, excluded=excluded)
