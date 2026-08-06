"""JavaScript / TypeScript / TSX parsers.

The three grammars share node shapes, so a common base handles extraction and
the subclasses only differ in ``grammar`` and ``extensions``.
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
    EDGE_IMPLEMENTS,
    EDGE_INHERITS,
    NODE_CLASS,
    NODE_FUNCTION,
    NODE_INTERFACE,
    NODE_METHOD,
    NODE_NAMESPACE,
    NODE_VARIABLE,
)

if TYPE_CHECKING:
    from tree_sitter import Node

_FUNCTION_VALUE_TYPES = {"arrow_function", "function", "function_expression"}


class EcmaScriptParser(TreeSitterParser):
    """Shared JS/TS extraction logic."""

    def classify(
        self, node: Node, source: bytes, *, inside_class: bool
    ) -> Definition | None:
        ntype = node.type
        if ntype == "internal_module":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_NAMESPACE, name=name, is_class=False)
        elif ntype in {"class_declaration", "abstract_class_declaration"}:
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_CLASS, name=name, is_class=True)
        elif ntype == "interface_declaration":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_INTERFACE, name=name, is_class=False)
        elif ntype == "type_alias_declaration":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_CLASS, name=name, is_class=False)
        elif ntype == "enum_declaration":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_CLASS, name=name, is_class=True)
        elif ntype in {
            "function_declaration",
            "generator_function_declaration",
            "function_signature",
        }:
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_FUNCTION, name=name, is_class=False)
        elif ntype == "method_definition":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_METHOD, name=name, is_class=False)
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
                    return Definition(kind=NODE_METHOD, name=name, is_class=False)
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
                    return Definition(
                        kind=NODE_METHOD,
                        name=node_text(prop, source),
                        is_class=False,
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
                        is_class=False,
                    )
            elif not inside_class and self._is_top_level_var(node):
                name_node = node.child_by_field_name("name")
                if name_node is not None and name_node.type == "identifier":
                    return Definition(
                        kind=NODE_VARIABLE,
                        name=node_text(name_node, source),
                        is_class=False,
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
                and (body := child.child_by_field_name("body")) is not None
                and body.type == "statement_block"
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
                node_text(child, source)
                for child in arguments.named_children
                if child.type == "identifier"
            ]
        if node.type == "jsx_attribute":
            value = node.child_by_field_name("value") or next(
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
                node_text(child, source)
                for child in value.named_children
                if child.type == "identifier"
            ]
        if node.type in {"jsx_opening_element", "jsx_self_closing_element"}:
            component = next(
                (child for child in node.named_children if child.type == "identifier"),
                None,
            )
            return [node_text(component, source)] if component is not None else []
        return []

    def supertypes(self, node: Node, source: bytes) -> list[SuperType]:
        out: list[SuperType] = []
        for child in node.children:
            if child.type == "class_heritage":
                out.extend(self._heritage(child, source))
            elif child.type == "extends_type_clause":
                # interface ... extends A, B
                for ident in child.children:
                    if ident.type in {"type_identifier", "identifier"}:
                        out.append(
                            SuperType(
                                name=node_text(ident, source), edge_kind=EDGE_INHERITS
                            )
                        )
        return out

    def _heritage(self, heritage: Node, source: bytes) -> list[SuperType]:
        out: list[SuperType] = []
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
        return out

    def _type_name(self, node: Node, source: bytes) -> str | None:
        if node.type in {"identifier", "type_identifier"}:
            return node_text(node, source)
        if node.type == "member_expression":
            prop = node.child_by_field_name("property")
            return node_text(prop, source) if prop is not None else None
        return None

    def _callee_name(self, func: Node, source: bytes) -> str | None:
        if func.type == "identifier":
            return node_text(func, source)
        if func.type == "member_expression":
            obj = func.child_by_field_name("object")
            prop = func.child_by_field_name("property")
            if prop is None:
                return None
            prop_name = node_text(prop, source)
            # Emit "Object.method" for qualified resolution
            if obj is not None and obj.type == "identifier":
                return f"{node_text(obj, source)}.{prop_name}"
            return prop_name
        return None

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

    def type_refs(self, node: Node, source: bytes) -> list[str]:
        if node.type not in {
            "function_declaration",
            "generator_function_declaration",
            "function_signature",
            "method_definition",
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
        # Return type annotation (direct child type_annotation)
        ret = node.child_by_field_name("return_type")
        if ret is not None:
            _collect_ts_type_ids(ret, source, out)
        else:
            # Some grammars put it as a direct child
            for child in node.children:
                if child.type == "type_annotation" and child != params:
                    _collect_ts_type_ids(child, source, out)
                    break
        return out


def _string_content(node: Node, source: bytes) -> str:
    """Extract the text content of a string node, stripping quotes."""
    for child in node.children:
        if child.type == "string_fragment":
            return node_text(child, source)
    # Fallback: strip quotes manually
    text = node_text(node, source)
    return text.strip("'\"")


def _module_ref_name(module_path: str) -> str:
    tail = module_path.rstrip("/").rsplit("/", 1)[-1]
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
    if (
        node.type == "identifier"
        and node.parent
        and node.parent.type
        in {
            "type_annotation",
            "generic_type",
        }
    ):
        name = node_text(node, source)
        if name not in _TS_BUILTIN_TYPES:
            out.append(name)
        return
    # Don't descend into value expressions
    if node.type in {"call_expression", "arrow_function", "function"}:
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
