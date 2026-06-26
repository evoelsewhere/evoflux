"""C# language parser."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from app.services.code_graph.parsers.base import (
    Definition,
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


class CSharpParser(TreeSitterParser):
    name: ClassVar[str] = "csharp"
    extensions: ClassVar[tuple[str, ...]] = (".cs",)
    grammar: ClassVar[str] = "csharp"

    def classify(
        self, node: Node, source: bytes, *, inside_class: bool
    ) -> Definition | None:
        ntype = node.type
        if ntype == "class_declaration":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_CLASS, name=name, is_class=True)
        elif ntype == "interface_declaration":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_INTERFACE, name=name, is_class=True)
        elif ntype == "struct_declaration":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_CLASS, name=name, is_class=True)
        elif ntype == "enum_declaration":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_CLASS, name=name, is_class=True)
        elif ntype == "record_declaration":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_CLASS, name=name, is_class=True)
        elif ntype == "method_declaration":
            name = self._name(node, source)
            if name:
                kind = NODE_METHOD if inside_class else NODE_FUNCTION
                return Definition(kind=kind, name=name, is_class=False)
        elif ntype == "constructor_declaration":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_METHOD, name=name, is_class=False)
        elif ntype == "property_declaration":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_METHOD, name=name, is_class=False)
        elif ntype == "local_function_statement":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_FUNCTION, name=name, is_class=False)
        elif ntype == "delegate_declaration":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_FUNCTION, name=name, is_class=False)
        return None

    def call_target(self, node: Node, source: bytes) -> str | None:
        if node.type == "invocation_expression":
            func = node.child_by_field_name("function")
            if func is None:
                return None
            if func.type == "identifier":
                return node_text(func, source)
            if func.type == "member_access_expression":
                name_node = func.child_by_field_name("name")
                if name_node is not None:
                    return node_text(name_node, source)
        elif node.type == "object_creation_expression":
            type_node = node.child_by_field_name("type")
            if type_node is not None:
                return _simple_type_name(type_node, source)
        return None

    def supertypes(self, node: Node, source: bytes) -> list[SuperType]:
        if node.type not in (
            "class_declaration",
            "interface_declaration",
            "struct_declaration",
            "record_declaration",
        ):
            return []
        out: list[SuperType] = []
        for child in node.children:
            if child.type == "base_list":
                is_interface_decl = node.type == "interface_declaration"
                for sub in child.children:
                    name = _simple_type_name(sub, source)
                    if name:
                        # In C#, the first item in base_list for a class is the
                        # base class (if it starts uppercase and isn't prefixed I).
                        # Heuristic: names starting with I followed by uppercase
                        # are likely interfaces.
                        if is_interface_decl:
                            edge = EDGE_INHERITS
                        elif _looks_like_interface(name):
                            edge = EDGE_IMPLEMENTS
                        else:
                            edge = EDGE_INHERITS
                        out.append(SuperType(name=name, edge_kind=edge))
        return out

    def docstring(self, node: Node, source: bytes) -> str | None:
        # C# uses XML doc comments (///) preceding declarations.
        prev = node.prev_named_sibling
        if prev is None:
            return None
        lines: list[str] = []
        cur = prev
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
        # Strip XML tags for a cleaner summary.
        cleaned: list[str] = []
        for line in lines:
            stripped = _strip_xml_tags(line)
            if stripped:
                cleaned.append(stripped)
        return "\n".join(cleaned) if cleaned else None

    def _name(self, node: Node, source: bytes) -> str | None:
        name_node = node.child_by_field_name("name")
        return node_text(name_node, source) if name_node is not None else None


def _simple_type_name(node: Node, source: bytes) -> str | None:
    """Extract a simple type name from a C# type node."""
    if node.type == "identifier":
        return node_text(node, source)
    if node.type == "generic_name":
        # generic_name → identifier + type_argument_list
        for child in node.children:
            if child.type == "identifier":
                return node_text(child, source)
        return None
    if node.type == "qualified_name":
        # Namespace.Type → Type
        right = node.child_by_field_name("right")
        return node_text(right, source) if right is not None else None
    return None


def _looks_like_interface(name: str) -> bool:
    """Heuristic: C# interfaces conventionally start with 'I' + uppercase."""
    return len(name) >= 2 and name[0] == "I" and name[1].isupper()


def _strip_xml_tags(text: str) -> str:
    """Remove XML tags from a doc comment line."""
    import re

    return re.sub(r"<[^>]+>", "", text).strip()
