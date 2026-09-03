"""Kotlin language parser."""

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
    NODE_PROPERTY,
    NODE_VARIABLE,
)

if TYPE_CHECKING:
    from tree_sitter import Node


class KotlinParser(TreeSitterParser):
    name: ClassVar[str] = "kotlin"
    extensions: ClassVar[tuple[str, ...]] = (".kt", ".kts")
    grammar: ClassVar[str] = "kotlin"

    def root_prefix(self, root: Node, source: bytes) -> str:
        for child in root.children:
            if child.type != "package_header":
                continue
            package = next(
                (sub for sub in child.children if sub.type == "identifier"), None
            )
            if package is not None:
                return f"{node_text(package, source)}."
            break
        return ""

    def classify(
        self, node: Node, source: bytes, *, inside_class: bool
    ) -> Definition | None:
        ntype = node.type
        if ntype == "class_declaration":
            name = self._class_name(node, source)
            if name:
                if _has_direct_child(node, "enum"):
                    kind = NODE_ENUM
                else:
                    kind = NODE_INTERFACE if _is_interface(node) else NODE_CLASS
                return Definition(kind=kind, name=name, is_class=True)
        elif _has_direct_child(node, "object_literal"):
            name = next(
                (
                    node_text(child, source)
                    for child in node.children
                    if child.type == "simple_identifier"
                ),
                None,
            )
            if name:
                return Definition(kind=NODE_CLASS, name=name, is_class=True)
        elif ntype == "function_declaration":
            name = self._func_name(node, source)
            if name:
                kind = NODE_METHOD if inside_class else NODE_FUNCTION
                return Definition(kind=kind, name=name)
        elif ntype == "property_declaration":
            name = self._property_name(node, source)
            if name:
                kind = NODE_FIELD if inside_class else NODE_VARIABLE
                return Definition(kind=kind, name=name)
        elif ntype == "class_parameter" and _has_direct_child(
            node, "binding_pattern_kind"
        ):
            name = self._func_name(node, source)
            if name:
                return Definition(kind=NODE_FIELD, name=name)
        elif ntype == "enum_entry":
            name = self._func_name(node, source)
            if name:
                return Definition(kind=NODE_PROPERTY, name=name)
        elif ntype == "type_alias":
            name = self._class_name(node, source)
            if name:
                return Definition(kind=NODE_CLASS, name=name)
        return None

    def call_target(self, node: Node, source: bytes) -> str | None:
        if node.type != "call_expression":
            return None
        # Kotlin call_expression: first child is callee, then call_suffix
        for child in node.children:
            if child.type == "simple_identifier":
                return node_text(child, source)
            if child.type == "navigation_expression":
                return _kt_expression_path(child, source)
            if child.type == "call_suffix":
                break
        return None

    def supertypes(self, node: Node, source: bytes) -> list[SuperType]:
        if node.type != "class_declaration":
            return []
        out: list[SuperType] = []
        is_interface = _is_interface(node)
        for child in node.children:
            if child.type == "delegation_specifier":
                name = _delegation_name(child, source)
                if name:
                    if is_interface:
                        edge = EDGE_INHERITS
                    elif _contains_node_type(child, "constructor_invocation"):
                        edge = EDGE_INHERITS
                    else:
                        edge = EDGE_IMPLEMENTS
                    out.append(SuperType(name=name, edge_kind=edge))
        return out

    def docstring(self, node: Node, source: bytes) -> str | None:
        return _preceding_comment(node, source)

    def import_refs(self, node: Node, source: bytes) -> list[ImportRef]:
        if node.type != "import_header":
            return []
        # Children: "import", identifier (dotted path), then optionally
        # either an "import_alias" (aliased import) or a "wildcard_import".
        # For an aliased import the symbol actually defined at the target is
        # still the last dotted segment — the alias only renames the local
        # binding — so we record that original name, matching how
        # python.py/rust.py treat "import X as Y".
        path_node = next((c for c in node.children if c.type == "identifier"), None)
        if path_node is None:
            return []
        dotted = node_text(path_node, source)
        is_wildcard = any(c.type == "wildcard_import" for c in node.children)
        if is_wildcard:
            return [ImportRef(name="*", module_path=f"{dotted}.*")]
        alias_container = next(
            (child for child in node.children if child.type == "import_alias"), None
        )
        alias = (
            next(
                (
                    child
                    for child in alias_container.children
                    if child.type == "type_identifier"
                ),
                None,
            )
            if alias_container is not None
            else None
        )
        return [
            ImportRef(
                name=dotted.rpartition(".")[2] or dotted,
                module_path=dotted,
                local_name=node_text(alias, source) if alias is not None else None,
            )
        ]

    def decorators(self, node: Node, source: bytes) -> list[str]:
        out: list[str] = []
        for child in node.children:
            if child.type == "modifiers":
                for mod in child.children:
                    if mod.type == "annotation":
                        name = _kt_annotation_name(mod, source)
                        if name:
                            out.append(name)
        return out

    def type_refs(self, node: Node, source: bytes) -> list[str]:
        out: list[str] = []
        if node.type == "function_declaration":
            for child in node.children:
                if child.type == "function_value_parameters":
                    for parameter in child.children:
                        if parameter.type == "parameter":
                            type_node = _kt_declared_type(parameter)
                            if type_node is not None:
                                _collect_kt_type_ids(type_node, source, out)
                elif child.type in _KT_TYPE_NODE_TYPES:
                    _collect_kt_type_ids(child, source, out)
        elif node.type == "class_parameter":
            type_node = _kt_declared_type(node)
            if type_node is not None:
                _collect_kt_type_ids(type_node, source, out)
        elif node.type == "property_declaration":
            declaration = next(
                (
                    child
                    for child in node.children
                    if child.type == "variable_declaration"
                ),
                None,
            )
            if declaration is not None:
                type_node = _kt_declared_type(declaration)
                if type_node is not None:
                    _collect_kt_type_ids(type_node, source, out)
        elif node.type == "type_alias":
            for child in node.children:
                if (
                    child.type in _KT_TYPE_NODE_TYPES
                    and child.type != "type_identifier"
                ):
                    _collect_kt_type_ids(child, source, out)
        type_parameters = _kt_enclosing_type_parameters(node, source)
        return [name for name in dict.fromkeys(out) if name not in type_parameters]

    def _class_name(self, node: Node, source: bytes) -> str | None:
        for child in node.children:
            if child.type == "type_identifier":
                return node_text(child, source)
        return None

    def _func_name(self, node: Node, source: bytes) -> str | None:
        for child in node.children:
            if child.type == "simple_identifier":
                return node_text(child, source)
        return None

    def _property_name(self, node: Node, source: bytes) -> str | None:
        for child in node.children:
            if child.type == "variable_declaration":
                for sub in child.children:
                    if sub.type == "simple_identifier":
                        return node_text(sub, source)
        return None


