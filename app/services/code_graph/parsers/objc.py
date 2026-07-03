"""Objective-C language parser."""

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

    def import_refs(self, node: Node, source: bytes) -> list[ImportRef]:
        # #import/#include are preproc_include nodes (shared with the C/C++
        # grammar family) — they DO appear as regular nodes in the normal
        # child hierarchy (verified via the real parse tree), so base.py's
        # `_walk` visits them like any other statement.
        if node.type == "preproc_include":
            path_node = node.child_by_field_name("path")
            if path_node is None:
                return []
            if path_node.type == "system_lib_string":
                # <Foundation/Foundation.h> — angle brackets, framework-qualified.
                raw = node_text(path_node, source).strip("<>")
                name = raw.split("/", 1)[0]
                return [ImportRef(name=name, module_path=raw)]
            if path_node.type == "string_literal":
                # "MyHeader.h" — a quoted local include. These resolve within
                # the same target rather than naming an external package, but
                # we still emit a ref (using the header name as-is) so the
                # raw specifier is available; the cross-repo resolver is free
                # to treat local-looking paths differently downstream.
                raw = _string_literal_content(path_node, source)
                if not raw:
                    return []
                name = raw.rsplit("/", 1)[-1]
                return [ImportRef(name=name, module_path=raw)]
            return []
        if node.type == "module_import":
            # @import SomeModule; or @import Foo.Bar; (Clang module import) —
            # a dotted submodule path is multiple sibling identifier nodes
            # joined by "." tokens, not one dotted identifier like Swift's.
            idents = [c for c in node.children if c.type == "identifier"]
            if not idents:
                return []
            dotted = ".".join(node_text(c, source) for c in idents)
            return [ImportRef(name=node_text(idents[-1], source), module_path=dotted)]
        return []

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

    def decorators(self, node: Node, source: bytes) -> list[str]:
        out: list[str] = []
        # ObjC availability attributes and other attributes
        prev = node.prev_named_sibling
        while prev is not None:
            if prev.type == "attribute_declaration":
                _collect_objc_attr_names(prev, source, out)
            elif prev.type == "availability_attribute":
                out.append("availability")
            elif prev.type not in ("comment",):
                break
            prev = prev.prev_named_sibling
        # Also check direct children for attributes
        for child in node.children:
            if child.type in ("attribute_declaration", "availability_attribute"):
                if child.type == "availability_attribute":
                    out.append("availability")
                else:
                    _collect_objc_attr_names(child, source, out)
        return out

    def type_refs(self, node: Node, source: bytes) -> list[str]:
        if node.type not in {
            "method_declaration",
            "implementation_definition",
            "function_definition",
        }:
            return []
        out: list[str] = []
        # Return type
        ret = node.child_by_field_name("return_type")
        if ret is not None:
            for child in ret.children:
                if child.type == "type_identifier":
                    name = node_text(child, source)
                    if name not in _OBJC_BUILTIN_TYPES:
                        out.append(name)
        # Parameter types
        for child in node.children:
            if child.type == "parameter_list":
                for param in child.children:
                    if param.type == "parameter_declaration":
                        type_node = param.child_by_field_name("type")
                        if type_node is not None:
                            name = node_text(type_node, source)
                            if name not in _OBJC_BUILTIN_TYPES:
                                out.append(name)
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


def _string_literal_content(node: Node, source: bytes) -> str:
    """Extract the text content of a string_literal, stripping quotes."""
    for child in node.children:
        if child.type == "string_content":
            return node_text(child, source)
    return node_text(node, source).strip('"')


_OBJC_BUILTIN_TYPES = frozenset(
    {
        "BOOL",
        "Class",
        "CGFloat",
        "NSInteger",
        "NSString",
        "NSUInteger",
        "SEL",
        "id",
        "instancetype",
        "int",
        "float",
        "double",
        "char",
        "void",
        "long",
        "short",
        "unsigned",
        "signed",
        "size_t",
    }
)


def _collect_objc_attr_names(node: Node, source: bytes, out: list[str]) -> None:
    """Extract attribute names from an ObjC attribute_declaration node."""
    for child in node.children:
        if child.type == "identifier":
            out.append(node_text(child, source))
        elif child.type == "argument_list":
            for arg in child.children:
                if arg.type == "identifier":
                    out.append(node_text(arg, source))


def _strip_objc_doc(text: str) -> str:
    s = text.strip()
    if s.startswith("/**"):
        s = s[3:]
    if s.endswith("*/"):
        s = s[:-2]
    lines = [ln.strip().lstrip("* ").strip() for ln in s.split("\n")]
    return "\n".join(ln for ln in lines if ln and not ln.startswith("@"))
