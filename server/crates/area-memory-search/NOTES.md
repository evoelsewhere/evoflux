# area-memory-search NOTES

Python source: `app/api/routes/wiki.py`, `app/api/routes/team/search_everywhere.py`,
`app/api/routes/team/app_search.py`, `app/api/schemas/{search_everywhere,app_search}.py`,
`app/services/{wiki,memory,app_search_service,search_everywhere_service}.py`,
`app/core/wiki_seed.py`. Also named by the board row but **not served by these
routes** (see "Services in the row that have no route"): `memory_vector.py`,
`memory_stream_store.py`, `scoped_memory.py`, `models/memory.py`. Unit
`memory-search` (`server/routing.toml`; pin breakers `adapter:memory-search`,
`file-lock:wiki`). Contract tests: `contract-tests/memory-search/` (92 cases; all
pass against Python v3.1.1 on Windows, one skips there: the symlink escape).

**Status:** La (this crate's stub, NOTES, contract tests). The crate is not mounted
(`units.rs` untouched): a mounted empty router would answer 404 for a unit still
owned by Python. Lb sizing is at the end. No `api-types/src/memory_search.rs` stub
was added (the other La lanes added none either; the types are small and listed
below).

## Routes

Every route: `401 {"detail":"Unauthorized — EvoFlux access key required."}` for a
missing or wrong bearer token, before validation (a token in the query string is not
accepted). FastAPI `422 {"detail":[{"type","loc","msg","input"}]}` for body/query
errors; unknown method `405`, unknown path `404`.

| Endpoint | Behaviour | Errors |
|---|---|---|
| `GET /api/wiki/tree?unprocessed_only=bool` | the wiki grouped into `system` (`USER.md`, `INDEX.md`, `LOG.md`, `LINT.md` in that order, only those that exist), `notes`, `topics`, `entities`, `sources`, `comparisons`, `imports` (key order is that of the response model: system, notes, topics, entities, sources, comparisons, imports). Each row `{path, description, updated, tags, confidence, sources}`. Sub-folders are listed by sorted name, only regular files whose suffix is exactly `.md`. `unprocessed_only` keeps only notes that have no `dream_notes_log` row or were modified after `processed_at`; other sections are not filtered | `422` (`bool_parsing`) |
| `GET /api/wiki/file?path=` | `{path, content, description, updated, tags, confidence, sources}`; `path` is echoed as sent; content is read as UTF-8 text, so CRLF becomes LF | `400` path rule, `404 Wiki file not found: <path>` (also for a directory), `422`, `500` plain-text `Internal Server Error` for non UTF-8 content |
| `PUT /api/wiki/file` `{path, content}` | validates the path, writes the bytes atomically under the write lock, `200` (never `201`) with the same shape as GET built from the *written* content | `400`, `422` (body validation first, then the path rules) |
| `DELETE /api/wiki/file?path=` | `{"status":"ok","path":<as sent>}`; `USER.md`, `INDEX.md`, `LOG.md` are refused (`400 Refusing to delete protected wiki file: X. Overwrite the contents instead.`) before the existence check; `LINT.md` may be deleted | `400`, `404`, `422` |
| `POST /api/team/search-app` `{query (1..1000), limit (1..100, default 40)}` | `{items:[{id,kind,label,description,session_id,path,metadata}]}` over sessions, messages, projects, workspaces, Memory pages, scheduled tasks, agents and skills | `422` |
| `POST /api/team/workspace/search-everywhere?workspace=` `{query, limit (default 50)}` | `{items:[{id,kind,label,description,path,line,metadata}]}` over one directory: files, folders, git branches and commits, problems, skills | `422 Workspace does not exist or is not a directory: <resolved>`, `422` |

### Wiki path rules (`validate_wiki_path`, first failing rule wins)

1. empty: `Wiki path must not be empty.`
2. starts with `/` or `~`, or `Path.is_absolute()`: `Wiki path must be relative: <p>`
3. suffix not exactly `.md` (`.MD`, `.md `, `.md` alone fail): `Wiki files must be Markdown (.md): <p>`
4. a raw `/`- or `\`-separated segment is `..` or `.`: `Wiki path may not contain '..' or '.': <p>`
5. one segment: must be one of `INDEX.md, LINT.md, LOG.md, USER.md` (case sensitive):
   `Only INDEX.md, LINT.md, LOG.md, USER.md are valid at wiki root level: <p>`
6. two segments: first one of `comparisons, entities, imports, notes, sources, topics`:
   `Wiki subdir must be one of [comparisons, entities, imports, notes, sources, topics]: got '<x>'`
7. more: `Wiki path too deep (max 2 components): <p>`
8. the resolved path (symlinks followed) must stay inside the wiki root:
   `Wiki path escapes root: <p>`

All are `400`. `topics//a.md` is valid (empty segments vanish) and is echoed unchanged.

### Frontmatter (`parse_frontmatter`)

`^\s*---\r?\n(.*?)\r?\n---\r?\n?(.*)` (dot matches newline) then `yaml.safe_load`.
No match, YAML error, empty or non-mapping block: all fields empty. `description`
= `str(value).strip()` (so a null value gives `"None"`, a number `"12"`); `updated`:
date or datetime → `isoformat()`, string → stripped or null if blank, anything
else null; `tags`: list → `str(t).strip().lower()` dropping blanks (a scalar gives
`[]`); `confidence`: `high|medium|low` after strip/lower else null; `sources`: list
→ stripped strings, blanks dropped. **Needs the YAML 1.1 loader** (dev-shared):
`2026-03-04` is a date, `yes` would be a bool, and so on.

## search-app: sources and merge

Sources run in a fixed order and are merged **round-robin** (one item from each
non-empty group in turn, de-duplicating by `id`) until `limit`; each source is capped
at `min(limit, 25)`:

| Group | Source | Row |
|---|---|---|
| 1 sessions | `chat_sessions` where `parent_session_id IS NULL`, `session_type != 'side_chat'`, `title`/`agent_name`/`workspace`/`scheduled_task_name` ILIKE `%q%` (wildcards escaped), newest `updated_at` first, 400 scanned | `id session:<uuid>`, label title or `scheduled_task_name` or `Untitled chat`, description `mode · <workspace basename> · agent · scheduled · <task>`, metadata `{mode, workspace, project_id, updated_at}` |
| 2 messages | `session_messages` roles user/assistant with content ILIKE, newest first, 200 scanned; one row per owning conversation (team member replies map to `parent_session_id` or `source_session_id`); chats whose own title matched are dropped from this group | `id message:<newest matching message id>`, label owner title, description `"N matches · excerpt"` (`N+` once the 200-row window is full) or just the excerpt, metadata `{mode, workspace, project_id, message_id, role, agent_name, match_count, excerpt, created_at}` |
| 3 projects | `coding_projects` not hidden/deleted, substring on name/description | `project:<id>`, description or `Coding project` |
| 4 workspaces | `coding_workspaces` not hidden/deleted that belong to a live coding project (worktrees resolve through `source_path`), substring on name/path | `workspace:<id>`, path and metadata `{workspace, kind, project_id}` |
| 5 scheduled tasks | all `scheduled_task` rows, substring on name/prompt/cron | `scheduled-task:<id>`, description `<cron or "every Ns" or type> · <status or paused>` (a new task's status is `pending`) |
| 6 memory | `search_memory_files(query, limit=min(limit,8), scope="all", abstain_weak=True)` | `memory:<path>`, label = frontmatter `description` or path with Markdown noise removed, description = excerpt cut to 200 characters, metadata `{source_ref}` |
| 7 agents | `config/agents/*.md` and `coding/*.md` (400 scanned), substring on name and file text | `agent:<name>`, description = frontmatter description or first prose line (240 chars) |
| 8 skills | every discovered skill (user, project roots, plugin, built-in) | `app-skill:<name>`, path = skill location, metadata `{name, source}` |

A failing source degrades to an empty group (warning logged). The excerpt window is
70 characters either side, `…` marks a cut, and `**`, `__`, `~~`, backticks, `<!-- -->`
and `#` heading marks are stripped from the window only.

### Memory scoring (`app/services/memory.py`)

Tokens `[^\W_]+` casefolded; stop words dropped (English and Vietnamese lists in the
source); light inflection stripping (`ies→y`, `ing`, `ed`, trailing `s` but not `ss`, doubled final
letter). Score = `overlap × coverage / ln(len(tokens)+10)` on `path\ntext`. With
`abstain_weak`, a page needs at least 1 piece of evidence for a query of ≤ 2 meaningful tokens, otherwise at least 2,
and coverage ≥ 0.5. Re-rank multiplier `1 + .12·path + .15·description + .2·tag + .5·coverage`.
Sorted by `(-score, source_ref)`. Candidates: `USER.md`, then `topics entities sources
comparisons` and (scope `all`) `notes imports`, each sorted by name, `.md` only,
unreadable files skipped. `source_ref`: `memory:user`, `topic:<stem>`, `entity:`,
`source:`, `comparison:`, `import:<stem>`, `note:<file name>`.

## search-everywhere: sources

`validate_workspace` only checks that the path (with `~` expanded, resolved) is an
existing directory. Four sources run concurrently, results are concatenated in the
order paths, problems, git, skills; de-duplicated by `id`; `per_source =
max(5, min(20, limit // 3))`.

- **paths**: `os.walk` top-down; at each level directories (sorted) are pruned when
  named `.git`, starting with `.`, in `node_modules dist build .venv venv __pycache__
  .ruff_cache .pytest_cache`, or matched by the workspace root `.gitignore`; entries
  are the sub-folders first and then the files, each sorted; the match is a
  case-insensitive substring of the relative POSIX path; stops after 20 000 entries
  visited. `id file:<path>` / `folder:<path>`; file metadata `{size, mtime (float),
  mime}` (`mimetypes`, default `application/octet-stream`), folder metadata null.
- **problems**: the in-memory problem list of `problems_service` (owned by the
  git-coding unit); not exercised here, it is populated by other routes.
- **git**: `git branch --format=%(refname:short)` filtered by substring and
  `git log --max-count=N --grep=<query> -i --format=%H%x1f%s` (5 s timeouts); a
  non-repository gives nothing. Rows `git-branch:<name>` (metadata `{branch}`) and
  `git-commit:<sha>` (label subject, description `sha[:12]`, metadata `{sha}`).
- **skills**: `discover_skills([workspace]).user_visible()` (project roots
  `.evoflux/skills`, `.agents/skills`, `.claude/skills` in the workspace and its
  ancestors, plus user, home, plugin and built-in), substring on `name description`,
  `skill:<name>`, metadata `{name, insert_text: "$name "}`.

## Files, tables and state

| Resource | Read | Written |
|---|---|---|
| `<wiki>/**` (`EVOFLUX_WIKI_DIR`) | all wiki routes, search-app memory | `PUT`/`DELETE`, `wiki_seed` (creates the six folders and a default `USER.md` at start-up), dream, the `note` tool, the extraction hook |
| `<wiki>/.memory-write.lock` | – | opened `a+b` and `flock`ed (POSIX only) around every write; Python on Windows takes no file lock, only an in-process `RLock` |
| `<wiki>/.scoped-memory-v1-backfilled` | – | written at start-up by the note back-fill (an atomic temp file `..scoped-memory-...evoflux-tmp` is briefly visible) |
| tables `chat_sessions`, `session_messages`, `coding_projects`, `coding_workspaces`, `coding_project_workspaces`, `scheduled_task`, `dream_notes_log` | search-app, tree | none by these routes |
| `config/agents`, skill roots, workspace tree, `git` | search-app, search-everywhere | none |

Writes use `atomic_write_bytes` (sibling `.<name>.XXXX.evoflux-tmp`, fsync, `os.replace`,
mode of an existing file kept). The pin `file-lock:wiki` exists because dream, the
`note` tool and extraction run in Python and write the same files: Rust must take the
same `.memory-write.lock` flock on POSIX while Python owns those writers.

## Services in the row that have no route

- `memory_stream_store.py` is the in-memory SSE turn store of the chat loop (single
  process, replay journal, TTL cleanup). It belongs to `chat-core`, not to this unit.
- `scoped_memory.py` (tables `memory_facts` and evidence, extraction claims) and
  `memory_vector.py` (optional semantic backend, disabled by default) are used by the
  agent loop hooks (`memory_context`, `memory_extraction`) and the `memory_search`
  tool; no HTTP route reads them. They move with `agent-loop-chat` / the tools lane.

## Findings (characterised by the tests; Rust must match unless the owner decides otherwise)

- **S1 no workspace authorisation.** `search-everywhere` accepts any existing
  directory on the machine (`~`, a drive root, another user's folder): it ignores
  `EVOFLUX_WORKSPACE_ROOTS`, the session and the project, and returns file names,
  sizes, mtimes and git branches/commit subjects. The Rust sidecar should authorise
  the workspace like the other workspace routes. *Needs a security review at Lb.*
- **S2 no length or depth limits on the wiki write**: `PUT` accepts any size.
- **P1 ILIKE only folds ASCII.** The SQL prefilter lowers only ASCII, so an
  upper-case non-ASCII title (`NƠI`) is never found, while a lower-case one is found
  by an upper-case query. The re-check in Python cannot rescue rows the prefilter dropped.
- **G1 `.gitignore` applies to directories only**: files matching a pattern
  (`*.log`) are still returned; dot-directories are pruned but dot files are not.
- **O1 sort order is OS dependent**: `sorted(Path.iterdir())` is case-insensitive on
  Windows and case-sensitive on POSIX. Tests avoid mixed case.
- **O2 backslash paths**: `topics\x.md` is a valid two-segment path on Windows and a
  root-level error on POSIX. Not tested.
- **E1 500 on non UTF-8**: `GET` of a file that is not UTF-8 returns a plain-text 500,
  and `GET /tree` lists such a file with empty metadata instead.
- **T1 stale scoped-memory marker** `..scoped-memory-*.evoflux-tmp` can be visible in
  the wiki root for a moment at start-up; tests ignore names containing `.scoped-memory`.
- **R1 the 20 000-entry cap** and the 5 s git timeouts are untested (slow).

## Test map

| File | Covers |
|---|---|
| `test_auth_routes.py` | `401` on all six routes, missing and wrong token, auth before validation, token in query |
| `test_wiki_tree.py` | seeded tree, sections and order, filtering, 18 frontmatter cases, unreadable files, `unprocessed_only` with the dream log, missing folders, boolean parsing |
| `test_wiki_file.py` | all path rules on GET/PUT/DELETE, metadata, 404, CRLF, non-UTF-8, exact bytes, every section, lock file, body validation order, protected files, symlink escape (POSIX) |
| `test_search_app.py` | validation and bounds, every source's row shape, grouping and round-robin, limits, ILIKE wildcards and non-ASCII, memory scoring cases, special characters |
| `test_search_everywhere.py` | validation, workspace errors, S1, file/folder rows and order, ignore rules, per-source caps, git rows, group order, workspace skills, read-only |

Not covered: the 20 000-entry cap, git timeouts, problems rows (state owned by
git-coding), memory scoring beyond the cases above, Windows backslash paths, and
`TARGET=rust` (not applicable until Lb mounts the crate).

## Lb: size and dependencies

**Size: medium, about 1,400 lines of non-test Rust**: wiki store, path rules, frontmatter
(about 450), memory scoring (about 250), app search sources and merge (about 400),
repository search (about 300).

Depends on: (a) the YAML 1.1 loader for frontmatter (dev-shared); (b) `core::db` reads
for the seven tables; (c) the shared atomic writer and the `.memory-write.lock` flock
(`file-lock:wiki` pin) plus an adapter so Python dream/note/extraction see Rust writes;
(d) agent and skill discovery from the `agents-skills-registry` lane for groups 7 and 8
and for the workspace skills; (e) a `git` runner and the gitignore matcher shared with the
filesystem tools; (f) the problems list owned by git-coding; (g) owner decisions on
S1, P1 and G1. **Needs a security review at Lb** (path confinement, workspace
authorisation, file writes).
