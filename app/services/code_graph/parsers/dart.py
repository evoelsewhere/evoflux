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
                    kind=NODE_CLASS, name=node_text(name, source), is_class=True
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
        # Dart doesn't have a straightforward call_expression in all grammars.
        # Look for identifiers in selector chains.
        if node.type == "identifier":
            # Handled by parent walk
            pass
        return None

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
        name = (
            node_text(alias, source)
            if alias is not None
            else _dart_local_name(module_path)
        )
        return [ImportRef(name=name, module_path=module_path)]

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
