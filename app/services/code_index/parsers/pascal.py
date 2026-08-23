"""Pascal/Delphi/Free Pascal language parser."""

from __future__ import annotations

import re
from dataclasses import replace
from typing import TYPE_CHECKING, ClassVar

from app.services.code_index.parsers.base import (
    Definition,
    ImportRef,
    SuperType,
    TreeSitterParser,
    node_text,
)
from app.services.code_index.graph_types import (
    EDGE_CONTAINS,
    EDGE_IMPLEMENTS,
    EDGE_INHERITS,
    EDGE_REFERENCES,
    NODE_CLASS,
    NODE_ENUM,
    NODE_FIELD,
    NODE_FUNCTION,
    NODE_INTERFACE,
    NODE_METHOD,
    NODE_MODULE,
    NODE_PROPERTY,
    NODE_STRUCT,
    NODE_VARIABLE,
)

if TYPE_CHECKING:
    from tree_sitter import Node

    from app.services.code_index.graph_types import ExtractedNode, ParseResult


class PascalParser(TreeSitterParser):
    name: ClassVar[str] = "pascal"
    extensions: ClassVar[tuple[str, ...]] = (".pas", ".pp", ".dpr", ".lpr")
    grammar: ClassVar[str] = "pascal"

    def identifier_reference_targets(self, node: Node, source: bytes) -> list[str]:
        # Pascal grammar identifiers cover declaration names, unit path
        # segments, selector members, property accessors, and runtime reads.
        # Precise declaration/type/call/import hooks below avoid emitting those
        # syntax fragments as unrelated references.
        return []

    def parse(self, *, file_path: str, source: bytes) -> ParseResult:
        result = super().parse(file_path=file_path, source=source)
        _coalesce_pascal_callables(result)
        return result

    def classify(
        self, node: Node, source: bytes, *, inside_class: bool
    ) -> Definition | None:
        ntype = node.type
        if ntype in {"unit", "program", "library"}:
            name = self._unit_name(node, source)
            if name:
                return Definition(kind=NODE_MODULE, name=name)
        elif ntype == "declType":
            name_node = node.child_by_field_name("name")
            if name_node:
                kind = _pascal_decl_kind(node)
                return Definition(
                    kind=kind,
                    name=node_text(name_node, source),
                )
        elif ntype == "declEnumValue":
            name = node.child_by_field_name("name")
            if name is not None:
                return Definition(kind=NODE_PROPERTY, name=node_text(name, source))
        elif ntype == "declField":
            name = node.child_by_field_name("name")
            if name is not None:
                return Definition(kind=NODE_FIELD, name=node_text(name, source))
        elif ntype in {"declVar", "declConst"}:
            name = node.child_by_field_name("name")
            if name is not None:
                return Definition(kind=NODE_VARIABLE, name=node_text(name, source))
        elif ntype == "declProp":
            name = node.child_by_field_name("name")
            if name is not None:
                return Definition(
                    kind=NODE_PROPERTY,
                    name=node_text(name, source),
                )
        elif ntype == "defProc":
            name = self._proc_name(node, source)
            if name:
                owner, separator, leaf = name.rpartition(".")
                kind = NODE_METHOD if separator else NODE_FUNCTION
                unit = _enclosing_unit_name(node, source) if owner else None
                return Definition(
                    kind=kind,
                    name=leaf if separator else name,
                    prefix=(
                        f"{unit + '.' if unit else ''}{owner}." if owner else None
                    ),
                )
        elif ntype == "declProc":
            if node.parent is not None and node.parent.type == "defProc":
                return None
            name = self._proc_name(node, source)
            if name:
                return Definition(
                    kind=(
                        NODE_METHOD
                        if _inside_pascal_class(node)
                        else NODE_FUNCTION
                    ),
                    name=name,
                )
        return None

    def call_target(self, node: Node, source: bytes) -> str | None:
        if node.type != "exprCall":
            return None
        entity = node.child_by_field_name("entity")
        return _pascal_static_name(entity, source) if entity is not None else None

    def import_refs(self, node: Node, source: bytes) -> list[ImportRef]:
        if node.type != "declUses":
            return []
        body = node_text(node, source).strip()
        _, body = body.split(maxsplit=1)
        identifier = r"[^\W\d]\w*"
        out: list[ImportRef] = []
        for match in re.finditer(
            rf"(?:^|,)\s*({identifier}(?:\.{identifier})*)"
            r"(?:\s+(?i:in)\s+['\"]([^'\"]+)['\"])?",
            body,
        ):
            dotted, explicit_path = match.groups()
            out.append(
                ImportRef(
                    name=dotted.rsplit(".")[-1],
                    module_path=explicit_path or dotted,
                )
            )
        return out

    def supertypes(self, node: Node, source: bytes) -> list[SuperType]:
        if node.type != "declType":
            return []
        container = next(
            child
            for index, child in enumerate(node.children)
            if node.field_name_for_child(index) == "type"
        )
        if container.type not in {"declClass", "declIntf"}:
            return []
        parents = [
            node_text(child, source)
            for index, child in enumerate(container.children)
            if container.field_name_for_child(index) == "parent"
            and child.type == "typeref"
        ]
        if parents:
            if container.type == "declIntf":
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
        return []

    def docstring(self, node: Node, source: bytes) -> str | None:
        prev = node.prev_named_sibling
        if prev is not None and prev.type == "comment":
            text = node_text(prev, source)
            if text.startswith("///"):
                lines: list[str] = []
                current: Node | None = prev
                while current is not None and current.type == "comment":
                    line = node_text(current, source)
                    if not line.startswith("///"):
                        break
                    lines.append(line[3:].strip())
                    current = current.prev_named_sibling
                lines.reverse()
                return "\n".join(line for line in lines if line) or None
            if text.startswith("{"):
                return text.strip("{}").strip()
            if text.startswith("(*"):
                return text[2:-2].strip() if text.endswith("*)") else text[2:].strip()
        return None

    def type_refs(self, node: Node, source: bytes) -> list[str]:
        out: list[str] = []
        if node.type in {"declProp", "declField", "declVar", "declConst"}:
            type_node = node.child_by_field_name("type")
            if type_node is not None:
                _collect_pascal_type_refs(type_node, source, out)
            return list(dict.fromkeys(out))
        if node.type == "declType" and _pascal_decl_kind(node) == NODE_CLASS:
            type_node = node.child_by_field_name("type")
            if type_node is not None and type_node.type not in {
                "declClass",
                "declIntf",
            }:
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

    def _unit_name(self, node: Node, source: bytes) -> str | None:
        module = next(
            child for child in node.named_children if child.type == "moduleName"
        )
        return node_text(module, source)


