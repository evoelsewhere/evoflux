"""Rust language parser."""

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
    NODE_CLASS,
    NODE_ENUM,
    NODE_FUNCTION,
    NODE_INTERFACE,
    NODE_METHOD,
    NODE_MODULE,
    NODE_STRUCT,
    NODE_VARIABLE,
)
from app.services.code_index.parsers.symbol_leaves import rust_leaf_definition

if TYPE_CHECKING:
    from tree_sitter import Node


class RustParser(TreeSitterParser):
    name: ClassVar[str] = "rust"
    extensions: ClassVar[tuple[str, ...]] = (".rs",)
    grammar: ClassVar[str] = "rust"

    def classify(
        self, node: Node, source: bytes, *, inside_class: bool
    ) -> Definition | None:
        leaf = rust_leaf_definition(node, source)
        if leaf is not None:
            return leaf
        ntype = node.type
        if ntype == "mod_item":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_MODULE, name=name)
        elif ntype == "struct_item":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_STRUCT, name=name, is_class=True)
        elif ntype == "enum_item":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_ENUM, name=name, is_class=True)
        elif ntype == "union_item":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_STRUCT, name=name, is_class=True)
        elif ntype == "trait_item":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_INTERFACE, name=name, is_class=True)
        elif ntype == "impl_item":
            # `impl Trait for Type` or `impl Type`
            # We don't emit a node for impl blocks — their children (functions)
            # are methods. But we mark inside_class so children become methods.
            type_node = node.child_by_field_name("type")
            if type_node is not None:
                name = _type_name(type_node, source)
                if name:
                    return Definition(kind=NODE_CLASS, name=name, is_class=True)
        elif ntype == "type_item":
            # type alias: type Foo = Bar;
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_CLASS, name=name)
        elif ntype == "function_item":
            name = self._name(node, source)
            if name:
                kind = NODE_METHOD if inside_class else NODE_FUNCTION
                return Definition(kind=kind, name=name)
        elif ntype == "function_signature_item":
            # Trait method declarations
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_METHOD, name=name)
        elif ntype == "const_item":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_VARIABLE, name=name)
        elif ntype == "static_item":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_VARIABLE, name=name)
        return None

    def call_target(self, node: Node, source: bytes) -> str | None:
        ntype = node.type
        if ntype == "call_expression":
            func = node.child_by_field_name("function")
            if func is None:
                return None
            static_name = _rust_value_name(func, source)
            if static_name is not None:
                return static_name
            if func.type == "field_expression":
                field = func.child_by_field_name("field")
                return node_text(field, source) if field is not None else None
        elif ntype == "macro_invocation":
            # println!(...), vec![...] — the macro name is the "macro" field
            macro = node.child_by_field_name("macro")
            if macro is not None:
                return node_text(macro, source)
        return None

    def supertypes(self, node: Node, source: bytes) -> list[SuperType]:
        if node.type != "impl_item":
            return []
        # The grammar exposes the implemented trait separately from the target
        # type for simple, scoped, and generic `impl Trait for Type` blocks.
        trait = node.child_by_field_name("trait")
        if trait is None:
            return []
        trait_name = _type_name(trait, source)
        return (
            [SuperType(name=trait_name, edge_kind=EDGE_IMPLEMENTS)]
            if trait_name
            else []
        )

    def docstring(self, node: Node, source: bytes) -> str | None:
        return _preceding_doc_comments(node, source)

    def import_refs(self, node: Node, source: bytes) -> list[ImportRef]:
        if node.type != "use_declaration":
            return []
        out: list[ImportRef] = []
        for child in node.children:
            if child.type == "scoped_identifier":
                # use std::io::Result;
                name_node = child.child_by_field_name("name")
                path_node = child.child_by_field_name("path")
                if name_node is not None and path_node is not None:
                    out.append(
                        ImportRef(
                            name=node_text(name_node, source),
                            module_path=node_text(path_node, source),
                        )
                    )
            elif child.type == "scoped_use_list":
                # use crate::models::{User, Post};
                path_node = child.child_by_field_name("path")
                if path_node is None:
                    continue
                module_path = node_text(path_node, source)
                for sub in child.children:
                    if sub.type == "use_list":
                        out.extend(_rust_use_list(sub, source, module_path))
            elif child.type == "identifier":
                # use something; (rare)
                out.append(ImportRef(name=node_text(child, source), module_path=""))
            elif child.type == "use_as_clause":
                path_node = child.child_by_field_name("path")
                alias_node = child.child_by_field_name("alias")
                if path_node is not None:
                    if path_node.type == "scoped_identifier":
                        name_node = path_node.child_by_field_name("name")
                    else:
                        name_node = path_node
                    if name_node is not None:
                        out.append(
                            ImportRef(
                                name=node_text(name_node, source),
                                module_path=node_text(path_node, source),
                                local_name=(
                                    node_text(alias_node, source)
                                    if alias_node is not None
                                    else None
                                ),
                            )
                        )
        return out

    def decorators(self, node: Node, source: bytes) -> list[str]:
        out: list[str] = []
        prev = node.prev_named_sibling
        while prev is not None and prev.type == "attribute_item":
            name = _rust_attr_name(prev, source)
            if name:
                out.insert(0, name)
            prev = prev.prev_named_sibling
        return out

    def type_refs(self, node: Node, source: bytes) -> list[str]:
        if node.type not in {
            "function_item",
            "function_signature_item",
            "field_declaration",
            "enum_variant",
            "associated_type",
            "type_item",
            "const_item",
            "static_item",
        }:
            return []
        out: list[str] = []
        if node.type in {"type_item", "const_item", "static_item"}:
            type_node = node.child_by_field_name("type")
            if type_node is not None:
                _collect_rust_type_ids(type_node, source, out)
            return list(dict.fromkeys(out))
        if node.type == "associated_type":
            bounds = node.child_by_field_name("bounds")
            if bounds is not None:
                _collect_rust_type_ids(bounds, source, out)
            return list(dict.fromkeys(out))
        if node.type in {"field_declaration", "enum_variant"}:
            _collect_rust_type_ids(node, source, out)
            return list(dict.fromkeys(out))
        params = node.child_by_field_name("parameters")
        if params is not None:
            _collect_rust_type_ids(params, source, out)
        ret = node.child_by_field_name("return_type")
        if ret is not None:
            _collect_rust_type_ids(ret, source, out)
        return out

    def _name(self, node: Node, source: bytes) -> str | None:
        name_node = node.child_by_field_name("name")
        return node_text(name_node, source) if name_node is not None else None


