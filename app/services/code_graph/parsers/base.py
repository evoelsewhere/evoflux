"""Base class and protocol for tree-sitter backed language parsers.

Adding a new language means subclassing :class:`TreeSitterParser`, declaring its
``grammar``/``extensions`` and overriding a handful of small hooks
(:meth:`classify`, :meth:`call_target`, :meth:`supertypes`, :meth:`docstring`).
The generic tree walk, qualified-name construction, ``contains``/``calls``/
``inherits`` edge emission and safety limits all live here, so language modules
stay tiny and declarative.

The official tree-sitter API is used deliberately: ``Parser(get_language(name))``
with ``bytes`` input. The ``get_parser`` helper from ``tree_sitter_language_pack``
returns a binding whose ``parse`` wants ``str`` and whose ``root_node`` is a
method — avoid it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Protocol, runtime_checkable

from app.services.code_graph.types import (
    EDGE_CALLS,
    EDGE_CONTAINS,
    EDGE_DECORATED_BY,
    EDGE_IMPORTS,
    EDGE_REFERENCES,
    EDGE_USES,
    ExtractedEdge,
    ExtractedNode,
    ParseResult,
)

if TYPE_CHECKING:
    from tree_sitter import Node, Parser

# Guardrails so a single pathological file can't blow up indexing.
_MAX_NODES_PER_FILE = 6000
_MAX_DEPTH = 120
_MAX_SIGNATURE_LEN = 240


@runtime_checkable
class LanguageParser(Protocol):
    """Parses one file's bytes into a :class:`ParseResult`."""

    name: str
    extensions: tuple[str, ...]

    def parse(self, *, file_path: str, source: bytes) -> ParseResult: ...


@dataclass(frozen=True, slots=True)
class Definition:
    """A node the parser recognises as a symbol definition."""

    kind: str
    name: str
    is_class: bool
    prefix: str | None = None  # override parent prefix (e.g. Go receiver type)


@dataclass(frozen=True, slots=True)
class SuperType:
    """A base type referenced by a class (``inherits``/``implements``)."""

    name: str
    edge_kind: str


@dataclass(frozen=True, slots=True)
class ImportRef:
    """A symbol imported from another module.

    ``name`` is the symbol's name in the target module. ``local_name`` is the
    binding used by this source file when the import is aliased and otherwise
    defaults to ``name``. ``module_path`` is the raw import source string (e.g.
    ``"./utils"``, ``"app.services"``, ``"fmt"``).
    """

    name: str
    module_path: str
    local_name: str | None = None


def node_text(node: Node, source: bytes) -> str:
    """Decode a node's source span as UTF-8 (lossy)."""
    return source[node.start_byte : node.end_byte].decode("utf-8", "replace")


