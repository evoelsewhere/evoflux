"""Web component parsers: Svelte, Vue, Astro.

These frameworks embed JS/TS in specialized blocks (<script> or frontmatter).
The parser extracts the script content and delegates to the EcmaScript parser.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import PurePosixPath
import re
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
    EDGE_CONTAINS,
    EDGE_IMPORTS,
    EDGE_REFERENCES,
    NODE_MODULE,
    NODE_VARIABLE,
    ExtractedEdge,
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
        component_name, component_id, result = _component_shell(
            language=self.name,
            file_path=file_path,
            line_end=root.end_point[0] + 1,
        )

        for block_index, (script_node, content_node) in enumerate(
            self._extract_scripts(root)
        ):
            script_bytes = source[content_node.start_byte : content_node.end_byte]
            delegated = self._parser_for_script(script_node, source).parse(
                file_path=file_path,
                source=script_bytes,
            )
            if delegated.file_path != file_path:
                raise RuntimeError("delegated script parser changed the file path")
            line_offset = content_node.start_point[0]
            local_ids = {"<file>": component_id}

            for node in delegated.nodes:
                if node.local_id == "<file>":
                    continue
                local_id = f"<script:{block_index}>{node.local_id}"
                local_ids[node.local_id] = local_id
                result.nodes.append(
                    replace(
                        node,
                        local_id=local_id,
                        qualified_name=f"{component_name}.{node.qualified_name}",
                        line_start=node.line_start + line_offset,
                        line_end=node.line_end + line_offset,
                    )
                )

            for edge in delegated.edges:
                result.edges.append(
                    replace(
                        edge,
                        src_local_id=local_ids[edge.src_local_id],
                        dst_local_id=(
                            local_ids[edge.dst_local_id]
                            if edge.dst_local_id is not None
                            else None
                        ),
                        line=(
                            edge.line + line_offset if edge.line is not None else None
                        ),
                    )
                )

        for name, line in _template_references(root, source, dialect=self.name):
            result.edges.append(
                ExtractedEdge(
                    src_local_id=component_id,
                    kind=EDGE_REFERENCES,
                    dst_name=name,
                    line=line,
                )
            )
        for ref, line in _external_script_imports(root, source):
            result.edges.append(
                ExtractedEdge(
                    src_local_id=component_id,
                    kind=EDGE_IMPORTS,
                    dst_name=ref.name,
                    module_path=ref.module_path,
                    local_name=ref.name,
                    line=line,
                )
            )
        result.edges[:] = dict.fromkeys(result.edges)
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

    def _parser_for_script(self, script_node: Node, source: bytes) -> TreeSitterParser:
        if script_node.type == "frontmatter":
            return self._default_script_parser()
        lang = _element_attribute(script_node, "lang", source)
        if lang is None:
            return self._default_script_parser()
        lang = lang.casefold()
        if lang == "tsx":
            return TsxParser()
        if lang in {"ts", "typescript"}:
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

    def _extract_scripts(self, root: Node) -> list[tuple[Node, Node]]:
        scripts = super()._extract_scripts(root)
        for node in _descendants(root):
            if node.type != "script_element":
                continue
            content = next(child for child in node.children if child.type == "raw_text")
            scripts.append((node, content))
        return scripts


class LiquidParser(TreeSitterParser):
    """Liquid template language — minimal parser capturing assigns and renders."""

    name: ClassVar[str] = "liquid"
    extensions: ClassVar[tuple[str, ...]] = (".liquid",)
    grammar: ClassVar[str] = "liquid"

    def parse(self, *, file_path: str, source: bytes) -> ParseResult:
        result = super().parse(file_path=file_path, source=source)
        return _wrap_result_in_component(result)

    def identifier_reference_targets(self, node: Node, source: bytes) -> list[str]:
        return []

    def reference_targets(self, node: Node, source: bytes) -> list[str]:
        if node.type == "access":
            return [node_text(node, source)]
        if (
            node.type == "string"
            and node.parent is not None
            and node.parent.type
            in {
                "include_statement",
                "render_statement",
            }
        ):
            raw = node_text(node, source)
            if not _quoted_template_literal(raw):
                return [raw]
        if node.type != "identifier" or _liquid_identifier_is_binding(node):
            return []
        if node.parent is not None and node.parent.type == "access":
            return []
        return [node_text(node, source)]

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
        field = fields.get(node.type)
        name_node = node.child_by_field_name(field) if field is not None else None
        if name_node is None and node.type in {
            "increment_statement",
            "decrement_statement",
        }:
            name_node = next(
                child for child in node.named_children if child.type == "identifier"
            )
        if name_node is None:
            return []
        return [
            Definition(
                kind=NODE_VARIABLE,
                name=node_text(name_node, source),
            )
        ]

    def call_target(self, node: Node, source: bytes) -> str | None:
        return _liquid_template_name(node, source)

    def import_refs(self, node: Node, source: bytes) -> list[ImportRef]:
        template = _liquid_template_name(node, source)
        if not template:
            return []
        return [ImportRef(name=template.rsplit("/")[-1], module_path=template)]

    def supertypes(self, node: Node, source: bytes) -> list[SuperType]:
        return []

    def docstring(self, node: Node, source: bytes) -> str | None:
        return None


def _component_shell(
    *, language: str, file_path: str, line_end: int
) -> tuple[str, str, ParseResult]:
    component_name = PurePosixPath(file_path.replace("\\", "/")).stem
    component_id = "<component>"
    file_node = ExtractedNode(
        local_id="<file>",
        kind="file",
        name=file_path,
        qualified_name=file_path,
        line_start=1,
        line_end=line_end,
    )
    component_node = ExtractedNode(
        local_id=component_id,
        kind=NODE_MODULE,
        name=component_name,
        qualified_name=component_name,
        line_start=1,
        line_end=line_end,
    )
    result = ParseResult(
        language=language,
        file_path=file_path,
        nodes=[file_node, component_node],
        edges=[
            ExtractedEdge(
                src_local_id="<file>",
                kind=EDGE_CONTAINS,
                dst_local_id=component_id,
                line=1,
            )
        ],
    )
    return component_name, component_id, result


def _wrap_result_in_component(result: ParseResult) -> ParseResult:
    file_node = result.nodes[0]
    component_name, component_id, wrapped = _component_shell(
        language=result.language,
        file_path=result.file_path,
        line_end=file_node.line_end,
    )
    wrapped.nodes.extend(
        replace(node, qualified_name=f"{component_name}.{node.qualified_name}")
        for node in result.nodes[1:]
    )
    wrapped.edges.extend(
        replace(
            edge,
            src_local_id=(
                component_id if edge.src_local_id == "<file>" else edge.src_local_id
            ),
        )
        for edge in result.edges
    )
    wrapped.edges[:] = dict.fromkeys(wrapped.edges)
    return wrapped


def _descendants(node: Node):
    for child in node.named_children:
        yield child
        yield from _descendants(child)


def _element_attribute(node: Node, name: str, source: bytes) -> str | None:
    start_tag = next(child for child in node.children if child.type == "start_tag")
    for candidate in start_tag.named_children:
        if candidate.type != "attribute":
            continue
        attribute_name = next(
            child
            for child in candidate.named_children
            if child.type == "attribute_name"
        )
        if node_text(attribute_name, source).casefold() != name:
            continue
        value = next(
            (
                child
                for child in _descendants(candidate)
                if child.type == "attribute_value"
            ),
            None,
        )
        return node_text(value, source).strip() if value is not None else None
    return None


def _external_script_imports(root: Node, source: bytes) -> list[tuple[ImportRef, int]]:
    out: list[tuple[ImportRef, int]] = []
    for node in _descendants(root):
        if node.type != "script_element":
            continue
        module_path = _element_attribute(node, "src", source)
        if not module_path:
            continue
        clean_path = re.split(r"[?#]", module_path)[0]
        name = PurePosixPath(clean_path).stem
        if name:
            out.append(
                (
                    ImportRef(name=name, module_path=module_path),
                    node.start_point[0] + 1,
                )
            )
    return out


_VUE_BUILTIN_TAGS = frozenset(
    {"Component", "KeepAlive", "Slot", "Suspense", "Teleport", "Transition"}
)
_STATIC_TEMPLATE_NAME = re.compile(r"^[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*$")


def _template_references(
    root: Node, source: bytes, *, dialect: str
) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for tag in _descendants(root):
        if tag.type not in {"start_tag", "self_closing_tag"}:
            continue
        tag_name_node = next(
            child for child in tag.named_children if child.type == "tag_name"
        )
        tag_name = node_text(tag_name_node, source)
        reference = _component_tag_reference(tag_name, dialect=dialect)
        if reference:
            out.append((reference, tag.start_point[0] + 1))

        for attribute in tag.named_children:
            if attribute.type not in {"attribute", "directive_attribute"}:
                continue
            expression = _template_attribute_reference(
                attribute, source, dialect=dialect
            )
            if expression:
                out.append((expression, attribute.start_point[0] + 1))
    for expression_node in _descendants(root):
        if expression_node.type not in {
            "expression",
            "html_interpolation",
            "interpolation",
        }:
            continue
        value = node_text(expression_node, source).strip("{} ")
        if _STATIC_TEMPLATE_NAME.fullmatch(value):
            out.append((value, expression_node.start_point[0] + 1))
    return sorted(out, key=lambda item: item[1])


def _component_tag_reference(tag_name: str, *, dialect: str) -> str | None:
    if dialect == "vue":
        if tag_name in _VUE_BUILTIN_TAGS:
            return None
        if tag_name[:1].isupper():
            return tag_name
        if "-" in tag_name:
            return "".join(part[:1].upper() + part[1:] for part in tag_name.split("-"))
        return None
    if tag_name == "Fragment":
        return None
    return tag_name if tag_name[:1].isupper() else None


def _template_attribute_reference(
    attribute: Node,
    source: bytes,
    *,
    dialect: str,
) -> str | None:
    raw = node_text(attribute, source).strip()
    is_vue_binding = dialect == "vue" and raw.startswith(("@", "v-on:", ":", "v-bind:"))
    is_braced_binding = any(
        child.type == "attribute_js_expr" for child in _descendants(attribute)
    )
    if not is_vue_binding and not is_braced_binding:
        return None
    value = next(
        node_text(child, source)
        for child in _descendants(attribute)
        if child.type in {"attribute_js_expr", "attribute_value"}
    ).strip()
    return value if _STATIC_TEMPLATE_NAME.fullmatch(value) else None


def _liquid_identifier_is_binding(node: Node) -> bool:
    parent = node.parent
    if parent is None:
        return False
    for field in ("variable_name", "variable", "item", "key"):
        if parent.child_by_field_name(field) == node:
            return True
    return parent.type in {"increment_statement", "decrement_statement"}


def _quoted_template_literal(raw: str) -> bool:
    return len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {"'", '"'}


def _liquid_template_name(node: Node, source: bytes) -> str | None:
    if node.type not in {"include_statement", "render_statement"}:
        return None
    file_node = next(child for child in node.named_children if child.type == "string")
    raw = node_text(file_node, source)
    return raw[1:-1] if _quoted_template_literal(raw) else None
