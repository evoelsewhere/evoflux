"""Safety boundaries for the bundled document preview engine.

OOXML files are ZIP containers.  Preview parsers must not see an archive until
its central directory has passed inexpensive structural and resource checks.
The cache helpers in this module likewise operate only on names owned by the
preview engine and never follow symlinks while cleaning generated data.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import struct
import time
import zipfile
from pathlib import Path

from app.plugin_platform.previews import (
    DocumentPreviewError,
    DocumentPreviewUnsupportedError,
)

OOXML_PREVIEW_EXTENSIONS = frozenset({".docx", ".xlsx", ".pptx"})

MAX_OOXML_ARCHIVE_ENTRIES = 4_096
MAX_OOXML_CENTRAL_DIRECTORY_BYTES = 8 * 1024 * 1024
MAX_OOXML_EXPANDED_BYTES = 256 * 1024 * 1024
MAX_OOXML_MEMBER_BYTES = 64 * 1024 * 1024
MAX_OOXML_COMPRESSION_RATIO = 200.0
MAX_OOXML_PART_NAME_BYTES = 1_024
MAX_OOXML_CONTENT_TYPES_BYTES = 1024 * 1024

MAX_DOCUMENT_PREVIEW_CACHE_ENTRIES = 96
MAX_DOCUMENT_PREVIEW_CACHE_BYTES = 512 * 1024 * 1024
STALE_DOCUMENT_PREVIEW_TEMP_SECONDS = 24 * 60 * 60

_EOCD_SIGNATURE = b"PK\x05\x06"
_EOCD = struct.Struct("<4s4H2LH")
_CENTRAL_HEADER_SIGNATURE = b"PK\x01\x02"
_CENTRAL_HEADER = struct.Struct("<4s6H3L5H2L")
_CACHE_FILE = re.compile(r"^[0-9a-f]{64}\.html$")
_CACHE_TEMP_FILE = re.compile(r"^(?:\.[0-9a-f]{64}-[^/]+|[0-9a-f]{64})\.tmp$")
_CACHE_PAGE_DIRECTORY = re.compile(r"^[0-9a-f]{64}-pages$")
_EXPECTED_MAIN_PART = {
    ".docx": "word/document.xml",
    ".xlsx": "xl/workbook.xml",
    ".pptx": "ppt/presentation.xml",
}
_ACTIVE_PART_MARKERS = (
    "/activex/",
    "/ctrlprops/",
    "/customui/",
    "/dialogsheets/",
    "/macrosheets/",
    "/vbadata.xml",
    "/vbaproject.bin",
)
_ACTIVE_CONTENT_TYPE_MARKERS = (
    b"macroenabled",
    b"vnd.ms-office.activex",
    b"vnd.ms-office.oleobject",
    b"vnd.ms-office.vbaproject",
)
_DANGEROUS_EMBEDDED_SUFFIXES = frozenset(
    {
        ".bat",
        ".cmd",
        ".com",
        ".dll",
        ".exe",
        ".hta",
        ".jar",
        ".js",
        ".jse",
        ".msi",
        ".ps1",
        ".scr",
        ".vbe",
        ".vbs",
        ".wsf",
    }
)


def _invalid_package() -> DocumentPreviewError:
    return DocumentPreviewError(
        "Could not render this document: invalid or damaged OpenXML package."
    )


def _read_bounded_eocd(source: Path) -> tuple[int, int, int]:
    """Return ``(entry_count, central_size, central_offset)`` without ZipFile.

    ``zipfile.ZipFile`` materializes the complete central directory.  Reading
    its small fixed trailer first lets us reject an excessive entry count or
    central directory before that allocation occurs.
    """

    source_size = source.stat().st_size
    if source_size < _EOCD.size:
        raise _invalid_package()
    tail_size = min(source_size, _EOCD.size + 65_535)
    with source.open("rb") as handle:
        handle.seek(source_size - tail_size)
        tail = handle.read(tail_size)

    cursor = len(tail)
    while True:
        position = tail.rfind(_EOCD_SIGNATURE, 0, cursor)
        if position < 0:
            raise _invalid_package()
        cursor = position
        if position + _EOCD.size > len(tail):
            continue
        (
            _signature,
            disk_number,
            central_disk,
            disk_entries,
            total_entries,
            central_size,
            central_offset,
            comment_size,
        ) = _EOCD.unpack_from(tail, position)
        absolute_position = source_size - tail_size + position
        if absolute_position + _EOCD.size + comment_size != source_size:
            continue
        break

    if disk_number != 0 or central_disk != 0 or disk_entries != total_entries:
        raise DocumentPreviewUnsupportedError(
            "Multi-volume OpenXML packages are not supported by the in-app viewer."
        )
    if (
        total_entries == 0xFFFF
        or central_size == 0xFFFFFFFF
        or central_offset == 0xFFFFFFFF
    ):
        raise DocumentPreviewUnsupportedError(
            "ZIP64 OpenXML packages exceed the in-app preview safety limits."
        )
    if total_entries > MAX_OOXML_ARCHIVE_ENTRIES:
        raise DocumentPreviewUnsupportedError(
            "This OpenXML package contains too many parts for safe preview."
        )
    if central_size > MAX_OOXML_CENTRAL_DIRECTORY_BYTES:
        raise DocumentPreviewUnsupportedError(
            "This OpenXML package has an oversized directory for safe preview."
        )
    if central_offset + central_size != absolute_position:
        raise _invalid_package()

    # Do not trust the EOCD count alone.  A forged small count would otherwise
    # let ZipFile allocate objects for every header in a much larger directory.
    with source.open("rb") as handle:
        handle.seek(central_offset)
        central_directory = handle.read(central_size)
    if len(central_directory) != central_size:
        raise _invalid_package()
    entry_count = 0
    offset = 0
    while offset < len(central_directory):
        if offset + _CENTRAL_HEADER.size > len(central_directory):
            raise _invalid_package()
        fields = _CENTRAL_HEADER.unpack_from(central_directory, offset)
        if fields[0] != _CENTRAL_HEADER_SIGNATURE:
            raise _invalid_package()
        filename_size, extra_size, comment_size, entry_disk = fields[10:14]
        if entry_disk != 0 or filename_size > MAX_OOXML_PART_NAME_BYTES:
            raise DocumentPreviewUnsupportedError(
                "This OpenXML package contains an unsafe part directory."
            )
        offset += _CENTRAL_HEADER.size + filename_size + extra_size + comment_size
        if offset > len(central_directory):
            raise _invalid_package()
        entry_count += 1
        if entry_count > MAX_OOXML_ARCHIVE_ENTRIES:
            raise DocumentPreviewUnsupportedError(
                "This OpenXML package contains too many parts for safe preview."
            )
    if entry_count != total_entries:
        raise _invalid_package()
    return total_entries, central_size, central_offset


def _normalise_part_name(raw_name: str) -> str:
    if not raw_name or "\x00" in raw_name or "\\" in raw_name:
        raise DocumentPreviewUnsupportedError(
            "This OpenXML package contains an unsafe part name."
        )
    if (
        len(raw_name.encode("utf-8", errors="surrogatepass"))
        > MAX_OOXML_PART_NAME_BYTES
    ):
        raise DocumentPreviewUnsupportedError(
            "This OpenXML package contains an oversized part name."
        )
    if raw_name.startswith(("/", "//")) or (
        len(raw_name) >= 2 and raw_name[0].isalpha() and raw_name[1] == ":"
    ):
        raise DocumentPreviewUnsupportedError(
            "This OpenXML package contains an unsafe part name."
        )
    is_directory = raw_name.endswith("/")
    candidate = raw_name[:-1] if is_directory else raw_name
    parts = candidate.split("/")
    if not candidate or any(part in {"", ".", ".."} for part in parts):
        raise DocumentPreviewUnsupportedError(
            "This OpenXML package contains an unsafe part name."
        )
    return "/".join(parts) + ("/" if is_directory else "")


def _reject_active_part(part_name: str) -> None:
    lowered = f"/{part_name.casefold()}"
    if any(marker in lowered for marker in _ACTIVE_PART_MARKERS):
        raise DocumentPreviewUnsupportedError(
            "Documents with macros or active controls cannot be previewed safely."
        )
    if "/embeddings/" in lowered and Path(part_name).suffix.casefold() in (
        _DANGEROUS_EMBEDDED_SUFFIXES
    ):
        raise DocumentPreviewUnsupportedError(
            "Documents with executable embedded content cannot be previewed safely."
        )


def preflight_ooxml_package(source: Path, suffix: str | None = None) -> None:
    """Validate an OOXML ZIP against preview resource and content policy."""

    package_suffix = (suffix or source.suffix).casefold()
    if package_suffix not in OOXML_PREVIEW_EXTENSIONS:
        return

    expected_entries, _central_size, _central_offset = _read_bounded_eocd(source)
    try:
        with zipfile.ZipFile(source) as archive:
            entries = archive.infolist()
            if len(entries) != expected_entries:
                raise _invalid_package()

            expanded_size = 0
            names: dict[str, zipfile.ZipInfo] = {}
            for entry in entries:
                part_name = _normalise_part_name(entry.filename)
                folded_name = part_name.casefold()
                if folded_name in names:
                    raise DocumentPreviewUnsupportedError(
                        "This OpenXML package contains duplicate part names."
                    )
                names[folded_name] = entry

                if entry.flag_bits & 0x1 or entry.flag_bits & 0x40:
                    raise DocumentPreviewUnsupportedError(
                        "Encrypted OpenXML packages cannot be previewed in-app."
                    )
                if entry.compress_type not in {
                    zipfile.ZIP_STORED,
                    zipfile.ZIP_DEFLATED,
                }:
                    raise DocumentPreviewUnsupportedError(
                        "This OpenXML package uses an unsupported compression method."
                    )
                unix_mode = (entry.external_attr >> 16) & 0xFFFF
                if unix_mode and stat.S_ISLNK(unix_mode):
                    raise DocumentPreviewUnsupportedError(
                        "This OpenXML package contains an unsafe symbolic link."
                    )
                if entry.file_size > MAX_OOXML_MEMBER_BYTES:
                    raise DocumentPreviewUnsupportedError(
                        "This OpenXML package contains an oversized part."
                    )
                expanded_size += entry.file_size
                if expanded_size > MAX_OOXML_EXPANDED_BYTES:
                    raise DocumentPreviewUnsupportedError(
                        "This OpenXML package expands beyond the safe preview limit."
                    )
                if entry.file_size:
                    if not entry.compress_size:
                        raise DocumentPreviewUnsupportedError(
                            "This OpenXML package has an unsafe compression ratio."
                        )
                    ratio = entry.file_size / entry.compress_size
                    if ratio > MAX_OOXML_COMPRESSION_RATIO:
                        raise DocumentPreviewUnsupportedError(
                            "This OpenXML package has an unsafe compression ratio."
                        )
                _reject_active_part(part_name)

            required = {
                "[content_types].xml",
                "_rels/.rels",
                _EXPECTED_MAIN_PART[package_suffix],
            }
            if not required.issubset(names):
                raise _invalid_package()

            content_types_info = names["[content_types].xml"]
            if content_types_info.file_size > MAX_OOXML_CONTENT_TYPES_BYTES:
                raise DocumentPreviewUnsupportedError(
                    "This OpenXML package has oversized content metadata."
                )
            content_types = archive.read(content_types_info).lower()
            if any(marker in content_types for marker in _ACTIVE_CONTENT_TYPE_MARKERS):
                raise DocumentPreviewUnsupportedError(
                    "Documents with macros, OLE objects, or active controls cannot be "
                    "previewed safely."
                )
    except DocumentPreviewError:
        raise
    except (OSError, RuntimeError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise _invalid_package() from exc


def cached_preview_is_valid(path: Path, *, max_bytes: int) -> bool:
    """Return true only for a bounded, regular cache file (never a symlink)."""

    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISREG(metadata.st_mode) and 0 < metadata.st_size <= max_bytes


def prepare_preview_cache_directory(cache_directory: Path) -> None:
    """Create the cache directory without accepting a redirected child path."""

    cache_root = cache_directory.parent
    cache_root.mkdir(parents=True, exist_ok=True)
    try:
        metadata = cache_directory.lstat()
    except FileNotFoundError:
        cache_directory.mkdir(mode=0o700)
        return
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise DocumentPreviewError("The document preview cache path is unsafe.")


def _remove_owned_path(path: Path) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        path.unlink(missing_ok=True)
        return
    shutil.rmtree(path, ignore_errors=True)


def _remove_legacy_office_cache(cache_root: Path) -> None:
    # This exact directory was exclusively owned by the removed preview engine.
    # A symlink at the old location is unlinked, never traversed.
    _remove_owned_path(cache_root / "office-previews")


def maintain_preview_cache(
    cache_directory: Path,
    *,
    preserve: Path | None = None,
    now: float | None = None,
) -> None:
    """Prune generated previews and remove safe legacy/transient cache paths."""

    prepare_preview_cache_directory(cache_directory)
    _remove_legacy_office_cache(cache_directory.parent)
    current_time = time.time() if now is None else now
    candidates: list[tuple[int, str, int, Path]] = []

    try:
        entries = list(cache_directory.iterdir())
    except FileNotFoundError:
        return
    for entry in entries:
        name = entry.name
        try:
            metadata = entry.lstat()
        except FileNotFoundError:
            continue
        if _CACHE_FILE.fullmatch(name):
            if stat.S_ISLNK(metadata.st_mode):
                entry.unlink(missing_ok=True)
            elif stat.S_ISREG(metadata.st_mode):
                candidates.append((metadata.st_mtime_ns, name, metadata.st_size, entry))
            continue
        if not (
            _CACHE_TEMP_FILE.fullmatch(name) or _CACHE_PAGE_DIRECTORY.fullmatch(name)
        ):
            continue
        if current_time - metadata.st_mtime < STALE_DOCUMENT_PREVIEW_TEMP_SECONDS:
            continue
        _remove_owned_path(entry)

    candidates.sort()
    entry_count = len(candidates)
    total_bytes = sum(candidate[2] for candidate in candidates)
    for _mtime, _name, size, entry in candidates:
        if (
            entry_count <= MAX_DOCUMENT_PREVIEW_CACHE_ENTRIES
            and total_bytes <= MAX_DOCUMENT_PREVIEW_CACHE_BYTES
        ):
            break
        if preserve is not None and entry == preserve:
            continue
        try:
            entry.unlink()
        except FileNotFoundError:
            pass
        else:
            entry_count -= 1
            total_bytes -= size


def mark_cached_preview_used(path: Path) -> None:
    """Refresh LRU metadata without ever following a replaced symlink."""

    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            return
        os.utime(path, None, follow_symlinks=False)
    except (FileNotFoundError, OSError):
        return


__all__ = [
    "MAX_DOCUMENT_PREVIEW_CACHE_BYTES",
    "MAX_DOCUMENT_PREVIEW_CACHE_ENTRIES",
    "MAX_OOXML_ARCHIVE_ENTRIES",
    "MAX_OOXML_CENTRAL_DIRECTORY_BYTES",
    "MAX_OOXML_COMPRESSION_RATIO",
    "MAX_OOXML_CONTENT_TYPES_BYTES",
    "MAX_OOXML_EXPANDED_BYTES",
    "MAX_OOXML_MEMBER_BYTES",
    "MAX_OOXML_PART_NAME_BYTES",
    "OOXML_PREVIEW_EXTENSIONS",
    "STALE_DOCUMENT_PREVIEW_TEMP_SECONDS",
    "cached_preview_is_valid",
    "maintain_preview_cache",
    "mark_cached_preview_used",
    "preflight_ooxml_package",
    "prepare_preview_cache_directory",
]
