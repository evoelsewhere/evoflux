# Risk-based PR/MR review playbook

Use this playbook for non-trivial reviews, re-reviews, and merge-readiness assessments. The objective is to find material defects with evidence, not to maximize comment count.

## Contents

1. Establish the change contract
2. Build the change and blast-radius map
3. Assign review depth by risk
4. Run semantic review passes
5. Verify with proportionate evidence
6. Write high-quality findings
7. Re-review safely after new commits
8. Apply decision and merge gates

## 1. Establish the change contract

Before judging the implementation, state what the change is supposed to do.

Use:

- PR/MR title and description
- linked issue or discussion available in the normalized context
- tests and fixtures
- public API documentation and repository conventions
- explicit constraints in the user's request

Identify unclear requirements and scope drift. A change can be locally correct yet still violate the intended contract.

Separate:

- promised behavior
- inferred behavior
- out-of-scope behavior
- compatibility guarantees

Do not invent product requirements. Turn consequential uncertainty into a question or a clearly labeled assumption.

## 2. Build the change and blast-radius map

Review the diff in repository context, not in isolation.

Map:

- entry points and changed control flow
- callers, callees, and shared utility consumers
- public APIs, schemas, serialized formats, and event contracts
- database schema, migrations, backfills, rollback, and mixed-version operation
- authentication, authorization, tenant boundaries, secrets, and user-controlled input
- shared mutable state, queues, jobs, locks, caching, retries, and idempotency
- configuration defaults, feature flags, deployment, and operational dependencies
- UI loading, empty, error, permission, keyboard, and accessibility states
- cross-repository or provider adapter consumers in a project session

For generated, vendored, lock, snapshot, or compiled files:

- find and review the source change
- verify regeneration is intentional and reproducible
- do not ask the author to hand-edit generated output
- flag unexpected dependency or transitive changes

## 3. Assign review depth by risk

### High risk

Use exhaustive data-flow and failure-path review for:

- authentication, authorization, identity, tenant isolation, or secrets
- destructive actions, payments, irreversible state, or data loss
- database migrations, backfills, serialization, or protocol changes
- concurrency, distributed state, retries, queues, or idempotency
- dependency, infrastructure, deployment, or permission changes
- provider-neutral abstractions that map to several Git servers

Require targeted negative and failure-path verification. Confirm rollback or recovery behavior when applicable.

### Medium risk

Use affected-path plus boundary review for:

- public behavior or API changes
- new state transitions
- shared services and reusable components
- user-visible workflow changes

Trace important callers and consumers and test boundaries, not only the happy path.

### Low risk

Use focused review for:

- documentation-only changes
- isolated test cleanup
- mechanical refactors with no behavior change
- style or copy updates

Still verify that the claimed lack of behavior change is true. Escalate the risk tier if hidden coupling appears.

## 4. Run semantic review passes

### Contract and correctness

- Does the implementation satisfy every promised behavior?
- Are empty, null, boundary, malformed, duplicate, and out-of-order inputs handled?
- Are all state transitions valid and atomic enough for the domain?
- Are error paths observable and safe?

### Security and privacy

- Is every action authorized at the correct resource boundary?
- Can user-controlled values reach queries, paths, templates, logs, or commands unsafely?
- Are tokens, credentials, personal data, or secrets exposed in responses or logs?
- Are server-side checks used instead of trusting UI state?

### Data, migrations, and compatibility

- Can old and new application versions coexist during rollout?
- Is the migration safe for existing data and realistic data volume?
- Are defaults, nullability, constraints, indexes, rollback, and retry behavior correct?
- Are API, event, schema, and serialized-format consumers backward compatible?

### Concurrency and resilience

- What happens on duplicate delivery, retry, timeout, cancellation, or partial failure?
- Are read-modify-write sequences protected?
- Are idempotency keys stable for one logical action but distinct for different actions?
- Could stale provider state cause a duplicate comment, outdated inline position, or wrong merge?

### Performance and resource bounds

