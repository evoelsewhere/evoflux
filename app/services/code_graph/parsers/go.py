"""Go language parser."""

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
    NODE_CLASS,
    NODE_FUNCTION,
    NODE_INTERFACE,
    NODE_METHOD,
    NODE_VARIABLE,
)

if TYPE_CHECKING:
    from tree_sitter import Node


class GoParser(TreeSitterParser):
    name: ClassVar[str] = "go"
    extensions: ClassVar[tuple[str, ...]] = (".go",)
    grammar: ClassVar[str] = "go"

    def classify(
        self, node: Node, source: bytes, *, inside_class: bool
    ) -> Definition | None:
        ntype = node.type
        if ntype == "type_declaration":
            # type_declaration → type_spec or type_alias
            spec = _first_child_of_type(node, "type_spec")
            if spec is not None:
                name = self._spec_name(spec, source)
                if not name:
                    return None
                body = spec.child_by_field_name("type")
                if body is not None and body.type == "interface_type":
                    return Definition(kind=NODE_INTERFACE, name=name, is_class=True)
                # struct_type, or other named types
                return Definition(kind=NODE_CLASS, name=name, is_class=True)
            # type alias: type Foo = ...
            alias = _first_child_of_type(node, "type_alias")
            if alias is not None:
                for child in alias.children:
                    if child.type == "type_identifier":
                        return Definition(
                            kind=NODE_CLASS,
                            name=node_text(child, source),
                            is_class=False,
                        )
            return None
        if ntype == "function_declaration":
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                return Definition(
                    kind=NODE_FUNCTION,
                    name=node_text(name_node, source),
                    is_class=False,
                )
        if ntype == "method_declaration":
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                receiver_type = self._receiver_type(node, source)
                prefix = f"{receiver_type}." if receiver_type else None
                return Definition(
                    kind=NODE_METHOD,
                    name=node_text(name_node, source),
                    is_class=False,
                    prefix=prefix,
                )
        if ntype in ("const_declaration", "var_declaration"):
            return self._var_or_const(node, source)
        return None

    def call_target(self, node: Node, source: bytes) -> str | None:
        if node.type != "call_expression":
            return None
        func = node.child_by_field_name("function")
        if func is None:
            return None
        if func.type == "identifier":
            return node_text(func, source)
        if func.type == "selector_expression":
            operand = func.child_by_field_name("operand")
            field = func.child_by_field_name("field")
            if field is None:
                return None
            field_name = node_text(field, source)
            # Emit "Package.Func" or "Type.Method" for qualified resolution
            if operand is not None and operand.type == "identifier":
                return f"{node_text(operand, source)}.{field_name}"
            return field_name
        return None

    def supertypes(self, node: Node, source: bytes) -> list[SuperType]:
        # Go doesn't have explicit inheritance. Interface embedding is the closest.
        # For interface types, extract embedded interfaces.
        if node.type != "type_declaration":
            return []
        spec = _first_child_of_type(node, "type_spec")
        if spec is None:
            return []
        body = spec.child_by_field_name("type")
        if body is None:
            return []
        out: list[SuperType] = []
        if body.type == "interface_type":
            for child in body.children:
                if child.type == "type_elem":
                    # Embedded interface: type_elem > type_identifier
                    for sub in child.children:
                        if sub.type == "type_identifier":
                            out.append(
                                SuperType(
                                    name=node_text(sub, source),
                                    edge_kind=EDGE_IMPLEMENTS,
                                )
                            )
                        elif sub.type == "qualified_type":
                            name_node = sub.child_by_field_name("name")
                            if name_node is not None:
                                out.append(
                                    SuperType(
                                        name=node_text(name_node, source),
                                        edge_kind=EDGE_IMPLEMENTS,
                                    )
                                )
        return out

    def docstring(self, node: Node, source: bytes) -> str | None:
        # Go uses comment blocks immediately preceding a declaration.
        # Walk backwards from the node's start to find adjacent comments.
        return _preceding_comment(node, source)

    def type_refs(self, node: Node, source: bytes) -> list[str]:
        if node.type not in {"function_declaration", "method_declaration"}:
            return []
        out: list[str] = []
        # Parameters
        params = node.child_by_field_name("parameters")
        if params is not None:
            _collect_go_type_ids(params, source, out)
        # Result type(s)
        result = node.child_by_field_name("result")
        if result is not None:
            _collect_go_type_ids(result, source, out)
        return out

    def _spec_name(self, spec: Node, source: bytes) -> str | None:
        name_node = spec.child_by_field_name("name")
        if name_node is not None:
            return node_text(name_node, source)
        # Fallback: first type_identifier child
        for child in spec.children:
            if child.type == "type_identifier":
                return node_text(child, source)
        return None

    def _receiver_type(self, node: Node, source: bytes) -> str | None:
        """Extract the receiver type name from a method_declaration."""
        receiver = node.child_by_field_name("receiver")
        if receiver is None:
            return None
        # receiver is a parameter_list: (name *Type) or (name Type)
        for param in receiver.children:
            if param.type == "parameter_declaration":
                type_node = param.child_by_field_name("type")
                if type_node is not None:
                    return _go_type_name(type_node, source)
        return None

    def _var_or_const(self, node: Node, source: bytes) -> Definition | None:
        """Capture package-level var/const declarations (single-spec only)."""
        # Only capture if parent is source_file (package level)
        if node.parent is None or node.parent.type != "source_file":
            return None
        # Look for single spec with a name
        for child in node.children:
            if child.type in ("const_spec", "var_spec"):
                name_node = child.child_by_field_name("name")
                if name_node is not None:
                    return Definition(
                        kind=NODE_VARIABLE,
                        name=node_text(name_node, source),
                        is_class=False,
                    )
        return None

    def import_refs(self, node: Node, source: bytes) -> list[ImportRef]:
        if node.type != "import_declaration":
            return []
        out: list[ImportRef] = []
        for child in node.children:
            if child.type == "import_spec":
                out.extend(self._import_spec(child, source))
            elif child.type == "import_spec_list":
                for spec in child.children:
                    if spec.type == "import_spec":
                        out.extend(self._import_spec(spec, source))
        return out

    def _import_spec(self, spec: Node, source: bytes) -> list[ImportRef]:
        path_node = spec.child_by_field_name("path")
        if path_node is None:
            return []
        # Strip quotes from the path string
        raw = node_text(path_node, source).strip('"')
        # The target package is conventionally the last path segment; an
        # explicit package identifier changes only the local binding.
        target_name = raw.rsplit("/", 1)[-1]
        name_node = spec.child_by_field_name("name")
        local_name = (
            node_text(name_node, source)
            if name_node is not None and name_node.type == "package_identifier"
            else None
        )
        return [
            ImportRef(
                name=target_name,
                module_path=raw,
                local_name=local_name,
            )
        ]


