"""Scala language parser."""

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
    NODE_INTERFACE,
    NODE_METHOD,
)

if TYPE_CHECKING:
    from tree_sitter import Node


class ScalaParser(TreeSitterParser):
    name: ClassVar[str] = "scala"
    extensions: ClassVar[tuple[str, ...]] = (".scala", ".sc")
    grammar: ClassVar[str] = "scala"

    def classify(
        self, node: Node, source: bytes, *, inside_class: bool
    ) -> Definition | None:
        ntype = node.type
        if ntype == "trait_definition":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_INTERFACE, name=name, is_class=True)
        elif ntype == "class_definition":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_CLASS, name=name, is_class=True)
        elif ntype == "object_definition":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_CLASS, name=name, is_class=True)
        elif ntype == "function_definition":
            name = self._name(node, source)
            if name:
                kind = NODE_METHOD if inside_class else NODE_FUNCTION
                return Definition(kind=kind, name=name, is_class=False)
        elif ntype == "val_definition":
            # Only capture named vals inside classes as properties
            if inside_class:
                name = self._val_name(node, source)
                if name:
                    return Definition(kind=NODE_METHOD, name=name, is_class=False)
        elif ntype == "type_definition":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_CLASS, name=name, is_class=False)
        return None

    def call_target(self, node: Node, source: bytes) -> str | None:
        if node.type == "call_expression":
            func = node.child_by_field_name("function")
            if func is None:
                return None
            if func.type == "identifier":
                return node_text(func, source)
            if func.type == "field_expression":
                field = func.child_by_field_name("field")
                if field is not None:
                    return node_text(field, source)
            if func.type == "generic_function":
                fn = func.child_by_field_name("function")
                if fn is not None and fn.type == "identifier":
                    return node_text(fn, source)
        return None

    def supertypes(self, node: Node, source: bytes) -> list[SuperType]:
        if node.type not in (
            "class_definition",
            "trait_definition",
            "object_definition",
        ):
            return []
        out: list[SuperType] = []
        for child in node.children:
            if child.type == "extends_clause":
                for sub in child.children:
                    name = _scala_type_name(sub, source)
                    if name:
                        out.append(SuperType(name=name, edge_kind=EDGE_INHERITS))
        return out

    def docstring(self, node: Node, source: bytes) -> str | None:
        prev = node.prev_named_sibling
        if prev is not None and prev.type == "comment":
            text = node_text(prev, source)
            if text.startswith("/**"):
                return _strip_scaladoc(text)
        return None

    def import_refs(self, node: Node, source: bytes) -> list[ImportRef]:
        if node.type != "import_declaration":
            return []
        # A single import_declaration can hold several comma-separated import
        # paths (`import a.b.C, d.e.F`); split on the top-level unnamed ","
        # tokens (not the ones inside a namespace_selectors list) into
        # independent segments, each a dotted "path" optionally followed by
        # a namespace_selectors ({A, B => C}) or namespace_wildcard (_ / *).
        segments: list[list[Node]] = [[]]
        for child in node.children:
            if child.type == "import":
                continue
            if child.type == ",":
                segments.append([])
                continue
            segments[-1].append(child)
        out: list[ImportRef] = []
        for segment in segments:
            out.extend(_scala_import_segment(segment, source))
        return out

    def decorators(self, node: Node, source: bytes) -> list[str]:
        out: list[str] = []
        prev = node.prev_named_sibling
        while prev is not None and prev.type == "annotation":
            name = _scala_annotation_name(prev, source)
            if name:
                out.append(name)
            prev = prev.prev_named_sibling
        return out

    def type_refs(self, node: Node, source: bytes) -> list[str]:
        if node.type != "function_definition":
            return []
        out: list[str] = []
        # Parameter types
        params = node.child_by_field_name("parameters")
        if params is not None:
            for param in params.children:
                if param.type == "parameter":
                    type_node = param.child_by_field_name("type")
                    if type_node is not None:
                        _collect_scala_type_ids(type_node, source, out)
        # Return type
        ret = node.child_by_field_name("return_type")
        if ret is not None:
            _collect_scala_type_ids(ret, source, out)
        return out

    def _name(self, node: Node, source: bytes) -> str | None:
        name_node = node.child_by_field_name("name")
        if name_node is not None:
            return node_text(name_node, source)
        for child in node.children:
            if child.type == "identifier":
                return node_text(child, source)
        return None

    def _val_name(self, node: Node, source: bytes) -> str | None:
        pattern = node.child_by_field_name("pattern")
        if pattern is not None and pattern.type == "identifier":
            return node_text(pattern, source)
        return None


