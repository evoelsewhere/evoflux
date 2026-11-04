# P-007: shared archive extraction

Python references: `app/plugin_platform/installer.py::_safe_archive_name` and
`_extract_archive`; `app/plugin_platform/marketplaces.py::_extract_repository_subdirectory`;
`app/cli/seed.py::_install_from_github`; ZIP consumers in `app/services/import_service.py`.
This is a shared library, with no mounted HTTP endpoints or contract-test area.
No Python caller or application routing is changed. The workspace's `crates/*`
membership automatically includes this crate; no explicit member edit is needed.

## API

`shared_archive::extract_zip(src: impl Read, dest: impl AsRef<Path>, limits: Limits)`
and `extract_tar_gz` return `Extracted { entries, bytes }`. Entry totals include
logical files and directories; byte totals count actual file contents. The
destination's parent must exist. A destination directory is created if absent;
an existing normal directory is accepted. Existing files are never overwritten.
The API is synchronous: async callers must use the bounded blocking pool and
own cancellation/staging cleanup. An error can leave partial output. Consumers
must extract to disposable staging before publishing, installing or executing.

Defaults: 4096 entries, 120 MiB file contents, 50 MiB input, compression ratio
200. Gzip decoding is additionally bounded by `max_total_bytes` plus an 8 MiB
`max_tar_metadata_bytes` allowance for framing/metadata, including ignored data
after a tar end marker. All gzip members and their checksums are read within that
budget before tar parsing. ZIP ratios apply to each entry; gzip ratios apply to
the entire decoded stream. Limits use checked or saturating arithmetic.

## Confinement and caller responsibilities

Archive filenames are decoded and validated as Unicode before OS path interpretation
(tar names require UTF-8; ZIP retains its format-defined decoding):
no absolute, traversal, empty/dot components, backslash, control characters,
Windows device/stream names, trailing dots/spaces or paths longer than 4096 bytes.
Components shaped like a Windows 8.3 short name (the base name up to the first `.`
ends in `~` and ASCII digits: `LONGDI~1`, `FILENA~12.TXT`, `~1`) are refused on
every OS, because on an 8.3-enabled volume they can open an existing directory
under its long name and bypass the duplicate screening (SR-014). Other names with
`~` are extracted as is: `a~b`, `~tmp`, `a~`, `~`, `a~1b`, `x.y~1`, `back~up.txt`.
Case-colliding names use full Unicode 16 case folding (`caseless`), including
expansions such as sharp-s and final sigma. Archive symbolic/hard links, devices, FIFOs,
GNU sparse records and other special entries are refused, including internal links.

The caller grants access to the destination's parent. The root and each nested
directory are opened with capability-based `open_dir_nofollow`; a path component
cannot redirect the extraction through a link/junction. Files use `create_new`,
so existing hard links and files cannot cause an outside overwrite. Ownership,
setuid and archive write permissions are never applied; Unix files retain only
the portable executable signal (0755 vs 0644), as with Python plugins.

GNU long names and local PAX paths are validated after resolution. Raw tar headers
are checked first so sparse/device/link records cannot trigger special decoding.
PAX record framing is validated; GitHub global comments are accepted, while global
path/size/link overrides and conflicting local PAX/raw header sizes are refused.
The latter is a conservative difference from Python: normal agreeing size fields
work, but ambiguous physical layouts are rejected before either tar pass writes.
ZIP's exact-pinned 9.3.0 iterable API reads EOCD/ZIP64 first and enforces the raw
entry count before parsing per-entry metadata; local/central header consistency
is enforced, and repeated names are preserved for duplicate screening.
Consumers still own plugin-root requirements,
GitHub prefix/subtree selection, digests, installation policy and publish/cleanup.

## Test map

- Python plugin traversal and cross-platform unsafe path tests -> archive path attack
  table for both formats, including Windows junctions without symlink privileges.
- Python invalid ZIP test -> malformed ZIP/gzip and CRC regressions.
- Python normal packing/install content -> nested/Unicode/empty file extraction.
- Installer size/count/ratio protections -> exact-boundary and bomb tests for both.
- Links, existing files/hard links, case collisions -> generated attack archives and
  sentinel-file tests; global/local PAX, GNU long names and metadata bombs -> tar tests.

Python's existing selected archive tests pass (3 cases). Shared library assertions
are Rust unit/integration tests, not HTTP contract tests. Hardening differences
are recorded in `server/KNOWN_DIFFERENCES.md`. Needs security review (path confinement,
archive writes and resource limits).
