"""C and C++ language parsers.

C and C++ share the same tree-sitter grammar family (``c`` / ``cpp``) with very
similar node shapes.  A common base handles the shared extraction logic and the
subclasses differ in grammar, extensions, and C++ specific constructs (classes,
namespaces, templates).
"""

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
    EDGE_INHERITS,
    NODE_CLASS,
    NODE_ENUM,
    NODE_FIELD,
    NODE_FUNCTION,
    NODE_METHOD,
    NODE_NAMESPACE,
    NODE_PROPERTY,
    NODE_STRUCT,
    NODE_VARIABLE,
)

if TYPE_CHECKING:
    from tree_sitter import Node


class CFamilyParser(TreeSitterParser):
    """Shared C/C++ extraction logic."""

    def classify(
        self, node: Node, source: bytes, *, inside_class: bool
    ) -> Definition | None:
        ntype = node.type
        if ntype == "namespace_definition":
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                name = node_text(name_node, source).replace("::", ".")
                return Definition(kind=NODE_NAMESPACE, name=name)
        # struct/union/enum definitions (with a name)
        elif ntype in ("struct_specifier", "union_specifier"):
            name = self._specifier_name(node, source)
            if name and self._has_body(node):
                return Definition(kind=NODE_STRUCT, name=name, is_class=True)
        elif ntype == "enum_specifier":
            name = self._specifier_name(node, source)
            if name and self._has_body(node):
                return Definition(kind=NODE_ENUM, name=name, is_class=True)
        elif ntype == "class_specifier":
            # C++ only
            name = self._specifier_name(node, source)
            if name:
                return Definition(kind=NODE_CLASS, name=name, is_class=True)
        elif ntype == "function_definition":
            name = self._function_name(node, source)
            if name:
                scope = self._function_scope(node, source)
                kind = (
                    NODE_METHOD
                    if inside_class or (scope and _looks_like_class_scope(scope))
                    else NODE_FUNCTION
                )
                return Definition(
                    kind=kind,
                    name=name,
                    prefix=self._absolute_scope_prefix(node, source, scope),
                )
        elif ntype in ("declaration", "field_declaration"):
            # Forward declarations, prototypes, and pure virtual methods.
            name = self._declaration_func_name(node, source)
            if name:
                scope = self._function_scope(node, source)
                kind = (
                    NODE_METHOD
                    if inside_class or (scope and _looks_like_class_scope(scope))
                    else NODE_FUNCTION
                )
                return Definition(
                    kind=kind,
                    name=name,
                    prefix=self._absolute_scope_prefix(node, source, scope),
                )
        elif ntype == "enumerator" and inside_class:
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                return Definition(kind=NODE_PROPERTY, name=node_text(name_node, source))
        elif ntype in {"field_identifier", "identifier"}:
            owner = self._declaration_for_name(node)
            if owner is not None and not _contains_node_type(
                owner.child_by_field_name("declarator"), "function_declarator"
            ):
                if inside_class:
                    return Definition(kind=NODE_FIELD, name=node_text(node, source))
                if not inside_class and self._is_file_scope_declaration(owner):
                    return Definition(kind=NODE_VARIABLE, name=node_text(node, source))
        elif ntype == "type_definition":
            # Named struct/union/enum typedefs are represented by their
            # underlying specifier so fields and enumerators remain owned by
            # the body instead of a duplicate nested alias node.
            type_node = node.child_by_field_name("type")
            if (
                type_node is not None
                and type_node.type
                in {"struct_specifier", "union_specifier", "enum_specifier"}
                and self._specifier_name(type_node, source)
            ):
                return None
            # Anonymous aggregate or primitive typedef.
            name = self._typedef_name(node, source)
            if name:
                is_aggregate = bool(
                    type_node is not None
                    and type_node.type
                    in {"struct_specifier", "union_specifier", "enum_specifier"}
                )
                kind = (
                    NODE_ENUM
                    if type_node is not None and type_node.type == "enum_specifier"
                    else NODE_STRUCT
                    if is_aggregate
                    else NODE_CLASS
                )
                return Definition(kind=kind, name=name, is_class=is_aggregate)
        return None

    def call_target(self, node: Node, source: bytes) -> str | None:
        if node.type == "call_expression":
            func = node.child_by_field_name("function")
            if func is not None:
                return self._callee_name(func, source)
        elif node.type == "new_expression":
            type_node = node.child_by_field_name("type")
            if type_node is not None:
                return _simple_c_type_name(type_node, source)
        return None

    def _callee_name(self, func: Node, source: bytes) -> str | None:
        if func.type == "identifier":
            return node_text(func, source)
        if func.type == "field_expression":
            argument = func.child_by_field_name("argument")
            field = func.child_by_field_name("field")
            if field is not None:
                receiver = (
                    self._callee_name(argument, source)
                    if argument is not None
                    else None
                )
                name = node_text(field, source)
                return f"{receiver}.{name}" if receiver else name
        if func.type == "call_expression":
            nested = func.child_by_field_name("function")
            return self._callee_name(nested, source) if nested is not None else None
        if func.type == "qualified_identifier":
            return node_text(func, source).replace("::", ".")
        if func.type == "template_function":
            name_node = func.child_by_field_name("name")
            if name_node is not None:
                return node_text(name_node, source)
        return None

    def supertypes(self, node: Node, source: bytes) -> list[SuperType]:
        if node.type != "class_specifier":
            return []
        out: list[SuperType] = []
        for child in node.children:
            if child.type == "base_class_clause":
                for sub in child.children:
                    if sub.type == "type_identifier":
                        out.append(
                            SuperType(
                                name=node_text(sub, source), edge_kind=EDGE_INHERITS
                            )
                        )
                    elif sub.type == "qualified_identifier":
                        name = _qualified_c_name(sub, source)
                        if name:
                            out.append(
                                SuperType(
                                    name=name,
                                    edge_kind=EDGE_INHERITS,
                                )
                            )
        return out

    def decorators(self, node: Node, source: bytes) -> list[str]:
        owner = self._definition_owner(node)
        out: list[str] = []
        for child in owner.children:
            if child.type in {
                "attribute_declaration",
                "attribute_specifier",
                "ms_declspec_modifier",
            }:
                _collect_c_attr_names(child, source, out)
        return out

    def type_refs(self, node: Node, source: bytes) -> list[str]:
        owner = node
        if node.type in {"field_identifier", "identifier"}:
            declaration = self._declaration_for_name(node)
            if declaration is not None:
                owner = declaration
        if owner.type not in {
            "function_definition",
            "declaration",
            "field_declaration",
            "type_definition",
        }:
            return []
        out: list[str] = []
        type_node = owner.child_by_field_name("type")
        if type_node is not None:
            _collect_c_type_ids(type_node, source, out)
        decl = owner.child_by_field_name("declarator")
        if decl is not None:
            _collect_c_param_types(decl, source, out)
        return list(dict.fromkeys(out))

    def docstring(self, node: Node, source: bytes) -> str | None:
        return _preceding_comment(self._definition_owner(node), source)

    def import_refs(self, node: Node, source: bytes) -> list[ImportRef]:
        if node.type != "preproc_include":
            return []
        path_node = node.child_by_field_name("path")
        if path_node is None:
            return []
        if path_node.type not in {"system_lib_string", "string_literal"}:
            return []
        literal = node_text(path_node, source)
        raw = literal[1:-1]
        if not raw:
            return []
        name = raw.rpartition("/")[2] or raw
        return [ImportRef(name=name, module_path=raw)]

    # -- helpers ------------------------------------------------------------

    def _specifier_name(self, node: Node, source: bytes) -> str | None:
        name_node = node.child_by_field_name("name")
        return node_text(name_node, source) if name_node is not None else None

    def _has_body(self, node: Node) -> bool:
        return node.child_by_field_name("body") is not None

    def _function_name(self, node: Node, source: bytes) -> str | None:
        decl = node.child_by_field_name("declarator")
        if decl is None:
            return None
        return self._declarator_name(decl, source)

    def _function_scope(self, node: Node, source: bytes) -> str | None:
        decl = node.child_by_field_name("declarator")
        while decl is not None:
            if decl.type == "qualified_identifier":
                parts = _qualified_identifier_parts(decl, source)
                return ".".join(parts[:-1]) or None
            decl = decl.child_by_field_name("declarator")
        return None

    def _absolute_scope_prefix(
        self, node: Node, source: bytes, scope: str | None
    ) -> str | None:
        if not scope:
            return None
        namespaces: list[str] = []
        ancestor = node.parent
        while ancestor is not None:
            if ancestor.type == "namespace_definition":
                name = ancestor.child_by_field_name("name")
                if name is not None:
                    namespaces.append(node_text(name, source).replace("::", "."))
            ancestor = ancestor.parent
        namespaces.reverse()
        return ".".join([*namespaces, scope]) + "."

    def _declarator_name(self, node: Node, source: bytes) -> str | None:
        """Recursively extract the identifier from a declarator chain."""
        if node.type == "identifier":
            return node_text(node, source)
        if node.type == "field_identifier":
            return node_text(node, source)
        # function_declarator, pointer_declarator, reference_declarator, etc.
        inner = node.child_by_field_name("declarator")
        if inner is not None:
            return self._declarator_name(inner, source)
        # destructor_name: ~Foo
        if node.type == "destructor_name":
            return node_text(node, source)
        # qualified_identifier: Namespace::func
        if node.type == "qualified_identifier":
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                return self._declarator_name(name_node, source)
        # template_function
        if node.type == "template_function":
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                return node_text(name_node, source)
        # operator overloads: operator==
        if node.type == "operator_name":
            return node_text(node, source)
        return None

    def _declaration_func_name(self, node: Node, source: bytes) -> str | None:
        """Extract function name from a forward declaration inside a class."""
        decl = node.child_by_field_name("declarator")
        if decl is None:
            return None
        # Only match function_declarator patterns
        if decl.type == "function_declarator":
            return self._declarator_name(decl, source)
        return None

    def _typedef_name(self, node: Node, source: bytes) -> str | None:
        decl = node.child_by_field_name("declarator")
        name = _declarator_name_node(decl) if decl is not None else None
        return node_text(name, source) if name is not None else None

    def _declaration_for_name(self, node: Node) -> Node | None:
        ancestor = node.parent
        while ancestor is not None and ancestor.type not in {
            "declaration",
            "field_declaration",
        }:
            ancestor = ancestor.parent
        if ancestor is None:
            return None
        for index, declarator in enumerate(ancestor.children):
            if ancestor.field_name_for_child(index) != "declarator":
                continue
            name_node = _declarator_name_node(declarator)
            if _same_node(name_node, node):
                return ancestor
        return None

    def _definition_owner(self, node: Node) -> Node:
        parent = node.parent
        if (
            node.type in {"struct_specifier", "union_specifier", "enum_specifier"}
            and parent is not None
            and parent.type == "type_definition"
        ):
            return parent
        if node.type in {"field_identifier", "identifier"}:
            declaration = self._declaration_for_name(node)
            if declaration is not None:
                return declaration
        return node

    def _is_file_scope_declaration(self, node: Node) -> bool:
        parent = node.parent
        while parent is not None and parent.type in {
            "declaration_list",
            "linkage_specification",
        }:
            parent = parent.parent
        return bool(
            parent is not None
            and parent.type in {"translation_unit", "namespace_definition"}
        )


