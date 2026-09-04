# Workbench, files, and Side Chat

The workbench keeps task tools beside the conversation. Available panels depend
on mode and workspace, but share one dock and open-with contract.

## Workbench surfaces

| Surface | Work | Coding | Backend owner |
|---|---:|---:|---|
| Workspace files and uploads | Yes | Repository tree/files | team file routes and watcher |
| Read-only document preview | Yes | Yes | document preview service |
| Terminal | Yes | Yes | terminal WebSocket service |
| Managed processes/previews | Yes | Yes | process manager and agent process/preview tools |
| Persistent browser | Yes | Yes | direct browser bridge/Tauri |
| Wiki | Yes | Yes | wiki routes/service |
| Scheduler | Yes | Yes | scheduler routes/service |
| Plugin Center | Yes | Yes | plugin platform |
| Side Chat | Yes | Yes | side-chat routes and panel |
| Source editor/Git/graph/Problems | No | Yes | Coding services |

The dock lazy-loads panels and supports responsive overlay behavior. Split mode
can show conversation, editor/workspace and auxiliary tools simultaneously;
Monitor focuses on multi-agent progress.

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
- XLSX formula display is calculated conservatively and never executes workbook
  macros or arbitrary formulas.

Preview cache is regeneratable and stored outside user workspaces. Unsafe
external URLs, path escapes and active embedded content are rejected.

## Terminal and processes

Each terminal is scoped to a session and authorized current working directory.
POSIX uses PTY primitives; Windows uses ConPTY through `pywinpty`. A WebSocket
carries resize, input and output. Managed background commands and preview
servers have separate list/stop surfaces and are terminated during sidecar
shutdown.

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
