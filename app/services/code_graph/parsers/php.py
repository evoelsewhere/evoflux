"""PHP language parser."""

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
    NODE_INTERFACE,
    NODE_METHOD,
    NODE_NAMESPACE,
)

if TYPE_CHECKING:
    from tree_sitter import Node


class PhpParser(TreeSitterParser):
    name: ClassVar[str] = "php"
    extensions: ClassVar[tuple[str, ...]] = (".php",)
    grammar: ClassVar[str] = "php"

    def root_prefix(self, root: Node, source: bytes) -> str:
        namespaces = [
            child for child in root.children if child.type == "namespace_definition"
        ]
        if len(namespaces) != 1:
            return ""
        namespace = namespaces[0]
        if namespace.child_by_field_name("body") is not None:
            return ""
        name = namespace.child_by_field_name("name")
        return f"{_php_namespace_name(name, source)}." if name is not None else ""

    def classify(
        self, node: Node, source: bytes, *, inside_class: bool
    ) -> Definition | None:
        ntype = node.type
        if ntype == "namespace_definition":
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                return Definition(
                    kind=NODE_NAMESPACE,
                    name=_php_namespace_name(name_node, source),
                    is_class=False,
                    prefix=("" if node.child_by_field_name("body") is None else None),
                )
        elif ntype == "class_declaration":
            name = self._field_name(node, source)
            if name:
                return Definition(kind=NODE_CLASS, name=name, is_class=True)
        elif ntype == "interface_declaration":
            name = self._field_name(node, source)
            if name:
                return Definition(kind=NODE_INTERFACE, name=name, is_class=True)
        elif ntype == "trait_declaration":
            name = self._field_name(node, source)
            if name:
                return Definition(kind=NODE_CLASS, name=name, is_class=True)
        elif ntype == "enum_declaration":
            name = self._field_name(node, source)
            if name:
                return Definition(kind=NODE_ENUM, name=name, is_class=True)
        elif ntype == "method_declaration":
            name = self._field_name(node, source)
            if name:
                return Definition(kind=NODE_METHOD, name=name, is_class=False)
        elif ntype == "function_definition":
            name = self._field_name(node, source)
            if name:
                return Definition(kind=NODE_FUNCTION, name=name, is_class=False)
        return None

    def import_refs(self, node: Node, source: bytes) -> list[ImportRef]:
        if node.type != "namespace_use_declaration":
            return []
        # Two shapes: a flat list of "namespace_use_clause" children (each a
        # full dotted path, optionally "as"-aliased), or a "namespace_name"
        # prefix followed by a "namespace_use_group" ("{Str, Arr as A}") whose
        # clauses are bare trailing segments to append to the prefix.
        group = next(
            (c for c in node.children if c.type == "namespace_use_group"), None
        )
        if group is not None:
            prefix_node = next(
                (c for c in node.children if c.type == "namespace_name"), None
            )
            prefix = node_text(prefix_node, source) if prefix_node is not None else ""
            out: list[ImportRef] = []
            for clause in group.children:
                if clause.type != "namespace_use_clause":
                    continue
                ref = self._use_clause_ref(clause, source, prefix=f"{prefix}\\")
                if ref is not None:
                    out.append(ref)
            return out
        out = []
        for clause in node.children:
            if clause.type != "namespace_use_clause":
                continue
            ref = self._use_clause_ref(clause, source, prefix="")
            if ref is not None:
                out.append(ref)
        return out

    def _use_clause_ref(
        self, clause: Node, source: bytes, *, prefix: str
    ) -> ImportRef | None:
        base = next(
            (c for c in clause.children if c.type in ("qualified_name", "name")),
            None,
        )
        if base is None:
            return None
        module_path = f"{prefix}{node_text(base, source)}"
        alias = clause.child_by_field_name("alias")
        if alias is not None:
            return ImportRef(
                name=_last_name(base, source) or node_text(base, source),
                module_path=module_path,
                local_name=node_text(alias, source),
            )
        return ImportRef(
            name=_last_name(base, source) or node_text(base, source),
            module_path=module_path,
        )

    def call_target(self, node: Node, source: bytes) -> str | None:
        ntype = node.type
        if ntype == "function_call_expression":
            func = node.child_by_field_name("function")
            if func is not None and func.type == "name":
                return node_text(func, source)
        elif ntype == "member_call_expression":
            name = node.child_by_field_name("name")
            if name is not None:
                receiver = node.child_by_field_name("object")
                if receiver is not None:
                    raw_receiver = node_text(receiver, source).lstrip("$")
                    return f"{raw_receiver}.{node_text(name, source)}"
                return node_text(name, source)
        elif ntype == "scoped_call_expression":
            name = node.child_by_field_name("name")
            if name is not None:
                scope = node.child_by_field_name("scope")
                if scope is not None:
                    raw_scope = node_text(scope, source).lstrip("$")
                    if raw_scope in {"self", "static", "parent"}:
                        raw_scope = "this"
                    return f"{raw_scope}.{node_text(name, source)}"
                return node_text(name, source)
        elif ntype == "object_creation_expression":
            for child in node.children:
                if child.type == "name":
                    return node_text(child, source)
                if child.type == "qualified_name":
                    return _last_name(child, source)
        return None

    def supertypes(self, node: Node, source: bytes) -> list[SuperType]:
        if node.type not in ("class_declaration", "interface_declaration"):
            return []
        out: list[SuperType] = []
        for child in node.children:
            if child.type == "base_clause":
                for sub in child.children:
                    if sub.type == "name":
                        out.append(
                            SuperType(
                                name=node_text(sub, source), edge_kind=EDGE_INHERITS
                            )
                        )
                    elif sub.type == "qualified_name":
                        out.append(
                            SuperType(
                                name=_last_name(sub, source) or "",
                                edge_kind=EDGE_INHERITS,
                            )
                        )
            elif child.type == "class_interface_clause":
                for sub in child.children:
                    if sub.type == "name":
                        out.append(
                            SuperType(
                                name=node_text(sub, source), edge_kind=EDGE_IMPLEMENTS
                            )
                        )
                    elif sub.type == "qualified_name":
                        out.append(
                            SuperType(
                                name=_last_name(sub, source) or "",
                                edge_kind=EDGE_IMPLEMENTS,
                            )
                        )
        return out

    def docstring(self, node: Node, source: bytes) -> str | None:
        prev = node.prev_named_sibling
        if prev is not None and prev.type == "comment":
            text = node_text(prev, source)
            if text.startswith("/**"):
                return _strip_phpdoc(text)
        return None

    def decorators(self, node: Node, source: bytes) -> list[str]:
        out: list[str] = []
        for child in node.children:
            if child.type == "attribute_list":
                for attr in child.children:
                    if attr.type == "attribute":
                        name = _php_attr_name(attr, source)
                        if name:
                            out.append(name)
        return out

    def type_refs(self, node: Node, source: bytes) -> list[str]:
        if node.type not in {"method_declaration", "function_definition"}:
            return []
        out: list[str] = []
        # Parameter types
        params = node.child_by_field_name("parameters")
        if params is not None:
            for param in params.children:
                if param.type == "simple_parameter":
                    for sub in param.children:
                        if sub.type in {
                            "type_identifier",
                            "named_type",
                            "union_type",
                            "intersection_type",
                            "nullable_type",
                        }:
                            _collect_php_type_ids(sub, source, out)
                            break
        # Return type
        ret = node.child_by_field_name("return_type")
        if ret is not None:
            _collect_php_type_ids(ret, source, out)
        return out

    def _field_name(self, node: Node, source: bytes) -> str | None:
        name_node = node.child_by_field_name("name")
        if name_node is not None:
            return node_text(name_node, source)
        for child in node.children:
            if child.type == "name":
                return node_text(child, source)
        return None


