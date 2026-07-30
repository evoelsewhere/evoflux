"""Java language parser."""

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
    NODE_INTERFACE,
    NODE_METHOD,
)

if TYPE_CHECKING:
    from tree_sitter import Node


class JavaParser(TreeSitterParser):
    name: ClassVar[str] = "java"
    extensions: ClassVar[tuple[str, ...]] = (".java",)
    grammar: ClassVar[str] = "java"

    def root_prefix(self, root: Node, source: bytes) -> str:
        # Java's qualified_name is a dotted path *within the file* by default
        # (see base.py) — without this, two classes with the same simple name
        # in different packages collide when resolving edges by name, and
        # cross-repo FQN matching (import "com.foo.Bar" against a sibling
        # repo's qualified_name) has nothing to match against.
        for child in root.children:
            if child.type == "package_declaration":
                for sub in child.children:
                    if sub.type in ("scoped_identifier", "identifier"):
                        return f"{node_text(sub, source)}."
        return ""

    def import_refs(self, node: Node, source: bytes) -> list[ImportRef]:
        if node.type != "import_declaration":
            return []
        # Children: "import", ["static"], scoped_identifier|identifier,
        # ["." , "asterisk"] for a wildcard import, ";".
        scoped = next(
            (c for c in node.children if c.type in ("scoped_identifier", "identifier")),
            None,
        )
        if scoped is None:
            return []
        dotted = node_text(scoped, source)
        is_wildcard = any(c.type == "asterisk" for c in node.children)
        if is_wildcard:
            return [ImportRef(name="*", module_path=f"{dotted}.*")]
        # Bare class import ("com.example.Baz") and static-member import
        # ("com.example.Helper.doThing") are syntactically identical here —
        # both just the last dotted segment as the locally-used name. The
        # cross-repo resolver retries with the segment stripped if a class
        # match fails, so no static-vs-class distinction is needed at
        # extraction time.
        return [ImportRef(name=dotted.rsplit(".", 1)[-1], module_path=dotted)]

    def classify(
        self, node: Node, source: bytes, *, inside_class: bool
    ) -> Definition | None:
        ntype = node.type
        if ntype == "class_declaration":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_CLASS, name=name, is_class=True)
        elif ntype == "interface_declaration":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_INTERFACE, name=name, is_class=True)
        elif ntype == "enum_declaration":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_CLASS, name=name, is_class=True)
        elif ntype == "record_declaration":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_CLASS, name=name, is_class=True)
        elif ntype == "annotation_type_declaration":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_INTERFACE, name=name, is_class=True)
        elif ntype == "method_declaration":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_METHOD, name=name, is_class=False)
        elif ntype == "constructor_declaration":
            name = self._name(node, source)
            if name:
                return Definition(kind=NODE_METHOD, name=name, is_class=False)
        return None

    def call_target(self, node: Node, source: bytes) -> str | None:
        if node.type == "method_invocation":
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                return node_text(name_node, source)
        elif node.type == "object_creation_expression":
            type_node = node.child_by_field_name("type")
            if type_node is not None:
                return _simple_type_name(type_node, source)
        return None

    def uses_target(self, node: Node, source: bytes) -> str | None:
        """Return a DI-wired field's type, else ``None``.

        Constructor/setter parameter types are already captured generically
        by ``type_refs()`` — this only covers the one pattern with no other
        extraction path: injected *fields*. Two signals count as injection:
        an explicit ``@Autowired``/``@Inject``/``@Resource`` annotation, or a
        ``final`` field with no initializer (Lombok's ``@RequiredArgsConstructor``
        generates the constructor, so the annotation is often absent — but an
        uninitialized ``final`` field can only be set by *some* constructor,
        making it a required collaborator either way).
        """
        if node.type != "field_declaration":
            return None
        modifiers = next((c for c in node.children if c.type == "modifiers"), None)
        mod_types = (
            {m.type for m in modifiers.children} if modifiers is not None else set()
        )
        if not _INJECTION_ANNOTATIONS.intersection(self.decorators(node, source)):
            if "final" not in mod_types:
                return None
            declarator = next(
                (c for c in node.children if c.type == "variable_declarator"), None
            )
            if (
                declarator is None
                or declarator.child_by_field_name("value") is not None
            ):
                return None
        for child in node.children:
            if child.type in {
                "type_identifier",
                "generic_type",
                "scoped_type_identifier",
            }:
                name = _simple_type_name(child, source)
                return name if name and name not in _JAVA_BUILTIN_TYPES else None
        return None

    def supertypes(self, node: Node, source: bytes) -> list[SuperType]:
        if node.type not in (
            "class_declaration",
            "interface_declaration",
            "enum_declaration",
        ):
            return []
        out: list[SuperType] = []
        for child in node.children:
            if child.type == "superclass":
                # extends clause
                for sub in child.children:
                    name = _simple_type_name(sub, source)
                    if name:
                        out.append(SuperType(name=name, edge_kind=EDGE_INHERITS))
            elif child.type == "super_interfaces":
                # implements clause
                edge = (
                    EDGE_IMPLEMENTS
                    if node.type != "interface_declaration"
                    else EDGE_INHERITS
                )
                for sub in child.children:
                    if sub.type == "type_list":
                        for t in sub.children:
                            name = _simple_type_name(t, source)
                            if name:
                                out.append(SuperType(name=name, edge_kind=edge))
                    else:
                        name = _simple_type_name(sub, source)
                        if name:
                            out.append(SuperType(name=name, edge_kind=edge))
            elif child.type == "extends_interfaces":
                # interface extends other interfaces
                for sub in child.children:
                    if sub.type == "type_list":
                        for t in sub.children:
                            name = _simple_type_name(t, source)
                            if name:
                                out.append(
                                    SuperType(name=name, edge_kind=EDGE_INHERITS)
                                )
        return out

    def docstring(self, node: Node, source: bytes) -> str | None:
        # Java uses block comments (Javadoc) preceding declarations.
        prev = node.prev_named_sibling
        if prev is not None and prev.type == "block_comment":
            text = node_text(prev, source)
            return _strip_javadoc(text)
        return None

    def _name(self, node: Node, source: bytes) -> str | None:
        name_node = node.child_by_field_name("name")
        return node_text(name_node, source) if name_node is not None else None

    def decorators(self, node: Node, source: bytes) -> list[str]:
        out: list[str] = []
        for child in node.children:
            if child.type == "modifiers":
                for mod in child.children:
                    if mod.type in {"marker_annotation", "annotation"}:
                        name_node = mod.child_by_field_name("name")
                        if name_node is not None:
                            out.append(node_text(name_node, source))
                break
        return out

    def type_refs(self, node: Node, source: bytes) -> list[str]:
        if node.type not in {"method_declaration", "constructor_declaration"}:
            return []
        out: list[str] = []
        # Return type — direct child type_identifier or generic_type
        for child in node.children:
            if child.type in {"type_identifier", "generic_type"}:
                name = _simple_type_name(child, source)
                if name and name not in _JAVA_BUILTIN_TYPES:
                    out.append(name)
                break
        # Parameter types
        params = node.child_by_field_name("parameters")
        if params is not None:
            for param in params.children:
                if param.type == "formal_parameter":
                    for child in param.children:
                        if child.type in {"type_identifier", "generic_type"}:
                            name = _simple_type_name(child, source)
                            if name and name not in _JAVA_BUILTIN_TYPES:
                                out.append(name)
                            break
        return out


