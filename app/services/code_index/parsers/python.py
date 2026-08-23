"""Python language parser."""

from __future__ import annotations

import ast
import inspect
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
    NODE_FIELD,
    NODE_FUNCTION,
    NODE_METHOD,
    NODE_VARIABLE,
)

if TYPE_CHECKING:
    from tree_sitter import Node


_BUILTIN_CALLS = frozenset(
    {
        "all",
        "any",
        "bool",
        "bytes",
        "dict",
        "enumerate",
        "float",
        "format",
        "frozenset",
        "getattr",
        "hasattr",
        "int",
        "isinstance",
        "issubclass",
        "iter",
        "len",
        "list",
        "max",
        "min",
        "next",
        "open",
        "print",
        "range",
        "repr",
        "reversed",
        "set",
        "setattr",
        "sorted",
        "str",
        "sum",
        "super",
        "tuple",
        "type",
        "zip",
    }
)


class PythonParser(TreeSitterParser):
    name: ClassVar[str] = "python"
    extensions: ClassVar[tuple[str, ...]] = (".py", ".pyi")
    grammar: ClassVar[str] = "python"

    def classify(
        self, node: Node, source: bytes, *, inside_class: bool
    ) -> Definition | None:
        if node.type == "class_definition":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_CLASS, name=name, is_class=True)
        elif node.type == "function_definition":
            name = self._name(node, source)
            if name:
                kind = NODE_METHOD if inside_class else NODE_FUNCTION
                return Definition(kind=kind, name=name)
        elif node.type == "assignment":
            return (
                self._class_level_assignment(node, source)
                if inside_class
                else self._module_level_assignment(node, source)
            )
        return None

    def call_target(self, node: Node, source: bytes) -> str | None:
        if node.type != "call":
            return None
        func = node.child_by_field_name("function")
        if func is None:
            return None
        if func.type == "identifier":
            target = node_text(func, source)
            return None if target in _BUILTIN_CALLS else target
        if func.type == "attribute":
            attr = func.child_by_field_name("attribute")
            if attr is None:
                return None
            qualified = _qualified_value_name(func, source)
            return qualified or node_text(attr, source)
        return None

    def reference_targets(self, node: Node, source: bytes) -> list[str]:
        """Capture named callables passed through dispatch boundaries.

        Python frequently invokes work indirectly (for example
        ``asyncio.to_thread(module.fn, ...)`` or ``executor.submit(fn)``). The
        callback is not the syntax tree's callee, but it is still a structural
        dependency that code navigation must retain.
        """
        if node.type != "call":
            return []
        arguments = node.child_by_field_name("arguments")
        if arguments is None:
            return []
        targets: list[str] = []
        for child in arguments.named_children:
            candidate = child
            if child.type == "keyword_argument":
                candidate = child.child_by_field_name("value") or child
            name = _qualified_value_name(candidate, source)
            if name is not None and name not in _BUILTIN_CALLS:
                targets.append(name)
        return targets

    def supertypes(self, node: Node, source: bytes) -> list[SuperType]:
        supers = node.child_by_field_name("superclasses")
        if supers is None:
            return []
        out: list[SuperType] = []
        for child in supers.children:
            name = _python_type_name(child, source)
            if name is not None:
                out.append(SuperType(name=name, edge_kind=EDGE_INHERITS))
        return out

    def docstring(self, node: Node, source: bytes) -> str | None:
        body = node.child_by_field_name("body")
        if body is None:
            return None
        first = next(iter(body.children), None)
        if first is None or first.type != "string":
            return None
        return _strip_py_string(node_text(first, source))

    def _name(self, node: Node, source: bytes) -> str | None:
        name = node.child_by_field_name("name")
        return node_text(name, source) if name is not None else None

    def decorators(self, node: Node, source: bytes) -> list[str]:
        # In Python, decorators live on the parent `decorated_definition` node
        parent = node.parent
        if parent is None or parent.type != "decorated_definition":
            return []
        out: list[str] = []
        for child in parent.children:
            if child.type == "decorator":
                name = _decorator_name(child, source)
                if name:
                    out.append(name)
        return out

    def type_refs(self, node: Node, source: bytes) -> list[str]:
        if node.type == "assignment":
            type_node = node.child_by_field_name("type")
            if type_node is None:
                return []
            out: list[str] = []
            _collect_type_identifiers(type_node, source, out)
            return list(dict.fromkeys(out))
        if node.type != "function_definition":
            return []
        out: list[str] = []
        # Parameter type annotations
        params = node.child_by_field_name("parameters")
        if params is not None:
            for param in params.children:
                if param.type in {"typed_parameter", "typed_default_parameter"}:
                    type_node = param.child_by_field_name("type")
                    if type_node is not None:
                        _collect_type_identifiers(type_node, source, out)
        # Return type annotation
        ret = node.child_by_field_name("return_type")
        if ret is not None:
            _collect_type_identifiers(ret, source, out)
        return list(dict.fromkeys(out))

    def _class_level_assignment(
        self, node: Node, source: bytes
    ) -> Definition | None:
        parent = node.parent
        if parent is None or parent.type != "block":
            return None
        if parent.parent is None or parent.parent.type != "class_definition":
            return None
        left = node.child_by_field_name("left")
        if left is None:
            return None
        if left.type != "identifier":
            return None
        name = node_text(left, source)
        if name.startswith("__") and name.endswith("__"):
            return None
        return Definition(kind=NODE_FIELD, name=name)

    def _module_level_assignment(self, node: Node, source: bytes) -> Definition | None:
        """Capture `NAME = value` at module level (not inside functions)."""
        parent = node.parent
        if parent is None or parent.type != "module":
            return None
        # LHS must be a simple identifier (not self.x, not tuple unpacking)
        left = node.child_by_field_name("left")
        if left is None:
            return None
        if left.type != "identifier":
            return None
        name = node_text(left, source)
        # Skip dunder assignments and private internals
        if name.startswith("__") and name.endswith("__"):
            return None
        return Definition(kind=NODE_VARIABLE, name=name)

    def import_refs(self, node: Node, source: bytes) -> list[ImportRef]:
        ntype = node.type
        if ntype == "import_from_statement":
            return self._from_import(node, source)
        if ntype == "import_statement":
            return self._bare_import(node, source)
        return []

    def _from_import(self, node: Node, source: bytes) -> list[ImportRef]:
        """Parse `from <module> import name1, name2 [as alias]`."""
        module_node = node.child_by_field_name("module_name")
        if module_node is None:
            return []
        module_path = node_text(module_node, source)
        out: list[ImportRef] = []
        for child in node.named_children:
            if child.end_byte <= module_node.end_byte:
                continue
            if child.type == "dotted_name":
                out.append(
                    ImportRef(name=node_text(child, source), module_path=module_path)
                )
            elif child.type == "aliased_import":
                name_node = child.child_by_field_name("name")
                if name_node is not None:
                    alias_node = child.child_by_field_name("alias")
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
        return out

    def _bare_import(self, node: Node, source: bytes) -> list[ImportRef]:
        """Parse `import os` or `import os.path`."""
        out: list[ImportRef] = []
        for child in node.children:
            if child.type == "dotted_name":
                text = node_text(child, source)
                # Use last component as the name, full path as module
                parts = text.split(".")
                out.append(ImportRef(name=parts[-1], module_path=text))
            elif child.type == "aliased_import":
                name_node = child.child_by_field_name("name")
                if name_node is not None:
                    text = node_text(name_node, source)
                    parts = text.split(".")
                    alias_node = child.child_by_field_name("alias")
                    out.append(
                        ImportRef(
                            name=parts[-1],
                            module_path=text,
                            local_name=(
                                node_text(alias_node, source)
                                if alias_node is not None
                                else None
                            ),
                        )
                    )
        return out


