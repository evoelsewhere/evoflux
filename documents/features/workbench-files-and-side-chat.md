# Workbench, files, and Side Chat

The workbench keeps task tools beside the conversation. Available panels depend
on mode and workspace, but share one dock and open-with contract.

## Workbench surfaces

| Surface | Work | Coding | Backend owner |
|---|---:|---:|---|
| Workspace files and uploads | Yes | Repository tree/files | team file routes and watcher |
| Read-only document preview | Yes | Yes | document preview service |
| Terminal, with a Running bar for managed processes/previews | Yes | Yes | terminal WebSocket service, process manager |
| Persistent browser | Yes | Yes | direct browser bridge/Tauri |
| Wiki | Yes | Yes | wiki routes/service |
| Scheduler | Yes | Yes | scheduler routes/service |
| Plugin Center | Yes | Yes | plugin platform |
| Side Chat | Yes | Yes | side-chat routes and panel |
| Source editor/Git/Problems | No | Yes | Coding services |

The dock lazy-loads panels and supports responsive overlay behavior. Split mode
can show conversation, editor/workspace and auxiliary tools simultaneously;
Monitor focuses on multi-agent progress.

### Which repository a Coding panel describes

A Coding session opens on one repository even when its project holds several:
something has to be the agent's working directory, and the project's first
member — by insertion order — is what the backend derives. That is a cwd, not a
verdict about which repository matters, and a panel that presents it as the
project is wrong.

The Source Control tab — both its Changes and Review views — therefore carries its own
repository selection. Terminal and the file tree stay rooted at the
session's own repository, which is where the agent actually runs.

## Files and uploads

Work uploads land under the session workspace so agent filesystem tools can use
relative paths. File APIs validate traversal and symlink boundaries, bound file
size/type handling, and serve media through explicit endpoints. Coding file
routes require an authorized workspace/project repository and use
repository-relative paths.

Filesystem watchers publish bounded server-sent events. The frontend invalidates
file queries instead of treating watcher payloads as a complete filesystem
snapshot.

## Explorer context menu

Both modes' file trees share one right-click menu (touch: long press). Work
mode, Coding's repository tree and the native desktop tree pass the
capabilities they can honour; an action with no handler is omitted rather than
shown disabled.

| Action | Behaviour |
|---|---|
| Attach as context | Inserts `@path` into the chat composer |
| Preview | Selects the entry in the panel's viewer |
| Open in default app | Hands the file to the OS handler |
| Open in ▸ | Opens that entry (not the workspace root) in a detected editor, terminal or file manager |
| Copy ▸ | Name, workspace-relative path, absolute path, or file contents |
| Save a copy | Writes the file somewhere else; labelled "Download" only in the browser build, where it actually is one |
| New file / New folder | Creates inside the clicked folder, or beside the clicked file |
| Rename / Duplicate / Delete | Mutates the entry; deletes confirm first, and folders require an explicit recursive flag |

App detection reuses the topbar's opener catalog, so the menu lists exactly the
applications the native shell found installed. "Save a copy" opens the OS save
dialog and the native side streams the bytes to the chosen path, so large
artifacts are not buffered in memory and no workspace URL (which carries the
desktop token) is handed to another application. Mutations go through the same
traversal and containment guards as reads: relative paths only, no `..`, no
escaping the workspace root, and an existing destination is refused instead of
overwritten. Session workspaces are addressed by session id
(`/api/team/{sid}/files/...`), coding workspaces by absolute root
(`/api/team/workspace/files/...`).

## Preview contract

- Images, audio, Markdown and supported text are rendered directly.
- HTML is sanitized/isolated before preview.
- PDF and HTML intake for agent context uses `markitdown` where supported.
- DOCX, XLSX and PPTX are read-only workspace previews backed by optional host
  engines; Office content is not silently injected into agent context.
- DOCX renders in the WebView with `docx-preview`
  (`web/src/lib/docx-preview-render.ts`) from the raw file, covering Word
  numbering, sections, headers/footers, footnotes/endnotes, tracked changes,
  floating text boxes and table merges. Its output is neutralized (no scripts,
  handlers, remote sources or navigable links) and serialized into the same
  inert CSP document and `[data-preview-item]` page contract as the backend.
  The backend python-docx renderer stays the fallback when client rendering
  fails or no raw file URL is available. `web/patches/docx-preview@0.4.1.patch`
  loads pictures nested inside VML groups and skips a detached-DOM `getBBox`
  that collapsed shapes to 0×0. DrawingML-only shapes (`wps`/`wpg` without a
  VML fallback) are still not drawn by docx-preview.
