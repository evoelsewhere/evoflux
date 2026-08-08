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

if TYPE_CHECKING:
    from tree_sitter import Node


class RustParser(TreeSitterParser):
    name: ClassVar[str] = "rust"
    extensions: ClassVar[tuple[str, ...]] = (".rs",)
    grammar: ClassVar[str] = "rust"

    def classify(
        self, node: Node, source: bytes, *, inside_class: bool
    ) -> Definition | None:
        ntype = node.type
        if ntype == "mod_item":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_MODULE, name=name, is_class=False)
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
                return Definition(kind=NODE_CLASS, name=name, is_class=False)
        elif ntype == "function_item":
            name = self._name(node, source)
            if name:
                kind = NODE_METHOD if inside_class else NODE_FUNCTION
                return Definition(kind=kind, name=name, is_class=False)
        elif ntype == "function_signature_item":
            # Trait method declarations
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_METHOD, name=name, is_class=False)
        elif ntype == "const_item":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_VARIABLE, name=name, is_class=False)
        elif ntype == "static_item":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_VARIABLE, name=name, is_class=False)
        return None

    def call_target(self, node: Node, source: bytes) -> str | None:
        ntype = node.type
        if ntype == "call_expression":
            func = node.child_by_field_name("function")
            if func is None:
                return None
            if func.type == "identifier":
                return node_text(func, source)
            if func.type == "scoped_identifier":
                # Type::method() or module::func()
                path_node = func.child_by_field_name("path")
                name_node = func.child_by_field_name("name")
                if name_node is not None:
                    name = node_text(name_node, source)
                    if path_node is not None and path_node.type in (
                        "identifier",
                        "type_identifier",
                    ):
                        return f"{node_text(path_node, source)}.{name}"
                    return name
            if func.type == "field_expression":
                value = func.child_by_field_name("value")
                field = func.child_by_field_name("field")
                if field is None:
                    return None
                field_name = node_text(field, source)
                if value is not None and value.type == "identifier":
                    return f"{node_text(value, source)}.{field_name}"
                return field_name
        elif ntype == "macro_invocation":
            # println!(...), vec![...] — the macro name is the "macro" field
            macro = node.child_by_field_name("macro")
            if macro is not None:
                return node_text(macro, source)
        return None

    def supertypes(self, node: Node, source: bytes) -> list[SuperType]:
        if node.type != "impl_item":
            return []
        # `impl Trait for Type` — emit "Type implements Trait"
        # The trait is the first type_identifier before `for` keyword
        trait_name: str | None = None
        saw_for = False
        for child in node.children:
            if child.type == "for":
                saw_for = True
                continue
            if not saw_for and child.type in (
                "type_identifier",
                "scoped_type_identifier",
            ):
                trait_name = _type_name(child, source)
        if trait_name and saw_for:
            return [SuperType(name=trait_name, edge_kind=EDGE_IMPLEMENTS)]
        return []

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
                if name_node is not None:
                    module_path = node_text(path_node, source) if path_node else ""
                    out.append(
                        ImportRef(
                            name=node_text(name_node, source),
                            module_path=module_path,
                        )
                    )
            elif child.type == "scoped_use_list":
                # use crate::models::{User, Post};
                path_node = child.child_by_field_name("path")
                module_path = node_text(path_node, source) if path_node else ""
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
                out.append(name)
            prev = prev.prev_named_sibling
        return out

    def type_refs(self, node: Node, source: bytes) -> list[str]:
        if node.type not in {"function_item", "function_signature_item"}:
            return []
        out: list[str] = []
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
    if node.type == "scoped_type_identifier":
        name_node = node.child_by_field_name("name")
        if name_node is not None:
            name = node_text(name_node, source)
            if name not in _RUST_BUILTIN_TYPES:
                out.append(name)
        return
    if node.type == "generic_type":
        for child in node.children:
            _collect_rust_type_ids(child, source, out)
        return
    if node.type in {
        "function_type",
        "tuple_type",
        "array_type",
        "pointer_type",
        "reference_type",
        "optional_type",
        "never_type",
    }:
        for child in node.children:
            _collect_rust_type_ids(child, source, out)
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
    """Extract Rust /// or //! doc comments preceding a node."""
    prev = node.prev_named_sibling
    if prev is None:
        return None
    lines: list[str] = []
    cur = prev
    while cur is not None and cur.type == "line_comment":
        text = node_text(cur, source)
        if text.startswith("///") or text.startswith("//!"):
            lines.append(text[3:].strip())
        else:
            break
        cur = cur.prev_named_sibling
    if not lines:
        return None
    lines.reverse()
    return "\n".join(lines)