_RUST_BUILTIN_TYPES = frozenset(
    {
        "bool",
        "char",
        "f32",
        "f64",
        "i8",
        "i16",
        "i32",
        "i64",
        "i128",
        "isize",
        "str",
        "u8",
        "u16",
        "u32",
        "u64",
        "u128",
        "usize",
        "Self",
    }
)


def _rust_attr_name(attr_item: Node, source: bytes) -> str | None:
    """Extract the attribute name from an attribute_item node: #[foo], #[foo::bar]."""
    for child in attr_item.children:
        if child.type == "attribute":
            for sub in child.children:
                if sub.type == "identifier":
                    return node_text(sub, source)
                if sub.type == "scoped_identifier":
                    name_node = sub.child_by_field_name("name")
                    if name_node is not None:
                        return node_text(name_node, source)
    return None


def _collect_rust_type_ids(node: Node, source: bytes, out: list[str]) -> None:
    """Recursively collect user-defined type identifiers from Rust type nodes."""
    if node.type == "type_identifier":
        name = node_text(node, source)
        if name not in _RUST_BUILTIN_TYPES:
            out.append(name)
        return
    for child in node.children:
        _collect_rust_type_ids(child, source, out)


def _type_name(node: Node, source: bytes) -> str | None:
    """Extract a simple name from a type node."""
    if node.type == "type_identifier":
        return node_text(node, source)
    if node.type == "scoped_type_identifier":
        name_node = node.child_by_field_name("name")
        return node_text(name_node, source) if name_node is not None else None
    if node.type == "generic_type":
        # Generic<T> → extract the base type
        type_node = node.child_by_field_name("type")
        return _type_name(type_node, source) if type_node is not None else None
    return None


def _rust_value_name(node: Node, source: bytes) -> str | None:
    """Return a static Rust path/field chain using graph qualification dots."""
    if node.type in {"identifier", "crate", "self", "super"}:
        return node_text(node, source)
    if node.type == "scoped_identifier":
        path = node.child_by_field_name("path")
        name = node.child_by_field_name("name")
        if path is None:
            return None
        if name is None:
            return None
        owner = _rust_value_name(path, source)
        return f"{owner}.{node_text(name, source)}" if owner else None
    if node.type == "field_expression":
        value = node.child_by_field_name("value")
        field = node.child_by_field_name("field")
        if value is None:
            return None
        if field is None:
            return None
        owner = _rust_value_name(value, source)
        return f"{owner}.{node_text(field, source)}" if owner else None
    return None


def _rust_use_list(use_list: Node, source: bytes, module_path: str) -> list[ImportRef]:
    """Extract names from a Rust use list: `{User, Post as Alias}`."""
    out: list[ImportRef] = []
    for child in use_list.children:
        if child.type == "identifier":
            out.append(
                ImportRef(name=node_text(child, source), module_path=module_path)
            )
        elif child.type == "use_as_clause":
            path_node = child.child_by_field_name("path")
            alias_node = child.child_by_field_name("alias")
            if path_node is not None:
                out.append(
                    ImportRef(
                        name=node_text(path_node, source),
                        module_path=module_path,
                        local_name=(
                            node_text(alias_node, source)
                            if alias_node is not None
                            else None
                        ),
                    )
                )
        elif child.type == "scoped_identifier":
            name_node = child.child_by_field_name("name")
            if name_node is not None:
                out.append(
                    ImportRef(
                        name=node_text(name_node, source), module_path=module_path
                    )
                )
    return out


def _preceding_doc_comments(node: Node, source: bytes) -> str | None:
    """Extract Rust line/block doc comments attached across attributes."""
    prev = node.prev_named_sibling
    while prev is not None and prev.type == "attribute_item":
        prev = prev.prev_named_sibling
    if prev is None:
        return None
    lines: list[str] = []
    cur = prev
    while cur is not None and cur.type in {"line_comment", "block_comment"}:
        text = node_text(cur, source)
        if text.startswith("///") or text.startswith("//!"):
            lines.append(text[3:].strip())
        elif (text.startswith("/**") or text.startswith("/*!")) and text.endswith("*/"):
            body = text[3:-2]
            cleaned = []
            for line in body.splitlines():
                value = line.strip()
                if value.startswith("*"):
                    value = value[1:].strip()
                cleaned.append(value)
            lines.append("\n".join(cleaned).strip())
        else:
            break
        cur = cur.prev_named_sibling
    if not lines:
        return None
    lines.reverse()
    return "\n".join(lines)
