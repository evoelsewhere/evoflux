"""AST-range-aware recursive chunking ported into the local indexing runtime."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

MAX_CHUNK_CHARS = 1_000
MIN_CHUNK_CHARS = 250
CHUNK_OVERLAP_CHARS = 150


class SymbolRange(Protocol):
    id: str
    kind: str
    name: str
    qualified_name: str
    line_start: int
    line_end: int


@dataclass(frozen=True, slots=True)
class ChunkRange:
    ordinal: int
    line_start: int
    line_end: int
    content: str
    symbol_id: str | None
    symbol_name: str | None


@dataclass(slots=True)
class _RangeNode:
    symbol: SymbolRange | None
    start: int
    end: int
    children: list[_RangeNode] = field(default_factory=list)


def split_source(
    *,
    file_path: str,
    text: str,
    symbols: Sequence[SymbolRange],
    max_chars: int = MAX_CHUNK_CHARS,
    min_chars: int = MIN_CHUNK_CHARS,
    overlap_chars: int = CHUNK_OVERLAP_CHARS,
) -> list[ChunkRange]:
    """Keep small definitions whole and recursively split oversized scopes."""
    lines = text.splitlines(keepends=True)
    if not lines and text:
        lines = [text]
    if not lines:
        return []
    root = _build_tree(symbols, len(lines))
    file_symbol = next((item for item in symbols if item.kind == "file"), None)
    pending: list[tuple[int, int, SymbolRange | None]] = []
    _partition(
        pending,
        lines,
        root,
        fallback=file_symbol,
        max_chars=max_chars,
        overlap_chars=overlap_chars,
    )
    pending = _merge_small_ranges(
        pending,
        lines,
        fallback=file_symbol,
        min_chars=min_chars,
        max_chars=max_chars,
    )
    chunks: list[ChunkRange] = []
    for start, end, symbol in pending:
        content = "".join(lines[start - 1 : end]).strip("\n")
        if not content.strip():
            continue
        for bounded_start, bounded_end, bounded_content in _split_content(
            content,
            line_start=start,
            max_chars=max_chars,
            overlap_chars=overlap_chars,
        ):
            chunks.append(
                ChunkRange(
                    ordinal=len(chunks),
                    line_start=bounded_start,
                    line_end=bounded_end,
                    content=bounded_content,
                    symbol_id=symbol.id if symbol else None,
                    symbol_name=(
                        symbol.qualified_name if symbol else Path(file_path).name
                    ),
                )
            )
    return chunks


def _split_content(
    content: str,
    *,
    line_start: int,
    max_chars: int,
    overlap_chars: int,
) -> list[tuple[int, int, str]]:
    """Enforce the hard chunk bound even for minified single-line files."""
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    overlap = max(0, min(overlap_chars, max_chars - 1))
    step = max_chars - overlap
    output: list[tuple[int, int, str]] = []
    offset = 0
    while offset < len(content):
        stop = min(len(content), offset + max_chars)
        raw = content[offset:stop]
        leading = len(raw) - len(raw.lstrip("\n"))
        trailing = len(raw) - len(raw.rstrip("\n"))
        actual_start = offset + leading
        actual_stop = stop - trailing
        section = content[actual_start:actual_stop]
        if section.strip():
            start = line_start + content.count("\n", 0, actual_start)
            final_character = max(actual_start, actual_stop - 1)
            end = line_start + content.count("\n", 0, final_character)
            output.append((start, end, section))
        if stop == len(content):
            break
        offset += step
    return output


def _merge_small_ranges(
    ranges: list[tuple[int, int, SymbolRange | None]],
    lines: list[str],
    *,
    fallback: SymbolRange | None,
    min_chars: int,
    max_chars: int,
) -> list[tuple[int, int, SymbolRange | None]]:
    """Pack adjacent small AST units while preserving the maximum bound."""
    if min_chars <= 0 or len(ranges) < 2:
        return ranges
    ordered = sorted(ranges, key=lambda item: (item[0], item[1]))
    output: list[tuple[int, int, SymbolRange | None]] = []
    index = 0
    while index < len(ordered):
        start, end, owner = ordered[index]
        index += 1
        while index < len(ordered) and _range_size(lines, start, end) < min_chars:
            next_start, next_end, next_owner = ordered[index]
            union_start, union_end = min(start, next_start), max(end, next_end)
            if _range_size(lines, union_start, union_end) > max_chars:
                break
            start, end = union_start, union_end
            if owner is not next_owner:
                owner = fallback
            index += 1
        output.append((start, end, owner))
    if len(output) > 1 and _range_size(lines, *output[-1][:2]) < min_chars:
        previous = output[-2]
        tail = output[-1]
        start, end = min(previous[0], tail[0]), max(previous[1], tail[1])
        if _range_size(lines, start, end) <= max_chars:
            owner = previous[2] if previous[2] is tail[2] else fallback
            output[-2:] = [(start, end, owner)]
    return output


def _range_size(lines: list[str], start: int, end: int) -> int:
    return sum(len(line) for line in lines[start - 1 : end])


def _build_tree(symbols: Sequence[SymbolRange], line_count: int) -> _RangeNode:
    root = _RangeNode(None, 1, line_count)
    candidates = sorted(
        (
            item
            for item in symbols
            if item.kind not in {"file", "module"}
            and item.line_start > 0
            and item.line_end >= item.line_start
        ),
        key=lambda item: (item.line_start, -item.line_end, item.qualified_name),
    )
    stack = [root]
    for symbol in candidates:
        start = min(max(1, symbol.line_start), line_count)
        end = min(max(start, symbol.line_end), line_count)
        while len(stack) > 1 and not (
            stack[-1].start <= start and end <= stack[-1].end
        ):
            stack.pop()
        node = _RangeNode(symbol, start, end)
        stack[-1].children.append(node)
        stack.append(node)
    return root


def _partition(
    output: list[tuple[int, int, SymbolRange | None]],
    lines: list[str],
    node: _RangeNode,
    *,
    fallback: SymbolRange | None,
    max_chars: int,
    overlap_chars: int,
) -> None:
    owner = node.symbol or fallback
    size = sum(len(line) for line in lines[node.start - 1 : node.end])
    if node.symbol is not None and size <= max_chars:
        _emit_bounded(
            output, lines, node.start, node.end, owner, max_chars, overlap_chars
        )
        return
    children = sorted(node.children, key=lambda item: (item.start, item.end))
    if not children:
        _emit_bounded(
            output, lines, node.start, node.end, owner, max_chars, overlap_chars
        )
        return
    cursor = node.start
    for child in children:
        if cursor < child.start:
            _emit_bounded(
                output,
                lines,
                cursor,
                child.start - 1,
                owner,
                max_chars,
                overlap_chars,
            )
        _partition(
            output,
            lines,
            child,
            fallback=fallback,
            max_chars=max_chars,
            overlap_chars=overlap_chars,
        )
        cursor = max(cursor, child.end + 1)
    if cursor <= node.end:
        _emit_bounded(output, lines, cursor, node.end, owner, max_chars, overlap_chars)


def _emit_bounded(
    output: list[tuple[int, int, SymbolRange | None]],
    lines: list[str],
    start: int,
    end: int,
    owner: SymbolRange | None,
    max_chars: int,
    overlap_chars: int,
) -> None:
    segment_start = start
    size = 0
    for line_number in range(start, end + 1):
        line_size = len(lines[line_number - 1])
        if size and size + line_size > max_chars:
            output.append((segment_start, line_number - 1, owner))
            segment_start = line_number
            size = 0
            for previous in range(line_number - 1, start - 1, -1):
                previous_size = len(lines[previous - 1])
                if size + previous_size > overlap_chars:
                    break
                segment_start = previous
                size += previous_size
        size += line_size
    if segment_start <= end:
        output.append((segment_start, end, owner))


__all__ = [
    "CHUNK_OVERLAP_CHARS",
    "ChunkRange",
    "MAX_CHUNK_CHARS",
    "MIN_CHUNK_CHARS",
    "split_source",
]
