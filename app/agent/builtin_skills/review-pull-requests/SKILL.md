---
name: review-pull-requests
description: Perform risk-based review and full lifecycle operations for pull requests or merge requests through EvoFlux provider-neutral REST tools and saved Git server credentials. Use when asked to inspect, summarize, review, re-review, assess readiness, address discussions, comment on, approve, request changes on, update, merge, close, reopen, or follow checks for a PR/MR in a Coding workspace or multi-repository project. Supports GitHub/Enterprise, GitLab self-managed, Bitbucket Cloud/Data Center, Gitea/Forgejo, and Azure DevOps without gh/glab.
---

# Review Pull Requests

Review PRs/MRs through EvoFlux code-review tools. Treat the normalized review context as the source of truth for provider state, discussion IDs, inline positions, approvals, checks, conflicts, and supported actions.

Use progressive disclosure:

- For any non-trivial review, re-review, or merge-readiness assessment, read [references/review-playbook.md](references/review-playbook.md).
- Before the first remote mutation, or whenever a tool argument or identifier is unclear, read [references/tool-contracts.md](references/tool-contracts.md).
- When an action is unsupported or provider semantics are unclear, read [references/provider-capabilities.md](references/provider-capabilities.md).

## Non-negotiable rules

- Use `list_code_reviews`, `get_code_review`, and the `*_code_review*` mutation tools for Git server operations.
- Do not use `gh`, `glab`, provider CLIs, raw `curl`, or shell commands to read or mutate remote PR/MR state.
- Use the saved connection selected by EvoFlux. Never request, print, persist, or pass API tokens as tool arguments.
- Never invent repository selectors, comment IDs, thread IDs, commit SHAs, paths, lines, reviewer IDs, or capabilities.
- Read `get_code_review` immediately before a position-sensitive or state-changing action.
- Treat `get_code_review.capabilities` as authoritative. Report an unsupported capability clearly; do not emulate it through an unrelated endpoint.
- Treat review requests as read-only unless the user also asks to post feedback or perform a decision/lifecycle action.
- Never approve, request changes, resolve a thread, update metadata, merge, close, or reopen based on stale review state.
- Keep review findings about the code, not the author.

Local code inspection remains allowed through normal read-only Coding tools and
specialist workflows. For an exact changed symbol, use native `code_graph`
with `callers`, `references`, `callees`, or bounded `impact` at depth 1.
Read [references/code-graph-contract.md](references/code-graph-contract.md)
when results are ambiguous, cross-repository, stale, dirty, pending, dynamic,
or truncated. Never pass PR prose or a feature description as `symbol`.
Use the repository's normal verification commands when evidence requires
running tests.

## Resolve scope first

The active Coding session defines the allowed repositories:

- A workspace session targets that repository.
- A project session includes every repository linked to the project.
- A worktree resolves to its source repository for credentials and remote review state.

Call `list_code_reviews` without `repository` when the user asks for all reviews in the current project. Supply an exact repository name, remote path, workspace path, or workspace ID when narrowing the result.

If the session contains multiple repositories and the requested PR/MR number is ambiguous:

1. Call `list_code_reviews`.
2. Match the repository from the returned review list or user context.
3. Ask for the repository only if ambiguity remains.

Do not assume PR/MR numbers are globally unique.

## Select the operating mode

Choose the least-mutating mode that satisfies the request:

- **Inspect:** analyze and report findings locally; make no remote changes.
- **Comment:** inspect, then post only the feedback the user requested.
- **Decision:** submit `approve`, `request_changes`, or `comment` after a fresh gate check.
- **Lifecycle:** update metadata, merge, close, or reopen only when explicitly requested.

“Review this PR/MR” means Inspect by default. Showing draft comments in the response is not the same as publishing them.

## Core review workflow

### 1. Load only the tools needed

The code-review tools are deferred. Activate each required tool with `load_tool` before calling it.

Prefer one activation per call:

```text
load_tool(tool_name="list_code_reviews")
load_tool(tool_name="get_code_review")
```

Do not pass a quoted or stringified array to `tool_names`. If batching is necessary, pass a native list value, not text:

```text
tool_names = ["list_code_reviews", "get_code_review"]
```

For a normal review, load:

- `list_code_reviews`
- `get_code_review`
- `get_code_review_checks` only when fresh checks are needed independently

At the start of a review, load only `list_code_reviews` and `get_code_review`, one call at a time. Do not preload comment, approval, update, merge, or close tools speculatively.

Load a mutation tool only after `get_code_review` confirms the capability and the requested workflow reaches that action.

### 2. Establish intent and current state

Call `get_code_review` and inspect:

- `review`: title, description, author, branches, provider-native metadata
- `changes`: changed files and diff/position metadata
- `comments`: normalized conversation and inline comments
- `approvals`: reviewer identities and states
- `checks`: normalized CI/pipeline state
- `mergeability`: merged state, conflicts, and provider mergeability
- `capabilities`: actions supported by this provider's REST adapter

Every normalized comment supplies:

- `stable_id` for durable display and correlation
- provider `id` and `thread_id` for mutations
- `parent_id` for reply relationships
- `path`, `line`, `side`, and `commit_id` for inline context
- `resolved`, `can_reply`, and `can_resolve`

Use these values exactly as returned.

Record the current source/head commit before reviewing. If the provider does not expose one, say that freshness cannot be proven.

### 3. Build a risk map before reading line by line

Identify:

- the change contract from the title, body, linked discussion, tests, and user request
- changed entry points, public interfaces, data models, migrations, permissions, and trust boundaries
- callers, consumers, configuration, deployment paths, and cross-repository effects
- generated, vendored, lock, or snapshot files that should be verified through their source rather than hand-edited

