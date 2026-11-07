# Office documents: runtime, preview and skills

| | |
| --- | --- |
| Status | Implemented (live check in the app pending) |
| Area | crate `evo-office`, engine, RPC, desktop shell, desktop UI |
| Created | 2026-11-07 |
| Updated | 2026-11-07 |
| ADD sections | [Crates](../../architecture/README.md), [Desktop app](../../architecture/README.md) |
| ADRs | [0008 Optional LibreOffice runtime for Office documents](../../architecture/decisions/0008-optional-libreoffice-runtime.md) |
| Related | [Code intelligence](../code-intelligence/sdd.md) (same install-on-demand pattern), [Customize](../customize-skills-plugins-connectors/sdd.md) |

## 1. Summary

evo v3 could open, render and edit Word, PowerPoint and Excel files because it
shipped an optional, downloadable LibreOffice runtime plus three Office skills.
v4 has neither. This feature brings that capability to the Rust engine: the
person installs a trimmed LibreOffice runtime from Settings with one click
(checksum-pinned, resumable, cancellable); the Files tool then previews
`.docx/.pptx/.xlsx` (and legacy/ODF siblings) as Office lays them out; agent
shells see the runtime (`EVO_SOFFICE`, PATH); and the `docx`, `pptx` and `xlsx`
skills ship with the app.

v3's HTML re-implementation of the three formats (a fallback used when no
runtime was installed) is **not** ported: without the runtime the preview says
so and offers the install, nothing else.

## 2. Scope

### 2.1 Goals

- Install, cancel, resume, uninstall and report the runtime from Settings, with
  byte progress; no restart needed to use it.
- Exact Office → PDF conversion with a hardened LibreOffice profile, serialized,
  with a timeout that kills the whole process tree.
- Files preview of Office documents (and of plain PDFs) in the desktop app.
- The runtime is visible to the agent's `bash`/`powershell` tools as
  `EVO_SOFFICE` and on `PATH`, live (installing it takes effect in running chats).
- Office skills (docx, pptx, xlsx) embedded in the engine and always available.

### 2.2 Non-goals

- A fallback HTML renderer, live "deck/workbook under construction" previews and
  annotation-driven editing (all v3 viewer features).
- Editing Office files in the app. The agent edits through the skills.
- Bundling LibreOffice in the installer (size); it stays an on-demand download.
- A system-installed LibreOffice as the preview engine. Only the pinned runtime
  is used for preview (reproducible output); skills still fall back to a
  `soffice` on `PATH`.

## 3. Requirements

### 3.1 Functional

| ID | Requirement | Acceptance check |
| --- | --- | --- |
| FR-1 | `office_status` reports platform support, pinned version, download/installed sizes, the installed version and the install job. | Unit test on the status of an empty home; the app shows the state. |
| FR-2 | `office_install` downloads the pinned archive, verifies size and SHA-256 before extracting, extracts only under `soffice/`, activates atomically, and removes older versions. | Tests with `file://` manifests: a good archive installs; wrong hash, wrong size, traversal, link escape, duplicate path and special file all fail without activating. |
| FR-3 | A failed or interrupted download resumes from the partial file (HTTP Range); a server that ignores Range restarts it. | Test with a local HTTP server. |
| FR-4 | `office_cancel_install` stops downloading/verifying and discards the partial; it is refused during extraction. | Test. |
| FR-5 | `office_uninstall` removes the runtime (not while installing). | Test. |
| FR-6 | `office_convert` turns a document into a cached PDF; a second call with an unchanged file is served from the cache; the cache is pruned by size. | Test with a fake `soffice`; real conversion checked in the app. |
| FR-7 | Conversions never run concurrently; a hang is killed (process tree) at the timeout; a fresh profile's first-run exit is retried once. | Test with a fake `soffice`. |
| FR-8 | Agent shells get `EVO_SOFFICE` and the runtime directory appended to `PATH` once the runtime is installed, without restarting chats. | Test of the shell-env provider; run `echo $EVO_SOFFICE` in a chat. |
| FR-9 | Files shows `.docx .doc .odt .rtf .pptx .ppt .odp .xlsx .xls .ods` as rendered pages, and `.pdf` as pages. With no runtime it shows an install prompt. | Manual check in the running app. |
| FR-10 | The docx/pptx/xlsx skills are listed in Customize and loadable without any user setup. | Engine test that the skills load from the extracted directory. |

### 3.2 Non-functional

| ID | Requirement | Acceptance check |
| --- | --- | --- |
| NFR-1 | Streamed download and hashing; archive up to 1 GiB, extracted up to 4 GiB, 60 000 entries. | Limits tested. |
| NFR-2 | Windows x64, macOS (x64, arm64), Linux x64. Other platforms report "not available". | `platform_key` test. |
| NFR-3 | No network access except the pinned HTTPS URL, and only when the person asks. | Review. |
| NFR-4 | Conversion of a 20-page document under 30 s on a laptop (after profile init). | Manual timing. |

## 4. Context and constraints

