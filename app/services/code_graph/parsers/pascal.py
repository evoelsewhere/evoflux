"""Pascal/Delphi/Free Pascal language parser."""

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
    EDGE_INHERITS,
    NODE_CLASS,
    NODE_FUNCTION,
    NODE_METHOD,
)

if TYPE_CHECKING:
    from tree_sitter import Node


class PascalParser(TreeSitterParser):
    name: ClassVar[str] = "pascal"
    extensions: ClassVar[tuple[str, ...]] = (".pas", ".pp", ".dpr", ".lpr")
    grammar: ClassVar[str] = "pascal"

    def classify(
        self, node: Node, source: bytes, *, inside_class: bool
    ) -> Definition | None:
        ntype = node.type
        if ntype == "declClass":
            name = self._type_name(node, source)
            if name:
                return Definition(kind=NODE_CLASS, name=name, is_class=True)
        elif ntype == "declType":
            # Covers class declarations inside type section
            name_node = node.child_by_field_name("name") or self._first_child_type(
                node, "genericTpl"
            )
            if name_node:
                return Definition(
                    kind=NODE_CLASS, name=node_text(name_node, source), is_class=True
                )
        elif ntype == "defProc":
            name = self._proc_name(node, source)
            if name:
                kind = NODE_METHOD if "." in name else NODE_FUNCTION
                return Definition(kind=kind, name=name.split(".")[-1], is_class=False)
        elif ntype == "declProc":
            name = self._proc_name(node, source)
            if name:
                return Definition(kind=NODE_METHOD, name=name, is_class=False)
        return None

    def call_target(self, node: Node, source: bytes) -> str | None:
        if node.type == "exprCall":
            for child in node.children:
                if child.type == "identifier":
                    return node_text(child, source)
                if child.type == "exprDot":
                    for sub in reversed(child.children):
                        if sub.type == "identifier":
                            return node_text(sub, source)
                    break
        return None

    def import_refs(self, node: Node, source: bytes) -> list[ImportRef]:
        if node.type != "declUses":
            return []
        out: list[ImportRef] = []
        for child in node.children:
            if child.type == "moduleName":
                dotted = node_text(child, source)
                if dotted:
                    out.append(
                        ImportRef(name=dotted.rsplit(".", 1)[-1], module_path=dotted)
                    )
        return out

    def supertypes(self, node: Node, source: bytes) -> list[SuperType]:
        if node.type not in ("declClass", "declType"):
            return []
        out: list[SuperType] = []
        for child in node.children:
            if child.type == "classParent":
                for sub in child.children:
                    if sub.type == "identifier":
                        out.append(
                            SuperType(
                                name=node_text(sub, source), edge_kind=EDGE_INHERITS
                            )
                        )
        return out

    def docstring(self, node: Node, source: bytes) -> str | None:
        prev = node.prev_named_sibling
        if prev is not None and prev.type == "comment":
            text = node_text(prev, source)
            if text.startswith("{"):
                return text.strip("{}").strip()
            if text.startswith("(*"):
                return text[2:-2].strip() if text.endswith("*)") else text[2:].strip()
        return None

    def type_refs(self, node: Node, source: bytes) -> list[str]:
        if node.type not in {"defProc", "declProc"}:
            return []
        out: list[str] = []
        for child in node.children:
            if child.type == "formalParameters":
                _collect_pascal_param_types(child, source, out)
            elif child.type == "resultType":
                for sub in child.children:
                    if sub.type == "typeIdentifier":
                        name = node_text(sub, source)
                        if name not in _PASCAL_BUILTIN_TYPES:
                            out.append(name)
        return out

    def _type_name(self, node: Node, source: bytes) -> str | None:
        for child in node.children:
            if child.type == "identifier":
                return node_text(child, source)
            if child.type == "genericTpl":
                for sub in child.children:
                    if sub.type == "identifier":
                        return node_text(sub, source)
        return None

    def _proc_name(self, node: Node, source: bytes) -> str | None:
        for child in node.children:
            if child.type == "moduleName":
                return node_text(child, source)
            if child.type == "identifier":
                return node_text(child, source)
        return None

    def _first_child_type(self, node: Node, ntype: str) -> Node | None:
        for child in node.children:
            if child.type == ntype:
                return child
        return None


_PASCAL_BUILTIN_TYPES = frozenset(
    {
        "Boolean",
        "Byte",
        "Cardinal",
        "Char",
        "Double",
        "Extended",
        "Integer",
        "Int64",
        "LongInt",
        "LongWord",
        "Pointer",
        "Real",
        "ShortInt",
        "ShortString",
        "Single",
        "SmallInt",
        "String",
        "WideChar",
        "WideString",
        "Word",
    }
)


def _collect_pascal_param_types(node: Node, source: bytes, out: list[str]) -> None:
    """Collect type identifiers from Pascal formal parameter sections."""
    for child in node.children:
        if child.type == "formalParameter":
            for sub in child.children:
                if sub.type == "typeIdentifier":
                    name = node_text(sub, source)
                    if name not in _PASCAL_BUILTIN_TYPES:
                        out.append(name)
                elif sub.type == "type":
                    for tsub in sub.children:
                        if tsub.type == "typeIdentifier":
                            name = node_text(tsub, source)
                            if name not in _PASCAL_BUILTIN_TYPES:
                                out.append(name)
