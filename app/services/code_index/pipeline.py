"""Pure source-to-target pipeline with stable, file-owned desired state."""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path
from dataclasses import dataclass

from app.services.code_index.parsers.registry import ParserRegistry, default_registry
from app.services.code_index.chunking import split_source
from app.services.code_index.file_matcher import SourceRecord
from app.services.code_index.languages import fallback_language
from app.services.code_index.semantic import embed_text

_REGISTRY = default_registry()


@dataclass(frozen=True, slots=True)
class SourceFileRow:
    file_path: str
    language: str
    fingerprint: str
    byte_size: int
    modified_ns: int
    changed_ns: int
    content: str
    processor: str
    graph_enabled: int


@dataclass(frozen=True, slots=True)
class SourceChunkRow:
    id: str
    file_path: str
    language: str
    line_start: int
    line_end: int
    content: str
    embedding: bytes
    symbol_id: str | None
    symbol_name: str | None


@dataclass(frozen=True, slots=True)
class SymbolRow:
    id: str
    local_id: str
    file_path: str
    language: str
    kind: str
    name: str
    qualified_name: str
    line_start: int
    line_end: int
    signature: str | None
    docstring: str | None


@dataclass(frozen=True, slots=True)
class RelationRow:
    id: str
    src_id: str
    kind: str
    dst_id: str | None
    dst_name: str | None
    module_path: str | None
    local_name: str | None
    file_path: str
    line: int | None


@dataclass(frozen=True, slots=True)
class FileState:
    source: SourceFileRow
    chunks: tuple[SourceChunkRow, ...]
    symbols: tuple[SymbolRow, ...]
    relations: tuple[RelationRow, ...]


def stable_id(*parts: object) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(str(part).encode("utf-8", "surrogatepass"))
        digest.update(b"\0")
    return digest.hexdigest()


def processing_identity(
    file_path: str,
    language_override: str | None = None,
    *,
    registry: ParserRegistry | None = None,
) -> str:
    """Identify parser + local implementation so parser edits invalidate targets."""
    extension = Path(file_path).suffix.casefold()
    if registry is not None:
        return _processing_identity_for_registry(extension, language_override, registry)
    return _processing_identity(extension, language_override)


@lru_cache(maxsize=64)
def _processing_identity(extension: str, language_override: str | None) -> str:
    """Cache implementation digests by parser identity, not by every file path."""
    return _processing_identity_for_registry(extension, language_override, _REGISTRY)


def _processing_identity_for_registry(
    extension: str,
    language_override: str | None,
    registry: ParserRegistry,
) -> str:
    parser = (
        registry.for_language(language_override)
        if language_override
        else registry.for_path(f"source{extension}")
    )
    digest = hashlib.sha256()
    digest.update(b"evoflux-code-context-pipeline\0")
    if parser is None:
        digest.update(
            f"search-only:{language_override or fallback_language(f'source{extension}')}".encode()
        )
    else:
        digest.update(
            f"{type(parser).__module__}:{type(parser).__qualname__}:"
            f"{parser.name}:{getattr(parser, 'grammar', '')}".encode()
        )
        config = getattr(parser, "config", None)
        if config is not None:
            digest.update(config.model_dump_json().encode("utf-8"))
    package = Path(__file__).parent
    implementation = [
        package / "chunking.py",
        package / "pipeline.py",
        package / "semantic.py",
        package / "languages.py",
        package / "graph_types.py",
        package / "parsers" / "base.py",
        package / "parsers" / "registry.py",
        Path(str(__import__(type(parser).__module__, fromlist=["x"]).__file__))
        if parser is not None
        else package / "file_matcher.py",
    ]
    for path in implementation:
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(str(path).encode("utf-8", "replace"))
    return digest.hexdigest()


def build_file_state(
    record: SourceRecord, *, registry: ParserRegistry | None = None
) -> FileState:
    """Parse one keyed component and declare all rows it owns."""
    active_registry = registry or _REGISTRY
    parser = (
        active_registry.for_language(record.language_override)
        if record.language_override
        else active_registry.for_path(record.key)
    )
    text = record.content.decode("utf-8")
    if parser is None:
        language = record.language_override or fallback_language(record.key)
        if language is None:
            raise ValueError(f"No parser or search-only language for {record.key}")
        file_id = stable_id(record.key, "file")
        symbols = [
            SymbolRow(
                id=file_id,
                local_id="file",
                file_path=record.key,
                language=language,
                kind="file",
                name=record.key,
                qualified_name=record.key,
                line_start=1,
                line_end=max(1, len(text.splitlines())),
                signature=None,
                docstring=None,
            )
        ]
        relations: list[RelationRow] = []
    else:
        parsed = parser.parse(file_path=record.key, source=record.content)
        language = parsed.language

        ids: dict[str, str] = {}
        symbols = []
        for node in parsed.nodes:
            symbol_id = stable_id(record.key, node.local_id)
            ids[node.local_id] = symbol_id
            symbols.append(
                SymbolRow(
                    id=symbol_id,
                    local_id=node.local_id,
                    file_path=record.key,
                    language=language,
                    kind=node.kind,
                    name=node.name,
                    qualified_name=node.qualified_name,
                    line_start=node.line_start,
                    line_end=node.line_end,
                    signature=node.signature,
                    docstring=node.docstring,
                )
            )

        relations = []
        seen_relations: set[str] = set()
        for edge in parsed.edges:
            source_id = ids.get(edge.src_local_id)
            if source_id is None:
                continue
            target_id = ids.get(edge.dst_local_id) if edge.dst_local_id else None
            relation_id = stable_id(
                record.key,
                source_id,
                edge.kind,
                target_id,
                edge.dst_name,
                edge.module_path,
                edge.local_name,
                edge.line,
            )
            if relation_id in seen_relations:
                continue
            seen_relations.add(relation_id)
            relations.append(
                RelationRow(
                    id=relation_id,
                    src_id=source_id,
                    kind=edge.kind,
                    dst_id=target_id,
                    dst_name=edge.dst_name,
                    module_path=edge.module_path,
                    local_name=edge.local_name,
                    file_path=record.key,
                    line=edge.line,
                )
            )

    chunk_rows = tuple(
        SourceChunkRow(
            id=stable_id(
                record.key,
                chunk.ordinal,
                chunk.line_start,
                chunk.line_end,
                chunk.content,
            ),
            file_path=record.key,
            language=language,
            line_start=chunk.line_start,
            line_end=chunk.line_end,
            content=chunk.content,
            embedding=embed_text(chunk.content),
            symbol_id=chunk.symbol_id,
            symbol_name=chunk.symbol_name,
        )
        for chunk in split_source(file_path=record.key, text=text, symbols=symbols)
    )
    return FileState(
        source=SourceFileRow(
            file_path=record.key,
            language=language,
            fingerprint=record.fingerprint,
            byte_size=len(record.content),
            modified_ns=record.modified_ns,
            changed_ns=record.changed_ns,
            content=text,
            processor=record.processor,
            graph_enabled=int(parser is not None),
        ),
        chunks=chunk_rows,
        symbols=tuple(symbols),
        relations=tuple(relations),
    )


__all__ = [
    "FileState",
    "RelationRow",
    "SourceChunkRow",
    "SourceFileRow",
    "SymbolRow",
    "build_file_state",
    "processing_identity",
    "stable_id",
]