def _pascal_static_name(node: Node, source: bytes) -> str | None:
    if node.type == "identifier":
        return node_text(node, source)
    if node.type != "exprDot":
        return None
    lhs = next(
        child
        for index, child in enumerate(node.children)
        if node.field_name_for_child(index) == "lhs"
    )
    rhs = next(
        child
        for index, child in enumerate(node.children)
        if node.field_name_for_child(index) == "rhs"
    )
    owner = _pascal_static_name(lhs, source)
    member = _pascal_static_name(rhs, source)
    if member is None:
        return None
    return f"{owner}.{member}" if owner else member


def _inside_pascal_class(node: Node) -> bool:
    ancestor = node.parent
    while ancestor is not None:
        if ancestor.type in {"declClass", "declIntf"}:
            return True
        ancestor = ancestor.parent
    return False


def _enclosing_unit_name(node: Node, source: bytes) -> str | None:
    ancestor = node.parent
    while ancestor is not None:
        if ancestor.type in {"unit", "program", "library"}:
            module = next(
                child
                for child in ancestor.named_children
                if child.type == "moduleName"
            )
            return node_text(module, source)
        ancestor = ancestor.parent
    return None


def _pascal_callable_key(node: ExtractedNode) -> tuple[str, str, str]:
    signature: str = node.signature  # ty: ignore[invalid-assignment]
    tail = signature.casefold().rpartition(node.name.casefold())[2].partition(";")[0]
    normalized_tail = re.sub(r"\s+", "", tail)
    return node.kind, node.qualified_name.casefold(), normalized_tail


def _coalesce_pascal_callables(result: ParseResult) -> None:
    groups: dict[tuple[str, str, str], list[ExtractedNode]] = {}
    for node in result.nodes:
        if node.kind in {NODE_FUNCTION, NODE_METHOD}:
            groups.setdefault(_pascal_callable_key(node), []).append(node)

    replacements: dict[str, str] = {}
    merged_nodes: dict[str, ExtractedNode] = {}
    for duplicates in groups.values():
        if len(duplicates) != 2:
            continue
        declaration, implementation = duplicates
        replacements[implementation.local_id] = declaration.local_id
        merged_nodes[declaration.local_id] = replace(
            implementation,
            local_id=declaration.local_id,
            name=declaration.name,
            qualified_name=declaration.qualified_name,
            docstring=declaration.docstring or implementation.docstring,
        )
    if not replacements:
        return

    result.nodes[:] = [
        merged_nodes.get(node.local_id, node)
        for node in result.nodes
        if node.local_id not in replacements
    ]

    edges = []
    semantic_refs: set[tuple[str, str, str | None]] = set()
    for edge in result.edges:
        if edge.kind == EDGE_CONTAINS and edge.dst_local_id in replacements:
            continue
        rewritten = replace(
            edge,
            src_local_id=replacements.get(edge.src_local_id, edge.src_local_id),
        )
        if rewritten.kind == EDGE_REFERENCES:
            key = (rewritten.src_local_id, rewritten.kind, rewritten.dst_name)
            if key in semantic_refs:
                continue
            semantic_refs.add(key)
        edges.append(rewritten)
    result.edges[:] = dict.fromkeys(edges)


_PASCAL_BUILTIN_TYPES = frozenset(
    {
        "ansistring",
        "boolean",
        "byte",
        "cardinal",
        "char",
        "currency",
        "double",
        "extended",
        "integer",
        "int64",
        "longint",
        "longword",
        "nativeint",
        "nativeuint",
        "pointer",
        "real",
        "shortint",
        "shortstring",
        "single",
        "smallint",
        "string",
        "variant",
        "widechar",
        "widestring",
        "word",
    }
)


def _pascal_decl_kind(node: Node) -> str:
    type_node = node.child_by_field_name("type") if node.type == "declType" else node
    if type_node is None:
        return NODE_CLASS
    if type_node.type == "declIntf":
        return NODE_INTERFACE
    if type_node.type == "declClass":
        child_types = {child.type for child in type_node.named_children}
        if "kRecord" in child_types:
            return NODE_STRUCT
        return NODE_CLASS
    if any(child.type == "declEnum" for child in type_node.named_children):
        return NODE_ENUM
    return NODE_CLASS


def _collect_pascal_type_refs(node: Node, source: bytes, out: list[str]) -> None:
    if node.type == "typerefDot":
        _append_pascal_type(node_text(node, source).strip(), out)
        return
    if node.type == "identifier":
        _append_pascal_type(node_text(node, source).strip(), out)
        return
    for child in node.named_children:
        _collect_pascal_type_refs(child, source, out)


def _append_pascal_type(name: str, out: list[str]) -> None:
    if name and name.lower() not in _PASCAL_BUILTIN_TYPES:
        out.append(name)
