# P-005: shared .env reader and writers

Reference: python-dotenv **1.2.2**, `dotenv/parser.py`, `variables.py`, and
`main.py` (`dotenv_values` with interpolation and override enabled);
`app/cli/seed.py::write_env_credentials` and
`app/api/routes/mcp.py::_save_env_values`.

This library has no routes or process-environment side effects. Its lookup closure
is supplied by the caller. Order is the first insertion order even when duplicate
keys replace a value; resolution happens immediately, with prior bindings shadowing
the injected environment (including `None` and empty strings). Defaults are used
only for absent names, not empty or bare bindings. Single-quoted values interpolate
too. Quoted backslashes decode only the Python parser's explicit escape sets;
malformed statements recover at the parser's current line position. A BOM is part
of the first key, and file CRLF and CR are normalized as Python text reads do.

Writer profiles reproduce Python's line matching, duplicate replacements, splitlines
(including Unicode separators), header, annotation placement and final newline.
`Quote::None` selects credential matching, including bare keys; `Quote::Double`
selects MCP assignment-only matching and its empty-batch no-op. Empty-removal,
header and comments can be configured independently. Duplicate update names use
the last value in first insertion order, like constructing a Python dict.
Comments are trusted caller annotations, not untrusted credential values.

Text output uses native line endings, including CRLF on Windows, just like the
Python writers' text streams. Fixture generation calls both actual writers with
real text streams for LF and CRLF; integration tests compare the matching bytes.
No newline normalization is done to either expected or actual bytes in the tests.
Invalid UTF-8 is an error, and only NotFound means a new file for the writer.
Like Python's `_is_file_or_fifo`, `read` selects regular files and Unix FIFOs,
returning an empty map for missing paths, failed metadata lookups and unsupported
types (including directories). Errors opening/reading a selected file propagate.

The two owner-approved differences (atomic MCP writes and input validation) are in
[`KNOWN_DIFFERENCES.md`](../../KNOWN_DIFFERENCES.md#shared-dotenv-p-005-servercratesshared-dotenv).
All batch inputs are validated before filesystem access. Tempfile creation, writes,
fsync and atomic persist run inside `spawn_blocking`; other I/O uses `tokio::fs`.
`tempfile`'s default and explicit Unix mode are 0600. Windows inherits the parent
directory ACL, as Python does; Unix permission bits do not describe Windows ACLs.
Tempfiles clean up on write/sync/persist failure. Existing symlink targets are read,
but the link itself is replaced, as with Python's credential writer. Callers must
serialize concurrent merges and choose trusted paths/directories; this crate adds
no locking or path confinement. File fsync precedes rename; directory fsync is not
part of Python's writer contract.

## Test map

- `tests/fixtures/gen_fixtures.py` calls `dotenv_values(path)` twice per reader text
  with isolated empty/fixed environments, and calls both actual Python writers.
- `tests/parity.rs` compares ordered reader pairs (both `parse` and `read`) and
  writer bytes, created flags, empty MCP no-op and temporary-file cleanup.
- `src/tests.rs` covers refused names/values, validation before creating parents,
  no secrets in error Display/Debug, invalid UTF-8, I/O failures, atomic replacement
  via a hard-link snapshot, failed replacement preserving old bytes, and Unix 0600.
- No HTTP contract tests: shared library, no caller cutover in this task.

Security review remains required before callers use these credential file writes.