_INJECTION_ANNOTATIONS = frozenset({"Autowired", "Inject", "Resource"})

_JAVA_BUILTIN_TYPES = frozenset(
    {
        "void",
        "int",
        "long",
        "short",
        "byte",
        "float",
        "double",
        "boolean",
        "char",
        "String",
        "Object",
    }
)


def _simple_type_name(node: Node, source: bytes) -> str | None:
    """Extract a simple type name, stripping generics and qualifications."""
    if node.type == "type_identifier":
        return node_text(node, source)
    if node.type == "generic_type":
        for child in node.children:
            if child.type == "type_identifier":
                return node_text(child, source)
    if node.type == "scoped_type_identifier":
        # com.example.Foo → Foo (last identifier)
        for child in reversed(node.children):
            if child.type == "type_identifier":
                return node_text(child, source)
    return None


def _strip_javadoc(text: str) -> str:
    """Strip Javadoc delimiters and leading asterisks."""
    s = text.strip()
    if s.startswith("/**"):
        s = s[3:]
    if s.endswith("*/"):
        s = s[:-2]
    lines = s.split("\n")
    cleaned: list[str] = []
    for line in lines:
        line = line.strip()
        if line.startswith("*"):
            line = line[1:].strip()
        if line:
            cleaned.append(line)
    return "\n".join(cleaned)
