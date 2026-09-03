"""PHP language parser."""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, ClassVar

from app.services.code_index.parsers.base import (
    Definition,
    ImportRef,
    SuperType,
    TreeSitterParser,
    node_text,
)
from app.services.code_index.graph_types import (
    EDGE_IMPLEMENTS,
    EDGE_INHERITS,
    NODE_CLASS,
    NODE_ENUM,
    NODE_FIELD,
    NODE_FUNCTION,
    NODE_INTERFACE,
    NODE_METHOD,
    NODE_NAMESPACE,
    NODE_PROPERTY,
    NODE_VARIABLE,
)

if TYPE_CHECKING:
    from tree_sitter import Node


class PhpParser(TreeSitterParser):
    name: ClassVar[str] = "php"
    extensions: ClassVar[tuple[str, ...]] = (".php",)
    grammar: ClassVar[str] = "php"

    def root_prefix(self, root: Node, source: bytes) -> str:
        namespaces = [
            child for child in root.children if child.type == "namespace_definition"
        ]
        if len(namespaces) != 1:
            return ""
        namespace = namespaces[0]
        if namespace.child_by_field_name("body") is not None:
            return ""
        name = namespace.child_by_field_name("name")
        return f"{_php_namespace_name(name, source)}." if name is not None else ""

    def classify(
        self, node: Node, source: bytes, *, inside_class: bool
    ) -> Definition | None:
        ntype = node.type
        if ntype == "namespace_definition":
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                return Definition(
                    kind=NODE_NAMESPACE,
                    name=_php_namespace_name(name_node, source),
                    prefix="",
                )
        elif ntype == "class_declaration":
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
                return Definition(kind=NODE_ENUM, name=name, is_class=True)
        elif ntype == "method_declaration":
            name = self._field_name(node, source)
            if name:
                return Definition(kind=NODE_METHOD, name=name)
        elif ntype == "function_definition":
            name = self._field_name(node, source)
            if name:
                return Definition(kind=NODE_FUNCTION, name=name)
        elif ntype == "property_element" and inside_class:
            name = self._field_name(node, source)
            if name:
                return Definition(kind=NODE_FIELD, name=name)
        elif ntype == "property_promotion_parameter":
            name = self._field_name(node, source)
            if name:
                return Definition(
                    kind=NODE_FIELD,
                    name=name,
                    prefix=_php_promoted_property_prefix(node, source),
                )
        elif ntype == "const_element":
            name = self._field_name(node, source)
            if name:
                kind = NODE_PROPERTY if inside_class else NODE_VARIABLE
                return Definition(kind=kind, name=name)
        elif ntype == "enum_case":
            name = self._field_name(node, source)
            if name:
                return Definition(kind=NODE_PROPERTY, name=name)
        return None

    def import_refs(self, node: Node, source: bytes) -> list[ImportRef]:
        if node.type != "namespace_use_declaration":
            return []
        # Two shapes: a flat list of "namespace_use_clause" children (each a
        # full dotted path, optionally "as"-aliased), or a "namespace_name"
        # prefix followed by a "namespace_use_group" ("{Str, Arr as A}") whose
        # clauses are bare trailing segments to append to the prefix.
        group = next(
            (c for c in node.children if c.type == "namespace_use_group"), None
        )
        if group is not None:
            prefix_node = next(
                (c for c in node.children if c.type == "namespace_name"), None
            )
            if prefix_node is None:
                return []
            prefix = node_text(prefix_node, source)
            out: list[ImportRef] = []
            for clause in group.children:
                if clause.type != "namespace_use_clause":
                    continue
                ref = self._use_clause_ref(clause, source, prefix=f"{prefix}\\")
                if ref is not None:
                    out.append(ref)
            return out
        out = []
        for clause in node.children:
            if clause.type != "namespace_use_clause":
                continue
            ref = self._use_clause_ref(clause, source, prefix="")
            if ref is not None:
                out.append(ref)
        return out

    def _use_clause_ref(
        self, clause: Node, source: bytes, *, prefix: str
    ) -> ImportRef | None:
        base = next(
            (c for c in clause.children if c.type in ("qualified_name", "name")),
            None,
        )
        if base is None:
            return None
        module_path = f"{prefix}{node_text(base, source)}"
        alias = clause.child_by_field_name("alias")
        if alias is not None:
            return ImportRef(
                name=_last_name(base, source) or node_text(base, source),
                module_path=module_path,
                local_name=node_text(alias, source),
            )
        return ImportRef(
            name=_last_name(base, source) or node_text(base, source),
            module_path=module_path,
        )

    def call_target(self, node: Node, source: bytes) -> str | None:
        ntype = node.type
        if ntype == "function_call_expression":
            func = node.child_by_field_name("function")
            if func is None:
                return None
            return (
                _php_expression_path(func, source)
                if func.type in {"name", "qualified_name"}
                else None
            )
        elif ntype in {"member_call_expression", "scoped_call_expression"}:
            return _php_expression_path(node, source)
        elif ntype == "object_creation_expression":
            for child in node.children:
                if child.type in {"name", "qualified_name"}:
                    return _last_name(child, source) or node_text(child, source)
        return None

    def reference_targets(self, node: Node, source: bytes) -> list[str]:
        if node.type != "use_declaration":
            return []
        return [
            _php_namespace_name(child, source)
            for child in node.children
            if child.type in {"name", "qualified_name"}
        ]

    def supertypes(self, node: Node, source: bytes) -> list[SuperType]:
        if node.type not in (
            "class_declaration",
            "interface_declaration",
            "enum_declaration",
        ):
            return []
        out: list[SuperType] = []
        for child in node.children:
            if child.type == "base_clause":
                out.extend(
                    SuperType(name=name, edge_kind=EDGE_INHERITS)
                    for name in _php_clause_names(child, source)
                )
            elif child.type == "class_interface_clause":
                out.extend(
                    SuperType(name=name, edge_kind=EDGE_IMPLEMENTS)
                    for name in _php_clause_names(child, source)
                )
        return out

    def docstring(self, node: Node, source: bytes) -> str | None:
        owner = _php_leaf_owner(node)
        prev = owner.prev_named_sibling
        if prev is not None and prev.type == "comment":
            text = node_text(prev, source)
            if text.startswith("/**"):
                return _strip_phpdoc(text)
        return None

    def decorators(self, node: Node, source: bytes) -> list[str]:
        owner = _php_leaf_owner(node)
        out: list[str] = []
        for child in owner.children:
            if child.type == "attribute_list":
                for attr in _php_attribute_nodes(child):
                    name = _php_attr_name(attr, source)
                    if name:
                        out.append(name)
        return out

    def type_refs(self, node: Node, source: bytes) -> list[str]:
        owner = _php_leaf_owner(node)
        out: list[str] = []
        if owner.type in {"method_declaration", "function_definition"}:
            params = owner.child_by_field_name("parameters")
            if params is not None:
                for param in params.children:
                    if param.type in {
                        "simple_parameter",
                        "property_promotion_parameter",
                    }:
                        type_node = param.child_by_field_name("type")
                        if type_node is not None:
                            _collect_php_type_ids(type_node, source, out)
            ret = owner.child_by_field_name("return_type")
            if ret is not None:
                _collect_php_type_ids(ret, source, out)
        elif owner.type in {
            "property_declaration",
            "property_promotion_parameter",
            "const_declaration",
        }:
            type_node = owner.child_by_field_name("type")
            if type_node is not None:
                _collect_php_type_ids(type_node, source, out)
        return list(dict.fromkeys(out))

    def _field_name(self, node: Node, source: bytes) -> str | None:
        name_node = next(
            (
                child
                for child in node.children
                if child.type in {"name", "variable_name"}
            ),
            None,
        )
        return (
            node_text(name_node, source).removeprefix("$")
            if name_node is not None
            else None
        )


