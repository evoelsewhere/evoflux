"""Pascal/Delphi/Free Pascal language parser."""

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
    NODE_MODULE,
    NODE_PROPERTY,
    NODE_STRUCT,
)

if TYPE_CHECKING:
    from tree_sitter import Node


class PascalParser(TreeSitterParser):
    name: ClassVar[str] = "pascal"
    extensions: ClassVar[tuple[str, ...]] = (".pas", ".pp", ".dpr", ".lpr")
    grammar: ClassVar[str] = "pascal"
    _unit_prefix: str = ""

    def root_prefix(self, root: Node, source: bytes) -> str:
        self._unit_prefix = ""
        unit = next(
            (child for child in root.named_children if child.type == "unit"), None
        )
        if unit is not None:
            name = self._unit_name(unit, source)
            if name:
                self._unit_prefix = f"{name}."
        return ""

    def classify(
        self, node: Node, source: bytes, *, inside_class: bool
    ) -> Definition | None:
        ntype = node.type
        if ntype == "unit":
            name = self._unit_name(node, source)
            if name:
                return Definition(kind=NODE_MODULE, name=name, is_class=True, prefix="")
        elif ntype == "declClass":
            name = self._type_name(node, source)
            if name:
                return Definition(kind=NODE_CLASS, name=name, is_class=True)
        elif ntype == "declType":
            name_node = node.child_by_field_name("name") or self._first_child_type(
                node, "genericTpl"
            )
            if name_node:
                kind = _pascal_decl_kind(node)
                return Definition(
                    kind=kind,
                    name=node_text(name_node, source),
                    is_class=kind
                    in {NODE_CLASS, NODE_INTERFACE, NODE_STRUCT, NODE_ENUM},
                )
        elif ntype == "declProp":
            name = node.child_by_field_name("name")
            if name is not None:
                return Definition(
                    kind=NODE_PROPERTY,
                    name=node_text(name, source),
                    is_class=False,
                )
        elif ntype == "defProc":
            name = self._proc_name(node, source)
            if name:
                kind = NODE_METHOD if "." in name else NODE_FUNCTION
                owner = name.rsplit(".", 1)[0] if "." in name else None
                return Definition(
                    kind=kind,
                    name=name.rsplit(".", 1)[-1],
                    is_class=False,
                    prefix=f"{self._unit_prefix}{owner}." if owner else None,
                )
        elif ntype == "declProc":
            if node.parent is not None and node.parent.type == "defProc":
                return None
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
        container = (
            node.child_by_field_name("type") if node.type == "declType" else node
        )
        if container is None or container.type != "declClass":
            return []
        parents = [
            node_text(child, source)
            for index, child in enumerate(container.children)
            if container.field_name_for_child(index) == "parent"
            and child.type == "typeref"
        ]
        if parents:
            if _pascal_decl_kind(node) == NODE_INTERFACE:
                return [
                    SuperType(name=name, edge_kind=EDGE_INHERITS) for name in parents
                ]
            return [
                SuperType(
                    name=name,
                    edge_kind=EDGE_INHERITS if index == 0 else EDGE_IMPLEMENTS,
                )
                for index, name in enumerate(parents)
            ]
        out: list[SuperType] = []
        for child in container.children:
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
        out: list[str] = []
        if node.type == "declProp":
            type_node = node.child_by_field_name("type")
            if type_node is not None:
                _collect_pascal_type_refs(type_node, source, out)
            return list(dict.fromkeys(out))
        if node.type not in {"defProc", "declProc"}:
            return []
        signature = node.child_by_field_name("header") or node
        args = signature.child_by_field_name("args")
        if args is not None:
            for argument in args.named_children:
                type_node = argument.child_by_field_name("type")
                if type_node is not None:
                    _collect_pascal_type_refs(type_node, source, out)
        return_type = signature.child_by_field_name("type")
        if return_type is not None:
            _collect_pascal_type_refs(return_type, source, out)
        return list(dict.fromkeys(out))

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
        header = node.child_by_field_name("header")
        if header is not None:
            return self._proc_name(header, source)
        name = node.child_by_field_name("name")
        if name is not None:
            return node_text(name, source)
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

    def _unit_name(self, node: Node, source: bytes) -> str | None:
        module = next(
            (child for child in node.named_children if child.type == "moduleName"),
            None,
        )
        return node_text(module, source) if module is not None else None


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


def _pascal_decl_kind(node: Node) -> str:
    type_node = node.child_by_field_name("type") if node.type == "declType" else node
    if type_node is None:
        return NODE_CLASS
    if type_node.type == "declClass":
        child_types = {child.type for child in type_node.named_children}
        if "kRecord" in child_types:
            return NODE_STRUCT
        if "kInterface" in child_types:
            return NODE_INTERFACE
        return NODE_CLASS
    if any(child.type == "declEnum" for child in type_node.named_children):
        return NODE_ENUM
    return NODE_CLASS


def _collect_pascal_type_refs(node: Node, source: bytes, out: list[str]) -> None:
    if node.type == "identifier":
        name = node_text(node, source)
        if name not in _PASCAL_BUILTIN_TYPES:
            out.append(name)
        return
    for child in node.named_children:
        _collect_pascal_type_refs(child, source, out)
