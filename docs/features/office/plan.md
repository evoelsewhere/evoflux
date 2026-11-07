# Office documents: runtime, preview and skills — Plan

| | |
| --- | --- |
| Spec | [spec.md](spec.md) |
| Tasks | [tasks.md](tasks.md) |
| Updated | 2026-11-07 |
| ADD sections | [5.1 Crate layers](../../architecture/README.md#51-crate-layers), [5.2 Desktop app](../../architecture/README.md#52-desktop-app) |
| ADRs | [0008 Optional LibreOffice runtime for Office documents](../../architecture/decisions/0008-optional-libreoffice-runtime.md) |

## 1. Context and constraints

- v3 implementation (tag `v3.1.1`: `app/services/office_runtime/*`,
  `scripts/build_libreoffice_runtime.py`, `.github/workflows/office-runtime.yml`)
  is the reference. Its assets are already published as release
  `office-runtime-26.8.0` (four platforms); the pins are carried over unchanged.
- Same install-on-demand shape as language servers (`evo-lsp`, RPC
  `install_language_server`, polled by the UI): see
  [Code intelligence](../code-intelligence/plan.md).
- ADD rules: the engine owns logic, the shell relays; layers point down;
  tool output and documents are untrusted; real engine in the app.
- LibreOffice is MPL-2.0; the bundle is downloaded, not redistributed inside evo.
- The skills are Apache-2.0 (kept, with their LICENSE files). Their scripts run
  through `uv run --with …` and `bun`, as in v3; evo does not ship Python.

## 2. Architecture check

| Rule | Result | Notes |
| --- | --- | --- |
| The engine owns agent logic; the shell relays and provides native features | ok | The engine owns the runtime, the preview cache and the RPC methods; the shell only adds `fs_read_bytes` to hand file bytes to the webview. |
| Layers point down; library crates stay free of engine/desktop concerns | ok | `evo-office` is a leaf crate: manifest, archive and `soffice` only — no chats, RPC or desktop. `evo-tools` gains a generic shell-env provider, not Office knowledge. |
| Protocol changes update `evo-protocol`, the engine and the desktop together | ok | New `office_*` RPC methods land in the engine and the desktop together; older engines answer with their usual unknown-request error (3.3). No protocol event: progress is polled. |
| Models come from models.dev; no hardcoded model facts | n/a | No model data. |
| Real engine in the app; settings and credentials reload live | ok | Installing the runtime takes effect in running chats (shell-env provider reads `install.json` per command); no restart. |
| Untrusted input stays untrusted; permissions, sandbox and project trust stay in the path | ok | Documents are untrusted (macros off, no external links); the download is pinned and verified; the agent reaches the runtime only through its normal shell tool, with its prompts and sandbox (3.7). |
| Desktop UI structure and `DESIGN.md` | ok | The viewer lives in `features/files`; the shared install component lives in `components/`. |
| Architecture changes have an ADD edit and an ADR | ok | New crate and optional downloaded runtime: [ADR 0008](../../architecture/decisions/0008-optional-libreoffice-runtime.md) and the ADD (tasks T4). |

## 3. Design

### 3.1 Overview

```text
Files (install prompt) ──RPC──► engine ──► evo-office::Runtime ──► <agent>/runtimes/libreoffice/
Files ──office_convert──► engine office.rs (cache) ──► soffice --headless --convert-to pdf
Files ◄── pdf path ───────┘      └─ fs_read_bytes (shell) ──► pdf.js pages
agent bash/powershell ◄── EVO_SOFFICE, PATH (shell-env provider reads install.json)
skills: embedded in engine ──► <agent>/bundled-skills/ (extracted on start) ──► skill loader
```

`evo-office` is a leaf crate: it knows the manifest, the archive format and how
to run `soffice`, not chats, RPC or the desktop. The engine owns the single
`Runtime` for the process, the preview cache and the RPC methods.

### 3.2 Components

| Layer | Path | Responsibility | Requirements |
| --- | --- | --- | --- |
| crate | `crates/evo-office/src/manifest.rs` | Pinned assets per platform, validation, test override | FR-1, FR-2, NFR-2, NFR-3 |
| crate | `crates/evo-office/src/install.rs` | Job state machine, resumable verified download, safe extraction, atomic activation, uninstall | FR-2, FR-3, FR-4, FR-5, NFR-1, NFR-3 |
| crate | `crates/evo-office/src/convert.rs` | Hardened profile, serialized conversion, retry, timeout and tree kill | FR-6, FR-7, NFR-4 |
| engine | `crates/evo-engine/src/office.rs` | Process-wide `Runtime`, RPC bodies, preview cache, shell-env provider, embedded skills | FR-1–FR-6, FR-8, FR-10 |
| engine | `crates/evo-engine/src/modes.rs` | RPC dispatch (`office_*`) | FR-1–FR-6 |
| engine | `crates/evo-engine/src/session.rs` | Builtin tools get the shell-env provider | FR-8 |
| engine | `crates/evo-engine/bundled-skills/` | The three skills | FR-10 |
| crate | `crates/evo-tools/src/os_env.rs` | `OsExecutionEnv::with_shell_env_provider` (dynamic env) | FR-8 |
| desktop shell | `apps/desktop/src-tauri/src/files.rs` | `fs_read_bytes` (raw bytes over IPC) | FR-9 |
| desktop UI | `apps/desktop/src/features/files/document-viewer.tsx` | Install prompt when no runtime; convert via engine, render PDF pages with pdf.js | FR-9 |
| desktop UI | `apps/desktop/src/components/office-install.tsx` | Install, progress, cancel, retry (used by the viewer) | FR-1–FR-4, FR-9 |

### 3.3 Interfaces

RPC (JSONL, like `list_language_servers`). The `office_*` management commands
all answer with the status object. Requirement map: `office_status` FR-1,
`office_install` FR-2/FR-3, `office_cancel_install` FR-4, `office_uninstall`
FR-5, `office_convert` FR-6/FR-7.

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

Agent shells: `EVO_SOFFICE` and the runtime directory appended to `PATH`
(FR-8).

Older engines answer unknown request types with their usual error; the UI shows
it as "update evo".

### 3.4 Data and storage

- `<agent>/runtimes/libreoffice/<version>/soffice/…` — the active runtime.
- `<agent>/runtimes/libreoffice/install.json` — `{id, version, platform, sha256, executable, installedAt}`.
- `<agent>/runtimes/libreoffice/profile/` — the hardened shared LibreOffice profile.
- `<agent>/runtimes/libreoffice/.download-<sha>.part`, `.staging-*` — transient.
- `<agent>/cache/office/<key>.pdf` — conversions; key = SHA-256 of
  `(canonical path, mtime, size, runtime version)`; pruned to 256 MiB, oldest first.
- `<agent>/bundled-skills/<engine version>/…` — extracted skills (as built:
  `<content hash>`, see 5).
- No database change.

### 3.5 Behaviour

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

### 3.6 Errors and edge cases

- Unsupported platform: status `available:false`; the UI hides the download.
- Offline / HTTP error: job `failed` with the message; Retry resumes.
- App quit mid-install: next install start removes staging; the partial is kept
  for the same asset only.
- Locked files on Windows (antivirus): rename retried with back-off.
- Corrupt or encrypted document: "conversion failed" with the last stderr lines.
- Document over 100 MB: refused before conversion.
- Uninstall while a conversion runs: the conversion fails; the cache survives.

### 3.7 Security and trust

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

### 3.8 Configuration

No settings keys and no settings page. `EVO_OFFICE_MANIFEST` (env, tests only).
The install prompt in the Files preview edits the install state live.

## 4. Alternatives considered

| Option | Why not |
| --- | --- |
| Port v3's pure-Python/HTML renderers as the no-runtime fallback | ~5 000 lines of approximate rendering; two code paths to keep equal. Dropped by decision. |
| Bundle LibreOffice in the installer | +190 MB for everyone. |
| Use any LibreOffice on PATH for preview | Output differs per version; harder to support. Skills may still use it. |
| Render pages to PNG in the engine (pdfium) | Heavy native dependency; pdf.js in the webview is enough and also shows plain PDFs. |
| A protocol event for install progress | The UI already polls like Code intelligence; one pattern. |
| A module in `evo-runtime` instead of a new crate | Process spawning and archive handling do not belong in the model/credential crate. |

## 5. As-built notes

- Install progress is polled (700 ms) like Code intelligence; no protocol event.
- The runtime is downloaded over HTTP/1.1: over HTTP/2 the GitHub release CDN
  stopped sending after 20–40 MB and the read timed out ("error decoding
  response body"); resume then repeated the stall. Found in the live check.
- The **Settings → Office** page was dropped after review: the install lives
  only in the Files preview of an Office file, so there is no UI to remove the
  runtime (`office_uninstall` stays an RPC without UI).
- Preview cache and extraction dirs follow this plan. The embedded skills are
  extracted to `<agent>/bundled-skills/<content hash>/` and appended last to the
  skill directories, so a user skill of the same name wins.
- `evo-tools` gained `ShellEnvProvider` (per-command env, `PATH` appended).
- `fs_read_bytes` and `worker-src blob:` in the CSP serve pdf.js; the viewer is
  lazy-loaded.
- Runtime build and release (tasks phase 5): only the build script is ported
  (`scripts/office-runtime/build_runtime.py`); the release workflow and
  `verify` script are not (they depended on the v3 app). The existing release
  `office-runtime-26.8.0` is what is pinned.
- Skills: v3 live-build scripts and `document_preview` steps were replaced by
  render-to-PNG (`transcode.py`, `contact_sheet.py`, `render_slides.py`,
  `pdf_out.py --png`) viewed with `read`; `EVOFLUX_*` variables became `EVO_SOFFICE`.
