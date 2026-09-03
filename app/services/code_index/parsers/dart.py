"""Dart language parser."""

from __future__ import annotations

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
    EDGE_CALLS,
    EDGE_IMPLEMENTS,
    EDGE_INHERITS,
    EDGE_REFERENCES,
    NODE_CLASS,
    NODE_ENUM,
    NODE_FIELD,
    NODE_FUNCTION,
    NODE_METHOD,
    NODE_PROPERTY,
    NODE_VARIABLE,
    ExtractedEdge,
    ParseResult,
)

if TYPE_CHECKING:
    from tree_sitter import Node


class DartParser(TreeSitterParser):
    name: ClassVar[str] = "dart"
    extensions: ClassVar[tuple[str, ...]] = (".dart",)
    grammar: ClassVar[str] = "dart"

    def parse(self, *, file_path: str, source: bytes) -> ParseResult:
        result = super().parse(file_path=file_path, source=source)
        return _reattach_dart_body_edges(result)

    def identifier_reference_targets(self, node: Node, source: bytes) -> list[str]:
        # Dart's grammar represents declaration names, selector members, and
        # constructor parameters as ordinary identifiers. The shared fallback
        # therefore produces mostly false positives; precise type/call hooks
        # below provide the trustworthy relations for this language.
        return []

    def classify(
        self, node: Node, source: bytes, *, inside_class: bool
    ) -> Definition | None:
        ntype = node.type
        if ntype == "class_definition":
            name = node.child_by_field_name("name")
            if name is not None:
                return Definition(
                    kind=NODE_CLASS, name=node_text(name, source), is_class=True
                )
        elif ntype == "enum_declaration":
            name = node.child_by_field_name("name")
            if name is not None:
                return Definition(kind=NODE_ENUM, name=node_text(name, source))
        elif ntype == "mixin_declaration":
            name = _dart_decl_name(node)
            if name is not None:
                return Definition(
                    kind=NODE_CLASS, name=node_text(name, source), is_class=True
                )
        elif ntype == "extension_declaration":
            name = _dart_decl_name(node)
            if name is not None:
                return Definition(
                    kind=NODE_CLASS, name=node_text(name, source), is_class=True
                )
        elif ntype == "function_signature":
            name = node.child_by_field_name("name")
            if name is not None:
                kind = NODE_METHOD if inside_class else NODE_FUNCTION
                return Definition(kind=kind, name=node_text(name, source))
        elif ntype == "getter_signature":
            name = node.child_by_field_name("name")
            if name is not None:
                return Definition(kind=NODE_METHOD, name=node_text(name, source))
        elif ntype == "setter_signature":
            name = node.child_by_field_name("name")
            if name is not None:
                return Definition(kind=NODE_METHOD, name=node_text(name, source))
        elif ntype == "constructor_signature":
            name = node.child_by_field_name("name")
            if name is not None:
                return Definition(kind=NODE_METHOD, name=node_text(name, source))
        elif ntype == "initialized_identifier":
            name = _dart_decl_name(node)
            if name is not None:
                kind = NODE_FIELD if inside_class else NODE_VARIABLE
                return Definition(kind=kind, name=node_text(name, source))
        elif ntype == "static_final_declaration":
            name = _dart_decl_name(node)
            if name is not None:
                return Definition(kind=NODE_VARIABLE, name=node_text(name, source))
        elif ntype == "enum_constant":
            name = _dart_decl_name(node)
            if name is not None:
                return Definition(kind=NODE_PROPERTY, name=node_text(name, source))
        elif ntype == "type_alias":
            name = _dart_first_child(node, {"type_identifier"})
            if name is not None:
                return Definition(kind=NODE_CLASS, name=node_text(name, source))
        return None

    def call_target(self, node: Node, source: bytes) -> str | None:
        if node.type != "selector" or not any(
            child.type == "argument_part" for child in node.children
        ):
            return None

        parts: list[str] = []
        current = node.prev_named_sibling
        while current is not None:
            if current.type == "identifier":
                parts.insert(0, node_text(current, source))
                break
            if current.type == "selector":
                name = _dart_selector_name(current, source)
                if name is None:
                    break
                parts.insert(0, name)
                current = current.prev_named_sibling
                continue
            if current.type in {
                "assignable_selector",
                "conditional_assignable_selector",
                "unconditional_assignable_selector",
            }:
                name = _dart_assignable_name(current, source)
                if name is None:
                    break
                parts.insert(0, name)
                current = current.prev_named_sibling
                continue
            if current.type in {"this", "super"}:
                parts.insert(0, "this")
                break
            break
        return ".".join(parts) if parts else None

    def import_refs(self, node: Node, source: bytes) -> list[ImportRef]:
        # `import 'uri' [as alias] [show/hide ...];` parses as
        # import_or_export > library_import > import_specification, with the
        # "configurable_uri" > "uri" > "string_literal" holding the quoted
        # URI and an optional "as" identifier (no locally-bound name for
        # show/hide combinators). `export 'uri';` parses as import_or_export
        # > library_export, with "configurable_uri" a *direct* child (no
        # wrapping import_specification, and no alias support in Dart).
        # Exports re-publish another module's symbols under this one, so
        # treating them as import-like edges is reasonable for cross-repo
        # resolution purposes.
        if node.type == "library_import":
            container = next(
                (c for c in node.children if c.type == "import_specification"), None
            )
        elif node.type == "library_export":
            container = node
        else:
            return []
        if container is None:
            return []
        uri_node = _find_uri(container)
        if uri_node is None:
            return []
        literal = node_text(uri_node, source)
        module_path = literal[1:-1]
        if not module_path:
            return []
        alias = next((c for c in container.children if c.type == "identifier"), None)
        target_name = _dart_local_name(module_path)
        return [
            ImportRef(
                name=target_name,
                module_path=module_path,
                local_name=node_text(alias, source) if alias is not None else None,
            )
        ]

    def supertypes(self, node: Node, source: bytes) -> list[SuperType]:
        if node.type != "class_definition":
            return []
        out: list[SuperType] = []
        for child in node.children:
            if child.type == "superclass":
                direct_types = [
                    sub for sub in child.children if sub.type == "type_identifier"
                ]
                name = (
                    _dart_type_name(direct_types[0], source) if direct_types else None
                )
                if name:
                    out.append(SuperType(name=name, edge_kind=EDGE_INHERITS))
                for mixins in child.children:
                    if mixins.type != "mixins":
                        continue
                    for sub in mixins.children:
                        mixin_name = _dart_type_name(sub, source)
                        if mixin_name:
                            out.append(
                                SuperType(name=mixin_name, edge_kind=EDGE_IMPLEMENTS)
                            )
            elif child.type == "interfaces":
                for sub in child.children:
                    name = _dart_type_name(sub, source)
                    if name:
                        out.append(SuperType(name=name, edge_kind=EDGE_IMPLEMENTS))
        return out

    def decorators(self, node: Node, source: bytes) -> list[str]:
        out: list[str] = []
        owner = _dart_definition_owner(node)
        for child in owner.children:
            if child.type == "annotation":
                name = _dart_annotation_name(child, source)
                if name:
                    out.append(name)
        prev = owner.prev_named_sibling
        preceding: list[str] = []
        while prev is not None and prev.type == "annotation":
            name = _dart_annotation_name(prev, source)
            if name:
                preceding.append(name)
            prev = prev.prev_named_sibling
        out.extend(reversed(preceding))
        return out

    def type_refs(self, node: Node, source: bytes) -> list[str]:
        owner = _dart_definition_owner(node)
        if owner.type not in {
            "function_signature",
            "method_signature",
            "getter_signature",
            "setter_signature",
            "constructor_signature",
            "declaration",
            "static_final_declaration",
            "type_alias",
        }:
            return []
        out: list[str] = []
        if owner.type == "static_final_declaration":
            _collect_dart_declared_types(owner, source, out)
        elif owner.type == "type_alias":
            alias = _dart_first_child(owner, {"type_identifier"})
            for child in owner.children:
                if child is not alias:
                    _collect_dart_type_ids(child, source, out)
        else:
            for child in owner.children:
                if child.type in {
                    "formal_parameter_list",
                    "type_identifier",
                    "generic_type",
                    "nullable_type",
                    "function_type",
                    "record_type",
                    "type_arguments",
                }:
                    _collect_dart_type_ids(child, source, out)
        type_parameters = _dart_enclosing_type_parameters(node, source)
        return [name for name in dict.fromkeys(out) if name not in type_parameters]

    def docstring(self, node: Node, source: bytes) -> str | None:
        owner = _dart_definition_owner(node)
        prev = owner.prev_named_sibling
        while prev is not None and prev.type == "annotation":
            prev = prev.prev_named_sibling
        if prev is not None and prev.type == "documentation_comment":
            text = node_text(prev, source)
            if text.startswith("///"):
                lines: list[str] = []
                cur: Node | None = prev
                while cur is not None and cur.type == "documentation_comment":
                    t = node_text(cur, source)
                    if t.startswith("///"):
                        lines.append(t[3:].strip())
                    else:
                        break
                    cur = cur.prev_named_sibling
                lines.reverse()
                return "\n".join(lines) if lines else None
        return None


