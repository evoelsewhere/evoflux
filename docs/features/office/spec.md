# Office documents: runtime, preview and skills — Spec

| | |
| --- | --- |
| Status | Implemented |
| Area | crate `evo-office`, engine, RPC, desktop shell, desktop UI |
| Created | 2026-11-07 |
| Updated | 2026-11-07 |
| Plan | [plan.md](plan.md) |
| Tasks | [tasks.md](tasks.md) |
| Related | [Code intelligence](../code-intelligence/spec.md) (same install-on-demand pattern), [Customize](../customize-skills-plugins-connectors/spec.md) |

## 1. Summary

evo v3 could open, render and edit Word, PowerPoint and Excel files because it
shipped an optional, downloadable LibreOffice runtime plus three Office skills.
v4 has neither. This feature brings that capability to the Rust engine: the
person opens an Office file in Files, which offers a trimmed LibreOffice runtime
to install with one click (checksum-pinned, resumable, cancellable); Files then
previews `.docx/.pptx/.xlsx` (and legacy/ODF siblings) as Office lays them out;
agent shells see the runtime (`EVO_SOFFICE`, `PATH`); and the `docx`, `pptx`
and `xlsx` skills ship with the app.

v3's HTML re-implementation of the three formats (a fallback used when no
runtime was installed) is **not** ported: without the runtime the preview says
so and offers the install, nothing else.

## 2. Scope

### 2.1 Goals

- Install, cancel and resume the runtime from the Files preview of an Office
  file, with byte progress; no restart needed to use it. There is no settings
  page; uninstalling exists in the engine but has no UI.
- Exact Office → PDF conversion with a hardened LibreOffice profile, serialized,
  with a timeout that kills the whole process tree.
- Files preview of Office documents (and of plain PDFs) in the desktop app.
- The runtime is visible to the agent's `bash`/`powershell` tools as
  `EVO_SOFFICE` and on `PATH`, live (installing it takes effect in running chats).
- Office skills (docx, pptx, xlsx) embedded in the engine and always available.

### 2.2 Non-goals

- A fallback HTML renderer, live "deck/workbook under construction" previews and
  annotation-driven editing (all v3 viewer features) — later brought back by
  [Office documents: v3 behaviour](../office-v3-parity/spec.md) (ADR 0009).
- Editing Office files in the app. The agent edits through the skills.
- Bundling LibreOffice in the installer (size); it stays an on-demand download.
- A system-installed LibreOffice as the preview engine. Only the pinned runtime
  is used for preview (reproducible output); skills still fall back to a
  `soffice` on `PATH`.

## 3. User scenarios

### US-1 Preview an Office file (priority P1)

A person wants to see a Word, PowerPoint or Excel file in Files as Office lays
it out, so that they can check a document without leaving evo.

Acceptance scenarios:

1. **Given** no runtime is installed, **when** the person opens a `.docx` in
   Files, **then** the preview says the runtime is missing and offers to
   install it.
2. **Given** the person clicks install, **when** the download runs, **then**
   the preview shows byte progress and, once installed, shows the document's
   pages without a restart.
3. **Given** the runtime is installed, **when** the person opens the same
   unchanged file again, **then** the pages come from the cache.
4. **Given** a `.pdf`, **when** the person opens it in Files, **then** it
   shows as pages.

### US-2 Install over a poor connection (priority P2)

A person on a slow or flaky network wants to stop and restart the download,
so that a large download is not lost.

Acceptance scenarios:

1. **Given** a download fails part way, **when** the person retries, **then**
   it continues from where it stopped.
2. **Given** a download is running, **when** the person cancels, **then** it
   stops and the partial download is discarded.
3. **Given** the archive does not match its pinned checksum, **when** it is
   verified, **then** nothing is installed.

### US-3 The agent works with Office documents (priority P1)

The agent wants Office skills and the runtime in its shell, so that it can
create, convert and check documents for the person.

Acceptance scenarios:

1. **Given** a fresh install of evo, **when** the person opens Customize,
   **then** the docx, pptx and xlsx skills are listed and can be loaded.