- PPTX renders on the backend. SmartArt is rebuilt from the drawing PowerPoint
  caches in `ppt/diagrams/drawingN.xml`, `mc:AlternateContent` resolves to its
  fallback branch, and OLE objects show their preview image or a labelled
  placeholder instead of disappearing. A shape that fails to render is logged
  and skipped rather than failing the whole deck.
- XLSX renders on the backend with conditional formatting (cell rules, colour
  scales, data bars, icon sets), hidden rows/columns, freeze panes, hidden
  gridlines, comments, hyperlinks (inert), drawing shapes/text boxes, chart
  sheets and hidden-sheet labels (`app/services/document_preview/xlsx_features.py`).
  Packages openpyxl rejects are retried once from an in-memory copy with
  markup-compatibility fallbacks resolved and unreadable pivot caches detached.
- XLSX formula display is calculated conservatively and never executes workbook
  macros or arbitrary formulas.

### Exact rendering runtime (LibreOffice)

The built-in renderers above approximate Office layout. For exact pages the
viewer offers an optional LibreOffice runtime that the user installs from the
viewer banner (`web/src/components/document-preview-runtime-banner.tsx`);
nothing downloads until they ask.

- **Bundle.** `scripts/build_libreoffice_runtime.py` turns an official The
  Document Foundation package (checksum-verified against
  download.documentfoundation.org) into a trimmed `soffice/` tree — help,
  translations, extensions, galleries, templates, Python/Java and unused icon
  themes removed; metric-compatible fonts kept — packs it as
  `libreoffice-<version>-<platform>.tar.gz` (about 180 MB on Windows) and
  prints its manifest entry (URL, SHA-256, size). macOS apps are re-sealed
  with an ad-hoc signature after trimming.
- **CI.** `.github/workflows/office-runtime.yml` builds and verifies every
  platform (macOS Apple Silicon and Intel, Windows x64, Linux x64) with
  `scripts/verify_office_runtime.py`, which installs through the real
  installer and converts generated DOCX/PPTX/XLSX through the preview
  pipeline. With `publish` it uploads the archives to the
  `office-runtime-<version>` release; the step summary prints the entries to
  pin in `app/services/office_runtime/manifest.py` (`PINNED_ASSETS`). The pin
  ships inside the application, so no separate signing key is needed. Until
  then the runtime reports unavailable and the banner stays hidden.
- **Install.** `app/services/office_runtime/installer.py` streams the archive
  with byte progress (`GET/POST /api/team/office-runtime/…`), rejects any size
  or SHA-256 mismatch, refuses archive entries outside `soffice/`,
  links that escape it and special files, then activates the tree under
  `<data dir>/runtimes/libreoffice/<version>` (renames retry through transient
  Windows antivirus locks). A download can be cancelled while it transfers;
  a failed one keeps its bytes in `.download-<sha256>.part` and Retry resumes
  with an HTTP range request (the SHA-256 still covers the whole archive).
  Leftover staging trees and other versions' partial downloads are removed
  on the next install. `EVOFLUX_OFFICE_RUNTIME_MANIFEST` can point at a
  local manifest to test an unpublished bundle; it passes the same checks.
- **Agent Skills.** Agent shells get a scrubbed environment, so the installed
  runtime is advertised explicitly: commands receive `EVOFLUX_SOFFICE` and
  the runtime's directory appended to `PATH` (after any user LibreOffice),
  which the Office Skills already look for. Their slide/page rasterisation
  uses Poppler's `pdftoppm` when present and otherwise pypdfium2 fetched by
  `uv`, so Poppler is optional.
- **Conversion.** `app/services/office_runtime/convert.py` runs headless
  `soffice` with one hardened profile (macros disabled, untrusted remote
  references blocked, external links never refreshed), serialized, with a
  timeout that kills the process tree. A fresh profile's silent first run is
  retried. Workbooks export one page per sheet.
