"""Swift language parser."""

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
    EDGE_IMPLEMENTS,
    EDGE_INHERITS,
    NODE_CLASS,
    NODE_FUNCTION,
    NODE_INTERFACE,
    NODE_METHOD,
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
                return Definition(kind=NODE_CLASS, name=name, is_class=True)
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