- v3 implementation (tag `v3.1.1`: `app/services/office_runtime/*`,
  `scripts/build_libreoffice_runtime.py`, `.github/workflows/office-runtime.yml`)
  is the reference. Its assets are already published as release
  `office-runtime-26.8.0` (four platforms); the pins are carried over unchanged.
- Same install-on-demand shape as language servers (`evo-lsp`, RPC
  `install_language_server`, polled by the UI): see
  [Code intelligence](../code-intelligence/sdd.md).
- ADD rules: the engine owns logic, the shell relays; layers point down;
  tool output and documents are untrusted; real engine in the app.
- LibreOffice is MPL-2.0; the bundle is downloaded, not redistributed inside evo.
- The skills are Apache-2.0 (kept, with their LICENSE files). Their scripts run
  through `uv run --with …` and `bun`, as in v3; evo does not ship Python.

## 5. Design

### 5.1 Overview

```text
Settings ──RPC──► engine ──► evo-office::Runtime ──► <agent>/runtimes/libreoffice/
Files ──office_convert──► engine office.rs (cache) ──► soffice --headless --convert-to pdf
Files ◄── pdf path ───────┘      └─ fs_read_bytes (shell) ──► pdf.js pages
agent bash/powershell ◄── EVO_SOFFICE, PATH (shell-env provider reads install.json)
skills: embedded in engine ──► <agent>/bundled-skills/ (extracted on start) ──► skill loader
```

`evo-office` is a leaf crate: it knows the manifest, the archive format and how
to run `soffice`, not chats, RPC or the desktop. The engine owns the single
`Runtime` for the process, the preview cache and the RPC methods.

### 5.2 Components

| Layer | Path | Responsibility |
| --- | --- | --- |
| crate | `crates/evo-office/src/manifest.rs` | Pinned assets per platform, validation, test override |
| crate | `crates/evo-office/src/install.rs` | Job state machine, resumable verified download, safe extraction, atomic activation, uninstall |
| crate | `crates/evo-office/src/convert.rs` | Hardened profile, serialized conversion, retry, timeout and tree kill |
| engine | `crates/evo-engine/src/office.rs` | Process-wide `Runtime`, RPC bodies, preview cache, shell-env provider, embedded skills |
| engine | `crates/evo-engine/src/modes.rs` | RPC dispatch (`office_*`) |
| engine | `crates/evo-engine/src/session.rs` | Builtin tools get the shell-env provider |
| engine | `crates/evo-engine/bundled-skills/` | The three skills |
| crate | `crates/evo-tools/src/os_env.rs` | `OsExecutionEnv::with_shell_env_provider` (dynamic env) |
| desktop shell | `apps/desktop/src-tauri/src/files.rs` | `fs_read_bytes` (raw bytes over IPC) |
| desktop UI | `apps/desktop/src/features/settings/sections/office-settings.tsx` | Install, progress, cancel, retry, uninstall |
| desktop UI | `apps/desktop/src/features/files/document-viewer.tsx` | Convert via engine, render PDF pages with pdf.js |

### 5.3 Interfaces

RPC (JSONL, like `list_language_servers`). The `office_*` management commands
all answer with the status object.

```jsonc
// requests: office_status, office_install, office_cancel_install,
//           office_dismiss_error, office_uninstall
// response (status):
{ "available": true, "platform": "win32-x64", "version": "26.8.0",
  "downloadBytes": 191184974, "installBytes": 635851559,
  "installedVersion": null,
  "job": { "phase": "downloading|verifying|extracting|failed",
           "version": "26.8.0", "bytesDone": 0, "bytesTotal": 191184974,
           "startedAt": "…", "error": null } }

// request  office_convert { "path": "C:/…/report.docx" }
// response { "pdf": "C:/Users/…/.evo/agent/cache/office/<key>.pdf",
//            "version": "26.8.0", "cached": false }
// errors: "not installed" | "unsupported type" | "too large" | "conversion failed: …"
```

Tauri: `fs_read_bytes(path) -> raw bytes` (max 200 MB, files only).

Older engines answer unknown request types with their usual error; the UI shows
it as "update evo".

### 5.4 Data and storage

- `<agent>/runtimes/libreoffice/<version>/soffice/…` — the active runtime.
- `<agent>/runtimes/libreoffice/install.json` — `{id, version, platform, sha256, executable, installedAt}`.
- `<agent>/runtimes/libreoffice/profile/` — the hardened shared LibreOffice profile.
- `<agent>/runtimes/libreoffice/.download-<sha>.part`, `.staging-*` — transient.
- `<agent>/cache/office/<key>.pdf` — conversions; key = SHA-256 of
  `(canonical path, mtime, size, runtime version)`; pruned to 256 MiB, oldest first.
- `<agent>/bundled-skills/<engine version>/…` — extracted skills.
- No database change.

### 5.5 Behaviour

Install: `idle → downloading → verifying → extracting → (activated | failed)`.
Cancel is accepted in the first two phases. A failure keeps the partial download
so Retry resumes; a checksum failure deletes it. Starting an install clears
leftovers of other versions.

