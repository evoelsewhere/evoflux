"""Config-driven structural parser — legacy languages without tree-sitter.

Implements the :class:`~app.services.code_graph.parsers.base.LanguageParser`
protocol from a YAML config (an AIM rulebook's ``extractors/*.yaml``) instead
of a grammar: node rules turn matched lines into graph nodes, edge rules turn
matched lines inside those nodes into ``calls``/``imports``/``references``
edges. That is deliberately the Azure-Samples approach — regex extraction is
demonstrably good enough to *seed* a code graph for COBOL/JCL/VB6-class
languages where tree-sitter grammars are weak or absent; LLM enrichment
covers the rest (aim-framework.md §3.9, risk #1).

The model is line-based and flat:

- ``scope: file`` rules match at most once per file (first hit wins) and
  produce a container node spanning the whole file — e.g. a COBOL
  ``PROGRAM-ID`` or a VB6 ``Attribute VB_Name``. The first file-scope node
  becomes the qualified-name prefix and ``contains`` parent for every block.
- ``scope: block`` rules open a node at the matched line. A block closes at
  its rule's ``end_match`` if given (VB6 ``End Sub``), else at the next line
  that opens *any* block, else EOF (COBOL paragraphs have no end marker —
  they end where the next paragraph starts). Blocks do not nest.
- Edge rules run over the lines inside each block whose kind matches the
  rule's ``from`` (or over container/file-level lines for ``from: file``),
  emitting name-refs the indexer resolves cross-file later.

There is no syntax awareness beyond the configured regexes: a "call" match
inside a comment or string literal is emitted anyway. Configs mitigate with
anchors and the keyword denylist; measure extraction recall on a real estate
before trusting coverage (aim-framework.md risk #1).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.code_graph.types import (
    EDGE_CALLS,
    EDGE_CONTAINS,
    EDGE_IMPORTS,
    EDGE_READS,
    EDGE_REFERENCES,
    EDGE_USES,
    EDGE_WRITES,
    ExtractedEdge,
    ExtractedNode,
    ParseResult,
)

# Same guardrails as the tree-sitter base: one pathological file must not
# blow up indexing. Lines beyond _MAX_LINE_LEN are skipped entirely rather
# than truncated — a megabyte-long "line" is minified/generated content, and
# running user-authored regexes over it invites catastrophic backtracking.
_MAX_NODES_PER_FILE = 6000
_MAX_LINE_LEN = 2000
_MAX_SIGNATURE_LEN = 240

#: Config edge kinds → canonical graph edge kinds. Deliberately a subset:
#: structural configs may only emit relationship kinds the rest of the
#: pipeline (path traversal, references queries) already understands.
_EDGE_KINDS: dict[str, str] = {
    "calls": EDGE_CALLS,
    "imports": EDGE_IMPORTS,
    "references": EDGE_REFERENCES,
    "uses": EDGE_USES,
    "reads": EDGE_READS,
    "writes": EDGE_WRITES,
}


class StructuralNodeRule(BaseModel):
    """One "this line defines a symbol" rule."""

    model_config = ConfigDict(extra="ignore")

    kind: str
    scope: str = Field(pattern="^(file|block)$")
    match: str
    # Only meaningful for scope=block: the line that closes the block. Blocks
    # without one close at the next opened block or EOF.
    end_match: str | None = None

    @model_validator(mode="after")
    def _validate(self) -> "StructuralNodeRule":
        if "name" not in re.compile(self.match).groupindex:
            raise ValueError(
                f"node_rule for kind '{self.kind}': match must have a "
                f"(?P<name>...) group."
            )
        return self


class StructuralEdgeRule(BaseModel):
    """One "this line references another symbol" rule."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    kind: str
    # Which node kind's lines this rule scans ("file" = container level).
    from_kind: str = Field(alias="from")
    match: str
    # Named group holding the referenced symbol. Optional when the pattern
    # has exactly one named group.
    target_group: str | None = None

    @model_validator(mode="after")
    def _validate(self) -> "StructuralEdgeRule":
        if self.kind not in _EDGE_KINDS:
            raise ValueError(
                f"edge_rule kind '{self.kind}' is not a known graph edge kind "
                f"(expected one of {sorted(_EDGE_KINDS)})."
            )
        groups = re.compile(self.match).groupindex
        if self.target_group is None:
            if len(groups) != 1:
                raise ValueError(
                    f"edge_rule '{self.kind}': pattern has {len(groups)} named "
                    f"groups — set target_group to pick one."
                )
            self.target_group = next(iter(groups))
        elif self.target_group not in groups:
            raise ValueError(
                f"edge_rule '{self.kind}': target_group '{self.target_group}' "
                f"not present in pattern."
            )
        return self