_PHP_BUILTIN_TYPES = frozenset(
    {
        "bool",
        "int",
        "float",
        "string",
        "array",
        "callable",
        "iterable",
        "object",
        "mixed",
        "void",
        "null",
        "never",
        "self",
        "static",
        "true",
        "false",
    }
)


def _php_attr_name(attr_node: Node, source: bytes) -> str | None:
    """Extract attribute name from a PHP attribute node."""
    for child in attr_node.children:
        if child.type in ("name", "qualified_name"):
            return _last_name(child, source) or node_text(child, source)
    return None


def _collect_php_type_ids(node: Node, source: bytes, out: list[str]) -> None:
    """Recursively collect user-defined type identifiers from PHP type nodes."""
    if node.type in ("name", "qualified_name", "type_identifier", "named_type"):
        name = _last_name(node, source) or node_text(node, source)
        if name.lower() not in _PHP_BUILTIN_TYPES:
            out.append(name)
        return
    if node.type in ("union_type", "intersection_type", "nullable_type"):
        for child in node.children:
            _collect_php_type_ids(child, source, out)
        return


def _last_name(node: Node, source: bytes) -> str | None:
    for child in reversed(node.children):
        if child.type == "name":
            return node_text(child, source)
    return None


def _php_namespace_name(node: Node, source: bytes) -> str:
    return node_text(node, source).strip("\\").replace("\\", ".")


def _strip_phpdoc(text: str) -> str:
    s = text.strip()
    if s.startswith("/**"):
        s = s[3:]
    if s.endswith("*/"):
        s = s[:-2]
    lines = [ln.strip().lstrip("* ").strip() for ln in s.split("\n")]
    return "\n".join(ln for ln in lines if ln and not ln.startswith("@"))
