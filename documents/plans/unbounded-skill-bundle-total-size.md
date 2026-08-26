# Unbounded aggregate size for Agent Skill bundles

Status: proposed

## Problem and outcome

EvoFlux currently rejects a user-managed Agent Skill when its optional bundle
resources exceed 20 MiB in aggregate. Large upstream Skills can stay within the
per-file and entry-count safety limits while legitimately exceeding that total,
which makes the Settings CRUD contract and `scripts/validate_skills.py`
incompatible with otherwise discoverable bundles.

The outcome is to remove the EvoFlux-owned aggregate byte ceiling for Agent
Skill bundles. Bundle validity remains bounded by file count, individual file
size, path safety, symlink policy, frontmatter, metadata, links and evaluation
contracts.

## Goals

- Remove the 20 MiB aggregate resource-size rejection from user Skill create
  and update transactions.
- Remove the matching aggregate-size error from the repository Skill
  validator.
- Keep existing transactions atomic when a large bundle update fails another
  validation rule.
- Keep Skill discovery, activation and bounded Settings previews unchanged.
- Document that EvoFlux imposes no aggregate bundle-byte limit while host
  filesystem, HTTP stack or packaging environments may still impose external
  limits.

## Non-goals

- Do not remove the 2 MiB per-resource limit.
- Do not remove or increase the Settings CRUD 2,000-entry limit.
- Do not remove or increase the validator 20,000-entry limit.
- Do not allow symlinks, traversal, absolute resource paths, special files or
  escaping paths.
- Do not change `SKILL.md`, agent metadata or evaluation-file size limits.
- Do not change chat attachment, upload or per-message 20 MB limits.
- Do not make invalid or untrusted Skills executable automatically.
- Do not add a configuration flag or retain 20 MiB as a default.

## User flows and states

### Create a large user Skill

Given a Skill bundle whose aggregate resources exceed 20 MiB, when the user
creates it through Settings or the Skills API, EvoFlux stages the complete
bundle and accepts it if every remaining validation rule passes. The response
shape and discovery behavior remain unchanged.

### Update an existing large user Skill

Given an existing user Skill larger than 20 MiB, when the user adds, replaces
or removes resources, EvoFlux validates the final staged state without summing
an aggregate byte budget. Publication remains atomic.

### Validate an external bundle

Given a bundle larger than 20 MiB, when a maintainer runs
`scripts/validate_skills.py`, aggregate size alone produces no finding. Other
violations still produce their existing error codes.

### Rejected states retained

An oversized individual resource, excess entry count, unsafe path, symlink,
special file, invalid metadata, broken resource link or invalid evaluation
fixture remains rejected exactly as before.

## Requirements and acceptance criteria

- **AC-1 — Create without aggregate ceiling:** A Skills API create request with
  aggregate resource bytes above the former 20 MiB threshold succeeds when
  every file and the final entry count remain within their existing limits.
- **AC-2 — Update without aggregate ceiling:** A Skills API update may produce
  a final bundle above 20 MiB and still commits atomically when all remaining
  checks pass.
- **AC-3 — Validator parity:** `scripts/validate_skills.py` does not emit
  `bundle-too-large` or reject a bundle solely because of aggregate bytes.
- **AC-4 — Per-file safety retained:** Create, update and validator paths still
  reject any non-control resource exceeding 2 MiB with their existing error
  contract.
- **AC-5 — Entry safety retained:** Settings CRUD still rejects a final bundle
  above 2,000 filesystem entries, while the validator retains its 20,000-entry
  bound and bounded directory consumption.
- **AC-6 — Filesystem safety retained:** Symlink, traversal, absolute path,
  special-file and escaping-path checks remain unchanged and covered.
- **AC-7 — Preview remains bounded:** Settings bundle listing still returns no
  more than 200 resource records and no more than 2 MiB of inline resource
  content, regardless of on-disk aggregate size.
- **AC-8 — No adjacent 20 MB changes:** Chat attachments, uploads and other
  non-Skill byte limits remain unchanged.