Classify the change as high, medium, or low risk using the playbook. Review high-risk areas exhaustively; do not spend equal effort on every changed line.

### 4. Review the change

Review tests before implementation where possible. Then assess:

1. Correctness and edge cases
2. Security and trust boundaries
3. Concurrency and state transitions
4. Data integrity, migrations, rollback, and compatibility
5. Public API, provider, and cross-repository compatibility
6. Architecture and repository conventions
7. Performance, failure handling, retries, and bounded resource usage
8. Operability: logs, metrics, diagnostics, and safe error messages
9. Test quality and verification coverage

Classify findings:

- `Critical`: security, data loss, or clearly broken production behavior
- `Required`: must change before approval
- `Suggestion`: worthwhile but non-blocking
- `Nit`: optional style preference

Include a precise file/path and line when the provider context supports it. Do not post speculative findings.

Every blocking finding must explain the trigger, observable behavior, impact, and smallest credible correction. Separate facts from assumptions. Consolidate duplicates and avoid posting a comment that already exists in the review.

### 5. Verify freshness and evidence

- Run proportionate local verification when the workspace is available.
- Inspect provider checks, but do not treat a green check as proof that the risky path was tested.
- Treat unknown, skipped, unavailable, or stale checks as non-success unless the user explicitly accepts the risk.
- Refresh `get_code_review` after a force-push, new commit, review mutation, or evidence that provider state changed.
- If the source/head commit changed during review, invalidate line positions and approval conclusions, then re-review the affected delta.

### 6. Decide before mutating

Use this order:

1. Discuss or post actionable findings.
2. Refresh review context after external changes.
3. Confirm required findings are addressed.
4. Verify checks, approvals, conflicts, and mergeability.
5. Approve or request changes.
6. Merge only after all gates pass and confirmation is granted.

Do not approve and request changes in the same review state.
Do not approve a draft PR/MR, an unverified head commit, or a review with unresolved required findings unless the user explicitly overrides the relevant policy and the provider permits it.

## Discussion actions

### Add a conversation comment

Use `add_code_review_comment`.

- Keep one logical concern per comment.
- Include evidence and the expected correction.
- Pass a stable `idempotency_key` for a logical comment when available.
- Do not retry after an ambiguous timeout until refreshing the review and checking whether the comment already exists.

### Add an inline comment

Use `add_code_review_inline_comment` with `path`, `line`, `side`, and commit coordinates from the latest `get_code_review`.

- Never derive line numbers from a local working tree alone.
- For GitLab, pass head, base, and start commit IDs returned by review position metadata.
- If the target line is unavailable or outdated, post a conversation comment with the file reference instead of guessing.

### Reply to a thread

Use `reply_code_review_thread` only when `can_reply` is true. Pass the normalized `thread_id`, not `stable_id`.

### Resolve or reopen a thread

Use `resolve_code_review_thread` or `reopen_code_review_thread` only when `can_resolve` is true.

Resolve only when:

- the requested change is present, or
- the discussion reached an explicit conclusion that requires no code change.

Refresh with `get_code_review` after reply or resolution mutations.

## Review decision actions

Use `submit_code_review` with exactly one event:

- `approve`: no unresolved required findings remain
- `request_changes`: at least one required finding blocks approval
- `comment`: feedback without a formal approval decision

Before `approve`:

- Read fresh checks.
- Confirm no merge conflicts.
- Confirm unresolved discussions are understood.
- Confirm required verification is present.
- Confirm the source/head commit matches the commit reviewed.

Azure DevOps may require a `reviewer_id`; take it from normalized approvals/reviewer context. Never guess it.

If formal request-changes is unsupported, post or propose the blocking findings through a supported comment path and report that the formal decision was not submitted.

## Updating review metadata

Use `update_code_review` only for fields explicitly requested by the user:

- title or body
- draft/ready state
- labels
- reviewers
- assignees

Check the matching capability first. Provider semantics differ, and some REST APIs cannot change draft state or assignees. Do not silently drop requested fields.

## Merge, close, and reopen

`merge_code_review` and `close_code_review` are important actions. Their tool calls require confirmation by default, including in Auto mode.

Before merge:

1. Refresh `get_code_review`.
2. Confirm the review is open and not already merged.
3. Confirm the source/head commit is still the reviewed commit.
4. Confirm required approvals and repository policy.
5. Confirm required discussions are resolved.
6. Confirm checks are successful or explicitly waived by the user.
7. Confirm no conflicts and mergeability is positive rather than unknown.
8. Use the provider-supported merge method.
9. Call `merge_code_review` once.
10. Refresh and report the final provider state.

Do not repeatedly call merge after a timeout. Refresh first.

Use `close_code_review` only when the user clearly intends to decline/close the review. Use `reopen_code_review` for the inverse transition. These state tools are idempotent when the provider state can be checked.

## Session-linked review behavior

When a review is opened through the Coding UI:

- Continue the existing review-linked Coding session when one exists.
- Preserve the session's workspace or project scope.
- Use only the session repository in a workspace panel; retain all project repositories only in project scope.
- Treat new `get_code_review` results as fresher than review context embedded in earlier chat messages.
- Refresh after any mutation so the chat and side panel converge on provider state.

Do not create a second review session merely because an extra session capability tag was added.

## Final response

Lead with the decision and current state. Report:

1. Review verdict: approve, request changes, comment-only, or blocked
2. Required findings with file/line evidence
3. Suggestions separately
4. Checks, approvals, conflicts, and mergeability
5. Reviewed source/head commit and verification performed
6. Remote actions actually completed
7. Unsupported, stale, waived, or unverified provider behavior

Never claim that a comment, approval, merge, close, or update succeeded unless the tool returned success or a refresh confirmed the state.
