"""Ruby language parser."""

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
    NODE_FUNCTION,
    NODE_METHOD,
    NODE_MODULE,
    NODE_PROPERTY,
    NODE_VARIABLE,
)

if TYPE_CHECKING:
    from tree_sitter import Node


class RubyParser(TreeSitterParser):
    name: ClassVar[str] = "ruby"
    extensions: ClassVar[tuple[str, ...]] = (".rb",)
    grammar: ClassVar[str] = "ruby"

    def identifier_reference_targets(self, node: Node, source: bytes) -> list[str]:
        # Ruby uses plain identifiers for declarations, modifier keywords,
        # macro DSLs, and calls. The shared fallback is overwhelmingly noisy;
        # explicit call/import/Sorbet/module hooks below are more trustworthy.
        return []

    def classify(
        self, node: Node, source: bytes, *, inside_class: bool
    ) -> Definition | None:
        ntype = node.type
        if ntype == "class":
            scoped_name = self._definition_name(node, source)
            if scoped_name:
                name, prefix = scoped_name
                return Definition(
                    kind=NODE_CLASS, name=name, is_class=True, prefix=prefix
                )
        elif ntype == "module":
            scoped_name = self._definition_name(node, source)
            if scoped_name:
                name, prefix = scoped_name
                return Definition(
                    kind=NODE_MODULE, name=name, is_class=True, prefix=prefix
                )
        elif ntype == "method":
            name = node.child_by_field_name("name")
            if name is not None:
                kind = NODE_METHOD if inside_class else NODE_FUNCTION
                return Definition(
                    kind=kind, name=node_text(name, source)
                )
        elif ntype == "singleton_method":
            name = node.child_by_field_name("name")
            if name is not None:
                return Definition(
                    kind=NODE_METHOD, name=node_text(name, source)
                )
        elif ntype == "assignment":
            left = node.child_by_field_name("left")
            name = _ruby_constant_path(left, source) if left is not None else None
            if name:
                owner, separator, local_name = name.rpartition(".")
                if not separator:
                    local_name = name
                kind = NODE_PROPERTY if inside_class else NODE_VARIABLE
                return Definition(
                    kind=kind,
                    name=local_name,
                    prefix=f"{owner}." if separator else None,
                )
        return None

    def call_target(self, node: Node, source: bytes) -> str | None:
        if node.type == "call":
            method = node.child_by_field_name("method")
            if method is not None:
                name = node_text(method, source)
                if name in _RUBY_NON_RUNTIME_CALLS:
                    return None
                receiver = node.child_by_field_name("receiver")
                receiver_path = (
                    _ruby_expression_path(receiver, source)
                    if receiver is not None
                    else None
                )
                return f"{receiver_path}.{name}" if receiver_path else name
        return None

    def reference_targets(self, node: Node, source: bytes) -> list[str]:
        if node.type != "call":
            return []
        method = node.child_by_field_name("method")
        if method is None or node_text(method, source) not in {
            "extend",
            "include",
            "prepend",
        }:
            return []
        arguments = node.child_by_field_name("arguments")
        if arguments is None:
            return []
        return [
            name
            for argument in arguments.named_children
            if (name := _ruby_constant_path(argument, source)) is not None
        ]

    def synthetic_definitions(
        self, node: Node, source: bytes, *, inside_class: bool
    ) -> list[Definition]:
        if node.type != "call":
            return []
        if not inside_class:
            return []
        if node.child_by_field_name("receiver") is not None:
            return []
        method = node.child_by_field_name("method")
        arguments = node.child_by_field_name("arguments")
        if method is None:
            return []
        if arguments is None:
            return []
        macro = node_text(method, source)
        if macro not in _RUBY_ATTRIBUTE_MACROS:
            return []

        definitions: list[Definition] = []
        for argument in arguments.named_children:
            name = _ruby_static_attribute_name(argument, source)
            if not name:
                continue
            if macro != "attr_writer":
                definitions.append(
                    Definition(kind=NODE_METHOD, name=name)
                )
            if macro != "attr_reader":
                definitions.append(
                    Definition(kind=NODE_METHOD, name=f"{name}=")
                )
        return definitions

    def import_refs(self, node: Node, source: bytes) -> list[ImportRef]:
        # Ruby has no dedicated import grammar node: `require`/`require_relative`
        # are ordinary method calls with one or more string-literal arguments.
        if node.type != "call":
            return []
        method = node.child_by_field_name("method")
        if method is None or node_text(method, source) not in (
            "require",
            "require_relative",
        ):
            return []
        args = node.child_by_field_name("arguments")
        if args is None:
            return []
        out: list[ImportRef] = []
        for arg in args.children:
            if arg.type != "string":
                continue
            module_path = _ruby_static_string(arg, source)
            if module_path is None:
                continue
            name = module_path.rpartition("/")[2] or module_path
            out.append(ImportRef(name=name, module_path=module_path))
        return out

    def supertypes(self, node: Node, source: bytes) -> list[SuperType]:
        if node.type != "class":
            return []
        sup = node.child_by_field_name("superclass")
        if sup is None:
            return []
        name = _ruby_constant_descendant(sup, source)
        return [SuperType(name=name, edge_kind=EDGE_INHERITS)] if name else []

    def decorators(self, node: Node, source: bytes) -> list[str]:
        out: list[str] = []
        if node.type == "method":
            prev = node.prev_named_sibling
            while prev is not None:
                if prev.type == "comment":
                    prev = prev.prev_named_sibling
                    continue
                name = _ruby_modifier_name(prev, source)
                if name is None:
                    break
                out.append(name)
                prev = prev.prev_named_sibling
        return out

    def type_refs(self, node: Node, source: bytes) -> list[str]:
        if node.type != "method":
            return []
        out: list[str] = []
        # Look for Sorbet sig block: sig { params(x: Type).returns(Type) }
        prev = node.prev_named_sibling
        while prev is not None:
            if prev.type == "comment":
                prev = prev.prev_named_sibling
                continue
            if _ruby_modifier_name(prev, source) is not None:
                prev = prev.prev_named_sibling
                continue
            if prev.type == "call" and _ruby_call_name(prev, source) == "sig":
                _collect_ruby_constant_types(prev, source, out)
                break
            break
        return list(dict.fromkeys(out))

    def docstring(self, node: Node, source: bytes) -> str | None:
        prev = node.prev_named_sibling
        if prev is not None and prev.type == "comment":
            lines: list[str] = []
            cur: Node | None = prev
            while cur is not None and cur.type == "comment":
                lines.append(node_text(cur, source))
                cur = cur.prev_named_sibling
            lines.reverse()
            cleaned = [ln.lstrip("#").strip() for ln in lines]
            return "\n".join(ln for ln in cleaned if ln) or None
        return None

    def _definition_name(
        self, node: Node, source: bytes
    ) -> tuple[str, str | None] | None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return None
        path = _ruby_constant_path(name_node, source)
        if not path:
            return None
        owner, separator, name = path.rpartition(".")
        return name, f"{owner}." if separator else None


