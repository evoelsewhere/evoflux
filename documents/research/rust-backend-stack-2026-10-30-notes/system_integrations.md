# Rust crates for EvoFlux system integrations (as of Oct 2026)

Method note: about 20 web searches and fetches. The most reliable evidence is the live `Cargo.toml` files of Zed and openai/codex (codex-rs), fetched 2026-10-30. Some claims under "Inferences" come from the researcher's prior knowledge (cutoff mid-2026) and were not re-verified this session. Each one is tagged **[prior knowledge, unverified]**.

## PTY: portable-pty vs alternatives; ConPTY quality on Windows; production users

### Takeaway
codex-rs uses `portable-pty = "0.9.0"` (wezterm's crate) in its `utils/pty` crate. Zed uses its own fork of `alacritty_terminal` (pinned by git rev), not portable-pty. For a headless backend that streams PTY bytes to a UI, portable-pty is the pragmatic choice. alacritty_terminal is the choice only if you also want a full VT emulator/grid in Rust.

### Cited Findings
- codex-rs workspace pins `portable-pty = "0.9.0"` and has a workspace member `utils/pty` — [codex-rs Cargo.toml](https://raw.githubusercontent.com/openai/codex/main/codex-rs/Cargo.toml)
- Zed pins `alacritty_terminal = { git = "https://github.com/zed-industries/alacritty", rev = "4c129667..." }`. It does not depend on portable-pty — [Zed Cargo.toml](https://raw.githubusercontent.com/zed-industries/zed/main/Cargo.toml)
- Zed's history includes Windows terminal fixes that depended on upstream alacritty changes ("Fix terminal on Windows (#8999)": shell process handle/PID from the child watcher). It also includes an alacritty_terminal upgrade to fix a rare PTY reader panic ("Bad file descriptor") at terminal start. This shows PTY plumbing is a recurring source of bugs even for large editors — [Zed commit #8999](https://git.secluded.site/zed/commit/e85d48495283933610011855af8940434867b1a4); [Zed commit #6715](https://git.secluded.site/zed/commit/252e7e94672ec638d614d630c0444ad685adb88a)
- General ConPTY vs WinPTY context: Eclipse CDT moved to ConPTY because WinPTY had many bugs, some of them unresolvable — [Eclipse CDT commit](https://eclipse.googlesource.com/gerrit/cdt/org.eclipse.cdt/+/4e9223995214cdb2296280e592e1e6ed604bf583%5E%21)

### Inferences
- Recommendation: `portable-pty 0.9` behind a thin internal trait, so the backend could be swapped later. codex-rs is the closest analogue (an agent backend that runs shells) and made this choice.
- **[prior knowledge, unverified]** portable-pty's ConPTY backend loads `conpty.dll` if one sits beside the executable, and otherwise uses the system kernel32 ConPTY. Older inbox ConPTY versions (Windows 10) have known issues: lost output on fast exit, resize redraw quirks, and no passthrough mode. wezterm ships its own `conpty.dll`/`OpenConsole.exe` for this reason. Consider bundling OpenConsole from the Microsoft Terminal releases for consistent behaviour.
- **[prior knowledge, unverified]** portable-pty's reader and writer are blocking `std::io`. Run them on `spawn_blocking` threads and bridge them to tokio channels. Releases are infrequent because the crate lives in the wezterm monorepo.

### Gaps
- Could not get portable-pty release dates, open ConPTY issues, or Warp's PTY stack. Warp's source is closed.

## Process management: tokio::process, process trees, Job Objects, cross-platform tree kill

### Takeaway
Use `tokio::process` together with `process-wrap` (watchexec org, successor to `command-group`, v9.x). It gives Job Objects on Windows, process groups/sessions on POSIX, and kill-on-drop. Set `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` so the whole tree dies when the backend exits or crashes.

### Cited Findings
- process-wrap wraps a `Command` to spawn into a group, session, or job object. It is the successor to command-group, dual Apache-2.0/MIT, and lives in the watchexec org — [process-wrap GitHub](https://github.com/watchexec/process-wrap); [README 9.0.1](https://docs.rs/crate/process-wrap/9.0.1/source/README.md)
- Features: `job-object` (Windows, on by default), `kill-on-drop` (all platforms, Tokio-only), process group (POSIX). For Windows process groups, use `CreationFlags::NEW_PROCESS_GROUP` and/or `JobObject::new()` — [README 9.0.1](https://docs.rs/crate/process-wrap/9.0.1/source/README.md)
- Version 9.0.0 was released 2025-08-09. 9.0.1 is the latest on docs.rs — [ecosyste.ms](https://science.ecosyste.ms/projects/52894); [docs.rs](https://docs.rs/crate/process-wrap/9.0.1/source/README.md)
- Older docs say that when both CreationFlags and JobObject wrappers are used, CreationFlags must come first or include CREATE_SUSPENDED. Not confirmed for v9 — [ecosyste.ms](https://science.ecosyste.ms/projects/52894)
- The raw Win32 pattern: a job with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, with the shell assigned to it, makes the kernel kill all descendants when the last handle closes — [aube windows_job.rs](https://preview.hex.pm/preview/aube/show/crates/aube-scripts/src/windows_job.rs)
- Zed uses `smol` plus a patched fork of `async-process` (`zed-industries/async-process`), not tokio::process. codex-rs uses tokio plus `windows-sys = "0.61.2"` directly — [Zed Cargo.toml](https://raw.githubusercontent.com/zed-industries/zed/main/Cargo.toml); [codex-rs Cargo.toml](https://raw.githubusercontent.com/openai/codex/main/codex-rs/Cargo.toml)

### Inferences
- PTY children: portable-pty spawns its own child, so process-wrap cannot wrap it directly. On Windows, create a job and call `AssignProcessToJobObject` on the PTY child's PID/handle right after spawn, using `windows`/`windows-sys`. On POSIX, the PTY child is already a session leader, so `killpg` on its pgid kills the tree.
- **[prior knowledge, unverified]** `win32job` is a small safe wrapper if you do not want raw windows-sys. A race exists between spawn and assignment (a grandchild could escape). CREATE_SUSPENDED then assign then resume closes it, which is what the process-wrap ordering note is about.

### Gaps
- No watchexec-specific documentation on its tree-kill strategy was found.

## Git: gix vs git2 vs git CLI; worktrees, status/diff, credentials

### Takeaway
Use a hybrid. Use `gix` (gitoxide) for fast read paths: repo discovery, refs, status, blob reads, diffs. Use the `git` CLI for writes, network operations, credentials, and worktree management. That way users' credential helpers, SSH config, hooks, and signing work exactly as in their terminal. codex-rs depends on gix (`0.89.0`, minimal features). Zed's workspace has neither git2 nor gix, and its git crate depends on an `askpass` crate, which points to a CLI-based design.

### Cited Findings
- codex-rs: `gix = { version = "0.89.0", default-features = false, features = ["sha1"] }`, with no git2. Members include `git-utils`, `utils/git-discovery`, and `worktree` — [codex-rs Cargo.toml](https://raw.githubusercontent.com/openai/codex/main/codex-rs/Cargo.toml)
- Zed: no `git2`/`gix` in workspace deps. `crates/git/Cargo.toml` depends on `askpass`, `smol`, `rope`, `sum_tree`, with no libgit2 — [Zed Cargo.toml](https://raw.githubusercontent.com/zed-industries/zed/main/Cargo.toml); [Zed crates/git/Cargo.toml](https://raw.githubusercontent.com/zed-industries/zed/main/crates/git/Cargo.toml)
- gitoxide sub-crate `gix-worktree` is at 0.59.0 (2026-10-22) and 0.58.0 (2026-10-08), showing a very active, roughly biweekly release cadence — [docs.rs gix-worktree](https://docs.rs/crate/gix-worktree/0.58.0)
- An openSUSE advisory says the gitoxide CLI 0.60.0 adds `gix worktree add/remove` and fixes a medium-severity CVE. This is secondary and the CVE ID could not be verified — [openSUSE advisory via linuxsecurity](https://linuxsecurity.com/advisories/opensuse/opensuse-2026-22126-1-gitoxide); [SUSE packagehub](https://packagehub.suse.com/packages/gitoxide/0_56_0-bp160_1_1/)
- gitoxide maintainers acknowledge it is not always as easy to use as git2. The gix docs index "git2" equivalents for migration — [gitoxide PR 1588](https://github.com/GitoxideLabs/gitoxide/pull/1588.patch); [Byron/gitoxide](https://www.Github.com/Byron/gitoxide)

### Inferences
- **[prior knowledge, unverified]** GitButler started on git2 and has been migrating heavily to gix. Byron (gitoxide's author) works with GitButler. Jujutsu uses gix as its git backend and dropped libgit2 for most operations, but shells out to `git` for fetch/push so that credentials and SSH config work. This "gix for local, CLI for network" split matches the codex/Zed evidence.
- Gotchas: gix is pre-1.0 with frequent breaking minor bumps, so pin it exactly and budget upgrade time. Worktree *creation* in the gix library is still young, so shell out to `git worktree add`. git2/libgit2 brings C build pain on Windows (OpenSSL/libssh2) and does not honour `credential.helper` (Git Credential Manager) without hand-written callbacks. That is the main reason to avoid it for network operations.
- On Windows, when shelling out, use `-c core.quotepath=off`, `--no-optional-locks` for status polling, and `GIT_TERMINAL_PROMPT=0`. Use an askpass helper (as Zed does) to route credential prompts to the UI.

### Gaps
- Could not get primary sources for GitButler or Jujutsu's current git backend split, or benchmark numbers for gix status vs git CLI on large Windows repos.

## File watching: notify / notify-debouncer-full

### Takeaway
`notify` 8.x is the default. codex-rs uses `notify = "8.2.0"`, and Zed carries a patched fork. Pair it with `notify-debouncer-full` (rename tracking plus file-ID cache). Expect lost events under load on macOS FSEvents and Windows ReadDirectoryChangesW, and design for periodic rescans.

### Cited Findings
- codex-rs: `notify = "8.2.0"` — [codex-rs Cargo.toml](https://raw.githubusercontent.com/openai/codex/main/codex-rs/Cargo.toml)
- Zed patches crates.io notify with `zed-industries/notify` at rev `d842f16b...`, which indicates upstream bugs they needed fixed — [Zed Cargo.toml](https://raw.githubusercontent.com/zed-industries/zed/main/Cargo.toml)
- Backends: inotify (Linux), FSEvents (macOS), ReadDirectoryChangesW (Windows), plus a poll fallback. The docs point to notify-debouncer-mini/-full for debouncing — [notify docs](https://docs.rs/notify/latest/i686-pc-windows-msvc/notify)
- The docs warn that when watching a very large number of files, notify may miss events. They suggest the PollWatcher as a fallback — [notify docs](https://docs.rs/notify/latest/i686-pc-windows-msvc/notify)

### Inferences
- **[prior knowledge, unverified]** Windows: RDCW buffer overflows produce a rescan-needed condition. Network drives and WSL `\\wsl$` paths do not deliver events, so detect them and switch to polling. Watching a directory can block its deletion or rename on Windows. Linux: the inotify watch limit (`fs.inotify.max_user_watches`) is exhausted by large `node_modules`, so watch recursively but filter with `ignore` rules. macOS FSEvents coalesces events and reports paths with symlinks resolved (`/private/var` vs `/var`).
- Python `watchfiles` already wraps notify, so behaviour parity with the current backend should be high.

### Gaps
- No notify-rs issue-tracker evidence on debouncer-full overflow handling was gathered.

## Code search: ripgrep crates as a library vs bundling rg

### Takeaway
Use `ignore` (gitignore-aware parallel walker) as a library. Both Zed (`ignore = "0.4.22"`) and codex-rs (`ignore = "0.4.23"`, `file-search` crate) do. For content search, either embed `grep-searcher` + `grep-regex` or keep bundling `rg`. Neither Zed nor codex-rs lists the `grep` crates as workspace deps.

### Cited Findings
- Zed: `ignore = "0.4.22"`, `globset = "0.4"` — [Zed Cargo.toml](https://raw.githubusercontent.com/zed-industries/zed/main/Cargo.toml)
- codex-rs: `ignore = "0.4.23"`, `regex = "1.12.3"`, and a `file-search` member. No `grep` crate in the workspace — [codex-rs Cargo.toml](https://raw.githubusercontent.com/openai/codex/main/codex-rs/Cargo.toml)

### Inferences
- **[prior knowledge, unverified]** codex-rs runs `rg` as a subprocess for the model's grep tool and uses `ignore` + `nucleo`/fuzzy matching for file-name search. Zed implements project search in-process with `ignore` plus its own matcher. The grep-* crates (grep-searcher, grep-regex, grep-matcher) are maintained by BurntSushi alongside ripgrep, but their API is low-level, with sink callbacks and no ready-made output formatting. Embedding them removes a binary to ship and sign and gives cancellation and streaming. Bundling rg gives exact CLI parity and `--json` output with almost no code.
- Recommendation: embed `ignore` + `grep-searcher` + `grep-regex` for the in-app search UI. Optionally keep `rg` available for agent shell tool calls, since models know rg's flags.

### Gaps
- Versions and release dates of grep-searcher were not verified this session.

## LSP client

### Takeaway
No Rust LSP *client* crate has an adoption footprint comparable to Zed's or Helix's in-house clients. Zed uses a fork of `lsp-types` and its own `lsp` crate. Recommendation: `lsp-types` (or Zed's fork) plus a small in-house JSON-RPC-over-stdio client on tokio, or evaluate `async-lsp` (supports client mode).

### Cited Findings
- Zed pins `lsp-types = { git = "https://github.com/zed-industries/lsp-types", rev = "82d7fc66..." }`. This forked dependency shows that upstream lsp-types lags or is missing features for real clients — [Zed Cargo.toml](https://raw.githubusercontent.com/zed-industries/zed/main/Cargo.toml)
- Small client crates exist but are immature. `tokio-lsp 0.1.1` (an LSP 3.16 client) and `lsp-client-rs 0.1.0` (subset of the spec, "only tested with gopls") — [tokio-lsp](https://docs.rs/crate/tokio-lsp/latest); [lsp-client-rs](https://docs.rs/crate/lsp-client-rs/latest)

### Inferences
- **[prior knowledge, unverified]** Helix's `helix-lsp` is an in-house tokio client on top of `lsp-types` (Helix has also forked lsp-types as `helix-lsp-types`). `async-lsp` (oxalica) is a tower-style framework usable for both server and client roles. `tower-lsp` is server-only. lsp-types 0.95/0.97 has had slow upstream maintenance, which is why both editors fork it.
- Gotchas: on Windows, LSP servers launched through `.cmd` shims (npm-installed servers) need `cmd /c` or resolution via `which`. Use URI ↔ path conversion carefully (drive-letter case, `file:///C:/`). Kill server process trees via a Job Object.

### Gaps
- Could not verify async-lsp's current version and maintenance status, or Helix's current lsp-types fork.

## Credential vault: keyring v3 and compatibility with Python keyring

### Takeaway
keyring-rs 3.6.x is current and used by codex-rs (`keyring = { version = "3.6", default-features = false }`). It is **not** target-name compatible with Python keyring on Windows by default. Rust uses `username.service`, while Python uses `service`, or `username@service` on collision. Use `Entry::new_with_target(service, service, username)` and fall back to `username@service` to read secrets written by the Python app.

### Cited Findings
- keyring 3.6.3 is latest. v3 has **no default features**, so platform stores must be enabled explicitly (e.g. `apple-native`, `windows-native`, `sync-secret-service`/`async-secret-service`, `linux-native`). All v2 data is forward-compatible — [keyring docs 3.6.3](https://docs.rs/crate/keyring/latest); [README](https://docs.rs/crate/keyring/3.6.3/source/README.md)
- keyring-rs Windows maps (service, user) to the TargetName `username.service` by default. `new_with_target` lets you set an explicit target name — [keyring windows.rs](https://docs.rs/crate/keyring/latest/source/src/windows.rs)
- Python keyring WinVaultKeyring uses `TargetName = service`, `UserName = username`, `Type = CRED_TYPE_GENERIC`, `Persist = CRED_PERSIST_ENTERPRISE` (default). When a second user writes to the same service, the earlier one is moved to `TargetName = f"{username}@{service}"`. Reads check `service` first, then the compound name if UserName mismatches. Values are decoded UTF-16 first, then UTF-8 as fallback — [jaraco/keyring Windows.py](https://raw.githubusercontent.com/jaraco/keyring/main/keyring/backends/Windows.py)
- codex-rs: `keyring = { version = "3.6", default-features = false }`, with a `keyring-store` member — [codex-rs Cargo.toml](https://raw.githubusercontent.com/openai/codex/main/codex-rs/Cargo.toml)
- A split-out `windows-native-keyring-store` crate exists (0.2.0), signalling the keyring v4 "store per crate" re-architecture — [docs.rs windows-native-keyring-store](https://docs.rs/windows-native-keyring-store/0.2.0/src/windows_native_keyring_store/lib.rs.html)

### Inferences
- Windows encoding: keyring-rs writes the password blob as UTF-16 by default for Windows **[prior knowledge, unverified]**, which matches Python's UTF-16-first decode. Verify with a round-trip test.
- **[prior knowledge, unverified]** On macOS, both use generic passwords with service = service and account = username, so they are compatible, but the Keychain ACL is per-app. The Rust binary reading the Python-created item triggers a "allow access" prompt, because the creating app is the Python interpreter. On Linux Secret Service, Python stores attributes `service`, `username`, plus `application: "Python keyring library"`. keyring-rs stores `service`, `username`, `target` attributes. Search by `service`+`username` matches, but verify the collection (`login`/default) and labels.
- Plan for a one-time migration: read with Python-compatible targets, rewrite with the Rust layout or keep Python layout permanently via `new_with_target`.
- Watch for keyring v4 (store-per-crate split), which will change the dependency surface.

### Gaps
- Linux Secret Service attribute compatibility was not verified against source this session.

## PDF text extraction

### Takeaway
`pdfium-render` (Pdfium is the same engine as pypdfium2) gives the closest parity with the current pypdfium2 output. It requires shipping a Pdfium binary per platform, dynamically bundled beside the exe (e.g. bblanchon/pdfium-binaries), or a static build. Pure-Rust options (`pdf-extract`, `lopdf`) avoid native deps but have markedly worse text fidelity.

### Cited Findings
- pdfium-render does not include Pdfium. It supports system dynamic, bundled dynamic, and static linking (`static` feature, `PDFIUM_STATIC_LIB_PATH` = directory). It will not build Pdfium for you. Static builds may need `libstdc++`/`libc++` or the `core_graphics` (macOS) features — [lib.rs pdfium-render](https://www.lib.rs/crates/pdfium-render); [upd.dev mirror](https://upd.dev/ajrcarey/pdfium-render)
- Pdfium supports rendering, text/image extraction, editing, and creation — [lib.rs pdfium-render](https://www.lib.rs/crates/pdfium-render)
- The crate has 68 releases on lib.rs, indicating sustained maintenance — [lib.rs](https://www.lib.rs/crates/pdfium-render)

### Inferences
- **[prior knowledge, unverified]** The pypdfium2 project itself uses bblanchon/pdfium-binaries builds, so bundling the same prebuilt `pdfium.dll`/`libpdfium.dylib`/`.so` (about 5–8 MB) gives identical output to today. `pdf-extract` (built on lopdf) struggles with CID fonts and layout ordering. `mupdf` Rust bindings are AGPL, so avoid them for a commercial desktop app. Pdfium is not thread-safe, so serialize calls on one worker thread (pdfium-render also enforces this).

### Gaps
- No comparative fidelity benchmark was found. The oxidize-pdf crate was not evaluated.

## HTML → Markdown

### Takeaway
`htmd` 0.5.x (a turndown.js port on html5ever, passes turndown's tests, supports tables) is the best general-purpose choice. Zed maintains its own `html_to_markdown` crate. Pre-clean the DOM with `scraper` (removing scripts, nav, and boilerplate) to mimic the BeautifulSoup step.

### Cited Findings
- htmd 0.5.4 is latest. It is inspired by turndown.js, passes turndown's test cases, depends only on html5ever, and converts a 1.37 MB Wikipedia page in about 16 ms (Apple M4). It supports tables and a "faithful" mode that keeps HTML for tags Markdown cannot express. Options and custom tag handlers come via a builder — [htmd docs](https://docs.rs/crate/htmd/latest); [htmd 0.5.0 README](https://docs.rs/crate/htmd/0.5.0/source/README.md)
- Zed has an in-house `html_to_markdown` workspace crate — [Zed Cargo.toml](https://raw.githubusercontent.com/zed-industries/zed/main/Cargo.toml)

### Inferences
- Fidelity vs markdownify: both htmd and markdownify are turndown-like heuristic converters. Expect differences in heading style, bullet chars, and escaping. Configure htmd's options to match current output and write golden tests from existing Python outputs.
- **[prior knowledge, unverified]** `html2md` (based on html5ever) is older and less configurable. `fast_html2md` (spider-rs) targets crawl throughput. Both are viable but have less test parity than htmd.

### Gaps
- No side-by-side fidelity comparison with Python markdownify was found.

## DuckDB, cron, and date/time

### Takeaway
DuckDB: `duckdb` crate 1.4.x with `features = ["bundled"]`. The cost is long C++ compile times and no ICU extension in bundled mode. Cron: `croner` 4.x, which now supports both chrono and jiff via the `CronDateTime` trait. Date/time: chrono is the ecosystem default (Zed, codex both use it). Jiff gives better IANA tz/DST semantics, so prefer jiff for scheduling logic if starting fresh.

### Cited Findings
- duckdb 1.4.4 is recommended as `duckdb = { version = "=1.4.4", features = ["bundled"] }`. Bundled compiles DuckDB via `cc`, which increases build time dramatically, and ships pregenerated bindings. **ICU extension is not included** in bundled mode (crates.io 10 MB limit) — [duckdb 1.4.4 README](https://docs.rs/crate/duckdb/1.4.4/source/README.md); [libduckdb-sys build.rs](https://docs.rs/crate/libduckdb-sys/1.4.4/source/build.rs)
- croner 4.0 introduces a generic `CronDateTime` trait and an optional `jiff` backend (`default = ["chrono"]`, optional `jiff`, `serde`). chrono-tz is no longer bundled, so users of named zones must add `chrono-tz` themselves — [croner 4.0 MIGRATION](https://docs.rs/crate/croner/4.0.0/source/MIGRATION.md); [croner 4.0 Cargo.toml](https://docs.rs/crate/croner/4.0.0/source/Cargo.toml)
- `jiff-cron` 0.3.0 is a separate jiff-based cron crate that handles DST gaps and folds — [jiff-cron](https://docs.rs/crate/jiff-cron/latest)
- chrono-tz embeds the entire tz database into the binary. Jiff can use the system tzdb or embed it — [jiff COMPARE.md](https://git.joshthomas.dev/mirrors/jiff/raw/tag/0.2.10/COMPARE.md)
- Zed uses `chrono 0.4` (no default features). codex-rs uses `chrono = "0.4.43"`. Neither lists jiff — [Zed Cargo.toml](https://raw.githubusercontent.com/zed-industries/zed/main/Cargo.toml); [codex-rs Cargo.toml](https://raw.githubusercontent.com/openai/codex/main/codex-rs/Cargo.toml)

### Inferences
- On Windows there is no system tzdb at `/usr/share/zoneinfo`, so jiff needs its `tzdb-bundle-platform`/bundled feature there **[prior knowledge, unverified]**. chrono-tz is always embedded.
- Bundled DuckDB adds minutes of C++ compile per clean build on Windows MSVC. Cache it in CI (sccache) or link a prebuilt `duckdb.dll` via `DUCKDB_LIB_DIR`.
- croniter parity: croner supports seconds, `L`/`W`/`#` modifiers **[prior knowledge, unverified]**. Test DST transitions against the Python croniter outputs.

### Gaps
- No direct measurements of DuckDB Windows build times. The `cron` and `saffron` crates were not evaluated this session.

## Web search without an API (DuckDuckGo)

### Takeaway
No maintained "ddgs for Rust" exists. Implement it with `reqwest` + `scraper` against `html.duckduckgo.com/html/` (POST) or `lite.duckduckgo.com`. Treat HTTP **202** as a soft block, back off, and fall back to another provider.

### Cited Findings
- DuckDuckGo's HTML endpoint returns HTTP 202 with its homepage instead of results when it detects bots. Generic success checks miss this, and the endpoint rate-limits aggressively — [rust_scrapling search.rs](https://docs.rs/crate/rust_scrapling/latest/source/src/fetchers/search.rs)
- `duckduckgo-search-cli` treats 202 as a distinct "soft-rate-limit" error (exit code 3), separate from 429 — [duckduckgo-search-cli](https://docs.rs/crate/duckduckgo-search-cli/0.1.0)
- `webtools-search` has a DDG Lite provider that also treats 202 as a challenge — [webtools-search ddg.rs](https://docs.rs/crate/webtools-search/0.3.0/source/src/providers/ddg.rs)
- Python duckduckgo_search users report the same "202 Ratelimit" with no clean fix — [agno community](https://community.agno.com/t/duckduckgo-search-rate-limit-issue/1021); [deer-flow discussion](https://github.com/bytedance/deer-flow/discussions/312)
- Third-party advice: use the HTML endpoint (which avoids the vqd token handshake), randomized multi-second delays, and exponential backoff. Proxies can make it worse. This is a vendor blog, so treat it with caution — [apiserpent blog](https://apiserpent.com/blog/scrape-duckduckgo-serp-for-free)

### Inferences
- Make the provider pluggable (DDG HTML, Brave/Tavily/SearXNG with user keys). Python ddgs already rotates across backends for this reason. Scraping may conflict with DDG's terms, which is a product and legal consideration.

### Gaps
- None of the small Rust DDG crates found showed production adoption.

## Command sandboxing

### Takeaway
Follow codex-rs, the most complete open-source reference. It uses Seatbelt (`sandbox-exec` with a generated SBPL profile) on macOS. On Linux it uses Landlock (`landlock = "0.4.4"`) plus seccomp (`seccompiler = "0.5.0"`), now alongside a bubblewrap path. On Windows it uses a restricted token with ACLs on writable roots and a synthetic SID, plus firewall rules for network blocking and an elevated sandbox-user mode. Windows is the hard part and remains less mature.

### Cited Findings
- codex-rs deps: `landlock = "0.4.4"`, `seccompiler = "0.5.0"`. Members: `sandboxing`, `linux-sandbox`, `bwrap`, `windows-sandbox-service`, `windows-sandbox-rs`, `mxc-sandbox`, `utils/sandbox-summary` — [codex-rs Cargo.toml](https://raw.githubusercontent.com/openai/codex/main/codex-rs/Cargo.toml)
- Per platform: Seatbelt on macOS, Landlock+seccomp on Linux (`codex-linux-sandbox`), restricted tokens and ACLs on Windows — [Vaughan: Inside the Codex Sandbox (Apr 2026)](https://codex.danielvaughan.com/2026/04/08/codex-sandbox-platform-implementation/); [Vaughan: Sandbox internals incl. bubblewrap (May 2026)](https://codex.danielvaughan.com/2026/05/03/codex-cli-sandbox-internals-seatbelt-bubblewrap-landlock-windows-dacl/)
- Windows details (third-party summary of OpenAI's May 2026 engineering post): a restricted token whose restricting SIDs are Everyone, the logon SID, and a synthetic `sandbox-write` SID. Write ACLs are granted only on workspace roots. Network is blocked by Windows Firewall outbound-deny rules for a `CodexSandboxOffline` user. On locked-down corporate machines it can fail with `CreateRestrictedToken failed: 87` — [Vaughan: Codex Windows Sandbox (May 2026)](https://codex.danielvaughan.com/2026/05/14/codex-cli-windows-sandbox-engineering-restricted-tokens-acls-elevated-architecture/)
- The original 2025 Windows sandbox commit was "alpha", based on a restricted token derived from an AppContainer profile. The design changed later — [Windows Sandbox Alpha commit mirror](https://forge.lthn.ai/core/core-agent-ide/commit/87cce88f4865685a863e143e0fad4cf5ea542e62)

### Inferences
- Sources are a third-party blog plus repo mirrors, not OpenAI docs directly. Verify against `codex-rs/windows-sandbox-rs` before copying the design. Codex's crates are Apache-2.0, so vendoring or adapting them is an option.
- **[prior knowledge, unverified]** `birdcage` (Phylum) does Landlock+seccomp on Linux and Seatbelt on macOS, but has no Windows support and slow maintenance. `extrasafe` is Linux-only seccomp/Landlock. Neither solves Windows. On Windows, the realistic tiers are: (1) policy and approval only (command allow/deny parsing, the Codex "approval" model); (2) Job Object limits plus a restricted token or low-integrity level; (3) the Codex-style ACL and firewall approach (needs elevation once); (4) AppContainer, which breaks many dev tools.
- Landlock needs kernel ≥5.13 (ABI v1) for filesystem rules and newer ABIs for network rules. Degrade gracefully (the landlock crate supports best-effort mode).

### Gaps
- birdcage and extrasafe maintenance status was not verified this session.

## Secret/PII redaction

### Takeaway
There is no dominant crate. The common pattern is gitleaks' `gitleaks.toml` rules compiled with `regex` (or a `regex::RegexSet` for one-pass matching), plus an entropy check, plus PII regexes. Candidates to study or vendor: `biip`, `veloci` (ex-velociredactor), `keyclaw`, `stakpak-shared::secrets`. codex-rs has its own `secrets` crate.

### Cited Findings
- `biip`: a PII scrubber for text with redactors for usernames, env secrets, IPs, API keys — [biip docs](https://docs.rs/biip)
- `velociredactor`/`veloci`: redacts secrets and PII in text and structured files, preserves structure, uses deterministic numbered tokens, and supports allowlists for false positives — [velociredactor](https://docs.rs/velociredactor); [veloci](https://docs.rs/veloci)
- `keyclaw`: a local proxy keeping secrets out of LLM traffic, using the bundled gitleaks.toml plus an entropy detector — [keyclaw secret-patterns](https://docs.rs/crate/keyclaw/latest/source/docs/secret-patterns.md)
- `stakpak-shared` has a gitleaks-based secrets module with opt-in privacy (PII) rules — [stakpak gitleaks.rs](https://docs.rs/stakpak-shared/0.3.54/src/stakpak_shared/secrets/gitleaks.rs.html)
- codex-rs has a workspace member named `secrets` — [codex-rs Cargo.toml](https://raw.githubusercontent.com/openai/codex/main/codex-rs/Cargo.toml)

### Inferences
- Recommendation: an in-house module that loads gitleaks rules into `regex` (rules needing lookarounds require `fancy-regex`) and adds exact-value redaction of known secrets (keyring values, env vars the app injected). Use `aho-corasick` for exact values. Deterministic placeholder tokens let the agent refer to a secret without seeing it.

### Gaps
- Crate versions, downloads, and maintenance for biip, veloci, and keyclaw were not verified. All appear small or new.

## Logging/observability

### Takeaway
Use `tracing` + `tracing-subscriber` + `tracing-appender` (rolling, non-blocking files) to replace loguru. codex-rs uses exactly this (0.1.44 / 0.3.22 / 0.2.3) plus `opentelemetry`/`opentelemetry-otlp` 0.31. opentelemetry-rust is still 0.x with frequent breaking changes. Logs and metrics are reported stable at the API/SDK level and traces still beta. For Prometheus, prefer `metrics` + `metrics-exporter-prometheus` or OTel's metrics SDK over the older `prometheus` crate.

### Cited Findings
- codex-rs: `tracing = "0.1.44"`, `tracing-subscriber = "0.3.22"`, `tracing-appender = "0.2.3"`, `opentelemetry = "0.31.0"`, `opentelemetry-otlp = "0.31.0"` — [codex-rs Cargo.toml](https://raw.githubusercontent.com/openai/codex/main/codex-rs/Cargo.toml)
- Zed: `tracing = "0.1.40"` and an internal `ztracing` crate — [Zed Cargo.toml](https://raw.githubusercontent.com/zed-industries/zed/main/Cargo.toml); [Zed crates/git Cargo.toml](https://raw.githubusercontent.com/zed-industries/zed/main/crates/git/Cargo.toml)
- A mid-2026 guide says opentelemetry-rust is on the 0.32 line. Logs and metrics are Stable (API/SDK) with OTLP exporters at RC. Everything is still pre-1.0 — [OpenObserve guide](https://openobserve.ai/opentelemetry/rust.md)
- Traces (API, SDK, OTLP) remain beta, and breaking changes are possible in minor versions — [dev.co listing](https://dev.co/observability/open-source/opentelemetry-rust)
- The 1.0 plan targeted early 2025 and slipped — [opentelemetry-rust issue #1678](https://github.com/open-telemetry/opentelemetry-rust/issues/1678)
- The logs path is the `tracing` bridge `opentelemetry-appender-tracing` (Stable) — [fork README](https://github.com/aaronjheng/opentelemetry-rust)

### Inferences
- There is a version conflict: codex pins 0.31 while the guide reports 0.32. Pin all opentelemetry-* crates and `tracing-opentelemetry` to one matched set, because mismatches are the top build issue.
- **[prior knowledge, unverified]** `metrics` (metrics-rs) + `metrics-exporter-prometheus` is lightweight, works well with tracing, and can serve `/metrics` or push. The `prometheus` crate (tikv) is mature but slow-moving. For a local-first desktop app, OTLP export should be opt-in and off by default. `tracing-appender`'s non-blocking `WorkerGuard` must be held for the process lifetime, or logs are lost on exit.

### Gaps
- `tracing-opentelemetry` current version and status were not verified. Download stats for `metrics` vs `prometheus` were not gathered.
