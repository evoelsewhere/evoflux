"""C and C++ language parsers.

C and C++ share the same tree-sitter grammar family (``c`` / ``cpp``) with very
similar node shapes.  A common base handles the shared extraction logic and the
subclasses differ in grammar, extensions, and C++ specific constructs (classes,
namespaces, templates).
"""

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
    NODE_ENUM,
    NODE_FUNCTION,
    NODE_METHOD,
    NODE_NAMESPACE,
    NODE_STRUCT,
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
                return Definition(kind=NODE_NAMESPACE, name=name, is_class=False)
        # struct/union/enum definitions (with a name)
        elif ntype in ("struct_specifier", "union_specifier"):
            name = self._specifier_name(node, source)
            if name and self._has_body(node):
                return Definition(kind=NODE_STRUCT, name=name, is_class=True)
        elif ntype == "enum_specifier":
            name = self._specifier_name(node, source)
            if name and self._has_body(node):
                return Definition(kind=NODE_ENUM, name=name, is_class=False)
        elif ntype == "class_specifier":
            # C++ only
            name = self._specifier_name(node, source)
            if name:
                return Definition(kind=NODE_CLASS, name=name, is_class=True)
        elif ntype == "function_definition":
            name = self._function_name(node, source)
            if name:
                kind = NODE_METHOD if inside_class else NODE_FUNCTION
                return Definition(kind=kind, name=name, is_class=False)
        elif ntype in ("declaration", "field_declaration") and inside_class:
            # Forward-declared or pure virtual methods in class body
            name = self._declaration_func_name(node, source)
            if name:
                return Definition(kind=NODE_METHOD, name=name, is_class=False)
        elif ntype == "type_definition":
            # typedef struct { ... } Name;
            name = self._typedef_name(node, source)
            if name:
                return Definition(kind=NODE_CLASS, name=name, is_class=False)
        return None

    def call_target(self, node: Node, source: bytes) -> str | None:
        if node.type != "call_expression":
            return None
        func = node.child_by_field_name("function")
        if func is None:
            return None
        return self._callee_name(func, source)

    def _callee_name(self, func: Node, source: bytes) -> str | None:
        if func.type == "identifier":
            return node_text(func, source)
        if func.type == "field_expression":
            field = func.child_by_field_name("field")
            if field is not None:
                return node_text(field, source)
        if func.type == "qualified_identifier":
            name_node = func.child_by_field_name("name")
            if name_node is not None:
                return self._callee_name(name_node, source)
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
                        name_node = sub.child_by_field_name("name")
                        if name_node is not None:
                            out.append(
                                SuperType(
                                    name=node_text(name_node, source),
                                    edge_kind=EDGE_INHERITS,
                                )
                            )
        return out

    def decorators(self, node: Node, source: bytes) -> list[str]:
        out: list[str] = []
        for child in node.children:
            if child.type == "attribute_declaration":
                # C++ [[attr]] or C11 _Alignas etc.
                _collect_c_attr_names(child, source, out)
            elif child.type == "attribute_specifier":
                # __attribute__((attr))
                _collect_c_attr_names(child, source, out)
            elif child.type == "ms_declspec_modifier":
                # __declspec(attr)
                _collect_c_attr_names(child, source, out)
        # Also check preceding siblings (e.g. __attribute__ before function)
        prev = node.prev_named_sibling
        while prev is not None:
            if prev.type in ("attribute_declaration", "attribute_specifier"):
                _collect_c_attr_names(prev, source, out)
            elif prev.type not in ("comment",):
                break
            prev = prev.prev_named_sibling
        return out

    def type_refs(self, node: Node, source: bytes) -> list[str]:
        if node.type not in {"function_definition", "declaration", "field_declaration"}:
            return []
        out: list[str] = []
        # Return type: the type node before the declarator
        for child in node.children:
            if child.type in {"primitive_type", "sized_type_specifier"}:
                continue
            if child.type == "struct_specifier":
                name = self._specifier_name(child, source)
                if name:
                    out.append(name)
            elif child.type == "enum_specifier":
                name = self._specifier_name(child, source)
                if name:
                    out.append(name)
            elif child.type in {"type_identifier", "qualified_identifier"}:
                name = node_text(child, source)
                if name not in _C_BUILTIN_TYPES:
                    out.append(name)
        # Parameter types from function_declarator
        decl = node.child_by_field_name("declarator")
        if decl is not None:
            _collect_c_param_types(decl, source, out)
        return out

    def docstring(self, node: Node, source: bytes) -> str | None:
        return _preceding_comment(node, source)

    def import_refs(self, node: Node, source: bytes) -> list[ImportRef]:
        if node.type != "preproc_include":
            return []
        path_node = node.child_by_field_name("path")
        if path_node is None:
            return []
        if path_node.type == "system_lib_string":
            # <vector> — strip the surrounding angle brackets
            raw = node_text(path_node, source).strip("<>")
        elif path_node.type == "string_literal":
            content = next(
                (c for c in path_node.children if c.type == "string_content"), None
            )
            if content is None:
                return []
            raw = node_text(content, source)
        else:
            return []
        if not raw:
            return []
        name = raw.rsplit("/", 1)[-1]
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
        if decl is not None and decl.type == "type_identifier":
            return node_text(decl, source)
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
            else:
                for sub in child.children:
                    if sub.type == "identifier":
                        out.append(node_text(sub, source))
                        break
        elif child.type == "argument_list":
            # __attribute__((attr, ...))
            for arg in child.children:
                if arg.type == "identifier":
                    out.append(node_text(arg, source))
                elif arg.type == "call_expression":
                    func = arg.child_by_field_name("function")
                    if func is not None and func.type == "identifier":
                        out.append(node_text(func, source))


def _collect_c_param_types(node: Node, source: bytes, out: list[str]) -> None:
    """Collect type identifiers from function parameters."""
    if node.type == "function_declarator":
        params = node.child_by_field_name("parameters")
        if params is not None:
            for param in params.children:
                if param.type == "parameter_declaration":
                    for child in param.children:
                        if child.type == "type_identifier":
                            name = node_text(child, source)
                            if name not in _C_BUILTIN_TYPES:
                                out.append(name)
                        elif child.type == "struct_specifier":
                            name_node = child.child_by_field_name("name")
                            if name_node is not None:
                                out.append(node_text(name_node, source))
                        elif child.type == "qualified_identifier":
                            name = node_text(child, source)
                            if name not in _C_BUILTIN_TYPES:
                                out.append(name)
        # Recurse into nested declarators
        for child in node.children:
            _collect_c_param_types(child, source, out)
    elif node.type in (
        "pointer_declarator",
        "reference_declarator",
        "parenthesized_declarator",
        "array_declarator",
    ):
        for child in node.children:
            _collect_c_param_types(child, source, out)


def _preceding_comment(node: Node, source: bytes) -> str | None:
    """Extract C-style doc comment (/** ... */ or /// lines) preceding a node."""
    prev = node.prev_named_sibling
    if prev is None or prev.type != "comment":
        return None
    text = node_text(prev, source)
    # Block comment (/** ... */)
    if text.startswith("/*"):
        s = text
        if s.startswith("/**"):
            s = s[3:]
        elif s.startswith("/*"):
            s = s[2:]
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
