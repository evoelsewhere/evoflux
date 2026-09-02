---
name: coding-git-workflow
description: Use this skill to structure commits, branches, and pull/merge-request submission for a piece of work — commit granularity, branch lifetime, and what a PR description must state. It favors small reviewable slices over one large branch and treats a version number as a promise to consumers; do not use it for the code change itself, or for reviewing someone else's pull/merge request.
---

# Structure commits, branches, and PR submission

Prefer many small, independently reviewable, working commits over one large
branch held open.
Do not load bundled references when this skill activates.

## Choose commit granularity

1. Commit at each point the working tree passes its narrow check — that
   state is a save point you could safely reset back to, not a checkpoint to
   defer. Do not batch unrelated changes into one commit; do not split one
   logical change across commits that each leave the tree broken.
2. Prefer several small, focused commits over one broad commit when the
   change spans independent concerns; do not force multiple commits onto a
   change that is genuinely small and cohesive.
3. Write the commit message as a statement about behavior, not a diary of
   edits: state what changed and why, not "fix stuff" or a restated diff.
4. Read [references/commit-and-release-discipline.md](references/commit-and-release-discipline.md)
   for atomic-commit criteria, branch-lifetime guidance, and versioning as a
   consumer promise.

## Execute one commit

1. **Stage.** Run `git status --porcelain`. Review it — and the content of
   any unfamiliar or sensitive-looking file — before staging; do not
   `git add` a credential, key, or unrelated in-progress file. Stage only the
   files that belong to this logical change.
2. **Analyze.** Run `git diff --cached` to assess technical scope and
   architectural impact — a boundary, schema, or public-contract shift
   documented under `documents/architecture/` or `documents/reference/`, not
   only the literal lines changed.
3. **Reconcile docs where the change requires it.** Update the specific
   documented contract the diff touches (a feature page, an architecture
   boundary, a reference page) when accepted behavior shipped; do not
   blanket-sync unrelated documentation on every commit.
4. **Generate the message.**
   - Format: `<type>: <subject>` — see the type table below.
   - Subject: a concise imperative summary of the staged diff.
   - Body: a blank line, then **Motivation**, a bulleted **Technical
     Changes** deep dive, and **Impact** (what a consumer or operator would
     observe).
5. **Commit.** Run `git commit -m "<message>"` and report the resulting
   commit hash with a brief summary. Never use `--no-verify` or bypass a
   commit hook to force a commit through.

| Category | Type |
| --- | --- |
| Features | `feat` |
| Fixes | `fix` |
| Refactor | `refactor` |
| Maintenance | `chore` / `docs` |
| Style | `style` |

## Keep branches short-lived

Prefer a branch merged within one to a few days over one held open across
many days of unrelated changes; an old branch accumulates conflict risk and
review burden. Use `worktree_start`/`worktree_finish` to isolate concurrent
work on separate branches without disrupting the primary working tree, and
prefer a feature-gated or default-off change over a long-lived branch when
the work cannot land as a single reviewable slice.

## Submit for review

State in the PR description what changed, why, what was deliberately not
touched (an explicit "did not touch" note prevents a reviewer from assuming
silence means completeness), and what was run to verify it. Use
`create_pull_request` only once the branch is pushed and the description is
ready; do not open a PR as a placeholder for unfinished work unless the user
asked for a draft.

## Execution discipline

Use `shell` for git commands (status, add, commit, log, diff) and
`worktree_start`/`worktree_finish` for isolated parallel branches. Confirm
the working tree status before a commit that could discard uncommitted work;
never force-push, rewrite shared history, or discard uncommitted changes
without explicit authorization for that specific action.

## Deliverable

State the commits made (or planned) and their granularity, the branch and
its expected lifetime, and the PR description content including anything
deliberately left untouched.