class StructuralConfig(BaseModel):
    """Parsed ``extractors/*.yaml`` — everything a StructuralParser needs."""

    model_config = ConfigDict(extra="ignore")

    id: str
    description: str = ""
    file_extensions: list[str] = Field(min_length=1)
    # Compile every regex case-insensitively (COBOL and JCL are); configs
    # for case-sensitive languages can turn it off.
    ignore_case: bool = True
    node_rules: list[StructuralNodeRule] = Field(min_length=1)
    edge_rules: list[StructuralEdgeRule] = Field(default_factory=list)
    # Matched edge targets in this set (case-insensitive) are dropped — the
    # standard way to keep language keywords out of a permissive calls regex.
    keyword_denylist: list[str] = Field(default_factory=list)


def load_structural_config(path: str | Path) -> StructuralConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Extractor config '{path}' must be a YAML mapping.")
    return StructuralConfig.model_validate(raw)


@dataclass(slots=True)
class _OpenBlock:
    rule: StructuralNodeRule
    local_id: str
    line_start: int


class StructuralParser:
    """A :class:`LanguageParser` built from a :class:`StructuralConfig`."""

    def __init__(self, config: StructuralConfig) -> None:
        self.config = config
        self.name = config.id
        self.extensions = tuple(ext.lower() for ext in config.file_extensions)
        flags = re.IGNORECASE if config.ignore_case else 0
        self._node_rules = [
            (rule, re.compile(rule.match, flags)) for rule in config.node_rules
        ]
        self._end_patterns = {
            rule.kind: re.compile(rule.end_match, flags)
            for rule in config.node_rules
            if rule.end_match
        }
        self._edge_rules = [
            (rule, re.compile(rule.match, flags)) for rule in config.edge_rules
        ]
        self._denylist = frozenset(word.upper() for word in config.keyword_denylist)

    # -- public API ---------------------------------------------------------
    def parse(self, *, file_path: str, source: bytes) -> ParseResult:
        text = source.decode("utf-8", "replace")
        lines = text.splitlines()
        total_lines = max(len(lines), 1)

        file_node = ExtractedNode(
            local_id="<file>",
            kind="file",
            name=file_path,
            qualified_name=file_path,
            line_start=1,
            line_end=total_lines,
        )
        result = ParseResult(language=self.name, file_path=file_path, nodes=[file_node])

        container = self._extract_container(lines, total_lines, result)
        prefix = f"{container.qualified_name}." if container else ""
        parent_id = container.local_id if container else "<file>"

        blocks = self._extract_blocks(
            lines, total_lines, result, prefix=prefix, parent_id=parent_id
        )
        self._extract_edges(lines, blocks, parent_id=parent_id, result=result)
        return result

    # -- extraction passes --------------------------------------------------
    def _extract_container(
        self, lines: list[str], total_lines: int, result: ParseResult
    ) -> ExtractedNode | None:
        """First match of each scope=file rule; the first node found becomes
        the container. Later file-scope nodes (rare) are still recorded."""
        container: ExtractedNode | None = None
        for rule, pattern in self._node_rules:
            if rule.scope != "file":
                continue
            for line_no, line in enumerate(lines, start=1):
                if len(line) > _MAX_LINE_LEN:
                    continue
                match = pattern.search(line)
                if not match:
                    continue
                name = match.group("name")
                node = ExtractedNode(
                    local_id=f"{name}#{line_no}",
                    kind=rule.kind,
                    name=name,
                    qualified_name=name,
                    line_start=line_no,
                    line_end=total_lines,
                    signature=_signature(line),
                )
                result.nodes.append(node)
                result.edges.append(
                    ExtractedEdge(
                        src_local_id="<file>",
                        kind=EDGE_CONTAINS,
                        dst_local_id=node.local_id,
                        line=line_no,
                    )
                )
                if container is None:
                    container = node
                break
        return container

    def _extract_blocks(
        self,
        lines: list[str],
        total_lines: int,
        result: ParseResult,
        *,
        prefix: str,
        parent_id: str,
    ) -> list[tuple[_OpenBlock, int]]:
        """Single pass opening/closing flat blocks. Returns (block, line_end)."""
        block_rules = [
            (rule, pattern)
            for rule, pattern in self._node_rules
            if rule.scope == "block"
        ]
        if not block_rules:
            return []

        closed: list[tuple[_OpenBlock, int]] = []
        open_block: _OpenBlock | None = None

        def _close(block: _OpenBlock, line_end: int) -> None:
            closed.append((block, line_end))

        for line_no, line in enumerate(lines, start=1):
            if len(line) > _MAX_LINE_LEN:
                continue
            if len(result.nodes) > _MAX_NODES_PER_FILE:
                break

            if open_block is not None:
                end_pattern = self._end_patterns.get(open_block.rule.kind)
                if end_pattern is not None and end_pattern.search(line):
                    _close(open_block, line_no)
                    open_block = None
                    continue

            for rule, pattern in block_rules:
                match = pattern.search(line)
                if not match:
                    continue
                # A block with an explicit end marker swallows everything
                # until that marker — lines inside it never open siblings
                # (a nested `Function` match inside a VB6 `Sub` body would
                # be a comment or string; real ones are flat).
                if (
                    open_block is not None
                    and self._end_patterns.get(open_block.rule.kind) is not None
                ):
                    break
                if open_block is not None:
                    _close(open_block, line_no - 1)
                    open_block = None
                name = match.group("name")
                qualified = f"{prefix}{name}" if prefix else name
                open_block = _OpenBlock(
                    rule=rule,
                    local_id=f"{qualified}#{line_no}",
                    line_start=line_no,
                )
                result.nodes.append(
                    ExtractedNode(
                        local_id=open_block.local_id,
                        kind=rule.kind,
                        name=name,
                        qualified_name=qualified,
                        line_start=line_no,
                        line_end=line_no,  # patched on close, see below
                    )
                )
                result.edges.append(
                    ExtractedEdge(
                        src_local_id=parent_id,
                        kind=EDGE_CONTAINS,
                        dst_local_id=open_block.local_id,
                        line=line_no,
                    )
                )
                break

        if open_block is not None:
            _close(open_block, total_lines)

        # ExtractedNode is frozen — rebuild closed blocks with real spans and
        # signatures now that end lines are known.
        end_by_id = {block.local_id: end for block, end in closed}
        for i, node in enumerate(result.nodes):
            end = end_by_id.get(node.local_id)
            if end is None or end == node.line_end:
                continue
            sig_line = (
                lines[node.line_start - 1] if node.line_start <= len(lines) else ""
            )
            result.nodes[i] = ExtractedNode(
                local_id=node.local_id,
                kind=node.kind,
                name=node.name,
                qualified_name=node.qualified_name,
                line_start=node.line_start,
                line_end=end,
                signature=_signature(sig_line),
            )
        return closed

    def _extract_edges(
        self,
        lines: list[str],
        blocks: list[tuple[_OpenBlock, int]],
        *,
        parent_id: str,
        result: ParseResult,
    ) -> None:
        if not self._edge_rules:
            return
        # Line → owning block, so file-level rules can skip block bodies and
        # block rules know their source node.
        owner_by_line: dict[int, _OpenBlock] = {}
        for block, line_end in blocks:
            for line_no in range(block.line_start, line_end + 1):
                owner_by_line[line_no] = block

        for line_no, line in enumerate(lines, start=1):
            if len(line) > _MAX_LINE_LEN:
                continue
            owner = owner_by_line.get(line_no)
            seen_on_line: set[tuple[str, str]] = set()
            for rule, pattern in self._edge_rules:
                if rule.from_kind == "file":
                    if owner is not None:
                        continue
                    src_id = parent_id
                elif owner is None or owner.rule.kind != rule.from_kind:
                    continue
                else:
                    src_id = owner.local_id
                for match in pattern.finditer(line):
                    if rule.target_group is None:  # validated in EdgeRule.__post_init__
                        continue
                    target = match.group(rule.target_group)
                    if not target or target.upper() in self._denylist:
                        continue
                    key = (rule.kind, target)
                    if key in seen_on_line:
                        continue
                    seen_on_line.add(key)
                    result.edges.append(
                        ExtractedEdge(
                            src_local_id=src_id,
                            kind=_EDGE_KINDS[rule.kind],
                            dst_name=target,
                            line=line_no,
                        )
                    )


def _signature(line: str) -> str:
    stripped = line.strip()
    if len(stripped) > _MAX_SIGNATURE_LEN:
        stripped = stripped[:_MAX_SIGNATURE_LEN].rstrip() + "…"
    return stripped


def load_structural_parsers(paths: list[Path]) -> list[StructuralParser]:
    """Build parsers from extractor config files, skipping broken ones.

    A malformed config in one rulebook must not take down indexing for the
    whole workspace — log-and-skip matches how the indexer treats individual
    unparsable files.
    """
    from loguru import logger

    parsers: list[StructuralParser] = []
    for path in paths:
        try:
            parsers.append(StructuralParser(load_structural_config(path)))
        except Exception as exc:
            logger.warning(
                "structural_extractor_config_invalid path={} error={}", path, exc
            )
    return parsers