def _same_node(left: Node | None, right: Node) -> bool:
    return bool(
        left is not None
        and left.start_byte == right.start_byte
        and left.end_byte == right.end_byte
    )


def _declarator_name_node(node: Node) -> Node | None:
    if node.type in {"identifier", "field_identifier", "type_identifier"}:
        return node
    for child in node.named_children:
        found = _declarator_name_node(child)
        if found is not None:
            return found
    return None


def _contains_node_type(node: Node | None, node_type: str) -> bool:
    if node is None:
        return False
    if node.type == node_type:
        return True
    return any(_contains_node_type(child, node_type) for child in node.children)


def _looks_like_class_scope(scope: str) -> bool:
    leaf = scope.split(".")[-1]
    return bool(leaf and leaf[0].isupper())


def _qualified_c_name(node: Node, source: bytes) -> str | None:
    if node.type == "qualified_identifier":
        parts = _qualified_identifier_parts(node, source)
        return ".".join(parts) if parts else None
    return _simple_c_type_name(node, source)


def _qualified_identifier_parts(node: Node, source: bytes) -> list[str]:
    scope = node.child_by_field_name("scope")
    name = node.child_by_field_name("name")
    parts = [node_text(scope, source)] if scope is not None else []
    if name is not None and name.type == "qualified_identifier":
        parts.extend(_qualified_identifier_parts(name, source))
    elif name is not None:
        local_name = _simple_c_type_name(name, source)
        if local_name:
            parts.append(local_name)
    return parts


