"""Ruby language parser."""

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
    NODE_FUNCTION,
    NODE_METHOD,
    NODE_MODULE,
)

if TYPE_CHECKING:
    from tree_sitter import Node


class RubyParser(TreeSitterParser):
    name: ClassVar[str] = "ruby"
    extensions: ClassVar[tuple[str, ...]] = (".rb",)
    grammar: ClassVar[str] = "ruby"

    def classify(
        self, node: Node, source: bytes, *, inside_class: bool
    ) -> Definition | None:
        ntype = node.type
        if ntype == "class":
            name = self._class_name(node, source)
            if name:
                return Definition(kind=NODE_CLASS, name=name, is_class=True)
        elif ntype == "module":
            name = self._module_name(node, source)
            if name:
                return Definition(kind=NODE_MODULE, name=name, is_class=True)
        elif ntype == "method":
            name = node.child_by_field_name("name")
            if name is not None:
                kind = NODE_METHOD if inside_class else NODE_FUNCTION
                return Definition(
                    kind=kind, name=node_text(name, source), is_class=False
                )
        elif ntype == "singleton_method":
            name = node.child_by_field_name("name")
            if name is not None:
                return Definition(
                    kind=NODE_METHOD, name=node_text(name, source), is_class=False
                )
        return None

    def call_target(self, node: Node, source: bytes) -> str | None:
        if node.type == "call":
            method = node.child_by_field_name("method")
            if method is not None:
                return node_text(method, source)
        elif node.type == "method_call":
            method = node.child_by_field_name("method")
            if method is not None:
                return node_text(method, source)
        return None

    def synthetic_definitions(
        self, node: Node, source: bytes, *, inside_class: bool
    ) -> list[Definition]:
        if (
            node.type != "call"
            or not inside_class
            or node.child_by_field_name("receiver") is not None
        ):
            return []
        method = node.child_by_field_name("method")
        arguments = node.child_by_field_name("arguments")
        if method is None or arguments is None:
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
                    Definition(kind=NODE_METHOD, name=name, is_class=False)
                )
            if macro != "attr_reader":
                definitions.append(
                    Definition(kind=NODE_METHOD, name=f"{name}=", is_class=False)
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
            content = next(
                (c for c in arg.children if c.type == "string_content"), None
            )
            if content is None:
                continue
            module_path = node_text(content, source)
            name = module_path.rsplit("/", 1)[-1]
            out.append(ImportRef(name=name, module_path=module_path))
        return out

    def supertypes(self, node: Node, source: bytes) -> list[SuperType]:
        if node.type != "class":
            return []
        sup = node.child_by_field_name("superclass")
        if sup is None:
            return []
        # superclass node contains '< ClassName'
        for child in sup.children:
            if child.type == "constant":
                return [
                    SuperType(name=node_text(child, source), edge_kind=EDGE_INHERITS)
                ]
            if child.type == "scope_resolution":
                for sub in reversed(child.children):
                    if sub.type == "constant":
                        return [
                            SuperType(
                                name=node_text(sub, source), edge_kind=EDGE_INHERITS
                            )
                        ]
        return []

    def decorators(self, node: Node, source: bytes) -> list[str]:
        out: list[str] = []
        if node.type == "method":
            prev = node.prev_named_sibling
            while prev is not None:
                if prev.type == "call":
                    method = prev.child_by_field_name("method")
                    if method is not None:
                        name = node_text(method, source)
                        if name in _RUBY_MODIFIER_KEYWORDS:
                            out.append(name)
                elif prev.type == "identifier":
                    name = node_text(prev, source)
                    if name in _RUBY_MODIFIER_KEYWORDS:
                        out.append(name)
                elif prev.type not in ("comment", "empty_statement"):
                    break
                prev = prev.prev_named_sibling
        return out

    def type_refs(self, node: Node, source: bytes) -> list[str]:
        if node.type != "method":
            return []
        out: list[str] = []
        # Look for Sorbet sig block: sig { params(x: Type).returns(Type) }
        prev = node.prev_named_sibling
        while prev is not None:
            if prev.type == "call":
                method = prev.child_by_field_name("method")
                if method is not None and node_text(method, source) == "sig":
                    _collect_ruby_sig_types(prev, source, out)
                    break
            elif prev.type not in ("call", "comment", "empty_statement"):
                break
            prev = prev.prev_named_sibling
        return out

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

    def _class_name(self, node: Node, source: bytes) -> str | None:
        for child in node.children:
            if child.type == "constant":
                return node_text(child, source)
        return None

    def _module_name(self, node: Node, source: bytes) -> str | None:
        for child in node.children:
            if child.type == "constant":
                return node_text(child, source)
        return None


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

_RUBY_ATTRIBUTE_MACROS = frozenset(
    {"attr_reader", "attr_writer", "attr_accessor"}
)


def _ruby_static_attribute_name(node: Node, source: bytes) -> str | None:
    if node.type == "simple_symbol":
        return node_text(node, source).removeprefix(":")
    if node.type == "string":
        content = next(
            (child for child in node.children if child.type == "string_content"), None
        )
        if content is not None:
            return node_text(content, source)
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
    if node.type == "constant":
        return node_text(node, source)
    if node.type == "scope_resolution":
        for child in reversed(node.children):
            if child.type == "constant":
                return node_text(child, source)
    return None