Convert: copy the source to `document.<ext>` in a temp dir (ASCII name,
original untouched), run `soffice --headless --invisible --norestore
--nolockcheck --nologo --nodefault -env:UserInstallation=<profile>
--convert-to <filter> --outdir …` under the global convert lock, retry once if
the profile was initialising, kill the tree at 180 s. Workbooks export one page
per sheet (`SinglePageSheets`).

Shell env: `OsExecutionEnv` asks a provider for extra variables at each command;
the provider reads `install.json`, so installing mid-chat works.

### 5.6 Errors and edge cases

- Unsupported platform: status `available:false`; the UI hides the download.
- Offline / HTTP error: job `failed` with the message; Retry resumes.
- App quit mid-install: next install start removes staging; the partial is kept
  for the same asset only.
- Locked files on Windows (antivirus): rename retried with back-off.
- Corrupt or encrypted document: "conversion failed" with the last stderr lines.
- Document over 100 MB: refused before conversion.
- Uninstall while a conversion runs: the conversion fails; the cache survives.

### 5.7 Security and trust

- The pin (URL, size, SHA-256) is compiled in; nothing is trusted from the
  network. HTTPS only. A test override manifest (`EVO_OFFICE_MANIFEST`) still
  passes every check and is the only way `file://` is accepted.
- Extraction validates every member first (root `soffice/`, no `..`, no absolute
  or drive paths, links stay inside, no devices, no duplicates, limits) and only
  then extracts.
- Documents are untrusted: macros disabled, `BlockUntrustedRefererLinks`,
  external links never refreshed.
- The agent reaches the runtime only through its normal shell tool, which keeps
  its permission prompts and sandbox. `office_convert` is a UI RPC, not an agent
  tool. The embedded skills are first-party content.

### 5.8 Configuration

No settings keys. `EVO_OFFICE_MANIFEST` (env, tests only). The Settings section
"Office" edits the install state live.

## 6. Alternatives considered

| Option | Why not |
| --- | --- |
| Port v3's pure-Python/HTML renderers as the no-runtime fallback | ~5 000 lines of approximate rendering; two code paths to keep equal. Dropped by decision. |
| Bundle LibreOffice in the installer | +190 MB for everyone. |
| Use any LibreOffice on PATH for preview | Output differs per version; harder to support. Skills may still use it. |
| Render pages to PNG in the engine (pdfium) | Heavy native dependency; pdf.js in the webview is enough and also shows plain PDFs. |
| A protocol event for install progress | The UI already polls like Code intelligence; one pattern. |
| A module in `evo-runtime` instead of a new crate | Process spawning and archive handling do not belong in the model/credential crate. |

## 7. Delivery plan

| Phase | Scope | Main files | Done when |
| --- | --- | --- | --- |
| 1 | `evo-office`: manifest, install, convert + tests; ADR; ADD | `crates/evo-office` | `cargo test -p evo-office` passes |
| 2 | Engine: `office.rs`, RPC, shell-env provider, preview cache | engine, `evo-tools` | engine tests pass |
| 3 | Embedded skills + loader dir | `bundled-skills/`, engine | FR-10 test |
| 4 | Desktop: Settings section, document viewer, `fs_read_bytes` | `apps/desktop` | manual check in the app |
| 5 | Runtime build script and release workflow ported from v3 | `scripts/office-runtime`, `.github/workflows` | docs updated |

## 8. Verification

| Requirement | Test or check | Result |
| --- | --- | --- |
| FR-1…FR-5 | `cargo test -p evo-office` | passed (2026-11-07) |
| FR-6, FR-7 | `cargo test -p evo-office convert`, `-p evo-engine office` | passed (2026-11-07) |
| FR-8 | `cargo test -p evo-tools shell_env_provider` + manual | passed (2026-11-07) |
| FR-9 | Manual in the running app (real runtime) | not run: the installed app holds the single instance |
| FR-10 | `cargo test -p evo-engine office` | passed (2026-11-07) |

## 9. Open questions

1. macOS and Linux conversions are untested locally (Windows only); the CI
   workflow of phase 5 covers them.

## 10. As-built notes

- Install progress is polled (700 ms) like Code intelligence; no protocol event.
- Preview cache and extraction dirs follow the SDD. The embedded skills are
  extracted to `<agent>/bundled-skills/<content hash>/` and appended last to the
  skill directories, so a user skill of the same name wins.
- `evo-tools` gained `ShellEnvProvider` (per-command env, PATH appended).
- `fs_read_bytes` and `worker-src blob:` in the CSP serve pdf.js; the viewer is
  lazy-loaded.
- Phase 5: only the build script is ported (`scripts/office-runtime/build_runtime.py`);
  the release workflow and `verify` script are not (they depended on the v3 app).
  The existing release `office-runtime-26.8.0` is what is pinned.
- Skills: v3 live-build scripts and `document_preview` steps were replaced by
  render-to-PNG (`transcode.py`, `contact_sheet.py`, `render_slides.py`,
  `pdf_out.py --png`) viewed with `read`; `EVOFLUX_*` variables became `EVO_SOFFICE`.

## 11. History

- 2026-11-07 — Draft and Accepted (scope and trade-offs delegated by the owner).