def _is_interface(node: Node) -> bool:
    """Check if a class_declaration is an interface (has 'interface' keyword)."""
    for child in node.children:
        if child.type == "interface":
            return True
    return False


def _has_direct_child(node: Node, node_type: str) -> bool:
    return any(child.type == node_type for child in node.children)


def _contains_node_type(node: Node, node_type: str) -> bool:
    if node.type == node_type:
        return True
    return any(_contains_node_type(child, node_type) for child in node.children)


def _kt_expression_path(node: Node, source: bytes) -> str | None:
    if node.type == "simple_identifier":
        return node_text(node, source)
    if node.type in {"this_expression", "super_expression"}:
        return "this"
    if node.type != "navigation_expression":
        return None
    receiver = node.named_children[0] if node.named_children else None
    suffix = next(
        (
            child
            for child in reversed(node.children)
            if child.type == "navigation_suffix"
        ),
        None,
    )
    receiver_path = (
        _kt_expression_path(receiver, source) if receiver is not None else None
    )
    name = (
        next(
            (child for child in suffix.children if child.type == "simple_identifier"),
            None,
        )
        if suffix is not None
        else None
    )
    if name is None:
        return receiver_path
    local_name = node_text(name, source)
    return f"{receiver_path}.{local_name}" if receiver_path else local_name


def _delegation_name(node: Node, source: bytes) -> str | None:
    """Extract type name from a delegation_specifier."""
    if node.type == "type_identifier":
        return node_text(node, source)
    for child in node.children:
        name = _delegation_name(child, source)
        if name:
            return name
    return None


_KT_BUILTIN_TYPES = frozenset(
    {
        "Any",
        "Boolean",
        "Byte",
        "Char",
        "Double",
        "Float",
        "Int",
        "Long",
        "Nothing",
        "Short",
        "String",
        "Unit",
    }
)

_KT_TYPE_NODE_TYPES = frozenset(
    {
        "function_type",
        "nullable_type",
        "parenthesized_type",
        "type_identifier",
        "user_type",
    }
)


def _kt_declared_type(node: Node) -> Node | None:
    return next(
        (child for child in node.children if child.type in _KT_TYPE_NODE_TYPES), None
    )


def _kt_enclosing_type_parameters(node: Node, source: bytes) -> set[str]:
    out: set[str] = set()
    current: Node | None = node
    while current is not None:
        for child in current.children:
            if child.type != "type_parameters":
                continue
            for parameter in child.children:
                if parameter.type != "type_parameter":
                    continue
                out.update(
                    node_text(nested, source)
                    for nested in parameter.children
                    if nested.type == "type_identifier"
                )
        current = current.parent
    return out


def _kt_annotation_name(node: Node, source: bytes) -> str | None:
    """Extract annotation name from a Kotlin annotation node."""
    user_type = next(
        (descendant for descendant in _kt_walk(node) if descendant.type == "user_type"),
        None,
    )
    if user_type is None:
        return None
    names = [child for child in user_type.children if child.type == "type_identifier"]
    return node_text(names[-1], source) if names else None


def _kt_walk(node: Node) -> Iterator[Node]:
    for child in node.children:
        yield child
        yield from _kt_walk(child)


def _collect_kt_type_ids(node: Node, source: bytes, out: list[str]) -> None:
    """Recursively collect user-defined type identifiers from Kotlin type nodes."""
    if node.type == "type_identifier":
        name = node_text(node, source)
        if name not in _KT_BUILTIN_TYPES:
            out.append(name)
        return
    if node.type == "user_type":
        direct_names = [
            child for child in node.children if child.type == "type_identifier"
        ]
        if direct_names:
            _collect_kt_type_ids(direct_names[-1], source, out)
        for child in node.children:
            if child.type != "type_identifier":
                _collect_kt_type_ids(child, source, out)
        return
    for child in node.children:
        _collect_kt_type_ids(child, source, out)


def _preceding_comment(node: Node, source: bytes) -> str | None:
    """Extract KDoc (/** ... */) or // comments preceding a node."""
    prev = node.prev_named_sibling
    if prev is None:
        return None
    if prev.type == "multiline_comment":
        text = node_text(prev, source)
        if text.startswith("/*"):
            text = text[2:]
        if text.endswith("*/"):
            text = text[:-2]
        lines = [ln.strip().lstrip("* ").strip() for ln in text.split("\n")]
        return "\n".join(ln for ln in lines if ln) or None
    return None
