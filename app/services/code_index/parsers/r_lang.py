"""R language parser."""

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
    EDGE_INHERITS,
    NODE_CLASS,
    NODE_FIELD,
    NODE_FUNCTION,
    NODE_METHOD,
    NODE_VARIABLE,
)

if TYPE_CHECKING:
    from tree_sitter import Node

_LOADER_CALLS = frozenset({"library", "require", "loadNamespace", "requireNamespace"})
_CLASS_CALLS = frozenset({"R6Class", "setClass", "setRefClass"})
_GENERIC_CALLS = frozenset({"setGeneric", "setGroupGeneric"})
_METHOD_CALLS = frozenset({"setMethod", "setReplaceMethod"})
_DECLARATION_CALLS = _CLASS_CALLS | _GENERIC_CALLS | _METHOD_CALLS


class RParser(TreeSitterParser):
    name: ClassVar[str] = "r"
    extensions: ClassVar[tuple[str, ...]] = (".r", ".R")
    grammar: ClassVar[str] = "r"

    def identifier_reference_targets(self, node: Node, source: bytes) -> list[str]:
        # R uses the same identifier node for bindings, parameters, member
        # selectors, package names, and runtime values. The shared fallback
        # therefore creates mostly unresolved fragments. Direct calls,
        # imports, declarations, and inheritance below are structurally exact.
        return []

    def classify(
        self, node: Node, source: bytes, *, inside_class: bool
    ) -> Definition | None:
        if node.type == "binary_operator":
            return self._assignment_definition(node, source)
        if node.type == "argument" and inside_class:
            name = node.child_by_field_name("name")
            value = node.child_by_field_name("value")
            if name is not None and value is not None:
                if value.type == "function_definition":
                    return Definition(kind=NODE_METHOD, name=node_text(name, source))
                if _is_member_argument(node, source):
                    return Definition(kind=NODE_FIELD, name=node_text(name, source))
        if node.type == "call":
            return self._call_definition(node, source)
        return None

    def call_target(self, node: Node, source: bytes) -> str | None:
        if node.type != "call":
            return None
        func = node.child_by_field_name("function")
        name = _r_static_name(func, source) if func is not None else None
        if name is None:
            return None
        leaf = name.rsplit(".")[-1]
        if leaf in _LOADER_CALLS or leaf == "source" or leaf in _DECLARATION_CALLS:
            return None
        if leaf in {"list", "c", "prototype"} and _inside_declaration_arguments(
            node, source
        ):
            return None
        return name

    def supertypes(self, node: Node, source: bytes) -> list[SuperType]:
        call = _class_declaration_call(node, source)
        if call is None:
            return []
        name = _r_call_leaf(call, source)
        argument_name = "inherit" if name == "R6Class" else "contains"
        value = _named_argument_value(call, argument_name, source)
        if value is None:
            return []
        return [
            SuperType(name=parent, edge_kind=EDGE_INHERITS)
            for parent in _r_static_values(value, source)
        ]

    def import_refs(self, node: Node, source: bytes) -> list[ImportRef]:
        # R has no import statement; packages are loaded via library(pkg)/
        # require(pkg) calls, or referenced inline via a pkg::fun namespace
        # operator (call_target already extracts the function half of that
        # for EDGE_CALLS — here we extract the package half for EDGE_IMPORTS).
        if node.type == "call":
            func = next(
                child
                for index, child in enumerate(node.children)
                if node.field_name_for_child(index) == "function"
            )
            if func.type == "identifier":
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
            lhs = next(
                child
                for index, child in enumerate(node.children)
                if node.field_name_for_child(index) == "lhs"
            )
            if lhs.type == "identifier":
                pkg = node_text(lhs, source)
                return [ImportRef(name=pkg, module_path=pkg)]
        return []

    def _call_definition(self, node: Node, source: bytes) -> Definition | None:
        # An assigned R6 declaration is owned by its assignment node so its
        # public/private function arguments inherit the class prefix exactly.
        parent = node.parent
        if (
            parent is not None
            and parent.type == "binary_operator"
            and _r_call_leaf(node, source) in _CLASS_CALLS
        ):
            return None
        name = _r_call_leaf(node, source)
        if name in _CLASS_CALLS:
            class_name = self._first_call_arg_text(node, source)
            if class_name:
                return Definition(kind=NODE_CLASS, name=class_name, is_class=True)
        if name in _GENERIC_CALLS:
            generic_name = self._first_call_arg_text(node, source)
            if generic_name:
                return Definition(kind=NODE_FUNCTION, name=generic_name)
        if name in _METHOD_CALLS:
            method_name = self._first_call_arg_text(node, source)
            owner = _positional_call_arg_text(node, 1, source)
            if method_name:
                return Definition(
                    kind=NODE_METHOD,
                    name=method_name,
                    prefix=f"{owner}." if owner else None,
                )
        return None

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
            value = next(
                item
                for index, item in enumerate(child.children)
                if child.field_name_for_child(index) == "value"
            )
            if value.type != "string":
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

    def _assignment_definition(
        self,
        node: Node,
        source: bytes,
    ) -> Definition | None:
        """Classify left/right function, class, and module-level assignments."""
        lhs = next(
            child
            for index, child in enumerate(node.children)
            if node.field_name_for_child(index) == "lhs"
        )
        rhs = next(
            child
            for index, child in enumerate(node.children)
            if node.field_name_for_child(index) == "rhs"
        )
        operator = next(
            child
            for index, child in enumerate(node.children)
            if node.field_name_for_child(index) == "operator"
        )
        op = node_text(operator, source)
        if rhs.type == "call" and _r_call_leaf(rhs, source) in _CLASS_CALLS:
            class_name = self._first_call_arg_text(rhs, source)
            if class_name:
                return Definition(kind=NODE_CLASS, name=class_name, is_class=True)
        if rhs.type == "function_definition":
            if lhs.type == "identifier":
                return Definition(
                    kind=NODE_FUNCTION,
                    name=node_text(lhs, source),
                )
        if (
            rhs.type == "identifier"
            and op in {"->", "->>"}
            and _unwrap_r_function(lhs) is not None
        ):
            return Definition(
                kind=NODE_FUNCTION,
                name=node_text(rhs, source),
            )
        if not _is_module_assignment(node):
            return None
        if lhs.type == "identifier" and op in {"<-", "<<-", "="}:
            return Definition(kind=NODE_VARIABLE, name=node_text(lhs, source))
        if rhs.type == "identifier" and op in {"->", "->>"}:
            return Definition(kind=NODE_VARIABLE, name=node_text(rhs, source))
        return None


