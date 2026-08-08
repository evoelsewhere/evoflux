"""AST-range-aware source partitioning for the internal code index."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from app.services.code_graph.types import NODE_FILE, NODE_MODULE
from app.services.codeindex.source import read_source_records

MAX_CHUNK_CHARS = 8_000


class SymbolRange(Protocol):
    key: str
    kind: str
    name: str
    qualified_name: str
    file_path: str
    language: str
    line_start: int
    line_end: int
    signature: str | None
    docstring: str | None


@dataclass(frozen=True, slots=True)
class SourceChunk:
    component_key: str
    node_key: str | None
    file_path: str
    language: str
    kind: str
    name: str
    qualified_name: str
    line_start: int
    line_end: int
    content: str
    signature: str | None = None
    docstring: str | None = None


@dataclass(slots=True)
class _RangeNode:
    symbol: SymbolRange | None
    start: int
    end: int
    children: list[_RangeNode] = field(default_factory=list)


def build_source_chunks(
    root: str | Path,
    relative_paths: Iterable[str],
    symbols: Sequence[SymbolRange],
    *,
    extensions: frozenset[str],
    max_chars: int = MAX_CHUNK_CHARS,
) -> list[SourceChunk]:
    """Partition source at parser-produced symbol boundaries.

    Small definitions stay intact. Oversized definitions recursively descend
    into their direct child symbols, while text between children remains owned
    by the parent. Files with no extracted symbols fall back to bounded line
    chunks. The result is non-overlapping source coverage rather than one copy
    per nested AST node.
    """
    root_path = Path(root).expanduser().resolve()
    by_file: dict[str, list[SymbolRange]] = {}
    for symbol in symbols:
        by_file.setdefault(symbol.file_path, []).append(symbol)

    chunks: list[SourceChunk] = []
    records = read_source_records(
        root_path,
        relative_paths,
        extensions=extensions,
    )
    for record in records:
        text = record.content.decode("utf-8", errors="replace")
        lines = text.splitlines(keepends=True)
        if not lines and text:
            lines = [text]
        if not lines:
            continue
        file_symbols = by_file.get(record.key, [])
        root_node = _build_range_tree(file_symbols, len(lines))
        file_symbol = next(
            (
                item
                for item in file_symbols
                if item.kind in {NODE_FILE, NODE_MODULE}
            ),
            None,
        )
        counters: dict[str, int] = {}
        _partition_range(
            chunks,
            lines,
            root_node,
            file_path=record.key,
            language=(file_symbol.language if file_symbol else "text"),
            fallback_symbol=file_symbol,
            max_chars=max_chars,
            counters=counters,
        )
    return chunks


def _build_range_tree(symbols: Sequence[SymbolRange], line_count: int) -> _RangeNode:
    root = _RangeNode(symbol=None, start=1, end=line_count)
    candidates = sorted(
        (
            symbol
            for symbol in symbols
            if symbol.kind not in {NODE_FILE, NODE_MODULE}
            and symbol.line_start > 0
            and symbol.line_end >= symbol.line_start
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
        node = _RangeNode(symbol=symbol, start=start, end=end)
        stack[-1].children.append(node)
        stack.append(node)
    return root


def _partition_range(
    output: list[SourceChunk],
    lines: list[str],
    node: _RangeNode,
    *,
    file_path: str,
    language: str,
    fallback_symbol: SymbolRange | None,
    max_chars: int,
    counters: dict[str, int],
) -> None:
    symbol = node.symbol or fallback_symbol
    # The virtual file root always descends into top-level symbols so exact
    # declarations retain their own searchable identity even in small files.
    # Real symbols stay intact until their source exceeds the chunk bound.
    if node.symbol is not None and _range_length(lines, node.start, node.end) <= max_chars:
        _emit_bounded(
            output,
            lines,
            node.start,
            node.end,
            symbol=symbol,
            file_path=file_path,
            language=language,
            max_chars=max_chars,
            counters=counters,
        )
        return

    children = sorted(node.children, key=lambda item: (item.start, item.end))
    if not children:
        _emit_bounded(
            output,
            lines,
            node.start,
            node.end,
            symbol=symbol,
            file_path=file_path,
            language=language,
            max_chars=max_chars,
            counters=counters,
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
                symbol=symbol,
                file_path=file_path,
                language=language,
                max_chars=max_chars,
                counters=counters,
            )
        _partition_range(
            output,
            lines,
            child,
            file_path=file_path,
            language=language,
            fallback_symbol=fallback_symbol,
            max_chars=max_chars,
            counters=counters,
        )
        cursor = max(cursor, child.end + 1)
    if cursor <= node.end:
        _emit_bounded(
            output,
            lines,
            cursor,
            node.end,
            symbol=symbol,
            file_path=file_path,
            language=language,
            max_chars=max_chars,
            counters=counters,
        )


def _range_length(lines: list[str], start: int, end: int) -> int:
    return sum(len(line) for line in lines[start - 1 : end])


def _emit_bounded(
    output: list[SourceChunk],
    lines: list[str],
    start: int,
    end: int,
    *,
    symbol: SymbolRange | None,
    file_path: str,
    language: str,
    max_chars: int,
    counters: dict[str, int],
) -> None:
    segment_start = start
    length = 0
    for line_number in range(start, end + 1):
        line_length = len(lines[line_number - 1])
        if length and length + line_length > max_chars:
            _append_chunk(
                output,
                lines,
                segment_start,
                line_number - 1,
                symbol=symbol,
                file_path=file_path,
                language=language,
                counters=counters,
            )
            segment_start = line_number
            length = 0
        length += line_length
    if segment_start <= end:
        _append_chunk(
            output,
            lines,
            segment_start,
            end,
            symbol=symbol,
            file_path=file_path,
            language=language,
            counters=counters,
        )


def _append_chunk(
    output: list[SourceChunk],
    lines: list[str],
    start: int,
    end: int,
    *,
    symbol: SymbolRange | None,
    file_path: str,
    language: str,
    counters: dict[str, int],
) -> None:
    content = "".join(lines[start - 1 : end]).strip("\n")
    if not content.strip():
        return
    kind = symbol.kind if symbol else NODE_FILE
    name = symbol.name if symbol else Path(file_path).name
    qualified_name = symbol.qualified_name if symbol else file_path
    identity = f"{file_path}\x1f{kind}\x1f{qualified_name}"
    part = counters.get(identity, 0)
    counters[identity] = part + 1
    output.append(
        SourceChunk(
            component_key=f"{identity}\x1f{part}",
            node_key=symbol.key if symbol else None,
            file_path=file_path,
            language=language,
            kind=kind,
            name=name,
            qualified_name=qualified_name,
            line_start=start,
            line_end=end,
            content=content,
            signature=symbol.signature if symbol else None,
            docstring=symbol.docstring if symbol else None,
        )
    )


__all__ = ["MAX_CHUNK_CHARS", "SourceChunk", "build_source_chunks"]