def _php_clause_names(node: Node, source: bytes) -> list[str]:
    out: list[str] = []
    for child in node.children:
        if child.type == "name":
            out.append(node_text(child, source))
        elif child.type == "qualified_name":
            name = _last_name(child, source)
            if name:
                out.append(name)
    return out


def _php_leaf_owner(node: Node) -> Node:
    parent = node.parent
    if parent is not None and parent.type in {
        "property_declaration",
        "const_declaration",
    }:
        return parent
    return node


def _php_attribute_nodes(node: Node) -> Iterator[Node]:
    for child in node.children:
        if child.type == "attribute":
            yield child
        else:
            yield from _php_attribute_nodes(child)


def _php_promoted_property_prefix(node: Node, source: bytes) -> str | None:
    class_name: str | None = None
    namespace_name: str | None = None
    root = node
    while root.parent is not None:
        root = root.parent
    ancestor = node.parent
    while ancestor is not None:
        if ancestor.type == "class_declaration":
            name = ancestor.child_by_field_name("name")
            if name is not None:
                class_name = node_text(name, source)
        elif ancestor.type == "namespace_definition":
            name = ancestor.child_by_field_name("name")
            if name is not None:
                namespace_name = _php_namespace_name(name, source)
        ancestor = ancestor.parent
    if namespace_name is None:
        namespaces = [
            child for child in root.children if child.type == "namespace_definition"
        ]
        if len(namespaces) == 1:
            name = namespaces[0].child_by_field_name("name")
            if name is not None:
                namespace_name = _php_namespace_name(name, source)
    if class_name is None:
        return None
    return ".".join(part for part in (namespace_name, class_name) if part) + "."