_RUBY_MODIFIER_KEYWORDS = frozenset(
    {
        "private",
        "protected",
        "public",
        "private_class_method",
        "public_class_method",
        "module_function",
        "attr_reader",
        "attr_writer",
        "attr_accessor",
        "abstract",
        "final",
        "sealed",
        "override",
    }
)

_RUBY_ATTRIBUTE_MACROS = frozenset({"attr_reader", "attr_writer", "attr_accessor"})
_RUBY_NON_RUNTIME_CALLS = (
    _RUBY_ATTRIBUTE_MACROS
    | _RUBY_MODIFIER_KEYWORDS
    | frozenset(
        {
            "extend",
            "include",
            "params",
            "prepend",
            "require",
            "require_relative",
            "returns",
            "sig",
            "type_parameters",
        }
    )
)


def _ruby_call_name(node: Node, source: bytes) -> str | None:
    if node.type != "call":
        return None
    method = node.child_by_field_name("method")
    return node_text(method, source) if method is not None else None


def _ruby_modifier_name(node: Node, source: bytes) -> str | None:
    name = node_text(node, source) if node.type == "identifier" else None
    return name if name in _RUBY_MODIFIER_KEYWORDS else None


def _ruby_expression_path(node: Node, source: bytes) -> str | None:
    if node.type in {"constant", "scope_resolution"}:
        return _ruby_constant_path(node, source)
    if node.type == "identifier":
        return node_text(node, source)
    if node.type == "self":
        return "this"
    if node.type == "call":
        method = node.child_by_field_name("method")
        if method is None:
            return None
        receiver = node.child_by_field_name("receiver")
        receiver_path = (
            _ruby_expression_path(receiver, source) if receiver is not None else None
        )
        name = node_text(method, source)
        return f"{receiver_path}.{name}" if receiver_path else name
    return None


