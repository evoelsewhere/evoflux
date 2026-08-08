---
name: review-pull-requests
description: Inspect, review, re-review, comment on, decide, update, follow checks for, merge, close, or reopen a pull request or merge request through EvoFlux provider-neutral review tools. Use for an explicit remote PR/MR in a Coding workspace or project; do not use for a local-only diff, ordinary git branch work, or source investigation with no review lifecycle.
---

# Review a pull request or merge request

Treat normalized remote review state as authoritative for commits, changes,
comments, inline positions, approvals, checks, conflicts, capabilities, and
supported actions. Do not load bundled references when this skill activates.

## Non-negotiable boundaries

- Use EvoFlux `*_code_review*` tools; do not use provider CLIs or raw HTTP.
- Use saved credentials; never request, print, or pass tokens.
- Never invent repository selectors, IDs, SHAs, paths, lines, reviewers,
  capabilities, or merge methods.
- “Review this PR” is read-only inspection unless the user explicitly requests
  a remote comment, decision, metadata change, merge, close, or reopen.
- Refresh before every position-sensitive or state-changing action and after
  every mutation. Never act on stale commit or capability state.

## State machine

### 1. RESOLVE

Resolve the exact repository and PR/MR. A workspace scopes one repository; a
project may contain several. List current reviews when the number is ambiguous
or when the user asks across the project. Do not assume review numbers are
globally unique.

Load only `list_code_reviews` and `get_code_review` initially. Do not preload
mutation tools. Call `get_code_review` and record the current source/head commit
plus live capabilities.

### 2. SELECT MODE

Choose the least-mutating mode that satisfies the request:

- **Inspect:** analyze and report only.
- **Comment:** publish only requested feedback.
- **Decision:** submit approve, request-changes, or comment after fresh gates.
- **Lifecycle:** update metadata, merge, close, or reopen only when explicit.

Read [references/review-playbook.md](references/review-playbook.md) only for a
non-trivial review, re-review, or merge-readiness decision. Do not load it for a
one-field status lookup.

### 3. REVIEW

Establish the intended contract and build a risk map from changed entry points,
public interfaces, data, migrations, permissions, concurrency, deployment, and
cross-repository effects. Review high-risk surfaces first and validate each
finding with a concrete trigger and impact.

When a changed behavior is not tied to an exact declaration, call `code_context` with `action="search"`
once with a stable diff literal, interface term, or code fragment. Promote its
repository-qualified range to an exact changed symbol; skip search when the
diff already exposes that symbol.

For an exact changed symbol, use `code_context` with direct `callers`,
`references`, `callees`, or bounded `impact` at depth 1. Once that symbol and
relationship are selected, make the graph the next structural observation;
do not continue broad grep or pass PR prose as `symbol`.

Keep `refresh=true` for the first indexed query and after edits. Use `refresh=false` only for an immediate follow-up that intentionally reuses the same index version.

Read
[references/code-context-contract.md](references/code-context-contract.md) only
after the result exposes ambiguity, stale/dirty data, cross-repository gaps,
dynamic wiring, or truncation.

Run proportionate local checks when the workspace is available. Green provider
checks do not prove the risky path was tested. Reject style-only, speculative,
duplicate, or unreachable findings.

Each actionable finding must include severity, trigger, behavior, impact,
current file/line evidence, and smallest credible correction.

### 4. PREPARE A MUTATION

Read [references/tool-contracts.md](references/tool-contracts.md) immediately
before the first remote mutation or whenever an identifier/argument is unclear.
Read [references/provider-capabilities.md](references/provider-capabilities.md)
only when live capabilities are false/unclear or provider semantics affect the
requested action.

Load only the mutation tool required for the next authorized action. Refresh
`get_code_review`, verify the source/head commit still matches, and take all IDs
and inline coordinates from that fresh response. If the commit changed,
invalidate affected positions and review conclusions before acting.

Use a stable idempotency key for one logical comment or mutation. After an
ambiguous timeout, refresh and check current state before retrying.

### 5. DECIDE OR COMPLETE LIFECYCLE

Approve only when no required finding remains and checks, discussions,
conflicts, mergeability, policies, and reviewed commit are acceptable. Request
changes only for evidenced blockers. If the provider does not support a formal
action, use the closest safe supported comment path and say what was not
recorded.

Merge only after a fresh gate check confirms the exact reviewed commit,
required approvals, successful required checks, resolved required discussions,
no conflicts, positive mergeability, and a supported merge method. Execute the
state-changing call once, refresh, and report confirmed provider state.

## Stop conditions

Stop when the review scope and commit are exact, every reported finding is
actionable and current, requested remote actions are verified by fresh state,
and unsupported/stale/unverified behavior is explicit.

## Deliverable

Lead with verdict and current state. Report required findings, suggestions,
checks, approvals, conflicts, mergeability, reviewed commit, local verification,
remote actions completed, and any unsupported, stale, waived, or unverified
condition. Never claim a mutation succeeded without tool success or refreshed
confirmation.