def _php_expression_path(node: Node, source: bytes) -> str | None:
    if node.type in {"name", "relative_scope"}:
        return node_text(node, source)
    if node.type == "variable_name":
        return node_text(node, source).removeprefix("$")
    if node.type == "qualified_name":
        return _php_namespace_name(node, source)
    if node.type in {"member_access_expression", "member_call_expression"}:
        receiver = node.child_by_field_name("object")
        name = node.child_by_field_name("name")
        receiver_path = (
            _php_expression_path(receiver, source) if receiver is not None else None
        )
        if name is None:
            return receiver_path
        local_name = node_text(name, source)
        return f"{receiver_path}.{local_name}" if receiver_path else local_name
    if node.type in {"scoped_property_access_expression", "scoped_call_expression"}:
        scope = node.child_by_field_name("scope")
        name = node.child_by_field_name("name")
        scope_path = _php_expression_path(scope, source) if scope is not None else None
        if scope_path in {"self", "static", "parent"}:
            scope_path = "this"
        if name is None:
            return scope_path
        local_name = node_text(name, source).removeprefix("$")
        return f"{scope_path}.{local_name}" if scope_path else local_name
    return None


_PHP_BUILTIN_TYPES = frozenset(
    {
        "bool",
        "int",
        "float",
        "string",
        "array",
        "callable",
        "iterable",
        "object",
        "mixed",
        "void",
        "null",
        "never",
        "parent",
        "self",
        "static",
        "true",
        "false",
    }
)


def _php_attr_name(attr_node: Node, source: bytes) -> str | None:
    """Extract attribute name from a PHP attribute node."""
    for child in attr_node.children:
        if child.type == "name":
            return node_text(child, source)
        if child.type == "qualified_name":
            return _last_name(child, source)
    return None


def _collect_php_type_ids(node: Node, source: bytes, out: list[str]) -> None:
    """Recursively collect user-defined type identifiers from PHP type nodes."""
    if node.type == "named_type":
        name = _last_name(node, source)
        if name is None:
            return
        if name.casefold() not in _PHP_BUILTIN_TYPES:
            out.append(name)
        return
    if node.type in {
        "union_type",
        "intersection_type",
        "nullable_type",
        "optional_type",
        "disjunctive_normal_form_type",
    }:
        for child in node.children:
            _collect_php_type_ids(child, source, out)
        return


def _last_name(node: Node, source: bytes) -> str | None:
    for child in reversed(node.children):
        if child.type == "name":
            return node_text(child, source)
        nested = _last_name(child, source)
        if nested is not None:
            return nested
    return None


def _php_namespace_name(node: Node, source: bytes) -> str:
    return node_text(node, source).strip("\\").replace("\\", ".")


def _strip_phpdoc(text: str) -> str:
    s = text.strip()
    if s.startswith("/**"):
        s = s[3:]
    if s.endswith("*/"):
        s = s[:-2]
    lines = [ln.strip().lstrip("* ").strip() for ln in s.split("\n")]
    return "\n".join(ln for ln in lines if ln and not ln.startswith("@"))
