"""Dart language parser."""

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
    NODE_ENUM,
    NODE_FUNCTION,
    NODE_METHOD,
)

if TYPE_CHECKING:
    from tree_sitter import Node


class DartParser(TreeSitterParser):
    name: ClassVar[str] = "dart"
    extensions: ClassVar[tuple[str, ...]] = (".dart",)
    grammar: ClassVar[str] = "dart"

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
                return Definition(
                    kind=NODE_ENUM, name=node_text(name, source), is_class=True
                )
        elif ntype == "mixin_declaration":
            name = node.child_by_field_name("name")
            if name is not None:
                return Definition(
                    kind=NODE_CLASS, name=node_text(name, source), is_class=True
                )
        elif ntype == "extension_declaration":
            name = node.child_by_field_name("name")
            if name is not None:
                return Definition(
                    kind=NODE_CLASS, name=node_text(name, source), is_class=True
                )
        elif ntype == "method_signature":
            name = node.child_by_field_name("name")
            if name is not None:
                return Definition(
                    kind=NODE_METHOD, name=node_text(name, source), is_class=False
                )
        elif ntype == "function_signature":
            name = node.child_by_field_name("name")
            if name is not None:
                kind = NODE_METHOD if inside_class else NODE_FUNCTION
                return Definition(
                    kind=kind, name=node_text(name, source), is_class=False
                )
        elif ntype == "getter_signature":
            name = node.child_by_field_name("name")
            if name is not None:
                return Definition(
                    kind=NODE_METHOD, name=node_text(name, source), is_class=False
                )
        elif ntype == "setter_signature":
            name = node.child_by_field_name("name")
            if name is not None:
                return Definition(
                    kind=NODE_METHOD, name=node_text(name, source), is_class=False
                )
        elif ntype == "constructor_signature":
            name = node.child_by_field_name("name")
            if name is not None:
                return Definition(
                    kind=NODE_METHOD, name=node_text(name, source), is_class=False
                )
        return None

    def call_target(self, node: Node, source: bytes) -> str | None:
        if node.type != "selector" or not any(
            child.type == "argument_part" for child in node.children
        ):
            return None

        parts: list[str] = []
        current = node.prev_named_sibling
        while current is not None:
            if current.type in {"identifier", "type_identifier"}:
                parts.insert(0, node_text(current, source))
                break
            if current.type == "selector":
                name = _dart_selector_name(current, source)
                if name is None:
                    break
                parts.insert(0, name)
                current = current.prev_named_sibling
                continue
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
        uri_node = _find_uri(container, source)
        if uri_node is None:
            return []
        module_path = node_text(uri_node, source).strip("'\"")
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
                name = _dart_type_name(child, source)
                if name:
                    out.append(SuperType(name=name, edge_kind=EDGE_INHERITS))
            elif child.type == "interfaces":
                for sub in child.children:
                    name = _dart_type_name(sub, source)
                    if name:
                        out.append(SuperType(name=name, edge_kind=EDGE_IMPLEMENTS))
            elif child.type == "mixins":
                for sub in child.children:
                    name = _dart_type_name(sub, source)
                    if name:
                        out.append(SuperType(name=name, edge_kind=EDGE_IMPLEMENTS))
        return out

    def decorators(self, node: Node, source: bytes) -> list[str]:
        out: list[str] = []
        prev = node.prev_named_sibling
        while prev is not None:
            if prev.type == "annotation":
                name = _dart_annotation_name(prev, source)
                if name:
                    out.append(name)
            elif prev.type not in ("comment",):
                break
            prev = prev.prev_named_sibling
        return out

    def type_refs(self, node: Node, source: bytes) -> list[str]:
        if node.type not in {
            "function_signature",
            "method_signature",
            "getter_signature",
            "setter_signature",
            "constructor_signature",
        }:
            return []
        out: list[str] = []
        # Return type
        ret = node.child_by_field_name("return_type")
        if ret is not None:
            _collect_dart_type_ids(ret, source, out)
        # Parameter types
        params = node.child_by_field_name("parameters")
        if params is not None:
            _collect_dart_param_types(params, source, out)
        return out

    def docstring(self, node: Node, source: bytes) -> str | None:
        prev = node.prev_named_sibling
        if prev is not None and prev.type == "comment":
            text = node_text(prev, source)
            if text.startswith("///"):
                lines: list[str] = []
                cur: Node | None = prev
                while cur is not None and cur.type == "comment":
                    t = node_text(cur, source)
                    if t.startswith("///"):
                        lines.append(t[3:].strip())
                    else:
                        break
                    cur = cur.prev_named_sibling
                lines.reverse()
                return "\n".join(lines) if lines else None
        return None


def _dart_type_name(node: Node, source: bytes) -> str | None:
    if node.type == "identifier":
        return node_text(node, source)
    if node.type == "type_identifier":
        return node_text(node, source)
    for child in node.children:
        if child.type == "identifier" or child.type == "type_identifier":
            return node_text(child, source)
    return None


def _dart_selector_name(node: Node, source: bytes) -> str | None:
    if any(child.type == "argument_part" for child in node.children):
        return None
    for child in node.children:
        if child.type in {
            "assignable_selector",
            "conditional_assignable_selector",
            "unconditional_assignable_selector",
        }:
            for sub in child.children:
                if sub.type == "identifier":
                    return node_text(sub, source)
    return None


def _find_uri(spec: Node, source: bytes) -> Node | None:
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
    for child in node.children:
        if child.type == "identifier":
            return node_text(child, source)
        if child.type == "constructor_invocation":
            for sub in child.children:
                if sub.type == "type_identifier":
                    return node_text(sub, source)
                if sub.type == "identifier":
                    return node_text(sub, source)
    return None


def _collect_dart_type_ids(node: Node, source: bytes, out: list[str]) -> None:
    """Recursively collect user-defined type identifiers from Dart type nodes."""
    if node.type == "type_identifier":
        name = node_text(node, source)
        if name not in _DART_BUILTIN_TYPES:
            out.append(name)
        return
    if node.type == "identifier":
        name = node_text(node, source)
        if name not in _DART_BUILTIN_TYPES and name[0:1].isupper():
            out.append(name)
        return
    if node.type in (
        "nullable_type",
        "generic_type",
        "function_type",
        "record_type",
        "type_arguments",
    ):
        for child in node.children:
            _collect_dart_type_ids(child, source, out)
        return
    for child in node.children:
        _collect_dart_type_ids(child, source, out)


def _collect_dart_param_types(node: Node, source: bytes, out: list[str]) -> None:
    """Collect type identifiers from Dart formal parameters."""
    for child in node.children:
        if child.type == "formal_parameter":
            type_node = child.child_by_field_name("type")
            if type_node is not None:
                _collect_dart_type_ids(type_node, source, out)


def _dart_local_name(module_path: str) -> str:
    """Derive a locally-usable name from a URI when no `as` alias is given.

    ``package:my_pkg/my_pkg.dart`` -> ``my_pkg``, ``dart:core`` -> ``core``,
    ``src/local_file.dart`` -> ``local_file``.
    """
    tail = module_path.rsplit("/", 1)[-1]
    tail = tail.rsplit(":", 1)[-1]
    if tail.endswith(".dart"):
        tail = tail[: -len(".dart")]
    return tail or module_path
