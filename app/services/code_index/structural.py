"""Dependency-free by-example structural matching grounded in tree-sitter ASTs."""

from __future__ import annotations

import re
from dataclasses import dataclass

from tree_sitter import Node, Parser
from tree_sitter_language_pack import get_language


@dataclass(frozen=True, slots=True)
class StructuralMatch:
    line_start: int
    line_end: int
    kind: str
    text: str
    captures: dict[str, str]


class StructuralPattern:
    r"""Compile code-index ``\NAME`` and ``\(ARGS*\)`` metavariables.

    Literal whitespace is formatting-insensitive. Candidate text is then
    anchored to the smallest valid named AST node, preventing plain substring
    matches in comments or malformed syntax.
    """

    def __init__(self, pattern: str, *, grammar: str) -> None:
        if not pattern.strip():
            raise ValueError("structural pattern cannot be empty")
        self.pattern = pattern
        self._regex = re.compile(_pattern_regex(pattern), re.MULTILINE | re.DOTALL)
        self._parser = Parser(get_language(grammar))
        self._required_terms = tuple(
            dict.fromkeys(
                term
                for term in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", pattern)
                if not _is_metavariable(pattern, term)
            )
        )

    def match(self, source: str, *, limit: int) -> list[StructuralMatch]:
        if any(term not in source for term in self._required_terms):
            return []
        raw = source.encode("utf-8")
        tree = self._parser.parse(raw)
        byte_offsets = _char_to_byte_offsets(source)
        output: list[StructuralMatch] = []
        seen: set[tuple[int, int]] = set()
        for candidate in self._regex.finditer(source):
            start_byte = byte_offsets[candidate.start()]
            end_byte = byte_offsets[candidate.end()]
            node = _smallest_named_node(tree.root_node, start_byte, end_byte)
            if node is None or node.is_error or _inside_non_code(node):
                continue
            identity = (node.start_byte, node.end_byte)
            if identity in seen:
                continue
            seen.add(identity)
            node_text = raw[node.start_byte : node.end_byte].decode("utf-8", "replace")
            if len(node_text) > 20_000:
                node_text = candidate.group(0)
                start_line = source.count("\n", 0, candidate.start()) + 1
                end_line = source.count("\n", 0, candidate.end()) + 1
            else:
                start_line = node.start_point[0] + 1
                end_line = node.end_point[0] + 1
            output.append(
                StructuralMatch(
                    line_start=start_line,
                    line_end=end_line,
                    kind=node.type,
                    text=node_text,
                    captures={
                        key: value
                        for key, value in candidate.groupdict().items()
                        if value is not None
                    },
                )
            )
            if len(output) >= limit:
                break
        return output


def _pattern_regex(pattern: str) -> str:
    parts: list[str] = []
    used: set[str] = set()
    ordinal = 0
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char.isspace():
            while index < len(pattern) and pattern[index].isspace():
                index += 1
            parts.append(r"\s+")
            continue
        if pattern.startswith(r"\(", index):
            close = pattern.find(r"\)", index + 2)
            if close < 0:
                raise ValueError("unclosed structural sequence metavariable")
            raw_name = pattern[index + 2 : close].rstrip("*").strip()
            name, ordinal = _capture_name(raw_name, ordinal, used)
            # Sequence metavariables are most often used inside argument lists.
            # Keep one balanced-parenthesis level so a candidate cannot drift
            # across unrelated declarations before AST validation.
            parts.append(f"(?P<{name}>(?:[^()]|\\([^()]*\\))*?)")
            index = close + 2
            continue
        if char == "\\":
            match = re.match(r"\\([A-Za-z_][A-Za-z0-9_]*|_)(\*)?", pattern[index:])
            if match is None:
                raise ValueError(f"invalid metavariable near offset {index}")
            raw_name, repeated = match.groups()
            name, ordinal = _capture_name(raw_name, ordinal, used)
            value = r"[\s\S]*?" if repeated else r"[A-Za-z_][A-Za-z0-9_]*"
            parts.append(f"(?P<{name}>{value})")
            index += len(match.group(0))
            continue
        parts.append(re.escape(char))
        index += 1
    return "".join(parts)


def _capture_name(raw: str, ordinal: int, used: set[str]) -> tuple[str, int]:
    base = raw if raw and raw != "_" else f"wildcard_{ordinal}"
    base = re.sub(r"\W", "_", base)
    name = base
    while name in used:
        ordinal += 1
        name = f"{base}_{ordinal}"
    used.add(name)
    return name, ordinal + 1


def _is_metavariable(pattern: str, term: str) -> bool:
    return f"\\{term}" in pattern or f"\\({term}" in pattern


def _char_to_byte_offsets(source: str) -> list[int]:
    offsets = [0]
    total = 0
    for char in source:
        total += len(char.encode("utf-8"))
        offsets.append(total)
    return offsets


def _smallest_named_node(root: Node, start: int, end: int) -> Node | None:
    if start < root.start_byte or end > root.end_byte:
        return None
    current = root
    while True:
        child = next(
            (
                item
                for item in current.named_children
                if item.start_byte <= start and end <= item.end_byte
            ),
            None,
        )
        if child is None:
            return current if current.is_named else None
        current = child


def _inside_non_code(node: Node) -> bool:
    current: Node | None = node
    while current is not None:
        kind = current.type.casefold()
        if (
            "comment" in kind
            or "string" in kind
            or "heredoc" in kind
            or kind in {"regex", "regex_pattern", "template_literal"}
        ):
            return True
        current = current.parent
    return False


__all__ = ["StructuralMatch", "StructuralPattern"]