def _r_call_leaf(node: Node, source: bytes) -> str | None:
    if node.type != "call":
        return None
    function = node.child_by_field_name("function")
    name = _r_static_name(function, source) if function is not None else None
    return name.rsplit(".")[-1] if name else None


def _r_static_name(node: Node, source: bytes) -> str | None:
    if node.type == "identifier":
        return node_text(node, source)
    if node.type in {"namespace_operator", "extract_operator"}:
        lhs = next(
            child
            for index, child in enumerate(node.children)
            if node.field_name_for_child(index) == "lhs"
        )
        rhs = next(
            child
            for index, child in enumerate(node.children)
            if node.field_name_for_child(index) == "rhs"
        )
        owner = _r_static_name(lhs, source)
        member = _r_static_name(rhs, source)
        if owner and member:
            return f"{owner}.{member}"
        return member
    if node.type == "string":
        content = node.child_by_field_name("content")
        return node_text(content, source) if content is not None else None
    return None


def _inside_declaration_arguments(node: Node, source: bytes) -> bool:
    ancestor = node.parent
    while ancestor is not None:
        if ancestor.type == "function_definition":
            return False
        if ancestor.type == "call" and _r_call_leaf(ancestor, source) in _DECLARATION_CALLS:
            return True
        ancestor = ancestor.parent
    return False


def _is_member_argument(node: Node, source: bytes) -> bool:
    arguments = node.parent
    call = arguments.parent if arguments is not None else None
    return bool(
        arguments is not None
        and arguments.type == "arguments"
        and call is not None
        and call.type == "call"
        and _r_call_leaf(call, source) in {"list", "c", "prototype"}
    )


def _class_declaration_call(node: Node, source: bytes) -> Node | None:
    if _r_call_leaf(node, source) in _CLASS_CALLS:
        return node
    if node.type != "binary_operator":
        return None
    rhs = node.child_by_field_name("rhs")
    if rhs is not None and _r_call_leaf(rhs, source) in _CLASS_CALLS:
        return rhs
    return None


def _named_argument_value(
    call: Node, argument_name: str, source: bytes
) -> Node | None:
    arguments = call.child_by_field_name("arguments")
    if arguments is None:
        return None
    for argument in arguments.named_children:
        if argument.type != "argument":
            continue
        name = argument.child_by_field_name("name")
        if name is not None and node_text(name, source) == argument_name:
            return argument.child_by_field_name("value")
    return None


def _positional_call_arg_text(call: Node, index: int, source: bytes) -> str | None:
    arguments = call.child_by_field_name("arguments")
    if arguments is None:
        return None
    positional = [
        argument
        for argument in arguments.named_children
        if argument.type == "argument"
        and argument.child_by_field_name("name") is None
    ]
    if index >= len(positional):
        return None
    value = positional[index].child_by_field_name("value")
    return _r_static_name(value, source) if value is not None else None


def _r_static_values(node: Node, source: bytes) -> list[str]:
    name = _r_static_name(node, source)
    if name:
        return [name]
    if _r_call_leaf(node, source) not in {"c", "list"}:
        return []
    arguments = node.child_by_field_name("arguments")
    if arguments is None:
        return []
    out: list[str] = []
    for argument in arguments.named_children:
        if argument.type != "argument":
            continue
        value = argument.child_by_field_name("value")
        if value is not None:
            out.extend(_r_static_values(value, source))
    return list(dict.fromkeys(out))


def _is_module_assignment(node: Node) -> bool:
    ancestor = node.parent
    while ancestor is not None:
        if ancestor.type == "function_definition":
            return False
        ancestor = ancestor.parent
    return True


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
    name = path.replace("\\", "/").rsplit("/")[-1]
    return name[:-2] if name.lower().endswith(".r") else name