2. **Given** a running chat, **when** the person installs the runtime,
   **then** the next shell command in that chat sees `EVO_SOFFICE` without
   restarting the chat.

### Edge cases

- Unsupported platform: the install is not offered (NFR-2).
- A document that hangs the converter: FR-7.
- The full list of failure cases: [plan 3.6](plan.md#36-errors-and-edge-cases).

## 4. Requirements

### 4.1 Functional

| ID | Requirement | Acceptance check |
| --- | --- | --- |
| FR-1 | The engine reports platform support, the pinned version, download and installed sizes, the installed version and the install job. | Unit test on the status of an empty home; the app shows the state. |
| FR-2 | Installing downloads the pinned archive, verifies size and SHA-256 before extracting, extracts only under the runtime's root folder, activates atomically, and removes older versions. | Tests with local test manifests: a good archive installs; wrong hash, wrong size, traversal, link escape, duplicate path and special file all fail without activating. |
| FR-3 | A failed or interrupted download resumes from the partial file (HTTP Range); a server that ignores Range restarts it. | Test with a local HTTP server. |
| FR-4 | Cancelling an install stops downloading/verifying and discards the partial; it is refused during extraction. | Test. |
| FR-5 | Uninstalling removes the runtime (not while installing). | Test. |
| FR-6 | Converting a document produces a cached PDF; a second conversion of an unchanged file is served from the cache; the cache is pruned by size. | Test with a fake `soffice`; real conversion checked in the app. |
| FR-7 | Conversions never run concurrently; a hang is killed (process tree) at the timeout; a fresh profile's first-run exit is retried once. | Test with a fake `soffice`. |
| FR-8 | Agent shells get `EVO_SOFFICE` and the runtime directory appended to `PATH` once the runtime is installed, without restarting chats. | Test of the shell-env provider; run `echo $EVO_SOFFICE` in a chat. |
| FR-9 | Files shows `.docx .doc .odt .rtf .pptx .ppt .odp .xlsx .xls .ods` as rendered pages, and `.pdf` as pages. With no runtime it shows an install prompt. | Manual check in the running app. |
| FR-10 | The docx/pptx/xlsx skills are listed in Customize and loadable without any user setup. | Engine test that the skills load from the extracted directory. |

### 4.2 Non-functional

| ID | Requirement | Acceptance check |
| --- | --- | --- |
| NFR-1 | Streamed download and hashing; archive up to 1 GiB, extracted up to 4 GiB, 60 000 entries. | Limits tested. |
| NFR-2 | Windows x64, macOS (x64, arm64), Linux x64. Other platforms report "not available". | Platform-key test. |
| NFR-3 | No network access except the pinned HTTPS URL, and only when the person asks. | Review. |
| NFR-4 | Conversion of a 20-page document under 30 s on a laptop (after profile init). | Manual timing. |

## 5. Success criteria

- SC-1 A person with no runtime gets from opening an Office file to seeing
  its pages with one click and no restart.
- SC-2 An interrupted download continues from where it stopped instead of
  starting again.
- SC-3 Reopening an unchanged document shows its pages without converting it
  again.
- SC-4 A running chat can use the runtime right after it is installed,
  without being restarted.

## 6. Clarifications

### 6.1 Open

None.

### 6.2 Resolved

- 2026-11-07 — Q: Port v3's HTML renderers as the no-runtime fallback? → A:
  No, dropped by decision (section 1, plan 4).
- 2026-11-07 — Q: Where does the person install the runtime? → A: Only in the
  Files preview of an Office file; the settings page was dropped after review
  (section 2.1, plan 5).
- 2026-11-07 — Q: How are conversions on macOS and Linux verified? They are
  untested locally (Windows only) and the release workflow was not ported.
  → A: A CI workflow covers them (tasks T13).

## 7. History

- 2026-11-07 — Draft and Accepted (scope and trade-offs delegated by the owner).
- 2026-11-07 — Live check: HTTP/1.1 download fix; Settings → Office removed, install from the Files preview only.
- 2026-11-07 — Moved to the spec / plan / tasks format.
- 2026-11-07 — Open clarifications answered by the owner (accepted as proposed).