def _strip_py_string(text: str) -> str | None:
    """Return Python's semantic string value, normalized like a docstring."""
    try:
        value = ast.literal_eval(text)
    except (SyntaxError, ValueError):
        return None
    if not isinstance(value, str):
        return None
    return inspect.cleandoc(value)


def _python_type_name(node: Node, source: bytes) -> str | None:
    if node.type == "identifier":
        return node_text(node, source)
    if node.type == "attribute":
        attr = node.child_by_field_name("attribute")
        return node_text(attr, source) if attr is not None else None
    if node.type == "subscript":
        value = node.child_by_field_name("value")
        return _python_type_name(value, source) if value is not None else None
    return None


def _qualified_value_name(node: Node, source: bytes) -> str | None:
    """Return an identifier/attribute chain used as a first-class value."""
    if node.type == "identifier":
        return node_text(node, source)
    if node.type == "call":
        function = node.child_by_field_name("function")
        if (
            function is not None
            and function.type == "identifier"
            and node_text(function, source) == "super"
        ):
            return "super"
        return None
    if node.type != "attribute":
        return None
    obj = node.child_by_field_name("object")
    attr = node.child_by_field_name("attribute")
    if obj is None or attr is None:
        return None
    prefix = _qualified_value_name(obj, source)
    if prefix is None:
        return None
    return f"{prefix}.{node_text(attr, source)}"


def _decorator_name(node: Node, source: bytes) -> str | None:
    """Extract the decorator name from a decorator node.

    Handles: @foo, @foo.bar, @foo(...), @foo.bar(...)
    """
    for child in node.children:
        if child.type == "identifier":
            return node_text(child, source)
        if child.type == "attribute":
            # Use the full dotted name
            return node_text(child, source)
        if child.type == "call":
            func = child.child_by_field_name("function")
            if func is not None:
                if func.type == "identifier":
                    return node_text(func, source)
                if func.type == "attribute":
                    return node_text(func, source)
    return None


# Builtins/primitives we don't want to emit as type references.
_PY_BUILTIN_TYPES = frozenset(
    {
        "int",
        "float",
        "str",
        "bytes",
        "bool",
        "None",
        "object",
        "list",
        "dict",
        "set",
        "tuple",
        "frozenset",
        "type",
        "Any",
        "Self",
    }
)


def _collect_type_identifiers(node: Node, source: bytes, out: list[str]) -> None:
    """Recursively collect user-defined type identifiers from a type node."""
    if node.type == "identifier":
        name = node_text(node, source)
        if name not in _PY_BUILTIN_TYPES:
            out.append(name)
        return
    if node.type == "attribute":
        # e.g. module.Type — use last segment
        attr = node.child_by_field_name("attribute")
        if attr is not None:
            name = node_text(attr, source)
            if name not in _PY_BUILTIN_TYPES:
                out.append(name)
        return
    # Recurse into generic_type, union_type, type, etc.
    for child in node.children:
        _collect_type_identifiers(child, source, out)
