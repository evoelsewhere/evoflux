"""JavaScript / TypeScript / TSX parsers.

The three grammars share node shapes, so a common base handles extraction and
the subclasses only differ in ``grammar`` and ``extensions``.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar

from app.services.code_index.parsers.base import (
    _MAX_SIGNATURE_LEN,
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
    NODE_VARIABLE,
)
from app.services.code_index.parsers.symbol_leaves import (
    ecmascript_leaf_definition,
)

if TYPE_CHECKING:
    from tree_sitter import Node

_FUNCTION_VALUE_TYPES = {"arrow_function", "function", "function_expression"}


class EcmaScriptParser(TreeSitterParser):
    """Shared JS/TS extraction logic."""

    def classify(
        self, node: Node, source: bytes, *, inside_class: bool
    ) -> Definition | None:
        leaf = ecmascript_leaf_definition(node, source)
        if leaf is not None:
            return leaf
        ntype = node.type
        if ntype == "internal_module":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_NAMESPACE, name=name)
        elif ntype in {"class_declaration", "abstract_class_declaration"}:
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_CLASS, name=name, is_class=True)
        elif ntype == "interface_declaration":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_INTERFACE, name=name)
        elif ntype == "type_alias_declaration":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_CLASS, name=name)
        elif ntype == "enum_declaration":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_ENUM, name=name, is_class=True)
        elif ntype in {
            "function_declaration",
            "generator_function_declaration",
            "function_signature",
        }:
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_FUNCTION, name=name)
        elif ntype == "method_definition":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_METHOD, name=name)
        elif ntype == "pair":
            # Object-literal property holding a function value, e.g.
            # `{ bar: function() {}, baz: () => {} }`. Unlike shorthand
            # methods (`foo() {}`, parsed as method_definition), these carry
            # no method_definition node of their own.
            value = node.child_by_field_name("value")
            if value is not None and value.type in _FUNCTION_VALUE_TYPES:
                key = node.child_by_field_name("key")
                name = self._property_name(key, source) if key is not None else None
                if name:
                    return Definition(kind=NODE_METHOD, name=name)
        elif ntype == "assignment_expression":
            # Prototype/instance method assignment, e.g.
            # `Obj.prototype.foo = function() {}` or `this.foo = () => {}`.
            left = node.child_by_field_name("left")
            right = node.child_by_field_name("right")
            if (
                left is not None
                and right is not None
                and left.type == "member_expression"
                and right.type in _FUNCTION_VALUE_TYPES
            ):
                prop = left.child_by_field_name("property")
                if prop is not None and prop.type == "property_identifier":
                    owner = left.child_by_field_name("object")
                    owner_name = (
                        _static_value_name(owner, source) if owner is not None else None
                    )
                    if owner_name and owner_name.endswith(".prototype"):
                        owner_name = owner_name.removesuffix(".prototype")
                    elif owner_name == "this":
                        owner_name = _enclosing_class_name(node, source)
                    return Definition(
                        kind=NODE_METHOD,
                        name=node_text(prop, source),
                        prefix=f"{owner_name}." if owner_name else None,
                    )
        elif ntype == "variable_declarator":
            value = node.child_by_field_name("value")
            if value is not None and (
                value.type in _FUNCTION_VALUE_TYPES
                or (
                    value.type == "call_expression"
                    and self._call_has_function_argument(value)
                )
            ):
                name_node = node.child_by_field_name("name")
                if name_node is not None and name_node.type == "identifier":
                    return Definition(
                        kind=NODE_FUNCTION,
                        name=node_text(name_node, source),
                    )
            elif not inside_class and self._is_top_level_var(node):
                name_node = node.child_by_field_name("name")
                if name_node is not None and name_node.type == "identifier":
                    return Definition(
                        kind=NODE_VARIABLE,
                        name=node_text(name_node, source),
                    )
        return None

    def _call_has_function_argument(self, call: Node) -> bool:
        """Recognize functions wrapped by any higher-order call.

        This covers memoized callbacks, decorators, and factory wrappers
        structurally, without a framework-specific hook-name list.
        """
        arguments = call.child_by_field_name("arguments")
        return bool(
            arguments
            and any(
                child.type in _FUNCTION_VALUE_TYPES
                for child in arguments.named_children
            )
        )

    def call_target(self, node: Node, source: bytes) -> str | None:
        if node.type == "call_expression":
            func = node.child_by_field_name("function")
            return self._callee_name(func, source) if func is not None else None
        if node.type == "new_expression":
            cons = node.child_by_field_name("constructor")
            return self._callee_name(cons, source) if cons is not None else None
        return None

    def reference_targets(self, node: Node, source: bytes) -> list[str]:
        """Capture named callbacks passed to APIs and JSX event properties.

        These are references rather than direct calls: a callee or framework
        controls when they run. This connects event, promise, subscription,
        timer, and React flows without any framework-specific name list.
        """
        if node.type == "call_expression":
            arguments = node.child_by_field_name("arguments")
            if arguments is None:
                return []
            return [
                name
                for child in arguments.named_children
                if (name := _static_value_name(child, source)) is not None
            ]
        if node.type == "jsx_attribute":
            value = next(
                (
                    child
                    for child in node.named_children
                    if child.type == "jsx_expression"
                ),
                None,
            )
            if value is None:
                return []
            return [
                name
                for child in value.named_children
                if (name := _static_value_name(child, source)) is not None
            ]
        if node.type in {"jsx_opening_element", "jsx_self_closing_element"}:
            component = next(
                (
                    child
                    for child in node.named_children
                    if child.type in {"identifier", "member_expression"}
                ),
                None,
            )
            if component is None:
                return []
            name = _static_value_name(component, source)
            return [name] if name is not None else []
        return []

    def supertypes(self, node: Node, source: bytes) -> list[SuperType]:
        out: list[SuperType] = []
        for child in node.children:
            if child.type == "class_heritage":
                out.extend(self._heritage(child, source))
            elif child.type == "extends_type_clause":
                # interface ... extends A, B
                for ident in child.children:
                    name = self._type_name(ident, source)
                    if name:
                        out.append(SuperType(name=name, edge_kind=EDGE_INHERITS))
        return out

    def _heritage(self, heritage: Node, source: bytes) -> list[SuperType]:
        out: list[SuperType] = []
        direct_edge_kind: str | None = None
        for clause in heritage.children:
            if clause.type == "extends_clause":
                for ident in clause.children:
                    name = self._type_name(ident, source)
                    if name:
                        out.append(SuperType(name=name, edge_kind=EDGE_INHERITS))
            elif clause.type == "implements_clause":
                for ident in clause.children:
                    name = self._type_name(ident, source)
                    if name:
                        out.append(SuperType(name=name, edge_kind=EDGE_IMPLEMENTS))
            elif clause.type == "extends":
                # The JavaScript grammar puts the keyword and identifier
                # directly under class_heritage instead of an extends_clause.
                direct_edge_kind = EDGE_INHERITS
            elif direct_edge_kind is not None:
                name = self._type_name(clause, source)
                if name:
                    out.append(SuperType(name=name, edge_kind=direct_edge_kind))
        return out

    def _type_name(self, node: Node, source: bytes) -> str | None:
        if node.type in {"identifier", "type_identifier"}:
            return node_text(node, source)
        if node.type in {"nested_type_identifier", "generic_type"}:
            name = node.child_by_field_name("name")
            if name is not None:
                return node_text(name, source)
        if node.type == "member_expression":
            prop = node.child_by_field_name("property")
            return node_text(prop, source) if prop is not None else None
        return None

    def _callee_name(self, func: Node, source: bytes) -> str | None:
        static_name = _static_value_name(func, source)
        if static_name is not None:
            return static_name
        if func.type != "member_expression":
            return None
        prop = func.child_by_field_name("property")
        return node_text(prop, source) if prop is not None else None

    def import_refs(self, node: Node, source: bytes) -> list[ImportRef]:
        if node.type == "export_statement":
            return self._export_refs(node, source)
        if node.type == "call_expression":
            return self._dynamic_import_ref(node, source)
        if node.type != "import_statement":
            return []
        source_node = node.child_by_field_name("source")
        if source_node is None:
            return []
        module_path = _string_content(source_node, source)
        if not module_path:
            return []
        out: list[ImportRef] = []
        for child in node.children:
            if child.type == "import_clause":
                out.extend(self._import_clause_names(child, source, module_path))
        return out or [
            ImportRef(name=_module_ref_name(module_path), module_path=module_path)
        ]

    def _export_refs(self, node: Node, source: bytes) -> list[ImportRef]:
        source_node = node.child_by_field_name("source")
        if source_node is None:
            return []
        module_path = _string_content(source_node, source)
        if not module_path:
            return []

        out: list[ImportRef] = []
        for descendant in _named_descendants(node):
            if descendant.type != "export_specifier":
                continue
            name_node = descendant.child_by_field_name("name")
            if name_node is None:
                continue
            alias_node = descendant.child_by_field_name("alias")
            out.append(
                ImportRef(
                    name=node_text(name_node, source),
                    module_path=module_path,
                    local_name=(
                        node_text(alias_node, source)
                        if alias_node is not None
                        else None
                    ),
                )
            )
        return out or [ImportRef(name="*", module_path=module_path)]

    def _dynamic_import_ref(self, node: Node, source: bytes) -> list[ImportRef]:
        function = node.child_by_field_name("function")
        if function is None or function.type != "import":
            return []
        arguments = node.child_by_field_name("arguments")
        if arguments is None:
            return []
        specifier = next(
            (child for child in arguments.named_children if child.type == "string"),
            None,
        )
        if specifier is None:
            return []
        module_path = _string_content(specifier, source)
        return (
            [ImportRef(name=_module_ref_name(module_path), module_path=module_path)]
            if module_path
            else []
        )

    def _import_clause_names(
        self, clause: Node, source: bytes, module_path: str
    ) -> list[ImportRef]:
        out: list[ImportRef] = []
        for child in clause.children:
            if child.type == "identifier":
                # Default import
                out.append(
                    ImportRef(name=node_text(child, source), module_path=module_path)
                )
            elif child.type == "named_imports":
                for spec in child.children:
                    if spec.type == "import_specifier":
                        name_node = spec.child_by_field_name("name")
                        if name_node is not None:
                            alias_node = spec.child_by_field_name("alias")
                            out.append(
                                ImportRef(
                                    name=node_text(name_node, source),
                                    module_path=module_path,
                                    local_name=(
                                        node_text(alias_node, source)
                                        if alias_node is not None
                                        else None
                                    ),
                                )
                            )
            elif child.type == "namespace_import":
                # import * as name → use last identifier
                for sub in child.children:
                    if sub.type == "identifier":
                        out.append(
                            ImportRef(
                                name=node_text(sub, source), module_path=module_path
                            )
                        )
        return out

    def _name(self, node: Node, source: bytes) -> str | None:
        name = node.child_by_field_name("name")
        return node_text(name, source) if name is not None else None

    def _property_name(self, key: Node, source: bytes) -> str | None:
        """Extract a static name from an object-literal property key.

        Handles ``{ foo: ... }`` and ``{ "foo": ... }``; computed keys
        (``{ [expr]: ... }``) have no static name and are skipped.
        """
        if key.type == "property_identifier":
            return node_text(key, source)
        if key.type == "string":
            return _string_content(key, source)
        return None

    def _is_top_level_var(self, node: Node) -> bool:
        """Check if a variable_declarator is at module/program level."""
        # Parent chain: variable_declarator → lexical_declaration/variable_declaration
        # → program/export_statement
        parent = node.parent
        if parent is None:
            return False
        grandparent = parent.parent
        if grandparent is None:
            return False
        return grandparent.type in {
            "program",
            "export_statement",
            "module",
        }

    def decorators(self, node: Node, source: bytes) -> list[str]:
        out: list[str] = []
        # Class-level decorators are direct children of class_declaration
        for child in node.children:
            if child.type == "decorator":
                name = _decorator_name(child, source)
                if name:
                    out.append(name)
        # Method-level decorators are preceding siblings in class_body
        if not out:
            prev = node.prev_named_sibling
            while prev is not None and prev.type == "decorator":
                name = _decorator_name(prev, source)
                if name:
                    out.insert(0, name)
                prev = prev.prev_named_sibling
        return out

    def _signature(self, node: Node, source: bytes) -> str:
        decorators = [child for child in node.children if child.type == "decorator"]
        if not decorators:
            return super()._signature(node, source)
        start = max(child.end_byte for child in decorators)
        first = source[start : node.end_byte].decode(errors="replace")
        first = first.lstrip().partition("\n")[0].strip()
        if len(first) > _MAX_SIGNATURE_LEN:
            first = first[:_MAX_SIGNATURE_LEN].rstrip() + "…"
        return first

    def docstring(self, node: Node, source: bytes) -> str | None:
        return _leading_jsdoc(node, source)

    def type_refs(self, node: Node, source: bytes) -> list[str]:
        if node.type == "type_alias_declaration":
            value = node.child_by_field_name("value")
            if value is None:
                return []
            out: list[str] = []
            _collect_ts_type_ids(value, source, out)
            return list(dict.fromkeys(out))
        if node.type not in {
            "function_declaration",
            "generator_function_declaration",
            "function_signature",
            "method_definition",
            "method_signature",
            "abstract_method_signature",
            "property_signature",
            "public_field_definition",
            "variable_declarator",
        }:
            return []
        out: list[str] = []
        # Parameter type annotations
        params = node.child_by_field_name("parameters")
        if params is not None:
            for param in params.children:
                if param.type in {"required_parameter", "optional_parameter"}:
                    for child in param.children:
                        if child.type == "type_annotation":
                            _collect_ts_type_ids(child, source, out)
        # Return/field annotation is a direct child across the three grammars.
        for child in node.children:
            if child.type == "type_annotation" and child != params:
                _collect_ts_type_ids(child, source, out)
                break
        return list(dict.fromkeys(out))


def _string_content(node: Node, source: bytes) -> str:
    """Extract the text content of a string node, stripping quotes."""
    text = node_text(node, source)
    is_quote = text[:1] in {"'", '"'}
    if len(text) >= 2 and text[0] == text[-1] and is_quote:
        return text[1:-1]
    return text


def _static_value_name(node: Node, source: bytes) -> str | None:
    """Return a statically named identifier/member chain used as a value."""
    if node.type in {"identifier", "this"}:
        return node_text(node, source)
    if node.type != "member_expression":
        return None
    obj = node.child_by_field_name("object")
    prop = node.child_by_field_name("property")
    if obj is None:
        return None
    if prop is None:
        return None
    owner = _static_value_name(obj, source)
    if owner is None:
        return None
    return f"{owner}.{node_text(prop, source)}"


def _enclosing_class_name(node: Node, source: bytes) -> str | None:
    ancestor = node.parent
    while ancestor is not None:
        if ancestor.type in {"class_declaration", "abstract_class_declaration"}:
            name = ancestor.child_by_field_name("name")
            return node_text(name, source) if name is not None else None
        ancestor = ancestor.parent
    return None


def _leading_jsdoc(node: Node, source: bytes) -> str | None:
    """Return the contiguous leading JSDoc attached to a declaration."""
    owner = node
    if node.parent is not None and node.parent.type == "export_statement":
        owner = node.parent
    comment = owner.prev_named_sibling
    while comment is not None and comment.type == "decorator":
        comment = comment.prev_named_sibling
    if comment is None or comment.type != "comment":
        return None
    raw = node_text(comment, source).strip()
    if not raw.startswith("/**") or not raw.endswith("*/"):
        return None
    lines = []
    for line in raw[3:-2].splitlines():
        cleaned = line.strip()
        if cleaned.startswith("*"):
            cleaned = cleaned[1:].strip()
        lines.append(cleaned)
    return "\n".join(lines).strip() or None


def _module_ref_name(module_path: str) -> str:
    tail = PurePosixPath(module_path).name
    for suffix in (".d.ts", ".tsx", ".ts", ".jsx", ".js", ".mjs", ".cjs"):
        if tail.endswith(suffix):
            return tail[: -len(suffix)]
    return tail or module_path


def _named_descendants(node: Node):
    for child in node.named_children:
        yield child
        yield from _named_descendants(child)


def _decorator_name(node: Node, source: bytes) -> str | None:
    """Extract the decorator name from a TS/JS decorator node (@foo, @foo(...))."""
    for child in node.children:
        if child.type == "identifier":
            return node_text(child, source)
        if child.type == "member_expression":
            return node_text(child, source)
        if child.type == "call_expression":
            func = child.child_by_field_name("function")
            if func is not None:
                if func.type == "identifier":
                    return node_text(func, source)
                if func.type == "member_expression":
                    return node_text(func, source)
    return None


# Primitive/builtin types to skip in TS/JS.
_TS_BUILTIN_TYPES = frozenset(
    {
        "string",
        "number",
        "boolean",
        "void",
        "null",
        "undefined",
        "never",
        "any",
        "unknown",
        "object",
        "symbol",
        "bigint",
    }
)


def _collect_ts_type_ids(node: Node, source: bytes, out: list[str]) -> None:
    """Recursively collect user-defined type identifiers from a TS type node."""
    if node.type == "type_identifier":
        name = node_text(node, source)
        if name not in _TS_BUILTIN_TYPES:
            out.append(name)
        return
    for child in node.children:
        _collect_ts_type_ids(child, source, out)


class JavaScriptParser(EcmaScriptParser):
    name: ClassVar[str] = "javascript"
    extensions: ClassVar[tuple[str, ...]] = (".js", ".jsx", ".mjs", ".cjs")
    grammar: ClassVar[str] = "javascript"


class TypeScriptParser(EcmaScriptParser):
    name: ClassVar[str] = "typescript"
    extensions: ClassVar[tuple[str, ...]] = (".ts", ".mts", ".cts")
    grammar: ClassVar[str] = "typescript"


class TsxParser(EcmaScriptParser):
    name: ClassVar[str] = "tsx"
    extensions: ClassVar[tuple[str, ...]] = (".tsx",)
    grammar: ClassVar[str] = "tsx"