class TreeSitterParser:
    """Generic tree-sitter walker; subclasses supply language specifics."""

    name: ClassVar[str]
    extensions: ClassVar[tuple[str, ...]]
    grammar: ClassVar[str]

    def __init__(self) -> None:
        self._parser: Parser | None = None

    # -- public API ---------------------------------------------------------
    def parse(self, *, file_path: str, source: bytes) -> ParseResult:
        parser = self._get_parser()
        tree = parser.parse(source)
        root = tree.root_node

        file_node = ExtractedNode(
            local_id="<file>",
            kind="file",
            name=file_path,
            qualified_name=file_path,
            line_start=1,
            line_end=root.end_point[0] + 1,
        )
        result = ParseResult(language=self.name, file_path=file_path, nodes=[file_node])
        self._walk(
            root,
            source,
            result,
            prefix=self.root_prefix(root, source),
            parent_local_id="<file>",
            inside_class=False,
            depth=0,
        )
        return result

    # -- hooks (override in subclasses) -------------------------------------
    def root_prefix(self, root: Node, source: bytes) -> str:
        """Qualified-name prefix derived from file-level context (e.g. a Java
        ``package`` declaration). Applied to every top-level symbol in the
        file, same as the ``prefix`` a nested class applies to its members.
        """
        return ""

    def classify(
        self, node: Node, source: bytes, *, inside_class: bool
    ) -> Definition | None:
        """Return a :class:`Definition` if ``node`` is a symbol, else ``None``."""
        return None

    def call_target(self, node: Node, source: bytes) -> str | None:
        """Return the callee name if ``node`` is a call, else ``None``."""
        return None

    def uses_target(self, node: Node, source: bytes) -> str | None:
        """Return a wired-in dependency's type name if ``node`` declares one
        (e.g. a DI-injected field), else ``None``."""
        return None

    def supertypes(self, node: Node, source: bytes) -> list[SuperType]:
        """Return base classes/interfaces for a class definition node."""
        return []

    def import_refs(self, node: Node, source: bytes) -> list[ImportRef]:
        """Return imported symbols if ``node`` is an import statement."""
        return []

    def decorators(self, node: Node, source: bytes) -> list[str]:
        """Return decorator/annotation names applied to a definition node."""
        return []

    def type_refs(self, node: Node, source: bytes) -> list[str]:
        """Return type names referenced in annotations/signatures of a definition."""
        return []

    def docstring(self, node: Node, source: bytes) -> str | None:
        """Return the documentation string for a definition node, if any."""
        return None

    # -- helpers ------------------------------------------------------------
    def _get_parser(self) -> Parser:
        if self._parser is None:
            from tree_sitter import Parser
            from tree_sitter_language_pack import get_language

            self._parser = Parser(get_language(self.grammar))
        return self._parser

    def _signature(self, node: Node, source: bytes) -> str:
        raw = node_text(node, source)
        first = raw.split("\n", 1)[0].strip()
        if len(first) > _MAX_SIGNATURE_LEN:
            first = first[:_MAX_SIGNATURE_LEN].rstrip() + "…"
        return first

    def _walk(
        self,
        node: Node,
        source: bytes,
        result: ParseResult,
        *,
        prefix: str,
        parent_local_id: str,
        inside_class: bool,
        depth: int,
    ) -> None:
        if depth > _MAX_DEPTH or len(result.nodes) > _MAX_NODES_PER_FILE:
            return

        definition = self.classify(node, source, inside_class=inside_class)
        if definition is not None:
            line_start = node.start_point[0] + 1
            line_end = node.end_point[0] + 1
            if definition.prefix is not None:
                qualified = f"{definition.prefix}{definition.name}"
            elif prefix:
                qualified = f"{prefix}{definition.name}"
            else:
                qualified = definition.name
            local_id = f"{qualified}#{line_start}"
            result.nodes.append(
                ExtractedNode(
                    local_id=local_id,
                    kind=definition.kind,
                    name=definition.name,
                    qualified_name=qualified,
                    line_start=line_start,
                    line_end=line_end,
                    signature=self._signature(node, source),
                    docstring=self.docstring(node, source),
                )
            )
            result.edges.append(
                ExtractedEdge(
                    src_local_id=parent_local_id,
                    kind=EDGE_CONTAINS,
                    dst_local_id=local_id,
                    line=line_start,
                )
            )
            for sup in self.supertypes(node, source):
                result.edges.append(
                    ExtractedEdge(
                        src_local_id=local_id,
                        kind=sup.edge_kind,
                        dst_name=sup.name,
                        line=line_start,
                    )
                )
            for dec_name in self.decorators(node, source):
                result.edges.append(
                    ExtractedEdge(
                        src_local_id=local_id,
                        kind=EDGE_DECORATED_BY,
                        dst_name=dec_name,
                        line=line_start,
                    )
                )
            for type_name in self.type_refs(node, source):
                result.edges.append(
                    ExtractedEdge(
                        src_local_id=local_id,
                        kind=EDGE_REFERENCES,
                        dst_name=type_name,
                        line=line_start,
                    )
                )
            child_prefix = f"{qualified}."
            child_parent = local_id
            child_inside_class = definition.is_class
        else:
            callee = self.call_target(node, source)
            if callee:
                result.edges.append(
                    ExtractedEdge(
                        src_local_id=parent_local_id,
                        kind=EDGE_CALLS,
                        dst_name=callee,
                        line=node.start_point[0] + 1,
                    )
                )
            used = self.uses_target(node, source)
            if used:
                result.edges.append(
                    ExtractedEdge(
                        src_local_id=parent_local_id,
                        kind=EDGE_USES,
                        dst_name=used,
                        line=node.start_point[0] + 1,
                    )
                )
            for imp in self.import_refs(node, source):
                result.edges.append(
                    ExtractedEdge(
                        src_local_id=parent_local_id,
                        kind=EDGE_IMPORTS,
                        dst_name=imp.name,
                        line=node.start_point[0] + 1,
                        module_path=imp.module_path,
                        local_name=imp.local_name or imp.name,
                    )
                )
            child_prefix = prefix
            child_parent = parent_local_id
            child_inside_class = inside_class

        for child in node.children:
            self._walk(
                child,
                source,
                result,
                prefix=child_prefix,
                parent_local_id=child_parent,
                inside_class=child_inside_class,
                depth=depth + 1,
            )
