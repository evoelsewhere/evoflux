"""Objective-C language parser."""

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


class ObjCParser(TreeSitterParser):
    name: ClassVar[str] = "objc"
    extensions: ClassVar[tuple[str, ...]] = (".m", ".mm")
    grammar: ClassVar[str] = "objc"

    def classify(
        self, node: Node, source: bytes, *, inside_class: bool
    ) -> Definition | None:
        ntype = node.type
        if ntype == "class_interface":
            name = self._ident(node, source)
            if name:
                return Definition(kind=NODE_CLASS, name=name, is_class=True)
        elif ntype == "class_implementation":
            name = self._ident(node, source)
            if name:
                return Definition(kind=NODE_CLASS, name=name, is_class=True)
        elif ntype == "protocol_declaration":
            name = self._ident(node, source)
            if name:
                return Definition(kind=NODE_INTERFACE, name=name, is_class=True)
        elif ntype == "category_interface":
            name = self._ident(node, source)
            if name:
                return Definition(kind=NODE_CLASS, name=name, is_class=True)
        elif ntype == "method_declaration":
            selector = self._selector_name(node, source)
            if selector:
                return Definition(kind=NODE_METHOD, name=selector, is_class=False)
        elif ntype == "implementation_definition":
            selector = self._selector_name(node, source)
            if selector:
                return Definition(kind=NODE_METHOD, name=selector, is_class=False)
        elif ntype == "function_definition":
            name = node.child_by_field_name("declarator")
            if name is not None:
                return Definition(
                    kind=NODE_FUNCTION,
                    name=_declarator_name(name, source) or "",
                    is_class=False,
                )
        return None

    def call_target(self, node: Node, source: bytes) -> str | None:
        if node.type == "message_expression":
            sel = node.child_by_field_name("selector")
            if sel is not None:
                return node_text(sel, source).replace(":", "")
            # Fallback: look for keyword_selector
            for child in node.children:
                if child.type == "keyword_selector":
                    return node_text(child, source).replace(":", "").replace(" ", "")
                if child.type == "identifier":
                    return node_text(child, source)
        elif node.type == "call_expression":
            func = node.child_by_field_name("function")
            if func is not None and func.type == "identifier":
                return node_text(func, source)
        return None

    def supertypes(self, node: Node, source: bytes) -> list[SuperType]:
        if node.type not in ("class_interface", "class_implementation"):
            return []
        out: list[SuperType] = []
        # Superclass: second identifier after ':'
        sup = node.child_by_field_name("superclass")
        if sup is not None:
            out.append(SuperType(name=node_text(sup, source), edge_kind=EDGE_INHERITS))
        else:
            # Positional: find identifier after ':'
            found_colon = False
            found_name = False
            for child in node.children:
                if child.type == ":":
                    found_colon = True
                elif found_colon and not found_name and child.type == "identifier":
                    out.append(
                        SuperType(
                            name=node_text(child, source), edge_kind=EDGE_INHERITS
                        )
                    )
                    found_name = True
                    break
        # Protocols in angle brackets
        for child in node.children:
            if child.type == "parameterized_arguments":
                for sub in child.children:
                    if sub.type == "identifier":
                        out.append(
                            SuperType(
                                name=node_text(sub, source), edge_kind=EDGE_IMPLEMENTS
                            )
                        )
                    elif sub.type == "type_name":
                        out.append(
                            SuperType(
                                name=node_text(sub, source), edge_kind=EDGE_IMPLEMENTS
                            )
                        )
        return out

    def docstring(self, node: Node, source: bytes) -> str | None:
        prev = node.prev_named_sibling
        if prev is not None and prev.type == "comment":
            text = node_text(prev, source)
            if text.startswith("/**"):
                return _strip_objc_doc(text)
        return None

    def _ident(self, node: Node, source: bytes) -> str | None:
        for child in node.children:
            if child.type == "identifier":
                return node_text(child, source)
        return None

    def _selector_name(self, node: Node, source: bytes) -> str | None:
        sel = node.child_by_field_name("selector")
        if sel is not None:
            return node_text(sel, source).replace(":", "")
        for child in node.children:
            if child.type == "keyword_selector":
                parts: list[str] = []
                for sub in child.children:
                    if sub.type == "keyword_declarator":
                        for k in sub.children:
                            if k.type == "identifier":
                                parts.append(node_text(k, source))
                                break
                return "".join(parts) if parts else None
            if child.type == "identifier":
                return node_text(child, source)
        return None


def _declarator_name(node: Node, source: bytes) -> str | None:
    if node.type == "identifier":
        return node_text(node, source)
    if node.type == "function_declarator":
        decl = node.child_by_field_name("declarator")
        if decl is not None:
            return _declarator_name(decl, source)
    return None


def _strip_objc_doc(text: str) -> str:
    s = text.strip()
    if s.startswith("/**"):
        s = s[3:]
    if s.endswith("*/"):
        s = s[:-2]
    lines = [ln.strip().lstrip("* ").strip() for ln in s.split("\n")]
    return "\n".join(ln for ln in lines if ln and not ln.startswith("@"))
