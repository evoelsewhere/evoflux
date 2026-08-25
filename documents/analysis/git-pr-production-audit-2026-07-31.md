# Git and pull-request production audit

Date: 2026-07-31

## Outcome

The Git and pull/merge-request feature is now substantially safer for the
single-user EvoFlux desktop deployment model. Remote operations are serialized
per workspace, non-interactive, bounded by configurable timeouts, kill their
whole process group on timeout/cancellation, redact credentials, and reject
unsafe remote inputs. Review APIs now have retry/concurrency/pagination policy,
TLS and mutation gates, and an end-to-end create-review flow in both the UI and
agent tool.

This audit does **not** classify an internet-exposed or multi-tenant EvoFlux
server as fully production-ready. The remaining architecture items below need
to be resolved for that deployment model.

## Fixed findings

### Git correctness and concurrency

- Fixed duplicate background requests constructing un-awaited coroutines.
- Fetch, pull, push, and tag push now hold the same per-workspace lock as local
  mutations, preventing checkout/rebase/commit races.
- Fixed linked-worktree conflict detection where `.git` is a pointer file.
- Fixed porcelain-v2 parsing for staged-and-unstaged files, renames, unmerged
  paths, quoted paths, and remote branch names.
- Fixed commit-file history (`git show`) argument ordering.
- Fixed unstage in an unborn repository and made no-op commit return HTTP 409.
- Stash apply/pop now surfaces unmerged files even when Git writes no operation
  marker.

### Git process and credential safety

- Every Git process is non-interactive and runs in an isolated process group.
- Timeout and task cancellation terminate child SSH, credential, hook, and Git
  processes; large diff output is stopped while streaming instead of buffered
  without limit.
- Saved server credentials are supplied through an ephemeral credential helper,
  never embedded in argv or persisted into the remote URL.
- Tokens and credentialed HTTP URLs are redacted from command results.
- Remote names, branch names, remote helper schemes, credentialed URLs, and
  unsupported protocols are rejected before process execution.
- Force-with-lease has a global opt-in kill switch; regular push stays enabled.

### Pull/merge-request reliability

- Read requests retry transient transport, timeout, rate-limit, and selected 5xx
  failures with bounded exponential backoff; mutations are never auto-retried.
- Redirects are rejected instead of forwarding credentials to another host.
- Repository aggregation has configurable concurrency and pagination caps.
- Plain HTTP and disabled TLS verification are blocked by default, including
  private review-image fetches.
- A global mutation kill switch covers create, comment, approve/request changes,
  update, close/reopen, thread resolution, and merge.
- Merge can require normalized successful checks.
- Ambiguous duplicate connection targets and duplicate token environment
  variables are rejected; changing a managed token variable safely cleans up
  the old secret after persistence.
- Credential `.env` updates are atomic and newly replaced files retain
  owner-only permissions.
- Review numbers and mutation bodies receive API-boundary validation.

### Product completeness

- Added create PR/MR REST API and a create-review dialog with branch defaults.
- Reworked the agent create-review tool to use the active registered Coding
  workspace, shared locks, saved credentials, configured timeouts, and provider
  REST APIs. It no longer resets a branch with `checkout -B` and supports clean,
  already-committed branches.
- Added a **Settings -> Git & reviews** screen and atomic runtime-settings writes.

## New settings

| Setting | Default | Allowed range / policy |
| --- | ---: | --- |
| Git network timeout | 120 s | 10-1800 s |
| Maximum diff output | 2 MB | 64 KB-50 MB |
| Pull strategy | Fast-forward only | FF-only, merge, rebase |
| Prune on fetch | On | Boolean |
| Force-with-lease | Off | Global opt-in |
| Review API timeout | 20 s | 2-300 s |
| Read retries | 2 | 0-5 |
| Initial retry backoff | 0.5 s | 0-10 s |
| Repository concurrency | 4 | 1-32 |
| Pages per repository | 5 | 1-20 |
| Review mutations | On | Global kill switch |
| Insecure connections | Off | Explicit development opt-in |
| Successful checks before merge | Off | Optional merge gate |

## Remaining production work

### P0 for internet-exposed or multi-tenant deployments

1. Enforce a registered-workspace/tenant allowlist at the API boundary. The
   shared `team_manager.validate_workspace` intentionally accepts any existing
   server directory and relies on desktop-token authentication.
2. Make access-key authentication mandatory in server mode and add role-based
   authorization for Git writes, force push, connection administration, review
   mutations, and merge.
3. Move API tokens from the config `.env` file to an OS keychain or external
   secret manager with rotation and audit events.
4. Add database-level unique constraints for connection resolution targets,
   with a migration that safely reconciles existing duplicates. Application
   checks currently prevent normal duplicates but cannot eliminate a
   cross-process race.

### P1 reliability and scale

1. Persist remote Git jobs with stable IDs, progress, cancellation, restart
   recovery, and operator-visible history. The current registry is in-memory.
2. Share/reuse provider HTTP clients and enforce a maximum JSON response body
   before decoding. Review list pagination is bounded, while some detail/file/
   comment adapters still consume only their provider's first detail page.
3. Add provider contract tests against sandbox GitHub Enterprise, GitLab,
   Bitbucket, Gitea/Forgejo, and Azure DevOps instances, including rate limits,
   permissions, redirects, TLS failures, and merge policies.
4. Add structured security/audit telemetry for remote URL changes, push/force
   push, token changes, review mutations, and merge, without secret payloads.

## Verification performed

- Targeted backend Git/review/settings/API/agent tests.
- Ruff lint and format checks on the changed backend surface.
- Targeted `ty` type checks on the changed backend surface.
- Frontend ESLint, TypeScript build check, and production Vite build.
- Full backend test suite was also run; any unrelated baseline failures are
  reported in the task handoff rather than hidden.
