# area-workspace-files NOTES

Python source: `app/api/routes/team/files.py`, `app/api/routes/team/language_servers.py`,
the three workspace routes of `app/api/routes/team/chat.py` (`/workspace/validate`,
`/workspace/browse`, `/workspace/tree`), `app/services/language_server_service.py`,
`app/agent/lsp_manager.py`, `app/services/team_manager.py` (`validate_workspace`),
`app/services/snapshot_service.py` (pin only, see below). Unit `workspace-files`
(`server/routing.toml`; pin breakers `adapter:workspace-files`, `file-lock:snapshot`).
Contract tests: `contract-tests/workspace-files/` (see "Test status").

**Status:** La (this crate's stub, NOTES, contract tests). The crate is not mounted:
`units.rs` is untouched, as for the other La lanes, because a mounted empty router
would answer 404 for a unit still owned by Python.

## Scope: which routes the unit really serves

`routing.toml` lists the unit's prefixes. Three things differ from the file layout:

- `files.py` also holds `GET /api/team/workspace/watch` and
  `GET /api/team/{session_id}/files/watch` (SSE). `routing.toml` gives both to
  `terminal-processes`, so they are **not** covered here.
- `files.py` also holds `GET /{session_id}/media/**` and
  `/{session_id}/document-preview/**` (+ deprecated `office-preview`), and
  `GET /workspace/files/preview`. The first two belong to `documents-preview`;
  `/workspace/files/preview` matches this unit's `workspace/files/**` prefix and is
  covered here for its path checks only (the render engine is that unit's).
- `/workspace/tree` is listed by the unit but reads the Coding project tables
  (`CodingProjectWorkspace`, `list_visible_coding_workspaces`), which `git-coding`
  also writes (`/api/team/projects/**`).

Route order matters in Python: the literal `/workspace/files/*` routes are declared
**before** the `/{session_id}/files/*` ones, otherwise `workspace` would be taken as a
session id and answer `400 Invalid session id.` A router must keep literal prefixes first.

## Endpoints

Every route: `401 {"detail":"Unauthorized — EvoFlux access key required."}` before any
validation (also before the multipart body of the upload). Validation errors are
FastAPI's `422 {"detail":[...]}`; messages below are `detail` strings.

### Coding workspace, addressed by `?workspace=<absolute folder>`

`workspace` is checked by `team_manager.validate_workspace`: expanded, resolved, must
be a directory, else `422 Workspace does not exist or is not a directory: <resolved>`.
There is **no allowlist** (S1 below).

| Endpoint | Behaviour | Errors |
|---|---|---|
| `GET /workspace/validate` | `{"workspace": <resolved>}` | `422` |
| `GET /workspace/files/list` | `{"workspace","files":[{path,name,size,mtime,mime}],"truncated"}`; recursive walk, sorted per folder, skips `.git`, `_SKIPPED_DIR_NAMES`, gitignored entries, linked-worktree folders (a submodule stays), files whose resolved path leaves the root; cap 10,000 files then `truncated: true` | `422` |
| `GET /workspace/files/read?path&download` | raw bytes via `FileResponse`, guessed type or `application/octet-stream`; `download=true` adds a `filename` disposition | `400 Path escapes workspace root.`, `404 File not found.`, `422` |
| `GET /workspace/files/preview?path` | same path checks, then the document engine (HTML, CSP) | `400`, `404`, `415` unsupported, `422` render error |
| `PUT /workspace/files/write?path` body `{"content": str}` (a `dict[str,str]`) | creates parents, writes UTF-8 | `422 Missing 'content' field.`, `400` escape, unhandled `500` when the target is a folder or the root (B1) |
| `POST /workspace/files/create?path&kind=file\|directory` | creates parents, `x`-mode file; `{"path": <relative posix>}` | `422 kind must be file or directory.`, `409 <name> already exists.`, `400`, `500 Create failed` |
| `POST /workspace/files/move?workspace` body `{from_path,to_path}` | rename; `{"ok":true}`; same path is a no-op | `404`, `409`, `400 Cannot move a folder into itself.`, `500 Move failed` |
| `POST /workspace/files/copy` | same body; files `copy2`, folders `copytree(symlinks=True)` | `404`, `409`, `400 Cannot copy a folder into itself.`, `500` |
| `DELETE /workspace/files/entry?path&recursive` | file unlink; folder only with `recursive=true`; a link to a folder is unlinked | `400 Directory delete requires recursive=true.`, `404`, `500` |
| `GET /workspace/status` | `{workspace,name,is_git_repo}` plus `branch` (null when detached), `dirty{staged,unstaged,untracked}`, `head{sha,subject,timestamp}` when `<root>/.git` exists and `git status` succeeds | `422`; git failures degrade to `is_git_repo: false` |
| `GET /workspace/git-diff/view?paths=` | `{workspace,is_git_repo,diff}`; diff against `HEAD` (or the empty tree), plus synthetic diffs of untracked files (256 KiB each); whole diff capped at 512 KiB | `422` bad path (absolute or starting with `..`), `500 git diff failed` |
| `GET /workspace/browse?path` | `{path,parent,directories:[{name,path}]}`: visible (non-dot) folders sorted case-insensitively, links folded to one entry by resolved path (first name wins); default is the home folder | `422 Not a directory: <p>`, `403 Cannot read directory: <p>` |
| `GET /workspace/tree` | every repository owned by a live Coding project, with its worktrees, plus the projects list | none |
| `POST /workspace/lsp/diagnostics`, `POST /workspace/lsp/semantic` | `workspace` + `path` validated (`422` workspace, `400` absolute or escaping path, `404 File not found.`) before the server lookup; an extension without a server answers `200 {"status":"unsupported"}`; a server that cannot start answers `200 {"status":"unavailable"}` (degrades the editor, never `500`); otherwise `status: ready` with the diagnostics or the semantic result | `422` body validation (position and `new_name` checks run after the mapping lookup) |
| `POST /workspace/language-servers/status` | overview of the managed catalog (state, source, extension counts per language, scan cap 50,000 files) for the given workspaces | `422` bad workspace |
| `POST /workspace/language-servers/{id}/install` | starts a pinned install job | `409 Unknown language server: <id>` |
| `POST /workspace/language-servers/{id}/install/dismiss` | `204`, idempotent, never fails | – |

### Work session, addressed by `/{session_id}`

`session_id` must be a UUID (`400 Invalid session id.`); no database row is needed. The
folder is `<EVOFLUX_WORKSPACE_DIR>/<id>` unless the row's `workspace` is set.

| Endpoint | Behaviour | Errors |
|---|---|---|
| `GET /{id}/files` | `{session_id,files,truncated,workspace_root}`; empty list when the folder does not exist | `400` |
| `GET /{id}/workspace` | `{session_id, workspace_root}` | `400` |
| `PUT /{id}/workspace` body `{"path": str\|null}` | absolute path is created (with parents) and stored; `null` resets; replies with the listing; updates the cached team's workspace | `400 Workspace path must be absolute.`, `400 Cannot create directory: ...`, `404 Session not found.` |
| `POST /{id}/files/upload?subfolder=` | multipart `files[]`; basename of each name; later duplicate wins; `subfolder` created | `400 Invalid subfolder path.`, `400 Subfolder escapes workspace root.`, `422` no file part, `500 Write failed` |
| `POST /{id}/files/{create,move,copy}`, `DELETE /{id}/files/...` | same semantics as the coding routes but rooted at the session folder; reply is the new listing | as above |
| `GET /{id}/uploads/{filename}` | flat file from `<session>/uploads/`; guessed type, attachment filename | `400 Invalid upload filename.`, `400` link or traversal, `404 Media file not found.` |

## Files, processes and state

| Resource | Used by |
|---|---|
| any folder named by `workspace=` or the session | read, written, deleted, copied, moved (the user's repository: never touched outside these routes) |
| `<EVOFLUX_WORKSPACE_DIR>/<session id>/` | created by upload and `PUT /workspace`; listed |
| `ChatSession.workspace` | written by `PUT /{id}/workspace`; read by every session route |
| `git` child processes | `status`, `git-diff/view` (`git -C <root> -c core.quotepath=false ...`, 5 s and 10 s timeouts) |
| language-server processes and installers | `lsp/*` and `language-servers/*` (npm, uv, go, rustup, gem, dotnet) under the EvoFlux cache; `close_language_servers` at shutdown |
| `snapshot_service` | not called by these routes; the files in a reverted session already match its snapshot, which is why the pin `file-lock:snapshot` exists: a Rust write must not race a restore |

## Pins check

`rg "routes.team.files|_session_workspace|_resolve_workspace_entry"` outside the
unit: `document_versions.py` imports `_resolve_workspace_entry` and
`_session_workspace`; `webbridge.py:1252` calls `list_coding_workspace_files` and
`list_workspace_files` in process (composer catalog); `_helpers.py` mirrors
`_safe_resolve`. `app/agent/lsp_manager.py` is also used by the agent LSP tool, the
post-edit hook and `change_set_service`. **Needs adapter** per `server/AGENTS.md`
§9 before cutover: the in-process callers above and the shared LSP clients. La stops
here and adds none.

## Odd behaviour (pinned as is unless noted)

- **B1** writing over a folder or the root is an unhandled `500 Internal Server Error`
  (the `OSError` is not caught).
- **B3** Windows rewrites trailing dots and spaces and `::$DATA`: `f.png.`, `f.png `
  and `f.png::$DATA` open `f.png`; uploads of such names land on the stripped file.
  Not normalised by Python.
- **B5** a gitignored folder shows no untracked files only for exact names.
- **B6** a scoped diff of an untracked file inside a folder is empty on Windows
  (`normpath` turns `sub/n.txt` into `sub\n.txt`).
- `list` hides gitignored entries and linked worktrees but keeps dot-folders.
- `..` that stays inside the root is accepted on read and write, rejected on
  create, move, copy and delete (the mutation helper rejects any `..` part).
- Reserved device names do not escape; a link to a folder outside is refused on every
  route, a link inside is followed.
- A `.git` file (worktree or submodule) counts as a repository, a subfolder of a
  repository does not.

## Security findings (for the owner)

- **S1: no workspace allowlist.** `validate_workspace` only checks that the folder
  exists; any folder on the machine can be listed (`browse`), read, written,
  deleted, copied, and adopted as a session folder (`PUT /{id}/workspace` creates it).
  The access key is the only gate. The Rust chat workspace is an allowlist; the port
  needs a decision (known difference, or port as is). Pinned by `test_*_no_allowlist_*`.
- **S2: untracked-file scan follows a directory link out of the workspace** and
  puts the contents of the linked folder into the diff. Pinned.
- **S3: `git status` and `git-diff/view` run `git` with the repository's own
  configuration**: a hostile `core.fsmonitor` hook in a cloned repository runs when
  the route is called. Pinned by `test_git_runs_the_repository_s_own_fsmonitor_hook`.
- **S4: no deny list for `.env`.** The Rust tools deny `**/.env` and `**/.env.*`;
  these routes read and write them freely. Pinned.
- **S5: upload has no size cap.** The whole part is read into memory and written.
- Paths are confined by resolve-and-compare (`relative_to` the resolved root); the
  tests cover `..`, absolute, drive-relative, UNC (refused before any network round
  trip), device names and links. A Rust port must resolve the same way, and must not
  introduce a check-then-use gap (the `create` route uses `x` mode for that reason).

## Test status

Contract tests: 93 test functions (about 120 cases with the parametrised ones; all pass and 4 skip vs Python v3.1.1) in `contract-tests/workspace-files/` (`conftest.py`,
`ws_helpers.py`, `test_auth_routes.py`, `test_coding_files.py`, `test_confinement.py`,
`test_git_browse_tree.py`, `test_lsp_language_servers.py`, `test_session_files.py`).
Results against Python v3.1.1 are in the LANDED line. `TARGET=rust` is not
applicable until Lb mounts the crate. Cases that need a real language server on
`PATH` or an installer are skipped on purpose.

## Lb: size and dependencies

Largest pieces: path confinement and the file mutations (small, security-critical),
the `.gitignore` matcher shared with the tools crate, the git child-process helpers
(shared with `git-coding`), and the language-server client (JSON-RPC over stdio,
install recipes) which is the bulk. Suggest three Lb slices: files and sessions,
git/browse/tree, language servers. Depends on `core::auth`, the database layer for
`ChatSession` and the Coding project tables, and the `net`/process helpers.