def _reattach_dart_body_edges(result: ParseResult) -> ParseResult:
    nodes = {node.local_id: node for node in result.nodes}
    children_by_parent: dict[str, list[str]] = {}
    for edge in result.edges:
        if edge.dst_local_id is not None:
            children_by_parent.setdefault(edge.src_local_id, []).append(
                edge.dst_local_id
            )

    callables: dict[str, list[tuple[int, str]]] = {}
    for parent_id, child_ids in children_by_parent.items():
        callables[parent_id] = [
            (nodes[child_id].line_start, child_id)
            for child_id in child_ids
            if nodes[child_id].kind in {NODE_FUNCTION, NODE_METHOD}
        ]

    rewritten: list[ExtractedEdge] = []
    for edge in result.edges:
        if edge.kind in {EDGE_CALLS, EDGE_REFERENCES}:
            if edge.line is not None:
                target = next(
                    (
                        local_id
                        for start, local_id in reversed(
                            callables.get(edge.src_local_id, [])
                        )
                        if start <= edge.line
                    ),
                    None,
                )
                if target is not None:
                    edge = replace(edge, src_local_id=target)
        rewritten.append(edge)
    result.edges[:] = dict.fromkeys(rewritten)
    return result


def _dart_first_child(node: Node, node_types: set[str]) -> Node | None:
    return next((child for child in node.children if child.type in node_types), None)


