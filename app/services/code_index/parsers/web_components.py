"""Web component parsers: Svelte, Vue, Astro.

These frameworks embed JS/TS in specialized blocks (<script> or frontmatter).
The parser extracts the script content and delegates to the EcmaScript parser.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, ClassVar

from app.services.code_index.parsers.base import (
    Definition,
    ImportRef,
    SuperType,
    TreeSitterParser,
    node_text,
)
from app.services.code_index.parsers.ecmascript import (
    JavaScriptParser,
    TsxParser,
    TypeScriptParser,
)
from app.services.code_index.graph_types import (
    NODE_VARIABLE,
    ExtractedNode,
    ParseResult,
)

if TYPE_CHECKING:
    from tree_sitter import Node


class _ScriptExtractParser(TreeSitterParser):
    """Base for component formats with embedded <script> or frontmatter."""

    _script_node_type: ClassVar[str] = "script_element"
    _content_node_type: ClassVar[str] = "raw_text"
    _default_script_parser: ClassVar[type[TreeSitterParser]] = JavaScriptParser

    def parse(self, *, file_path: str, source: bytes) -> ParseResult:
        """Parse and merge every embedded script block."""
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

        for block_index, (script_node, content_node) in enumerate(
            self._extract_scripts(root)
        ):
            script_bytes = source[content_node.start_byte : content_node.end_byte]
            delegated = self._parser_for_script(
                script_node, content_node, source
            ).parse(
                file_path=file_path,
                source=script_bytes,
            )
            line_offset = content_node.start_point[0]
            local_ids = {"<file>": "<file>"}

            for node in delegated.nodes:
                if node.local_id == "<file>":
                    continue
                local_id = f"<script:{block_index}>{node.local_id}"
                local_ids[node.local_id] = local_id
                result.nodes.append(
                    replace(
                        node,
                        local_id=local_id,
                        line_start=node.line_start + line_offset,
                        line_end=node.line_end + line_offset,
                    )
                )

            for edge in delegated.edges:
                result.edges.append(
                    replace(
                        edge,
                        src_local_id=local_ids.get(
                            edge.src_local_id, edge.src_local_id
                        ),
                        dst_local_id=(
                            local_ids.get(edge.dst_local_id, edge.dst_local_id)
                            if edge.dst_local_id is not None
                            else None
                        ),
                        line=(
                            edge.line + line_offset if edge.line is not None else None
                        ),
                    )
                )

        return result

    def _extract_scripts(self, root: Node) -> list[tuple[Node, Node]]:
        """Return top-level script containers and their content nodes."""
        scripts: list[tuple[Node, Node]] = []
        for child in root.children:
            if child.type == self._script_node_type:
                for sub in child.children:
                    if sub.type == self._content_node_type:
                        scripts.append((child, sub))
                        break
        return scripts

    def _parser_for_script(
        self, script_node: Node, content_node: Node, source: bytes
    ) -> TreeSitterParser:
        opening_tag = source[script_node.start_byte : content_node.start_byte].lower()
        if b'lang="tsx"' in opening_tag or b"lang='tsx'" in opening_tag:
            return TsxParser()
        if b'lang="ts"' in opening_tag or b"lang='ts'" in opening_tag:
            return TypeScriptParser()
        return self._default_script_parser()

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
    _default_script_parser: ClassVar[type[TreeSitterParser]] = TypeScriptParser


class LiquidParser(TreeSitterParser):
    """Liquid template language — minimal parser capturing assigns and renders."""

    name: ClassVar[str] = "liquid"
    extensions: ClassVar[tuple[str, ...]] = (".liquid",)
    grammar: ClassVar[str] = "liquid"

    def classify(
        self, node: Node, source: bytes, *, inside_class: bool
    ) -> Definition | None:
        return None

    def synthetic_definitions(
        self, node: Node, source: bytes, *, inside_class: bool
    ) -> list[Definition]:
        fields = {
            "assignment_statement": "variable_name",
            "capture_statement": "variable",
            "for_loop_statement": "item",
            "tablerow_statement": "item",
        }
        name_node = node.child_by_field_name(fields.get(node.type, ""))
        if name_node is None and node.type in {
            "increment_statement",
            "decrement_statement",
        }:
            name_node = next(
                (child for child in node.named_children if child.type == "identifier"),
                None,
            )
        if name_node is None:
            return []
        return [
            Definition(
                kind=NODE_VARIABLE,
                name=node_text(name_node, source),
                is_class=False,
            )
        ]

    def call_target(self, node: Node, source: bytes) -> str | None:
        return _liquid_template_name(node, source)

    def import_refs(self, node: Node, source: bytes) -> list[ImportRef]:
        template = _liquid_template_name(node, source)
        if not template:
            return []
        return [ImportRef(name=template.rsplit("/", 1)[-1], module_path=template)]

    def supertypes(self, node: Node, source: bytes) -> list[SuperType]:
        return []

    def docstring(self, node: Node, source: bytes) -> str | None:
        return None


def _liquid_template_name(node: Node, source: bytes) -> str | None:
    if node.type not in {"include_statement", "render_statement"}:
        return None
    file_node = node.child_by_field_name("file")
    if file_node is None:
        file_node = next(
            (child for child in node.named_children if child.type == "string"),
            None,
        )
    if file_node is None or file_node.type != "string":
        return None
    return node_text(file_node, source).strip("'\"")
