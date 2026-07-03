"""Web component parsers: Svelte, Vue, Astro.

These frameworks embed JS/TS in specialized blocks (<script> or frontmatter).
The parser extracts the script content and delegates to the EcmaScript parser.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from app.services.code_graph.parsers.base import (
    Definition,
    SuperType,
    TreeSitterParser,
    node_text,
)
from app.services.code_graph.parsers.ecmascript import TypeScriptParser
from app.services.code_graph.types import ParseResult

if TYPE_CHECKING:
    from tree_sitter import Node


class _ScriptExtractParser(TreeSitterParser):
    """Base for component formats with embedded <script> or frontmatter."""

    _script_node_type: ClassVar[str] = "script_element"
    _content_node_type: ClassVar[str] = "raw_text"

    def parse(self, *, file_path: str, source: bytes) -> ParseResult:
        """Extract script blocks and delegate to the TypeScript parser."""
        parser = self._get_parser()
        tree = parser.parse(source)
        root = tree.root_node

        # Find script content
        script_bytes = self._extract_script(root, source)
        if script_bytes:
            ts_parser = TypeScriptParser()
            return ts_parser.parse(file_path=file_path, source=script_bytes)

        # Fallback: return empty result with just the file node
        from app.services.code_graph.types import ExtractedNode

        file_node = ExtractedNode(
            local_id="<file>",
            kind="file",
            name=file_path,
            qualified_name=file_path,
            line_start=1,
            line_end=root.end_point[0] + 1,
        )
        return ParseResult(language=self.name, file_path=file_path, nodes=[file_node])

    def _extract_script(self, root: Node, source: bytes) -> bytes | None:
        """Walk tree to find script content node."""
        for child in root.children:
            if child.type == self._script_node_type:
                for sub in child.children:
                    if sub.type == self._content_node_type:
                        return source[sub.start_byte : sub.end_byte]
            # Astro frontmatter is a direct child
            if child.type == self._content_node_type:
                return source[child.start_byte : child.end_byte]
        return None

    def classify(
        self, node: Node, source: bytes, *, inside_class: bool
    ) -> Definition | None:
        return None

    def call_target(self, node: Node, source: bytes) -> str | None:
        return None

    def supertypes(self, node: Node, source: bytes) -> list[SuperType]:
        return []

    def docstring(self, node: Node, source: bytes) -> str | None:
        return None


class SvelteParser(_ScriptExtractParser):
    name: ClassVar[str] = "svelte"
    extensions: ClassVar[tuple[str, ...]] = (".svelte",)
    grammar: ClassVar[str] = "svelte"

    _script_node_type: ClassVar[str] = "script_element"
    _content_node_type: ClassVar[str] = "raw_text"


class VueParser(_ScriptExtractParser):
    name: ClassVar[str] = "vue"
    extensions: ClassVar[tuple[str, ...]] = (".vue",)
    grammar: ClassVar[str] = "vue"

    _script_node_type: ClassVar[str] = "script_element"
    _content_node_type: ClassVar[str] = "raw_text"


class AstroParser(_ScriptExtractParser):
    name: ClassVar[str] = "astro"
    extensions: ClassVar[tuple[str, ...]] = (".astro",)
    grammar: ClassVar[str] = "astro"

    _script_node_type: ClassVar[str] = "frontmatter"
    _content_node_type: ClassVar[str] = "frontmatter_js_block"


class LiquidParser(TreeSitterParser):
    """Liquid template language — minimal parser capturing assigns and renders."""

    name: ClassVar[str] = "liquid"
    extensions: ClassVar[tuple[str, ...]] = (".liquid",)
    grammar: ClassVar[str] = "liquid"

    def classify(
        self, node: Node, source: bytes, *, inside_class: bool
    ) -> Definition | None:
        # Liquid doesn't have classes/functions, but we can capture assignments
        return None

    def call_target(self, node: Node, source: bytes) -> str | None:
        if node.type == "render_statement":
            for child in node.children:
                if child.type == "string":
                    return node_text(child, source).strip("'\"")
        return None

    def supertypes(self, node: Node, source: bytes) -> list[SuperType]:
        return []

    def docstring(self, node: Node, source: bytes) -> str | None:
        return None