def _first_child_of_type(node: Node, type_name: str) -> Node | None:
    for child in node.children:
        if child.type == type_name:
            return child
    return None


def _go_type_name(node: Node, source: bytes) -> str | None:
    """Extract the simple type name, stripping pointer/slice wrappers."""
    if node.type == "type_identifier":
        return node_text(node, source)
    if node.type == "pointer_type":
        # *Type → Type
        for child in node.children:
            if child.type == "type_identifier":
                return node_text(child, source)
    if node.type == "generic_type":
        # Type[T] → Type
        for child in node.children:
            if child.type == "type_identifier":
                return node_text(child, source)
    if node.type == "qualified_type":
        name_node = node.child_by_field_name("name")
        return node_text(name_node, source) if name_node is not None else None
    return None


def _preceding_comment(node: Node, source: bytes) -> str | None:
    """Extract Go-style doc comment immediately preceding a node."""
    prev = node.prev_named_sibling
    if prev is None or prev.type != "comment":
        return None
    # Collect consecutive comment lines ending at the node.
    lines: list[str] = []
    cur = prev
    while cur is not None and cur.type == "comment":
        lines.append(node_text(cur, source))
        cur = cur.prev_named_sibling
    lines.reverse()
    # Strip // or /* */ prefixes.
    cleaned: list[str] = []
    for line in lines:
        if line.startswith("//"):
            cleaned.append(line[2:].strip())
        elif line.startswith("/*") and line.endswith("*/"):
            cleaned.append(line[2:-2].strip())
        else:
            cleaned.append(line.strip())
    return "\n".join(cleaned) if cleaned else None


_GO_BUILTIN_TYPES = frozenset(
    {
        "bool",
        "byte",
        "complex64",
        "complex128",
        "error",
        "float32",
        "float64",
        "int",
        "int8",
        "int16",
        "int32",
        "int64",
        "rune",
        "string",
        "uint",
        "uint8",
        "uint16",
        "uint32",
        "uint64",
        "uintptr",
        "any",
    }
)


def _collect_go_type_ids(node: Node, source: bytes, out: list[str]) -> None:
    """Recursively collect user-defined type identifiers from Go type nodes."""
    if node.type == "type_identifier":
        name = node_text(node, source)
        if name not in _GO_BUILTIN_TYPES:
            out.append(name)
        return
    # Don't recurse into function bodies
    if node.type == "block":
        return
    for child in node.children:
        _collect_go_type_ids(child, source, out)
