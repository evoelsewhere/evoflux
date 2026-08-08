"""Kotlin language parser."""

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
    EDGE_IMPLEMENTS,
    EDGE_INHERITS,
    NODE_CLASS,
    NODE_FUNCTION,
    NODE_INTERFACE,
    NODE_METHOD,
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
                kind = NODE_INTERFACE if _is_interface(node) else NODE_CLASS
                return Definition(kind=kind, name=name, is_class=True)
        elif ntype == "object_declaration":
            name = self._class_name(node, source)
            if name:
                return Definition(kind=NODE_CLASS, name=name, is_class=True)
        elif ntype == "function_declaration":
            name = self._func_name(node, source)
            if name:
                kind = NODE_METHOD if inside_class else NODE_FUNCTION
                return Definition(kind=kind, name=name, is_class=False)
        elif ntype == "property_declaration" and inside_class:
            name = self._property_name(node, source)
            if name:
                return Definition(kind=NODE_METHOD, name=name, is_class=False)
        return None

    def call_target(self, node: Node, source: bytes) -> str | None:
        if node.type != "call_expression":
            return None
        # Kotlin call_expression: first child is callee, then call_suffix
        for child in node.children:
            if child.type == "simple_identifier":
                return node_text(child, source)
            if child.type == "navigation_expression":
                return _nav_expr_name(child, source)
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
                    elif _looks_like_interface_kt(name):
                        edge = EDGE_IMPLEMENTS
                    else:
                        edge = EDGE_INHERITS
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
                name=dotted.rsplit(".", 1)[-1],
                module_path=dotted,
                local_name=node_text(alias, source) if alias is not None else None,
            )
        ]

    def decorators(self, node: Node, source: bytes) -> list[str]:
        out: list[str] = []
        prev = node.prev_named_sibling
        while prev is not None and prev.type == "annotation":
            name = _kt_annotation_name(prev, source)
            if name:
                out.append(name)
            prev = prev.prev_named_sibling
        # Also check for annotations as direct children (class/function modifiers)
        for child in node.children:
            if child.type == "modifiers":
                for mod in child.children:
                    if mod.type == "annotation":
                        name = _kt_annotation_name(mod, source)
                        if name:
                            out.append(name)
        return out

    def type_refs(self, node: Node, source: bytes) -> list[str]:
        if node.type != "function_declaration":
            return []
        out: list[str] = []
        # Parameter types
        params = node.child_by_field_name("parameters")
        if params is not None:
            for param in params.children:
                if param.type == "parameter":
                    type_node = param.child_by_field_name("type")
                    if type_node is not None:
                        _collect_kt_type_ids(type_node, source, out)
        # Return type
        ret = node.child_by_field_name("type")
        if ret is not None:
            _collect_kt_type_ids(ret, source, out)
        return out

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
            if child.type == "simple_identifier":
                return node_text(child, source)
        return None


def _is_interface(node: Node) -> bool:
    """Check if a class_declaration is an interface (has 'interface' keyword)."""
    for child in node.children:
        if child.type == "interface":
            return True
    return False


def _nav_expr_name(node: Node, source: bytes) -> str | None:
    """Extract the final member name from a navigation_expression."""
    for child in reversed(node.children):
        if child.type == "navigation_suffix":
            for sub in child.children:
                if sub.type == "simple_identifier":
                    return node_text(sub, source)
    return None


def _delegation_name(node: Node, source: bytes) -> str | None:
    """Extract type name from a delegation_specifier."""
    for child in node.children:
        if child.type == "user_type":
            for sub in child.children:
                if sub.type == "type_identifier":
                    return node_text(sub, source)
                if sub.type == "simple_identifier":
                    return node_text(sub, source)
        if child.type == "type_identifier":
            return node_text(child, source)
        if child.type == "simple_identifier":
            return node_text(child, source)
    return None


def _looks_like_interface_kt(name: str) -> bool:
    """Heuristic: Kotlin interfaces often start with uppercase but so do classes.

    Without type resolution we can't distinguish, so we treat all as INHERITS
    unless the name clearly follows interface naming conventions.
    """
    # Conservative: only 'I' prefix pattern (less common in Kotlin than C#)
    return False


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


def _kt_annotation_name(node: Node, source: bytes) -> str | None:
    """Extract annotation name from a Kotlin annotation node."""
    for child in node.children:
        if child.type == "user_type":
            for sub in child.children:
                if sub.type == "type_identifier":
                    return node_text(sub, source)
        if child.type == "constructor_invocation":
            for sub in child.children:
                if sub.type == "user_type":
                    for ssub in sub.children:
                        if ssub.type == "type_identifier":
                            return node_text(ssub, source)
    return None


def _collect_kt_type_ids(node: Node, source: bytes, out: list[str]) -> None:
    """Recursively collect user-defined type identifiers from Kotlin type nodes."""
    if node.type in ("type_identifier", "simple_identifier"):
        name = node_text(node, source)
        if name not in _KT_BUILTIN_TYPES:
            out.append(name)
        return
    if node.type == "user_type":
        for child in node.children:
            _collect_kt_type_ids(child, source, out)
        return
    if node.type == "nullable_type":
        for child in node.children:
            _collect_kt_type_ids(child, source, out)
        return
    if node.type == "type_argument_list":
        for child in node.children:
            _collect_kt_type_ids(child, source, out)
        return


def _preceding_comment(node: Node, source: bytes) -> str | None:
    """Extract KDoc (/** ... */) or // comments preceding a node."""
    prev = node.prev_named_sibling
    if prev is None:
        return None
    if prev.type == "multiline_comment":
        text = node_text(prev, source)
        if text.startswith("/**"):
            text = text[3:]
        elif text.startswith("/*"):
            text = text[2:]
        if text.endswith("*/"):
            text = text[:-2]
        lines = [ln.strip().lstrip("* ").strip() for ln in text.split("\n")]
        return "\n".join(ln for ln in lines if ln) or None
    return None
