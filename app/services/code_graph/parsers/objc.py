"""Objective-C language parser."""

from __future__ import annotations

from dataclasses import replace
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
    NODE_PROPERTY,
)

if TYPE_CHECKING:
    from tree_sitter import Node

    from app.services.code_graph.types import ParseResult


class ObjCParser(TreeSitterParser):
    name: ClassVar[str] = "objc"
    extensions: ClassVar[tuple[str, ...]] = (".m", ".mm")
    grammar: ClassVar[str] = "objc"

    def parse(self, *, file_path: str, source: bytes) -> ParseResult:
        result = super().parse(file_path=file_path, source=source)
        _coalesce_objc_classes(result)
        return result

    def classify(
        self, node: Node, source: bytes, *, inside_class: bool
    ) -> Definition | None:
        ntype = node.type
        if ntype == "class_interface":
            name = self._ident(node, source)
            if name:
                category = node.child_by_field_name("category")
                if category is not None:
                    name = f"{name}+{node_text(category, source)}"
                return Definition(kind=NODE_CLASS, name=name, is_class=True)
        elif ntype == "class_implementation":
            name = self._ident(node, source)
            if name:
                category = node.child_by_field_name("category")
                if category is not None:
                    name = f"{name}+{node_text(category, source)}"
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
        elif ntype == "property_declaration":
            name = _property_name(node, source)
            if name:
                return Definition(kind=NODE_PROPERTY, name=name, is_class=False)
        elif ntype == "function_definition":
            name = node.child_by_field_name("declarator")
            if name is not None:
                return Definition(
                    kind=NODE_FUNCTION,
                    name=_declarator_name(name, source) or "",
                    is_class=False,
                )
        return None

    def synthetic_definitions(
        self, node: Node, source: bytes, *, inside_class: bool
    ) -> list[Definition]:
        if node.type != "property_declaration" or not inside_class:
            return []
        name = _property_name(node, source)
        if not name:
            return []
        getter, setter = _property_accessors(node, name, source)
        definitions = [Definition(kind=NODE_METHOD, name=getter, is_class=False)]
        if setter is not None:
            definitions.append(
                Definition(kind=NODE_METHOD, name=setter, is_class=False)
            )
        return definitions

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
            identifiers = [
                child for child in node.children if child.type == "identifier"
            ]
            if identifiers:
                return node_text(identifiers[-1], source)
        elif node.type == "call_expression":
            func = node.child_by_field_name("function")
            if func is not None and func.type == "identifier":
                return node_text(func, source)
        return None

    def supertypes(self, node: Node, source: bytes) -> list[SuperType]:
        if node.type == "protocol_declaration":
            out: list[SuperType] = []
            for child in node.children:
                if child.type != "protocol_reference_list":
                    continue
                out.extend(
                    SuperType(
                        name=node_text(protocol, source), edge_kind=EDGE_INHERITS
                    )
                    for protocol in child.named_children
                    if protocol.type == "identifier"
                )
            return out
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
        if node.type == "property_declaration":
            out: list[str] = []
            _collect_objc_type_ids(node, source, out)
            return out
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
    declarator = node.child_by_field_name("declarator")
    if declarator is not None:
        return _declarator_name(declarator, source)
    for child in reversed(node.named_children):
        name = _declarator_name(child, source)
        if name:
            return name
    return None


def _property_name(node: Node, source: bytes) -> str | None:
    declaration = next(
        (child for child in node.children if child.type == "struct_declaration"), None
    )
    if declaration is None:
        return None
    declarator = next(
        (
            child
            for child in reversed(declaration.named_children)
            if child.type == "struct_declarator"
        ),
        None,
    )
    return _declarator_name(declarator, source) if declarator is not None else None


def _property_accessors(
    node: Node, name: str, source: bytes
) -> tuple[str, str | None]:
    getter = name
    setter: str | None = f"set{name[:1].upper()}{name[1:]}"
    for child in node.children:
        if child.type != "property_attributes_declaration":
            continue
        for attribute in child.named_children:
            if attribute.type != "property_attribute":
                continue
            text = "".join(node_text(attribute, source).split())
            if text == "readonly":
                setter = None
            elif text.startswith("getter="):
                getter = text.removeprefix("getter=").rstrip(":")
            elif text.startswith("setter="):
                setter = text.removeprefix("setter=").rstrip(":")
    return getter, setter


def _collect_objc_type_ids(node: Node, source: bytes, out: list[str]) -> None:
    if node.type == "type_identifier":
        name = node_text(node, source)
        if name not in _OBJC_BUILTIN_TYPES:
            out.append(name)
        return
    for child in node.named_children:
        _collect_objc_type_ids(child, source, out)


def _coalesce_objc_classes(result: ParseResult) -> None:
    canonical: dict[str, str] = {}
    replacements: dict[str, str] = {}
    nodes = []
    for node in result.nodes:
        if node.kind != NODE_CLASS:
            nodes.append(node)
            continue
        existing = canonical.get(node.qualified_name)
        if existing is None:
            canonical[node.qualified_name] = node.local_id
            nodes.append(node)
        else:
            replacements[node.local_id] = existing
    if not replacements:
        return

    result.nodes[:] = nodes
    edges = []
    seen = set()
    for edge in result.edges:
        rewritten = replace(
            edge,
            src_local_id=replacements.get(edge.src_local_id, edge.src_local_id),
            dst_local_id=replacements.get(edge.dst_local_id, edge.dst_local_id),
        )
        if rewritten not in seen:
            edges.append(rewritten)
            seen.add(rewritten)
    result.edges[:] = edges


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
