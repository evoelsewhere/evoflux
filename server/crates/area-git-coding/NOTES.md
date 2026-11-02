# area-git-coding NOTES

Python source: `app/api/routes/team/{git,git_ai,worktrees,reviews,projects,change_sets,problems,editor}.py`,
`app/api/schemas/{git,git_ai,change_sets,reviews,projects,problems}.py`,
`app/services/{git_ops,git_credentials,git_ai_service,coding_workspace_service,coding_project_service,coding_purge_service,coding_workspace_authorization,code_review_service,change_set_service,problems_service,editor_context_service,editor_action_service,delegation_worktree_service,verification_commands}.py`,
`app/agent/sandbox_config.py` (worktree roots). Unit `git-coding` (`server/routing.toml`;
pin breakers `adapter:git-coding`, `file-lock:git-repo`; service `standalone_coding_purge`).
Contract tests: `contract-tests/git-coding/` (see "Test status").

**Status:** La (this crate's stub, NOTES, contract tests). The crate is not mounted:
`units.rs` is untouched, as for the other La lanes.

The unit is wide. Four families share one workspace parameter and one set of git helpers:
local git (`/workspace/git/**`, 46 routes), worktrees, Coding projects, and the review
and editor helpers around them. `/workspace/git/ai` belongs to this unit by prefix (the
board also lists a `git-ai` lane, blocked on phase 2); only its refusals are covered.

## Scope: which routes the unit serves

`routing.toml` prefixes: `/api/team/workspace/git/**`, `/workspace/worktrees/**`,
`/reviews/**`, `/projects/**`, `/workspace/change-sets/**`, `/workspace/problems/**`,
`/workspace/editor/**`. Everything is under `/api/team`.

Every route: `401 {"detail":"Unauthorized — EvoFlux access key required."}` before
validation. Validation errors are FastAPI's `422 {"detail":[...]}`; messages below are
`detail` strings. The workspace parameter (`?workspace=` or a body field) is checked by
`team_manager.validate_workspace`: it must be an existing directory, else
`422 Workspace does not exist or is not a directory: <resolved>`. There is **no
allowlist** (S1).

## `/workspace/git`

| Endpoint | Behaviour | Errors |
|---|---|---|
| `GET /repository` | `is_git_repo`, `root`, `branch` (null when detached), `detached`, `upstream`, `head_sha` (12), `head_subject`, `user_name`, `user_email` (from `git config --get`, so global config shows through); a folder without `.git` (dir or file) answers `is_git_repo:false` with nulls | `422` workspace |
| `POST /repository/init` | `git init -b <default_branch>`; reply is the repository | `409 Git is already initialized`, `422 Invalid default branch: <x>` |
| `POST /repository/clone` | `{parent,url,directory?,branch?,depth?}` to `git clone --origin origin` with the saved credential for http(s) URLs; `{workspace,name,remote_url}` | `409 Clone destination already exists: <p>`, `422` directory / branch / url, `502`/`504` git |
| `POST /repository/identity` | local `user.name` and `user.email`, trimmed, no control characters | `422 Invalid Git identity` |
| `GET /changes` | `git status --porcelain=v2 --branch --untracked-files=all`; `files[{path,status,staged,old_path}]`, a file staged and changed again appears twice | none (git failure is an empty list) |
| `POST /stage`, `/stage-all`, `/unstage`, `/unstage-all`, `/discard` | `git add`, `restore --staged` (or `rm --cached` before the first commit), `restore` plus `clean -f -d` for untracked paths; `{"ok":true}` | `422 Not a git repository`, `502` git |
| `POST /commit` | optional `paths` are staged first; `amend`; reply `{sha,message}` | `409 Nothing to commit`, `502` |
| `GET/POST/DELETE /branches`, `POST /branches/checkout` | `for-each-ref` of heads and remotes (ahead/behind only for the current one); create (+ checkout by default), delete (`-d`, `-D` with `force`), `switch` | `422 Invalid branch name: <x>` / `Invalid ref name: <x>`, `502` |
| `GET /diff-view?path` | staged, unstaged or untracked file as a diff; untracked files are synthesised; over `git.max_diff_bytes` (2,000,000) `413` | `422 Invalid path` (absolute or `..`) |
| `GET/POST/DELETE /tags`, `POST /tags/push` | list (limit clamped to 1..500), lightweight or annotated create, delete, push one or all as a background job | `422 Invalid tag name: <x>`, `502` |
| `POST /merge`, `/rebase`, `/cherry-pick`, `/revert` | `{success,conflicts[],message}`; conflicts leave the operation in progress; SHAs must match `^[0-9a-f]{4,64}$` | `422 Invalid SHA: <x>` / `Invalid ref name` |
| `GET /conflicts`, `POST /continue`, `POST /abort` | state from `.git` markers; `422 No in-progress operation found` | `502` when git refuses |
| `POST /fetch`, `/pull`, `/push` | background job (below); `prune` defaults to settings `git.prune_on_fetch`; pull strategy defaults to `git.default_pull_strategy` (`ff_only`); `force_with_lease` needs `git.allow_force_push` | `403 Force push is disabled in Git & reviews settings.`, `422` remote / branch names |
| `GET /jobs` | the last job of the workspace or `null` | – |
| `GET/POST/PUT/DELETE /remotes` | `git remote` with URL validation (below) | `422`, `502` |
| `GET /log` | `--topo-order`, paged (`limit` 1..500, `skip`), `branch`, `all_branches`, `path`; `{entries,has_more,next_skip}` | `422 Invalid ref name` |
| `GET /log/{sha}/files` | `git show --name-status`; short SHAs allowed | `422 Invalid SHA` |
| `GET/POST/DELETE /stash`, `/stash/apply`, `/stash/pop` | list (`sha` is 8 characters), push (`include_untracked`), apply and pop report `{success,conflicts,message}` in the body (a missing index is `200 success:false`), drop | `502` for drop |

Background jobs (`GitJobRegistry`, in memory, keyed by the resolved workspace): at most
one per workspace; starting another while one runs returns the running job unchanged;
status `running`, `done`, `error` (`cancelled` on shutdown); a finished job is kept 10
minutes. `fetch`, `pull`, `push` and `tags/push` return the job at once. Each runs under
the workspace's `git` lock (`GitLockRegistry`, one asyncio lock per path).

`validate_ref_name` is a pure-Python approximation of `git check-ref-format --branch`;
tags and remotes use `git check-ref-format`.

## Worktrees

`GET/POST/DELETE /workspace/worktrees` (`source_workspace`): `422 Worktrees are only
supported for git projects.`; names are slugged (`My Feature!` is `my-feature`, blank is
`session`), made unique with `-1`, `-2` ... up to 26 tries (`409`), branch defaults to
`EvoFlux/<name>`; `git worktree add --no-checkout` then `reset --hard`, then the
database rows. Managed roots are `<repo>/.evoflux/worktrees` (default) and the legacy
`<data>/worktrees/<name>-<sha1[:10]>`; removal outside them is `403 Only
EvoFlux-managed worktrees can be removed.`, removal deletes the directory (`worktree
remove --force`) and `EvoFlux/*` branches only.

## Projects, tree, reviews

- `GET/POST /projects`, `GET/PUT/DELETE /projects/{id}`, `POST/PUT/DELETE
  /projects/{id}/workspaces[/{wid}]`: rows in `CodingProject`, `CodingProjectWorkspace`,
  `CodingWorkspace`. `DELETE` purges the project's sessions, runtime and scheduled
  tasks (`coding_purge_service`) and never touches the repositories. The sidebar tree
  (`/workspace/tree`, owned by `workspace-files` by prefix) reads the same tables.
- `/reviews/connections` (CRUD plus `POST /connections/test`): Git server connections;
  the token goes to `<config>/.env` under `EVOFLUX_GIT_CONNECTION_<ID>_TOKEN` (or the
  caller's variable name), is never echoed (`has_token`), and is removed with a managed
  connection.
- `GET /reviews`, `GET/POST /reviews/{workspace_id}[/{number}[/actions]]`,
  `GET /reviews/{workspace_id}/media`: provider-neutral pull-request calls to GitHub,
  GitLab, Bitbucket, Gitea or Azure DevOps. Only the refusals that come before a server
  call are covered (no test reaches a Git server).

## Change sets, problems, editor

- `POST /workspace/change-sets`, `GET /{id}`, `GET /{id}/files/{path}`, `POST
  /{id}/apply`, `POST /{id}/reject`: in-memory (1 hour TTL, 100 files, 2 MB per file,
  10 MB total), per-file `base_hash` staleness (`409 {"code":"stale_change_set","paths"}`),
  paths normalised to the repository. `apply` writes the files; with `verify` (default
  true) it then runs LSP diagnostics and the project's own test command derived from
  its files (`pytest`, `cargo test`, `go test ./...`, `npm|pnpm|bun test`), 120 s each
  (S4). Model-supplied `verification_commands` are ignored.
- `GET /workspace/problems`, `POST /{id}/dismiss|suppress|restore`: problems are in
  memory; decisions persist to `<workspace>/.evoflux/problems-decisions.json`, a file
  written inside the user's repository.
- `POST /workspace/editor/context|action`, `POST /workspace/git/ai`: need a Coding
  session and a model; the refusals before the model call are covered.

## Files, processes, state

| Resource | Used by |
|---|---|
| any folder named by `workspace` | read and written by git (working tree, index, `.git`), including hooks the repository defines |
| `git` child processes | process group, closed stdin, `GIT_TERMINAL_PROMPT=0`, timeouts 5 to 120 s (network jobs: `git.network_timeout_seconds`, 120 s), output cap `git.max_diff_bytes` where set |
| `<repo>/.evoflux/worktrees/**`, `.git/info/exclude` | worktree create (the root is locally ignored without editing tracked files) |
| `<config>/.env` | review connection tokens (`write_env_credentials`, shared with settings-providers) and `os.environ` |
| `<workspace>/.evoflux/problems-decisions.json` | problem decisions |
| tables `coding_workspace`, `coding_project`, `coding_project_workspace`, `git_server_connection`, `chat_session` | projects, worktrees, reviews |
| memory: `git_jobs`, `git_locks`, change sets, problems | lost on restart |

## Pins check

`rg "git_ops|git_credentials|coding_workspace_service|change_set_service|problems_service"`
outside the unit shows the agent side calling the same helpers in process: the shell and
git tools, `delegation_worktree_service`, `coding_workspace_authorization` (used by
chat-core to authorise a workspace), `post_edit_diagnostics` and `lsp_manager` (change
sets), `team_manager`. **Needs adapter** before cutover (`server/AGENTS.md` §9): the
authorisation check chat-core makes per Coding turn reads `CodingWorkspace` and
`CodingProjectWorkspace`, which this unit's project routes write; and the in-memory
change-set and problem stores that the agent tools publish into. La adds none.

## Odd behaviour (pinned as is unless noted)

- `GET /repository` reads `user.name` and `user.email` through git's normal lookup, so
  a developer's global identity appears in the reply.
- `POST /stage` without `paths` runs `git add` with no pathspec (git's own message,
  `502`); `POST /unstage` without paths acts on the whole tree.
- `discard` with paths restores tracked files to the **index**, not to `HEAD`.
- `stash` with nothing to stash is `{"ok":true}` and creates no entry.
- `stash/apply|pop` for a missing index is `200` with `success:false`; `drop` is `502`.
- A repository with no commit diffs against the empty tree and unstages with
  `git rm --cached`.
- `pull` on diverged history with the default `ff_only` ends the job in `error`, not the
  request.
- A second fetch/pull/push while one runs answers with the running job's own `op`.
- **B7** a tag name such as `-x` passes `git check-ref-format refs/tags/-x` and is then
  passed to `git tag` as an option (argument injection; `502` for `-x`). Branch, ref and
  remote names reject a leading dash; tag names do not.
- **B8** `POST /tags/push` with `tag` but no `remote` runs `git push refs/tags/<tag>`, so
  git takes the ref for the remote name and the job ends in `error`; it works with
  `remote`. Without `tag` (`--tags`) it works.
- `POST /cherry-pick` with an empty `shas` list is `200 success:false` (git refuses).
- **B9** `POST /continue` runs `git merge --continue` / `rebase --continue` without `GIT_EDITOR`, so git can wait for an editor that never comes until the 60 s or 120 s timeout (`504`); not exercised.
- `PUT /projects/{id}` with `settings` merges keys into the stored settings; it does not
  replace them.
- `ssh://user@host/...` remotes are refused (any URL userinfo is), while scp-like
  `git@host:path` is accepted.
- Worktree create runs `reset --hard` inside the new directory; if that fails, the
  worktree and the branch are removed.
- `DELETE /workspace/worktrees` for a path inside a managed root that git does not know
  is `{"removed":true}` (the database row is soft-deleted).

## Security findings (for the owner)

- **S1: no workspace allowlist** (same as workspace-files): any folder, with the access
  key as the only gate, can be initialised, cloned into, committed to, reset
  (`discard` removes untracked files with `clean -f -d`) or force-pushed (only when
  the setting allows it).
- **S2: repository hooks and configuration run.** Commit, merge, checkout, rebase and
  `git status` execute the repository's own hooks and `core.fsmonitor`/`core.sshCommand`
  settings, so a cloned repository can run code when the UI opens it. `GIT_*` is not
  scrubbed beyond the prompt variables.
- **S3: `file://`, `git://` and `ssh://` remotes are allowed** (clone and `remotes`),
  so a caller can clone any local repository into a workspace and make git talk to
  arbitrary hosts. URLs with `-` prefix, control characters, `::` helpers and embedded
  credentials are refused.
- **S4: `POST /workspace/change-sets/{id}/apply` with `verify` (default) runs the
  project's own test command** (`npm test`, `cargo test`, `pytest`, ...) with a scrubbed
  environment, up to 120 s, i.e. code from the repository whose files were just
  written. The command string is derived from files, never from the request.
- **S5: review connection `token_env_var` accepts any `[A-Z_][A-Z0-9_]*` name**, so
  `PATH`, `PYTHONPATH`, `LD_PRELOAD` or `EVOFLUX_*` can be written to `.env` and
  `os.environ` with a caller-chosen value (like settings-providers S2). The write
  happens before the row is committed. Not pinned by a test.
- **S6: `POST /reviews/connections/test` makes an outbound HTTPS request to a
  caller-chosen host** with a caller-supplied token (SSRF to any reachable address);
  `allow_insecure_connections` also allows `http` and `verify_ssl=false`. Not exercised.
- The credential for git network jobs travels as environment variables to an inline
  credential helper; output is scrubbed of the token (`sanitize_git_output`).
  `GIT_SSL_NO_VERIFY=1` is set when a connection disables `verify_ssl`.
- Problem decisions are written into the repository (`.evoflux/`), and worktrees into
  `<repo>/.evoflux/worktrees`: application state inside user-owned source.

## Test status

Contract tests: see the LANDED line for the case count and the results against Python
v3.1.1. They use local bare repositories as remotes, a temp `HOME` (the backend has no
git identity: routes that commit need a local one, which the fixtures set) and never
reach a Git server. `TARGET=rust` is not applicable until Lb mounts the crate. Not
covered: success paths of `/reviews/**` provider calls, `editor/action` and `git/ai`
with a model, `apply` with `verify=true`, `POST /connections/test` against a server,
credential-bearing network jobs.

## Lb: size and dependencies

Largest pieces: the git runner (process group, timeouts, output caps, credential
helper, sanitising) which `workspace-files` and the agent tools will share; the porcelain
v2 and log parsers; the job and lock registries; the worktree and project services
(database); change sets and problems (in-memory stores with TTL); the provider-neutral
review client (`code_review_service`, the bulk). Suggest slices: git local, git network
and jobs, worktrees, projects and tree, change sets and problems, reviews. Depends on
`core::auth`, `core::db`, a git process helper, the `net` HTTPS client, and the
`.env` writer from the settings port.
