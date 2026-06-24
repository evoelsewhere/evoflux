"""JavaScript / TypeScript / TSX parsers.

The three grammars share node shapes, so a common base handles extraction and
the subclasses only differ in ``grammar`` and ``extensions``.
"""

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

_FUNCTION_VALUE_TYPES = {"arrow_function", "function", "function_expression"}


class EcmaScriptParser(TreeSitterParser):
    """Shared JS/TS extraction logic."""

    def classify(
        self, node: Node, source: bytes, *, inside_class: bool
    ) -> Definition | None:
        ntype = node.type
        if ntype in {"class_declaration", "abstract_class_declaration"}:
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_CLASS, name=name, is_class=True)
        elif ntype == "interface_declaration":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_INTERFACE, name=name, is_class=False)
        elif ntype in {
            "function_declaration",
            "generator_function_declaration",
            "function_signature",
        }:
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_FUNCTION, name=name, is_class=False)
        elif ntype == "method_definition":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_METHOD, name=name, is_class=False)
        elif ntype == "variable_declarator":
            value = node.child_by_field_name("value")
            if value is not None and value.type in _FUNCTION_VALUE_TYPES:
                name_node = node.child_by_field_name("name")
                if name_node is not None and name_node.type == "identifier":
                    return Definition(
                        kind=NODE_FUNCTION,
                        name=node_text(name_node, source),
                        is_class=False,
                    )
        return None

    def call_target(self, node: Node, source: bytes) -> str | None:
        if node.type == "call_expression":
            func = node.child_by_field_name("function")
            return self._callee_name(func, source) if func is not None else None
        if node.type == "new_expression":
            cons = node.child_by_field_name("constructor")
            return self._callee_name(cons, source) if cons is not None else None
        return None

    def supertypes(self, node: Node, source: bytes) -> list[SuperType]:
        out: list[SuperType] = []
        for child in node.children:
            if child.type == "class_heritage":
                out.extend(self._heritage(child, source))
            elif child.type == "extends_type_clause":
                # interface ... extends A, B
                for ident in child.children:
                    if ident.type in {"type_identifier", "identifier"}:
                        out.append(
                            SuperType(
                                name=node_text(ident, source), edge_kind=EDGE_INHERITS
                            )
                        )
        return out

    def _heritage(self, heritage: Node, source: bytes) -> list[SuperType]:
        out: list[SuperType] = []
        for clause in heritage.children:
            if clause.type == "extends_clause":
                for ident in clause.children:
                    name = self._type_name(ident, source)
                    if name:
                        out.append(SuperType(name=name, edge_kind=EDGE_INHERITS))
            elif clause.type == "implements_clause":
                for ident in clause.children:
                    name = self._type_name(ident, source)
                    if name:
                        out.append(SuperType(name=name, edge_kind=EDGE_IMPLEMENTS))
        return out

    def _type_name(self, node: Node, source: bytes) -> str | None:
        if node.type in {"identifier", "type_identifier"}:
            return node_text(node, source)
        if node.type == "member_expression":
            prop = node.child_by_field_name("property")
            return node_text(prop, source) if prop is not None else None
        return None

    def _callee_name(self, func: Node, source: bytes) -> str | None:
        if func.type == "identifier":
            return node_text(func, source)
        if func.type == "member_expression":
            prop = func.child_by_field_name("property")
            return node_text(prop, source) if prop is not None else None
        return None

    def _name(self, node: Node, source: bytes) -> str | None:
        name = node.child_by_field_name("name")
        return node_text(name, source) if name is not None else None


class JavaScriptParser(EcmaScriptParser):
    name: ClassVar[str] = "javascript"
    extensions: ClassVar[tuple[str, ...]] = (".js", ".jsx", ".mjs", ".cjs")
    grammar: ClassVar[str] = "javascript"


class TypeScriptParser(EcmaScriptParser):
    name: ClassVar[str] = "typescript"
    extensions: ClassVar[tuple[str, ...]] = (".ts", ".mts", ".cts")
    grammar: ClassVar[str] = "typescript"


class TsxParser(EcmaScriptParser):
    name: ClassVar[str] = "tsx"
    extensions: ClassVar[tuple[str, ...]] = (".tsx",)
    grammar: ClassVar[str] = "tsx"