def _simple_c_type_name(node: Node, source: bytes) -> str | None:
    if node.type in {"identifier", "type_identifier"}:
        return node_text(node, source)
    if node.type in {
        "qualified_identifier",
        "template_type",
        "template_function",
        "struct_specifier",
        "union_specifier",
        "enum_specifier",
    }:
        name = node.child_by_field_name("name")
        return _simple_c_type_name(name, source) if name is not None else None
    return None


class CParser(CFamilyParser):
    name: ClassVar[str] = "c"
    extensions: ClassVar[tuple[str, ...]] = (".c", ".h")
    grammar: ClassVar[str] = "c"


class CppParser(CFamilyParser):
    name: ClassVar[str] = "cpp"
    extensions: ClassVar[tuple[str, ...]] = (
        ".cpp",
        ".hpp",
        ".cc",
        ".cxx",
        ".hxx",
        ".hh",
    )
    grammar: ClassVar[str] = "cpp"


_C_BUILTIN_TYPES = frozenset(
    {
        "bool",
        "char",
        "double",
        "float",
        "int",
        "long",
        "short",
        "unsigned",
        "signed",
        "void",
        "wchar_t",
        "char8_t",
        "char16_t",
        "char32_t",
        "size_t",
        "ptrdiff_t",
        "nullptr_t",
        "auto",
    }
)


