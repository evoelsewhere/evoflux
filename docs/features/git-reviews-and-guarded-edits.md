# Git, reviews, and guarded edits

Coding mode exposes the full local Git lifecycle and provider-neutral pull/merge
request review. Mutations are serialized per repository and sensitive output is
sanitized before it reaches logs or the UI.

## Local Git surface

The source-control UI and API support:

- repository status/init/clone and local identity;
- stage/unstage/discard by path or all changes;
- commit and bounded diff views;
- branch create/checkout/delete;
- tags create/delete/push;
- remote list/create/update/delete;
- fetch, pull with configured strategy, push and bounded long-running jobs;
- log and changed files per commit;
- stash list/create/apply/pop/drop;
- merge, rebase, cherry-pick and revert;
- conflict detection plus continue/abort;
- managed worktrees for parallel agents.

Git commands use argument arrays, repository locks, bounded output/timeouts and
process-group cleanup. Network credentials are injected through an ephemeral
credential helper scoped to the expected host; tokens and credential-bearing
URLs are redacted from errors and results. Force push is disabled by default.

## Git AI actions

Explicit AI actions can summarize changes, draft commit content or provide
review assistance. They receive bounded repository/diff context and return a
reviewable result; they do not silently run an unrelated Git mutation. The
selected model and capability validation use the same provider registry as
normal agent turns.

## Provider-neutral code reviews

Configured Git server connections support GitHub, GitLab, Bitbucket Cloud,
Bitbucket Server, Gitea and Azure DevOps. EvoFlux discovers repository remotes,
resolves the most specific connection, paginates within configured limits and
normalizes provider payloads into a stable review contract.

Depending on provider capability, users can list/open reviews, inspect changed
files, checks, discussions and approvals, add general/inline comments, reply or
resolve threads, approve/request changes, edit metadata/state, merge, and create
new pull/merge requests.

Mutation settings can disable review writes globally or require successful
checks before merge. Insecure HTTP/TLS connections are rejected unless the
operator explicitly enables them. Remote images are fetched only from validated
provider/CDN origins through bounded media routes.

## Guarded ChangeSets

AI editor actions, LSP code actions/rename and selected review/Git flows converge
on one ChangeSet contract:

1. normalize repository-relative paths and capture base hashes;
2. produce per-file diffs for review;
3. allow whole-set or selected-file acceptance/rejection;
4. reject stale files or document versions;
5. atomically replace accepted files and roll back earlier writes on failure;
6. optionally create a session snapshot;
7. run bounded, deterministic verification already supported by the project.

LSP UTF-16 positions are converted explicitly. No language server may bypass
review through a direct `workspace/applyEdit`.

## Source and tests

Primary code: `app/api/routes/team/git.py`, `git_ai.py`, `reviews.py`,
`change_sets.py`; `app/services/git_ops.py`, `git_ai_service.py`,
`code_review_service.py`, `change_set_service.py`; Git/review/editor components.

Focused tests cover Git parsing, locks, credentials, routes, provider adapters,
review mutations, ChangeSet atomicity/staleness/UTF-16 conversion, and the
frontend Git/review dialogs.