- **Viewer.** DOCX, XLSX and PPTX then render as PDF pages with a positioned,
  transparent text layer (search and selection keep working), slide/sheet
  labels and speaker notes. The preview cache key includes the renderer, so
  installing the runtime re-renders open files — the approximate pages stay
  visible until the exact ones replace them. A failed conversion falls back
  to the built-in renderers and the banner says so; the banner also offers
  an update when a newer runtime is pinned, and a hidden offer is remembered
  per version.
- **Slides.** With the slide thumbnails collapsed, a deck lays out every
  slide vertically and scrolls like a document; the slide counter follows
  the scroll and previous/next scroll to a slide. The workbench dock can be
  widened to 75% of the window (up to 1600 px) while the chat column keeps
  its minimum width.
- **Live decks.** The `pptx-official` Skill builds a deck one slide at a
  time with `scripts/deck_live.py`: `init` creates the file with its plan
  (slide count and titles) in the `evoflux.deck` custom document property,
  each slide is appended and saved atomically, `mark` re-embeds the plan
  after PptxGenJS rewrites the file, and `finish` marks it done.
  `app/services/document_preview/live_deck.py` reads the plan. While it is
  not done the deck always renders natively (never through LibreOffice),
  inside `<main data-deck-live="true">`: finished slides carry
  `data-slide-status="done"` (the newest also `data-slide-fresh`, which
  animates it in), the next planned slide is `building` (planned title,
  animated placeholder, deck progress bar) and the rest are `pending`.
  Motion is disabled under `prefers-reduced-motion`. The viewer keeps the
  last good render while a save re-renders, keeps zoom and scroll across
  saves of the same file, collapses the slide thumbnails and reports the
  state through `onLiveDeckChange` so Files hides its tree, and follows the
  slide being built until the user scrolls, clicks or navigates. Both are
  restored when the deck is finished unless the user toggled them meanwhile.
- **Generated documents.** `web/src/hooks/useGeneratedDocumentWatcher.ts`
  subscribes a Work session to `/api/team/{session}/files/watch`, refreshes
  the file list on every Office save and opens the preview of a document the
  agent just created, once per file, while a turn runs — unless another
  workbench tool is active or `oa.documents.autoOpenGenerated` is `"false"`.
- **Mislabelled files.** Office preflight names what a rejected file really
  is — a ZIP archive with an Office extension, a package saved under the
  wrong extension, or a legacy/password-protected file — instead of calling
  every such file "damaged".

Preview cache is regeneratable and stored outside user workspaces. Unsafe
external URLs, path escapes and active embedded content are rejected.

## Terminal and processes

Each terminal is scoped to a session and authorized current working directory.
POSIX uses PTY primitives; Windows uses ConPTY through `pywinpty`. A WebSocket
carries resize, input and output. Managed background commands and preview
servers are terminated during sidecar shutdown. There is no separate Processes
tool: every Terminal tab has a collapsible Running bar (`TerminalRunningBar`)
that lists them across sessions — the current session first, the tab's own PTY
left out — and stops them through `DELETE /team/processes/{id}`. Only a visible
Terminal tab polls `GET /team/processes`.

## Side Chat (`/btw`)

Side Chat is a focused child conversation linked to one source session. It
captures a bounded source transcript/context at creation, persists independent
messages, and streams on a separate side-chat channel. The parent session
continues to own workspace authorization and model policy.

Side Chat deliberately exposes a restricted tool set and does not mutate the
main transcript. Multiple Side Chats can coexist; deleting the source session
cascades its child sessions. The UI opens the docked `SideChatPanel` and the
`/btw` composer shortcut targets the current session.

The original design plan is preserved at
[`../plans/side-chat-feature-spec.md`](../plans/side-chat-feature-spec.md); this
page and the current routes are authoritative for implemented behavior.

## Source and tests

Primary code: `app/api/routes/team/files.py`, `terminal.py`, `processes.py`,
side-chat routes in `chat.py`, `app/services/document_preview/`,
`app/services/terminal_service.py`, `app/services/workspace_file_watcher.py`,
`web/src/components/workbench/`, `SideChatPanel/`, and preview components.

Focused tests cover team files/media/uploads, document-preview security,
terminal WebSockets, process lifecycle, Side Chat routes/hooks, HTML/Office
preview rendering and workspace watcher behavior.