def _collect_c_attr_names(node: Node, source: bytes, out: list[str]) -> None:
    """Extract attribute names from an attribute_declaration/specifier node."""
    for child in node.children:
        if child.type == "attribute":
            # [[attr]] or [[namespace::attr]]
            name_node = child.child_by_field_name("name")
            if name_node is not None:
                out.append(node_text(name_node, source))
        elif node.type == "ms_declspec_modifier" and child.type == "identifier":
            out.append(node_text(child, source))
        elif child.type == "argument_list":
            # __attribute__((attr, ...))
            for arg in child.children:
                if arg.type == "identifier":
                    out.append(node_text(arg, source))
                elif arg.type == "call_expression":
                    func = arg.child_by_field_name("function")
                    if func is not None:
                        name = _simple_c_type_name(func, source)
                        if name:
                            out.append(name)


def _collect_c_param_types(node: Node, source: bytes, out: list[str]) -> None:
    """Collect type identifiers from function parameters."""
    if node.type == "parameter_declaration":
        type_node = node.child_by_field_name("type")
        if type_node is not None:
            _collect_c_type_ids(type_node, source, out)
    for child in node.children:
        _collect_c_param_types(child, source, out)


def _collect_c_type_ids(node: Node, source: bytes, out: list[str]) -> None:
    if node.type in {"identifier", "type_identifier"}:
        name = node_text(node, source)
        if name not in _C_BUILTIN_TYPES:
            out.append(name)
        return
    if node.type in {"struct_specifier", "union_specifier", "enum_specifier"}:
        name = node.child_by_field_name("name")
        if name is not None:
            _collect_c_type_ids(name, source, out)
        return
    for child in node.children:
        _collect_c_type_ids(child, source, out)


def _preceding_comment(node: Node, source: bytes) -> str | None:
    """Extract C-style doc comment (/** ... */ or /// lines) preceding a node."""
    prev = node.prev_named_sibling
    if prev is None or prev.type != "comment":
        return None
    text = node_text(prev, source)
    # Block comment (/** ... */)
    if text.startswith("/*"):
        s = text[2:]
        if s.endswith("*/"):
            s = s[:-2]
        lines = [ln.strip().lstrip("* ").strip() for ln in s.split("\n")]
        return "\n".join(ln for ln in lines if ln) or None
    # Line comments (// or ///)
    lines: list[str] = []
    cur: Node | None = prev
    while cur is not None and cur.type == "comment":
        lines.append(node_text(cur, source))
        cur = cur.prev_named_sibling
    lines.reverse()
    cleaned = [ln.lstrip("/").strip() for ln in lines]
    return "\n".join(ln for ln in cleaned if ln) or None
