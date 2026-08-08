"""C# language parser."""

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
    EDGE_INHERITS,
    NODE_CLASS,
    NODE_ENUM,
    NODE_FUNCTION,
    NODE_INTERFACE,
    NODE_METHOD,
    NODE_NAMESPACE,
    NODE_STRUCT,
)

if TYPE_CHECKING:
    from tree_sitter import Node


class CSharpParser(TreeSitterParser):
    name: ClassVar[str] = "csharp"
    extensions: ClassVar[tuple[str, ...]] = (".cs",)
    grammar: ClassVar[str] = "csharp"

    def root_prefix(self, root: Node, source: bytes) -> str:
        for child in root.children:
            if child.type == "file_scoped_namespace_declaration":
                name = child.child_by_field_name("name")
                if name is not None:
                    return f"{node_text(name, source)}."
        return ""

    def classify(
        self, node: Node, source: bytes, *, inside_class: bool
    ) -> Definition | None:
        ntype = node.type
        if ntype in {"namespace_declaration", "file_scoped_namespace_declaration"}:
            name = self._name(node, source)
            if name:
                return Definition(
                    kind=NODE_NAMESPACE,
                    name=name,
                    is_class=False,
                    prefix="" if ntype == "file_scoped_namespace_declaration" else None,
                )
        elif ntype == "class_declaration":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_CLASS, name=name, is_class=True)
        elif ntype == "interface_declaration":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_INTERFACE, name=name, is_class=True)
        elif ntype == "struct_declaration":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_STRUCT, name=name, is_class=True)
        elif ntype == "enum_declaration":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_ENUM, name=name, is_class=True)
        elif ntype == "record_declaration":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_CLASS, name=name, is_class=True)
        elif ntype == "method_declaration":
            name = self._name(node, source)
            if name:
                kind = NODE_METHOD if inside_class else NODE_FUNCTION
                return Definition(kind=kind, name=name, is_class=False)
        elif ntype == "constructor_declaration":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_METHOD, name=name, is_class=False)
        elif ntype == "property_declaration":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_METHOD, name=name, is_class=False)
        elif ntype == "local_function_statement":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_FUNCTION, name=name, is_class=False)
        elif ntype == "delegate_declaration":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_FUNCTION, name=name, is_class=False)
        return None

    def import_refs(self, node: Node, source: bytes) -> list[ImportRef]:
        if node.type != "using_directive":
            return []
        # Children (no useful "target" field, so dispatch positionally):
        # bare:    "using" [qualified_name|identifier] ";" (optionally
        #          preceded by "global")
        # alias:   "using" name=identifier "=" [qualified_name|identifier] ";"
        # static:  "using" "static" [qualified_name|identifier] ";"
        # Static usings ("using static System.Math;") import a type's members
        # directly; the type's simple name is still the closest local anchor.
        alias_node = node.child_by_field_name("name")
        target = next(
            (
                c
                for c in node.children
                if c.type in ("qualified_name", "identifier") and c != alias_node
            ),
            None,
        )
        if target is None:
            return []
        dotted = node_text(target, source)
        if alias_node is not None:
            return [
                ImportRef(
                    name=dotted.rsplit(".", 1)[-1],
                    module_path=dotted,
                    local_name=node_text(alias_node, source),
                )
            ]
        local_name = dotted.rsplit(".", 1)[-1]
        return [ImportRef(name=local_name, module_path=dotted)]

    def call_target(self, node: Node, source: bytes) -> str | None:
        if node.type == "invocation_expression":
            func = node.child_by_field_name("function")
            if func is None:
                return None
            if func.type == "identifier":
                return node_text(func, source)
            if func.type == "member_access_expression":
                name_node = func.child_by_field_name("name")
                if name_node is not None:
                    receiver = next(
                        (child for child in func.named_children if child != name_node),
                        None,
                    )
                    name = node_text(name_node, source)
                    if receiver is not None:
                        raw_receiver = node_text(receiver, source)
                        if raw_receiver in {"this", "base"}:
                            raw_receiver = "this"
                        return f"{raw_receiver}.{name}"
                    return name
        elif node.type == "object_creation_expression":
            type_node = node.child_by_field_name("type")
            if type_node is not None:
                return _simple_type_name(type_node, source)
        return None

    def uses_target(self, node: Node, source: bytes) -> str | None:
        if node.type != "field_declaration":
            return None

        attributes = set(self.decorators(node, source))
        modifiers = {
            node_text(child, source)
            for child in node.children
            if child.type == "modifier"
        }
        is_injected = bool(attributes.intersection(_INJECTION_ATTRIBUTES))
        if not is_injected and "readonly" not in modifiers:
            return None

        declaration = next(
            (child for child in node.children if child.type == "variable_declaration"),
            None,
        )
        if declaration is None:
            return None
        if not is_injected:
            declarators = (
                child
                for child in declaration.children
                if child.type == "variable_declarator"
            )
            if any(
                any(child.type != "identifier" for child in declarator.named_children)
                for declarator in declarators
            ):
                return None

        type_node = declaration.child_by_field_name("type")
        if type_node is None:
            return None
        names: list[str] = []
        _collect_csharp_type_ids(type_node, source, names)
        return names[0] if names else None

    def supertypes(self, node: Node, source: bytes) -> list[SuperType]:
        if node.type not in (
            "class_declaration",
            "interface_declaration",
            "struct_declaration",
            "record_declaration",
        ):
            return []
        out: list[SuperType] = []
        for child in node.children:
            if child.type == "base_list":
                is_interface_decl = node.type == "interface_declaration"
                for sub in child.children:
                    name = _simple_type_name(sub, source)
                    if name:
                        # In C#, the first item in base_list for a class is the
                        # base class (if it starts uppercase and isn't prefixed I).
                        # Heuristic: names starting with I followed by uppercase
                        # are likely interfaces.
                        if is_interface_decl:
                            edge = EDGE_INHERITS
                        elif _looks_like_interface(name):
                            edge = EDGE_IMPLEMENTS
                        else:
                            edge = EDGE_INHERITS
                        out.append(SuperType(name=name, edge_kind=edge))
        return out

    def docstring(self, node: Node, source: bytes) -> str | None:
        # C# uses XML doc comments (///) preceding declarations.
        prev = node.prev_named_sibling
        if prev is None:
            return None
        lines: list[str] = []
        cur = prev
        while cur is not None and cur.type == "comment":
            text = node_text(cur, source)
            if text.startswith("///"):
                lines.append(text[3:].strip())
            else:
                break
            cur = cur.prev_named_sibling
        if not lines:
            return None
        lines.reverse()
        # Strip XML tags for a cleaner summary.
        cleaned: list[str] = []
        for line in lines:
            stripped = _strip_xml_tags(line)
            if stripped:
                cleaned.append(stripped)
        return "\n".join(cleaned) if cleaned else None

    def decorators(self, node: Node, source: bytes) -> list[str]:
        out: list[str] = []
        for child in node.children:
            if child.type != "attribute_list":
                continue
            for attribute in child.children:
                if attribute.type != "attribute":
                    continue
                name_node = attribute.child_by_field_name("name")
                if name_node is not None:
                    name = _simple_type_name(name_node, source)
                    if name:
                        out.append(name)
        return out

    def type_refs(self, node: Node, source: bytes) -> list[str]:
        if node.type not in {
            "method_declaration",
            "constructor_declaration",
            "property_declaration",
            "delegate_declaration",
        }:
            return []

        out: list[str] = []
        return_type = node.child_by_field_name("returns")
        if return_type is None and node.type == "property_declaration":
            return_type = node.child_by_field_name("type")
        if return_type is not None:
            _collect_csharp_type_ids(return_type, source, out)

        parameters = node.child_by_field_name("parameters")
        if parameters is not None:
            for parameter in parameters.children:
                if parameter.type != "parameter":
                    continue
                type_node = parameter.child_by_field_name("type")
                if type_node is not None:
                    _collect_csharp_type_ids(type_node, source, out)
        return list(dict.fromkeys(out))

    def _name(self, node: Node, source: bytes) -> str | None:
        name_node = node.child_by_field_name("name")
        return node_text(name_node, source) if name_node is not None else None


