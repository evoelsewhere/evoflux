# Git, source control, and code-review audit

Date: 2026-08-18

## Outcome

Coding Mode now covers the core repository lifecycle inside EvoFlux: clone or
open, inspect, edit, stage, discard, commit/amend, branch, fetch/pull/push,
history, stash, rebase/cherry-pick/revert, tags, conflicts, and create/review/
merge/close pull or merge requests. The remote-review contract is shared by
GitHub, GitLab, Bitbucket Cloud, Bitbucket Data Center, Gitea/Forgejo, and Azure
DevOps. Provider differences remain explicit instead of being simulated.

This pass built on the production-safety work recorded in
`git-pr-production-audit-2026-07-31.md`. Existing desktop changes outside the
Git/review surface were intentionally preserved.

## Findings fixed in this pass

### Repository acquisition and daily Git UX

- Added an in-app **Clone repository** flow to the existing Coding workspace
  picker. HTTPS clones reuse matching shared Git-server credentials; SSH clones
  use the user's SSH agent. Embedded credentials and unsafe remote-helper
  protocols remain rejected.
- Added clone validation for destination name, branch, existing targets,
  network timeout, output bounds, and server-local parent scope.
- Fixed amend being disabled when no files were staged even though the backend
  correctly supports `git commit --amend --no-edit`.
- Fixed discard failing for untracked-only selections and failing to remove
  nested untracked directories. Destructive file actions now have explicit UI
  confirmation.
- Fixed Git C-quoted UTF-8 paths, so files such as `café notes.txt` work in
  status and diff views.
- Fixed untracked diff detection to use the same porcelain-v2 parser as status,
  including quoted paths.
- Prevented a consumed workspace-picker trigger from reopening after responsive
  sidebar remounts or Coding navigation.

### Provider-neutral review context

- Added a normalized `files` contract across all six provider adapters:
  path/old path, status, additions/deletions, bounded patch, binary/truncation
  state, inline-comment eligibility, and current head/base/start coordinates.
- Retained provider-native `changes` for compatibility while giving the UI and
  AI one stable changed-file model.
- Added bounded pagination for detail files, comments, discussions, approvals,
  Bitbucket cursors, and Azure iteration changes. The earlier first-page-only
  gap is closed within the configured page limit.
- Fixed GitLab left-side inline comments to send `old_line` and the real old
  path for renamed files.
- Fixed Bitbucket Data Center merge requests to refresh and send the current PR
  version plus `strategyId`, matching its optimistic-concurrency API.

### Review workbench and AI linkage

- Review details now render changed files and unified patches using the same
  parser as local Source Control. Users can select a diff line and publish an
  inline comment without opening a provider website.
- Patch-unavailable, binary, and truncated states are explicit. Providers that
  return metadata without a text patch still expose file navigation and full AI
  review through the local checkout.
- Added guarded merge, close, and reopen actions with confirmation, check/
  approval/conflict context, provider-specific merge strategies, and draft or
  conflict blocking.
- Added Open, Ready, Drafts, Closed, and Merged review views. Closed and merged
  states are mapped to each provider's native lifecycle vocabulary.
- Create Review now detects an unpublished local source branch, pushes it with
  the saved credential, waits for the Git job, and then creates the PR/MR.
- Review mutations now surface provider failures in a toast instead of leaving
  unhandled promises or clearing failed comment drafts.
- New review chats start by calling `get_code_review` for the exact repository
  and number, grounding AI in current head SHA, normalized files, existing
  threads, approvals, checks, and mergeability. The prompt keeps remote
  publishing read-only until the user explicitly requests a mutation.

## Provider support matrix

| Workflow | GitHub | GitLab | Bitbucket Cloud | Bitbucket DC | Gitea/Forgejo | Azure DevOps |
| --- | --- | --- | --- | --- | --- | --- |
| List open/closed/merged | Yes | Yes | Yes | Yes | Yes | Yes |
| Create PR/MR | Yes | Yes | Yes | Yes | Yes | Yes |
| Normalized files | Patch | Patch | Metadata | Metadata | Patch | Metadata |
| Conversation/inline comments | Yes | Yes | Yes | Yes | Yes | Yes |
| Reply/resolve thread | Reply; REST cannot resolve | Yes | Yes | Yes | Version-limited | Yes |
| Approve/request changes | Yes/yes | Yes/no formal event | Yes/yes | Version-dependent | Yes/yes | Yes/yes |
| Checks and merge readiness | Yes | Yes | Yes | Often unavailable | Version-dependent | Yes |
| Merge/close/reopen | Yes | Yes | Yes | Yes | Yes | Yes |

“Metadata” means that provider's bounded file-list endpoint does not return a
unified patch. EvoFlux shows the affected files, uses the local repository for
full semantic review, and does not invent unsafe inline coordinates.

## Verification

- Backend Git/review service, route, credential, and agent-tool suites.
- New regression tests for clone, discard, Unicode paths, diff parsing,
  cross-provider file normalization, pagination, lifecycle filtering, GitLab
  old-side comments, and Bitbucket Data Center merge versioning.
- Ruff lint and format checks for the changed backend surface.
- Frontend TypeScript, ESLint, focused Vitest tests, and production build.
- Browser QA at desktop and 390x844 mobile breakpoints for the clone workspace
  picker, Source Control amend state, Review lifecycle filters, and workbench
  layout.

## Remaining architecture work

These items do not block the single-user desktop workflow, but remain before
claiming an internet-exposed, multi-tenant server deployment is complete:

1. Mandatory server-mode authentication and RBAC for Git writes, connection
   administration, review mutation, and merge.
2. OS keychain or external secret-manager storage with rotation and audit
   events, replacing config-file token storage.
3. Durable remote Git jobs with cancellation, restart recovery, progress, and
   history instead of the current in-memory registry.
4. Sandbox provider contract suites against real GitHub Enterprise, GitLab,
   Bitbucket, Gitea/Forgejo, and Azure instances, including version-specific
   merge policies and rate limits.
5. Optional provider-specific full-patch adapters for Bitbucket and Azure. Until
   then EvoFlux deliberately uses the local checkout rather than fabricating
   remote inline positions.
