# Tool sandbox security follow-up

Python references: `app/agent/sandbox_config.py::load_config`,
`app/agent/sandbox.py::{SandboxConfig.__init__,_is_denied,validate_path}` and
`app/agent/tools/builtin/filesystem/{read,ls,glob,grep}.py`.

DS3-003: `ToolCtx.denied_patterns` is loaded once per turn by chat-core, off the
runtime with `evoflux-shared-yaml`. Missing policy supplies no additional
patterns; invalid YAML, invalid pattern types or unreadable policy emits a
warning and supplies no user patterns. Nonblank strings are preserved exactly.
The built-in `.env` floor is independent of the saved policy. Custom patterns
use Python's case-sensitive matching on the resolved POSIX path. This reader
consumes the denied-pattern field only. Explicit-path errors preserve Python's
wording. Per-hit glob/grep filtering is intentional hardening: Python only
validates their search roots. `ls` validates its explicit path as Python does;
ordinary child entries preserve parity. Registry permissions, tool specs and
observation outputs are unchanged. Write/edit are still unavailable in Rust
(`PYTHON_ONLY_TOOLS`); their eventual ports must use this same policy before
mutation. No filesystem writes were enabled by this change.

DS3-004: `ls` filters refused links before following entries for type/size.
Both glob modes check resolved hits before reading timestamps; explicit glob
components refuse links into denied directories. Junction tests run on Windows;
file-symlink tests print a skip notice where privileges are absent.

SR-008: the base already cleared the fnmatch cache at 4,096 entries. The new
Weak-reference test observes eviction, rather than just checking that matching
still works. Removing the cap deliberately made it fail (4,097 retained).

Regression map: saved-policy Python contracts -> explicit-path errors for all
four available filesystem tools; Rust `tests/security.rs` -> Tool::call policy
propagation and both glob modes/grep discovery; chat-core flow test -> real
turn propagation and reload after settings change; sandbox unit -> custom case
semantics, resolved links, open guard and built-in floor; loader unit -> YAML
1.1, merge keys, blank strings, missing/invalid/unreadable files; listing units
-> outside links; fnmatch unit -> eviction and matching after eviction.

Needs security review: sandbox policy and path confinement.

## Verification on Windows

- `bash scripts/migration/gates.sh shared`: passed lint fixture, formatting,
  workspace clippy, **841/841** workspace nextest tests, dependency checks and
  shared path check. `cargo metadata --locked` and the server build also passed.
- `TARGET=rust ... pytest contract-tests/tools -q --no-cov`: **10 passed,
  1 skipped** (Rust specs are checked by nextest).
- `TARGET=python ... pytest contract-tests/tools -q --no-cov`: normal PATH has
  the pre-existing `test_tools_match_golden` mismatch when Python selects `rg`;
  reproduced in a clean `origin/migrate/rust-v4` checkout. With `rg` absent from
  the test process, **8 passed, 3 skipped** (documented Rust discovery hardening).
  Existing golden assertions and snapshots were preserved.
- Python chat-core contracts: **14 passed, 1 skipped, 1 pre-existing failure**.
  `test_python_reads_history_written_by_this_target` returns 500 on the next
  Python turn after restart; the same test fails on the clean integration base.
- `TARGET=rust ... pytest contract-tests/chat-core -q --no-cov -n 4`: **16 passed**.
- Scoped mutation results are in `MUTANTS.md`; no final missed candidates.
- `uv run ruff check contract-tests/tools`, `uv run ruff format --check
  contract-tests/tools` and `git diff --check`: passed.
- Linux/macOS checks were not run locally. File symlink creation lacks a Windows
  privilege here; junction tests run. Tools have no HTTP/OpenAPI route to diff.
