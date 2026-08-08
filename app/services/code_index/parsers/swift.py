"""Swift language parser."""

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
    NODE_ENUM,
    NODE_FUNCTION,
    NODE_INTERFACE,
    NODE_METHOD,
    NODE_STRUCT,
)

if TYPE_CHECKING:
    from tree_sitter import Node


class SwiftParser(TreeSitterParser):
    name: ClassVar[str] = "swift"
    extensions: ClassVar[tuple[str, ...]] = (".swift",)
    grammar: ClassVar[str] = "swift"

    def classify(
        self, node: Node, source: bytes, *, inside_class: bool
    ) -> Definition | None:
        ntype = node.type
        if ntype == "protocol_declaration":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_INTERFACE, name=name, is_class=True)
        elif ntype == "class_declaration":
            # Covers: class, struct, enum, actor
            name = self._name(node, source)
            if name:
                declaration_kind = next(
                    (
                        child.type
                        for child in node.children
                        if child.type in {"class", "struct", "enum", "actor"}
                    ),
                    "class",
                )
                kind = {
                    "struct": NODE_STRUCT,
                    "enum": NODE_ENUM,
                }.get(declaration_kind, NODE_CLASS)
                return Definition(kind=kind, name=name, is_class=True)
        elif ntype == "function_declaration":
            name = self._func_name(node, source)
            if name:
                kind = NODE_METHOD if inside_class else NODE_FUNCTION
                return Definition(kind=kind, name=name, is_class=False)
        elif ntype == "init_declaration":
            return Definition(kind=NODE_METHOD, name="init", is_class=False)
        elif ntype == "deinit_declaration":
            return Definition(kind=NODE_METHOD, name="deinit", is_class=False)
        elif ntype == "subscript_declaration":
            return Definition(kind=NODE_METHOD, name="subscript", is_class=False)
        elif ntype == "property_declaration" and inside_class:
            name = self._property_name(node, source)
            if name:
                return Definition(kind=NODE_METHOD, name=name, is_class=False)
        elif ntype == "typealias_declaration":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_CLASS, name=name, is_class=False)
        return None

    def import_refs(self, node: Node, source: bytes) -> list[ImportRef]:
        if node.type != "import_declaration":
            return []
        # Children: ["import" | modifiers (e.g. "@testable")], "import",
        # [a "kind" keyword: struct/class/enum/protocol/func/var/let], identifier.
        # The identifier child carries the (possibly dotted) module path, e.g.
        # "Foundation" or "Foundation.Date" for a scoped import.
        ident = next((c for c in node.children if c.type == "identifier"), None)
        if ident is None:
            return []
        dotted = node_text(ident, source)
        # A scoped import ("import struct Foundation.Date") names one specific
        # symbol from the module — the last dotted segment is the locally-used
        # name, mirroring java.py's handling of nested imports.
        return [ImportRef(name=dotted.rsplit(".", 1)[-1], module_path=dotted)]

    def call_target(self, node: Node, source: bytes) -> str | None:
        if node.type != "call_expression":
            return None
        # Swift call_expression: first child is the callee expression
        # then call_suffix with arguments
        for child in node.children:
            if child.type == "simple_identifier":
                return node_text(child, source)
            if child.type == "navigation_expression":
                return _nav_expr_name(child, source)
            if child.type == "call_suffix":
                break
        return None

    def supertypes(self, node: Node, source: bytes) -> list[SuperType]:
        if node.type not in ("class_declaration", "protocol_declaration"):
            return []
        out: list[SuperType] = []
        is_protocol = node.type == "protocol_declaration"
        for child in node.children:
            if child.type == "inheritance_specifier":
                name = _inheritance_name(child, source)
                if name:
                    # In Swift, protocols inherit protocols; classes can conform
                    edge = EDGE_INHERITS if is_protocol else EDGE_IMPLEMENTS
                    # Heuristic: first item for a class is likely the superclass
                    if not is_protocol and not out:
                        edge = EDGE_INHERITS
                    out.append(SuperType(name=name, edge_kind=edge))
        return out

    def docstring(self, node: Node, source: bytes) -> str | None:
        return _preceding_comment(node, source)

    def decorators(self, node: Node, source: bytes) -> list[str]:
        out: list[str] = []
        for child in node.children:
            if child.type == "attribute":
                name = _swift_attr_name(child, source)
                if name:
                    out.append(name)
            elif child.type == "modifiers":
                for mod in child.children:
                    if mod.type == "attribute":
                        name = _swift_attr_name(mod, source)
                        if name:
                            out.append(name)
        # Also check preceding siblings
        prev = node.prev_named_sibling
        while prev is not None:
            if prev.type == "attribute":
                name = _swift_attr_name(prev, source)
                if name:
                    out.append(name)
            elif prev.type not in ("comment", "multiline_comment"):
                break
            prev = prev.prev_named_sibling
        return out

    def type_refs(self, node: Node, source: bytes) -> list[str]:
        if node.type not in {
            "function_declaration",
            "init_declaration",
            "deinit_declaration",
            "subscript_declaration",
        }:
            return []
        out: list[str] = []
        # Parameter types
        for child in node.children:
            if child.type == "parameter":
                type_node = child.child_by_field_name("type")
                if type_node is not None:
                    _collect_swift_type_ids(type_node, source, out)
            elif child.type == "function_value_parameters":
                for param in child.children:
                    if param.type == "parameter":
                        type_node = param.child_by_field_name("type")
                        if type_node is not None:
                            _collect_swift_type_ids(type_node, source, out)
        # Return type
        ret = node.child_by_field_name("return_type")
        if ret is not None:
            _collect_swift_type_ids(ret, source, out)
        return out

    def _name(self, node: Node, source: bytes) -> str | None:
        name_node = node.child_by_field_name("name")
        if name_node is not None:
            return node_text(name_node, source)
        return None

    def _func_name(self, node: Node, source: bytes) -> str | None:
        name_node = node.child_by_field_name("name")
        if name_node is not None:
            return node_text(name_node, source)
        # Fallback: first simple_identifier child
        for child in node.children:
            if child.type == "simple_identifier":
                return node_text(child, source)
        return None

    def _property_name(self, node: Node, source: bytes) -> str | None:
        # property_declaration has a pattern child with the name
        for child in node.children:
            if child.type == "pattern" or child.type == "simple_identifier":
                return node_text(child, source)
        return None