def _simple_type_name(node: Node, source: bytes) -> str | None:
    """Extract a simple type name from a C# type node."""
    if node.type == "identifier":
        return node_text(node, source)
    if node.type == "generic_name":
        # generic_name → identifier + type_argument_list
        for child in node.children:
            if child.type == "identifier":
                return node_text(child, source)
        return None
    if node.type == "qualified_name":
        # Namespace.Type → Type
        right = node.child_by_field_name("right")
        return node_text(right, source) if right is not None else None
    return None


_INJECTION_ATTRIBUTES = frozenset({"Autowired", "Dependency", "FromServices", "Inject"})

_CSHARP_BUILTIN_TYPES = frozenset(
    {
        "bool",
        "byte",
        "char",
        "decimal",
        "double",
        "dynamic",
        "float",
        "int",
        "long",
        "nint",
        "nuint",
        "object",
        "sbyte",
        "short",
        "string",
        "uint",
        "ulong",
        "ushort",
        "void",
        "Boolean",
        "Byte",
        "Char",
        "Decimal",
        "Double",
        "Int16",
        "Int32",
        "Int64",
        "Object",
        "SByte",
        "Single",
        "String",
        "UInt16",
        "UInt32",
        "UInt64",
    }
)


def _collect_csharp_type_ids(node: Node, source: bytes, out: list[str]) -> None:
    if node.type == "predefined_type":
        return
    if node.type == "identifier":
        name = node_text(node, source)
        if name not in _CSHARP_BUILTIN_TYPES:
            out.append(name)
        return
    if node.type == "generic_name":
        for child in node.children:
            if child.type == "identifier":
                _collect_csharp_type_ids(child, source, out)
            elif child.type == "type_argument_list":
                _collect_csharp_type_ids(child, source, out)
        return
    if node.type == "qualified_name":
        right = node.child_by_field_name("right")
        if right is not None:
            _collect_csharp_type_ids(right, source, out)
        return
    for child in node.children:
        _collect_csharp_type_ids(child, source, out)


def _looks_like_interface(name: str) -> bool:
    """Heuristic: C# interfaces conventionally start with 'I' + uppercase."""
    return len(name) >= 2 and name[0] == "I" and name[1].isupper()


def _strip_xml_tags(text: str) -> str:
    """Remove XML tags from a doc comment line."""
    import re

    return re.sub(r"<[^>]+>", "", text).strip()