def _collect_ruby_constant_types(node: Node, source: bytes, out: list[str]) -> None:
    path = _ruby_constant_path(node, source)
    if path:
        parts = path.split(".")
        if parts[0] != "T" and parts[-1] not in {"TrueClass", "FalseClass"}:
            out.append(path)
        return
    for child in node.named_children:
        _collect_ruby_constant_types(child, source, out)


def _ruby_static_attribute_name(node: Node, source: bytes) -> str | None:
    if node.type == "simple_symbol":
        return node_text(node, source).removeprefix(":")
    if node.type == "string":
        return _ruby_static_string(node, source)
    return None


def _ruby_static_string(node: Node, source: bytes) -> str | None:
    if any(child.type != "string_content" for child in node.named_children):
        return None
    literal = node_text(node, source)
    return literal[1:-1]


def _ruby_constant_path(node: Node, source: bytes) -> str | None:
    if node.type not in {"constant", "scope_resolution"}:
        return None
    return node_text(node, source).removeprefix("::").replace("::", ".")


def _ruby_constant_descendant(node: Node, source: bytes) -> str | None:
    path = _ruby_constant_path(node, source)
    if path:
        return path
    for child in node.named_children:
        path = _ruby_constant_descendant(child, source)
        if path:
            return path
    return None


def _collect_ruby_sig_types(sig_node: Node, source: bytes, out: list[str]) -> None:
    """Extract type names from a Sorbet sig { ... } block."""
    for child in sig_node.children:
        if child.type == "call":
            _collect_ruby_sig_call_types(child, source, out)
            # Also check block (e.g. sig { ... })
            for sub in child.children:
                if sub.type == "call":
                    _collect_ruby_sig_call_types(sub, source, out)


def _collect_ruby_sig_call_types(
    call_node: Node, source: bytes, out: list[str]
) -> None:
    """Extract type names from params(x: Type).returns(Type) calls."""
    method = call_node.child_by_field_name("method")
    if method is None:
        return
    method_name = node_text(method, source)
    if method_name not in ("params", "returns", "type_parameters"):
        return
    args = call_node.child_by_field_name("arguments")
    if args is None:
        return
    for arg in args.children:
        if arg.type == "pair":
            # x: Type → value is the type
            value = arg.child_by_field_name("value")
            if value is not None and value.type in ("constant", "scope_resolution"):
                name = _ruby_type_name_from_node(value, source)
                if name:
                    out.append(name)
        elif arg.type in ("constant", "scope_resolution"):
            name = _ruby_type_name_from_node(arg, source)
            if name:
                out.append(name)


def _ruby_type_name_from_node(node: Node, source: bytes) -> str | None:
    return _ruby_constant_path(node, source)
