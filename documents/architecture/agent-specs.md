# Agent Spec-Driven architecture

Status: implemented

**Agent Spec-Driven** is the product surface for ASDD. It is a thin layer over the
repository's own working tree, and it does not replace teams, Workflows, Goal,
Plan mode, ChangeSets, Git worktrees or CompletionContract verification.

## The storage decision

ASDD has no tables. A change is a directory of Markdown in the repository, and
that is the whole persistence layer.

The method it replaced kept the same facts twice — five `trace_*` tables and a
tracked document tree — and defended the pair with a content hash on every
mutation and a unique index binding one run to one chat session. Every
disagreement between the two copies surfaced as a conflict the user could
neither see nor fix. Deleting the tables removed the disagreement, and with it
the hash and the session lock that existed only to manage it.

What that costs: no optimistic concurrency. Two writers racing on one file
overwrite each other. A per-repository lock serializes the product's own writes,
and `git diff` shows the result. That trade is the point of the design, not an
oversight.

## Layers

| Module | Owns |
|---|---|
| `asdd_document.py` | front matter and body; parse forgiving, render deterministic |
| `asdd_spec_format.py` | the requirement/scenario grammar and the delta merge |
| `asdd_store.py` | the catalogue on disk: changes, specs, evidence, archive |
| `asdd_lifecycle.py` | phase gates, blockers and the action rail, computed from files |
| `asdd_service.py` | API payloads and phase prompts |
| `asdd_setup_service.py` | what setup writes into a repository |
| `asdd_runtime.py` | the per-repository write lock |

Every module below `asdd_service` is synchronous and pure over the filesystem.
Routes call them through `asyncio.to_thread`, so filesystem I/O never runs on
the event loop and never sits inside a database transaction.

## Repository setup boundary

`/api/asdd/setup` resolves the authorized repository set from the current
workspace or Coding Project, closes the database read scope, and only then
inspects or writes repository files in a worker thread.

Setup writes:

```text
.evoflux/asdd/config.json
.evoflux/asdd/RULES.md
.evoflux/skills/asdd-{propose,specify,plan,implement,verify,archive}/SKILL.md
.evoflux/skills/asdd-*/.evoflux.json
.evoflux/skills/asdd-*/references/code-context-contract.md
<data_directory>/project.md
<data_directory>/specs/README.md
<data_directory>/changes/README.md
<data_directory>/changes/archive/
```

All of it is tracked, plus `.evoflux/asdd/.gitignore` carrying the single rule
`locks/`. The write lock is the one machine-local file ASDD creates; there is no
runtime ledger and no template cache, so everything ASDD needs at run time is
either a tracked file or comes from the installed package. That is what lets an
isolated worktree behave exactly like the checkout it came from.

The service rejects symlink and path escapes, invalid Skill front matter or
scope, oversized files and malformed manifests. An installation missing files or
carrying an older manifest reports `upgrade_required`; repair writes what is
missing and never touches a change or a capability spec.

Each Skill sidecar scopes it to Coding mode. The skill harness discovers
`.evoflux/skills` at project precedence, so the bundle is absent from global and
built-in catalogues and becomes eligible only when that repository is in the
active workspace or project.

## Identity

A change's identity is its directory name: kebab-case, derived from the title
unless the caller supplies one, and unique against both open and archived
changes. Nothing else identifies a change — no UUID, no content hash, no session
id — and no API takes one.

`delegation_tasks.asdd_change_id` records which change asked for a delegated
mission. It is a string, deliberately not a foreign key: the change lives in the
repository, so editing, renaming or archiving it cannot invalidate a row here.

## Concurrency

`asdd_runtime.asdd_catalogue_lock` serializes writes per runtime owner. A linked
Git worktree resolves to its source checkout through the Git common directory,
because two worktrees of one repository share a `.evoflux/` tree and locking per
checkout would let them interleave. The lock is reentrant: `archive_change`
rewrites several pages through helpers that take it themselves.

## Verification

`CompletionVerificationHook` still requires a machine-verified completion
contract after file mutations, and still content-addresses its own result cache
by `artifact_hash`. That hash is an internal cache key: nothing asks a person or
an agent to carry it, and no operation fails because it changed.

A repository running ASDD also gets a git baseline at the start of a turn, so
changes made by a shell command or a delegated member count toward that turn's
verification rather than only the edits made through file tools.