def _dart_decl_name(node: Node) -> Node | None:
    return _dart_first_child(node, {"identifier"})


def _dart_definition_owner(node: Node) -> Node:
    if node.type != "initialized_identifier":
        return node
    current = node.parent
    while current is not None and current.type != "declaration":
        current = current.parent
    return current if current is not None else node


def _collect_dart_declared_types(node: Node, source: bytes, out: list[str]) -> None:
    if node.type == "static_final_declaration":
        container = node.parent
        type_node = container.prev_named_sibling if container is not None else None
        if type_node is not None:
            _collect_dart_type_ids(type_node, source, out)
        return
    for child in node.children:
        if child.type in {
            "function_type",
            "generic_type",
            "nullable_type",
            "record_type",
            "type_arguments",
            "type_identifier",
        }:
            _collect_dart_type_ids(child, source, out)


def _dart_enclosing_type_parameters(node: Node, source: bytes) -> set[str]:
    out: set[str] = set()
    current: Node | None = node
    while current is not None:
        parameters = _dart_first_child(current, {"type_parameters"})
        if parameters is not None:
            for child in parameters.children:
                if child.type == "type_parameter":
                    name = _dart_first_child(child, {"type_identifier"})
                    if name is not None:
                        out.add(node_text(name, source))
        current = current.parent
    return out


def _dart_type_name(node: Node, source: bytes) -> str | None:
    if node.type == "type_identifier":
        return node_text(node, source)
    for child in node.children:
        if child.type == "type_identifier":
            return node_text(child, source)
    return None


def _dart_selector_name(node: Node, source: bytes) -> str | None:
    for child in node.children:
        if child.type in {
            "assignable_selector",
            "conditional_assignable_selector",
            "unconditional_assignable_selector",
        }:
            return _dart_assignable_name(child, source)
    return None


def _dart_assignable_name(node: Node, source: bytes) -> str | None:
    name = _dart_first_child(node, {"identifier"})
    return node_text(name, source) if name is not None else None


def _find_uri(spec: Node) -> Node | None:
    """Descend configurable_uri > uri > string_literal to the quoted URI."""
    for child in spec.children:
        if child.type == "configurable_uri":
            for sub in child.children:
                if sub.type == "uri":
                    for leaf in sub.children:
                        if leaf.type == "string_literal":
                            return leaf
    return None


_DART_BUILTIN_TYPES = frozenset(
    {
        "bool",
        "double",
        "dynamic",
        "int",
        "num",
        "String",
        "void",
        "Null",
        "Object",
        "Function",
        "List",
        "Map",
        "Set",
        "Iterable",
        "Future",
        "Stream",
        "Type",
    }
)


def _dart_annotation_name(node: Node, source: bytes) -> str | None:
    """Extract annotation name from a Dart annotation node."""
    name = _dart_first_child(node, {"identifier"})
    return node_text(name, source) if name is not None else None


def _collect_dart_type_ids(node: Node, source: bytes, out: list[str]) -> None:
    """Recursively collect user-defined type identifiers from Dart type nodes."""
    if node.type == "type_identifier":
        name = node_text(node, source)
        if name not in _DART_BUILTIN_TYPES:
            out.append(name)
        return
    if node.type == "type_arguments" and any(
        child.type == "." for child in node.children
    ):
        names = _dart_identifier_descendants(node)
        if names:
            name = node_text(names[-1], source)
            if name not in _DART_BUILTIN_TYPES:
                out.append(name)
        return
    for child in node.children:
        _collect_dart_type_ids(child, source, out)


def _dart_identifier_descendants(node: Node) -> list[Node]:
    out: list[Node] = []
    for child in node.children:
        if child.type in {"identifier", "type_identifier"}:
            out.append(child)
        else:
            out.extend(_dart_identifier_descendants(child))
    return out


def _dart_local_name(module_path: str) -> str:
    """Derive a locally-usable name from a URI when no `as` alias is given.

    ``package:my_pkg/my_pkg.dart`` -> ``my_pkg``, ``dart:core`` -> ``core``,
    ``src/local_file.dart`` -> ``local_file``.
    """
    tail = module_path.rpartition("/")[2] or module_path
    tail = tail.rpartition(":")[2] or tail
    if tail.endswith(".dart"):
        tail = tail[: -len(".dart")]
    return tail or module_path