- Are loops, queries, network calls, payloads, and caches bounded?
- Is there an N+1 query or per-item API request?
- Are pagination, rate limiting, and large diffs handled?
- Does failure cause unbounded retry, memory growth, or noisy logging?

### UI and session behavior

- Does workspace scope show only that repository?
- Does project scope include its repositories without leaking unrelated repositories?
- Are search and repository filters independent and composable?
- Does a review reuse the correct Coding session and refresh after mutations?
- Are loading, empty, error, stale, unsupported, and permission-denied states explicit?

### Provider adapters

- Does normalized behavior preserve provider-specific IDs and semantics?
- Are unsupported capabilities reported instead of simulated?
- Are inline coordinates built from the latest provider context?
- Are provider versions, pagination, error mapping, and capability negotiation tested?
- Are tokens redacted from logs, exceptions, and tracing?

## 5. Verify with proportionate evidence

Prefer the narrowest meaningful verification first, then expand when risk or failures justify it.

Check:

- tests for happy, negative, boundary, and regression behavior
- migration upgrade and downgrade when supported
- retry, duplicate, timeout, cancellation, and concurrency cases
- authorization and tenant-isolation cases
- each important provider mapping, including unsupported-capability behavior
- UI loading, empty, error, permission, and accessibility states
- lint, typecheck, build, and diagnostics relevant to changed code

Distinguish:

- **Passed:** directly verified against the reviewed commit
- **Failed:** verified and failing
- **Unknown:** not run, unavailable, stale, or not applicable
- **Waived:** explicitly accepted by an authorized user

Green provider checks are useful evidence, not proof of completeness. Never describe unknown checks as passing.

## 6. Write high-quality findings

A blocking finding should contain:

1. **Trigger:** the input, state, timing, or caller that reaches the problem
2. **Behavior:** what the code does
3. **Impact:** why it matters
4. **Correction:** the smallest credible direction for fixing it

Use the tightest current file and line range. If the line is stale or unavailable, use a conversation comment with a path or symbol reference.

Prioritize:

- Critical: exploitable security, data loss, or severe production failure
- Required: reproducible correctness, compatibility, safety, or policy failure
- Suggestion: material improvement that does not block
- Nit: optional readability or style preference

Avoid:

- vague statements such as “this may break”
- preferences presented as correctness failures
- comments already represented by an existing unresolved thread
- several comments for one root cause
- demands for unrelated refactors
- claims without a reachable scenario

If no actionable defect is found, say so directly and list residual risk or unverified areas.

## 7. Re-review safely after new commits

Record the source/head commit at the start of each review round.

After a new commit or force-push:

1. Refresh `get_code_review`.
2. Compare the latest source/head commit with the reviewed commit.
3. Re-map changed files and invalidated inline positions.
4. Re-check prior required findings against current code.
5. Re-run affected verification.
6. Reassess checks, approvals, conflicts, discussions, and mergeability.
7. Submit a decision only for the refreshed commit.

Do not assume a resolved discussion means the code changed correctly. Do not reuse an approval conclusion for an unreviewed head commit.

## 8. Apply decision and merge gates

### Approve

Approve only when:

- no unresolved Critical or Required finding remains
- the reviewed commit is still current
- required verification passed
- checks and conflicts are acceptable
- the PR/MR is not draft unless policy explicitly allows approval

### Request changes

Request changes when at least one evidenced Required or Critical finding blocks readiness. If the provider lacks a formal request-changes action, use supported comments and report that no formal decision was recorded.

### Comment only

Use comment-only when:

- findings are non-blocking
- requirements are too ambiguous for a safe decision
- important verification remains unknown
- the user asked for feedback but not a formal decision

### Merge

Merge only after refreshing state and confirming:

- the reviewed source/head commit is current
- policy-required approvals are present
- blocking discussions are resolved
- required checks passed or were explicitly waived
- conflicts are absent and mergeability is positive
- the requested merge method is supported
- the important-action confirmation is granted

After merge, refresh provider state and report what actually happened.