_SCALA_BUILTIN_TYPES = frozenset(
    {
        "Any",
        "AnyRef",
        "AnyVal",
        "Boolean",
        "Byte",
        "Char",
        "Double",
        "Float",
        "Int",
        "Long",
        "Nothing",
        "Null",
        "Short",
        "String",
        "Unit",
    }
)


def _scala_annotation_name(node: Node, source: bytes) -> str | None:
    """Extract annotation name from a Scala annotation node."""
    for child in node.children:
        if child.type == "identifier":
            return node_text(child, source)
        if child.type == "type_identifier":
            return node_text(child, source)
        if child.type == "constructor_annotation":
            for sub in child.children:
                if sub.type == "identifier":
                    return node_text(sub, source)
    return None


def _collect_scala_type_ids(node: Node, source: bytes, out: list[str]) -> None:
    """Recursively collect user-defined type identifiers from Scala type nodes."""
    if node.type == "type_identifier":
        name = node_text(node, source)
        if name not in _SCALA_BUILTIN_TYPES:
            out.append(name)
        return
    if node.type == "generic_type":
        for child in node.children:
            _collect_scala_type_ids(child, source, out)
        return
    for child in node.children:
        _collect_scala_type_ids(child, source, out)


def _scala_type_name(node: Node, source: bytes) -> str | None:
    if node.type == "type_identifier":
        return node_text(node, source)
    if node.type == "generic_type":
        for child in node.children:
            if child.type == "type_identifier":
                return node_text(child, source)
    return None


def _scala_import_segment(segment: list[Node], source: bytes) -> list[ImportRef]:
    """Extract ImportRefs from one comma-separated segment of an import_declaration.

    ``segment`` holds a dotted run of "path"-field ``identifier``/"."
    children, optionally followed by a ``namespace_selectors`` or
    ``namespace_wildcard`` suffix — the selectors/wildcard are NOT part of
    the leading dotted path, so `path_parts` here is only the prefix before
    the suffix (e.g. just `a`, `b` in `a.b.{C, D}`).
    """
    path_parts = [c for c in segment if c.type == "identifier"]
    tail = next(
        (c for c in segment if c.type in ("namespace_selectors", "namespace_wildcard")),
        None,
    )
    if tail is None:
        # Bare import: the last dotted segment is both the path prefix and
        # the locally-used name, e.g. `import a.b.C` -> name "C".
        if not path_parts:
            return []
        dotted = ".".join(node_text(p, source) for p in path_parts)
        return [ImportRef(name=node_text(path_parts[-1], source), module_path=dotted)]
    base_path = ".".join(node_text(p, source) for p in path_parts)
    if tail.type == "namespace_wildcard":
        return [ImportRef(name="*", module_path=f"{base_path}.*")]
    # namespace_selectors: `{Qux, Quux}` or `{Qux => AliasQux}` — fans out
    # into one ImportRef per selector, sharing the same dotted path prefix.
    # For a rename (`Qux => AliasQux`) the symbol actually defined at the
    # target is still the original name ("Qux") — the "=>" only renames the
    # local binding — so we record that, matching python.py's "import X as Y"
    # convention.
    out: list[ImportRef] = []
    for sub in tail.children:
        if sub.type == "identifier":
            out.append(ImportRef(name=node_text(sub, source), module_path=base_path))
        elif sub.type == "arrow_renamed_identifier":
            name_node = sub.child_by_field_name("name")
            if name_node is not None:
                alias_node = sub.child_by_field_name("alias")
                out.append(
                    ImportRef(
                        name=node_text(name_node, source),
                        module_path=base_path,
                        local_name=(
                            node_text(alias_node, source)
                            if alias_node is not None
                            else None
                        ),
                    )
                )
    return out


def _strip_scaladoc(text: str) -> str:
    s = text.strip()
    if s.startswith("/**"):
        s = s[3:]
    if s.endswith("*/"):
        s = s[:-2]
    lines = [ln.strip().lstrip("* ").strip() for ln in s.split("\n")]
    return "\n".join(ln for ln in lines if ln and not ln.startswith("@"))