- **AC-9 — Current documentation:** Feature documentation and EN/VI/JA Help
  state that aggregate Skill bundle bytes are unbounded by EvoFlux and list the
  remaining per-file, entry-count and filesystem constraints.
- **AC-10 — Clean integration:** Focused service/API/script tests, repository
  quality checks and `git diff --check` pass without unrelated changes.

## API, event, tool, and UI contracts

The existing `/api/skills` create/update schemas and success response shapes do
not change. The two aggregate-size errors are removed:

- `Skill resource updates exceed the 20 MiB limit.`
- `Final skill bundle resources exceed the 20 MiB limit.`

Existing errors for per-file size and entry count remain stable. No new event,
tool or persistence schema is introduced. Settings continues to display a
bounded preview rather than attempting to inline an entire large bundle.

## Data model, migration, and retention

No database or filesystem-layout migration is required. Existing Skill bundle
files remain in their current roots. Removing the aggregate ceiling can permit
more local disk consumption; EvoFlux does not copy or expand an existing bundle
as part of this change.

## Permissions, security, privacy, and trust

The aggregate byte ceiling is removed as an explicit product decision. The
following defenses remain mandatory: per-file limit, entry-count limit,
bounded directory enumeration, path containment, regular-file enforcement,
symlink rejection, atomic staging and normal tool permission/sandbox policy.

Large bundles can consume substantial disk space and make validation or copy
operations slower. This accepted risk must be visible in documentation. No
bundle gains trust, activation or execution permission merely because its size
is accepted. No new content is transmitted externally.

## Concurrency, failure, recovery, and idempotency

Create/update continues to stage and validate before publication. A failure in
any retained rule leaves the prior Skill byte-for-byte unchanged. Repeated
updates remain idempotent under the current API semantics. Process interruption
may leave only the existing temporary staging cleanup behavior; the published
bundle must never be partially replaced.

## Observability and diagnostics

Aggregate byte count no longer produces a validation diagnostic. Existing
structured API errors and validator findings for entry, per-file and path
violations remain. No document contents or resource payloads are added to logs.

## Compatibility, rollout, and rollback

This is a backward-compatible relaxation for valid clients and a deliberate
removal of one validation error. External HTTP servers, filesystems and package
formats may retain independent limits; EvoFlux does not claim to bypass them.

Rollout is immediate for source and packaged applications once shipped.
Rollback restores the two aggregate byte checks and their tests; existing
larger bundles remain ordinary files but would again be rejected on managed
create/update or validator execution.

## Verification matrix

| AC | Evidence |
|---|---|
| AC-1, AC-2 | API create/update tests with aggregate resources above a patched former threshold |
| AC-3 | Validator test proving aggregate bytes do not create `bundle-too-large` |
| AC-4 | Existing and focused per-file rejection tests |
| AC-5 | Existing bounded scandir and final entry-limit tests |
| AC-6 | Existing invalid resource path, symlink and transactional tests |
| AC-7 | Existing 200-record/2 MiB inline preview budget test |
| AC-8 | Source inspection plus unchanged attachment-limit tests |
| AC-9 | Feature and EN/VI/JA Help review/build evidence |
| AC-10 | Focused pytest, Ruff, ty, frontend checks and `git diff --check` |

## Ownership and source map

- Runtime Skill filesystem contract: `app/services/agent_fs.py`
- Skills API transaction integration: `app/api/routes/skills.py`
- Maintainer validator: `scripts/validate_skills.py`
- Service/API regression evidence: `tests/services/test_agent_fs.py`,
  `tests/api/routes/test_skills.py`
- Validator evidence: `tests/scripts/test_validate_skills.py`
- Current feature contract:
  `documents/features/tools-skills-mcp-and-plugins.md`
- In-app Help: `web/src/help/locales/en.ts`,
  `web/src/help/locales/vi.ts`, `web/src/help/locales/ja.ts`
