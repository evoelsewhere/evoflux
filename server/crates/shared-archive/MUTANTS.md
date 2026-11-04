# P-007 mutation gate

Changed production code is the whole new crate (`src/lib.rs`, `src/output.rs`).
Generate the diff from the repository base with server-relative paths:

```sh
git diff --relative=server origin/migrate/rust-v4 -- crates/shared-archive > archive.diff
cargo mutants --in-diff archive.diff -p evoflux-shared-archive \
  --test-tool nextest --shard 0/3   # then 1/3 and 2/3
```

Shards are zero-based. Each command is wrapped in `timeout 590`.
The first run missed a reversed early-oversize comparison in the copy loop
(`actual > size` to `<`); `files_larger_than_one_copy_buffer_extract_completely`
now extracts a 200 KiB file through several copy chunks in both formats.

Final Windows results (2026-11-03), 78 mutations: **69 caught, 2 unviable,
3 equivalent, 4 untestable on Windows, 0 other missed**.

Equivalent (no observable difference):
- `output.rs` `components`: `||` to `&&` before `*part == ".."`. Both `.` and
  `..` also end with `.`, which the following `ends_with(['.', ' '])` refuses,
  so the result is still `ArchiveError::Path`.
- `output.rs` `create_directory`: match guard `AlreadyExists` to `true`. Any
  other `create_dir` failure means the directory does not exist, so the
  following `open_dir_nofollow` fails too; the result is still an `Io` error
  and nothing is written. Only the wrapped OS error detail differs.
- `output.rs` `Output::entry`: copy buffer `64 * 1024` to `64 + 1024`. The
  buffer size only changes chunking; limits are checked per chunk either way.

Untestable on Windows (`#[cfg(unix)] portable_permissions`, not compiled here):
- replace body with `Ok(())`; `&` to `|`; `&` to `^`; `!=` to `==` in
  `mode & 0o111 != 0`.

## SR-014 (8.3 short-name aliases)

`git diff --relative=server origin/migrate/rust-v4 -- crates/shared-archive`
before the fix commit, `cargo mutants --in-diff ... -p evoflux-shared-archive
--test-tool nextest` (Windows, 2026-11-04): 7 mutations (`components` and the
new `short_name_alias`), **7 caught, 0 missed**.