def _nav_expr_name(node: Node, source: bytes) -> str | None:
    """Extract the final member name from a navigation_expression (a.b.c → c)."""
    for child in reversed(node.children):
        if child.type == "navigation_suffix":
            for sub in child.children:
                if sub.type == "simple_identifier":
                    return node_text(sub, source)
    return None


def _inheritance_name(node: Node, source: bytes) -> str | None:
    """Extract the type name from an inheritance_specifier."""
    for child in node.children:
        if child.type == "user_type":
            for sub in child.children:
                if sub.type == "type_identifier":
                    return node_text(sub, source)
                if sub.type == "simple_identifier":
                    return node_text(sub, source)
        if child.type == "type_identifier":
            return node_text(child, source)
    return None


_SWIFT_BUILTIN_TYPES = frozenset(
    {
        "Bool",
        "Character",
        "Double",
        "Float",
        "Float32",
        "Float64",
        "Int",
        "Int8",
        "Int16",
        "Int32",
        "Int64",
        "String",
        "UInt",
        "UInt8",
        "UInt16",
        "UInt32",
        "UInt64",
        "Void",
        "Any",
        "Self",
    }
)


def _swift_attr_name(attr_node: Node, source: bytes) -> str | None:
    """Extract attribute name from a Swift attribute node."""
    for child in attr_node.children:
        if child.type == "type_identifier":
            return node_text(child, source)
        if child.type == "simple_identifier":
            return node_text(child, source)
    return None


def _collect_swift_type_ids(node: Node, source: bytes, out: list[str]) -> None:
    """Recursively collect user-defined type identifiers from Swift type nodes."""
    if node.type == "type_identifier":
        name = node_text(node, source)
        if name not in _SWIFT_BUILTIN_TYPES:
            out.append(name)
        return
    if node.type == "simple_identifier":
        name = node_text(node, source)
        if name not in _SWIFT_BUILTIN_TYPES and name[0:1].isupper():
            out.append(name)
        return
    if node.type in {
        "array_type",
        "dictionary_type",
        "optional_type",
        "tuple_type",
        "function_type",
        "protocol_composition_type",
        "existential_type",
    }:
        for child in node.children:
            _collect_swift_type_ids(child, source, out)
        return
    if node.type in ("user_type",):
        for child in node.children:
            _collect_swift_type_ids(child, source, out)
        return
    for child in node.children:
        _collect_swift_type_ids(child, source, out)


def _preceding_comment(node: Node, source: bytes) -> str | None:
    """Extract Swift doc comment (/// lines or /** block) preceding a node."""
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
    if prev.type != "comment":
        return None
    lines: list[str] = []
    cur: Node | None = prev
    while cur is not None and cur.type == "comment":
        text = node_text(cur, source)
        if text.startswith("///"):
            lines.append(text[3:].strip())
        else:
            break
        cur = cur.prev_named_sibling
    if not lines:
        return None
    lines.reverse()
    return "\n".join(lines)
