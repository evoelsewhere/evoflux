---
name: review-pull-requests
description: Review and operate pull requests or merge requests through EvoFlux provider-neutral REST tools and saved Git server credentials. Use when asked to inspect, summarize, comment on, approve, request changes on, update, merge, close, reopen, or follow discussions and checks for a PR/MR in a Coding workspace or multi-repository project. Supports GitHub/Enterprise, GitLab self-managed, Bitbucket Cloud/Data Center, Gitea/Forgejo, and Azure DevOps without gh/glab.
---

# Review Pull Requests

Review PRs/MRs through EvoFlux code-review tools. Treat the normalized review context as the source of truth for provider state, discussion IDs, inline positions, approvals, checks, conflicts, and supported actions.

For provider-specific limitations, read [references/provider-capabilities.md](references/provider-capabilities.md) only when an action is unsupported or its semantics are unclear.

## Non-negotiable rules

- Use `list_code_reviews`, `get_code_review`, and the `*_code_review*` mutation tools for Git server operations.
- Do not use `gh`, `glab`, provider CLIs, raw `curl`, or shell commands to read or mutate remote PR/MR state.
- Use the saved connection selected by EvoFlux. Never request, print, persist, or pass API tokens as tool arguments.
- Never invent repository selectors, comment IDs, thread IDs, commit SHAs, paths, lines, reviewer IDs, or capabilities.
- Read `get_code_review` immediately before a position-sensitive or state-changing action.
- Treat `get_code_review.capabilities` as authoritative. Report an unsupported capability clearly; do not emulate it through an unrelated endpoint.
- Keep review findings about the code, not the author.

Local code inspection remains allowed through normal Coding tools such as `code_search`, `code_graph`, `grep`, `read`, and `lsp_diagnostics`. Use the repository's normal verification commands when evidence requires running tests.

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

### 3. Review the change

Review tests before implementation where possible. Then assess:

1. Correctness and edge cases
2. Security and trust boundaries
3. Concurrency and state transitions
4. Architecture and repository conventions
5. Performance and bounded resource usage
6. Test quality and verification coverage

Load `code-review-and-quality` when deeper multi-axis review guidance is needed.

Classify findings:

- `Critical`: security, data loss, or clearly broken production behavior
- `Required`: must change before approval
- `Suggestion`: worthwhile but non-blocking
- `Nit`: optional style preference

Include a precise file/path and line when the provider context supports it. Do not post speculative findings.

### 4. Decide before mutating

Use this order:

1. Discuss or post actionable findings.
2. Refresh review context after external changes.
3. Confirm required findings are addressed.
4. Verify checks, approvals, conflicts, and mergeability.
5. Approve or request changes.
6. Merge only after all gates pass and confirmation is granted.

Do not approve and request changes in the same review state.

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

Azure DevOps may require a `reviewer_id`; take it from normalized approvals/reviewer context. Never guess it.

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
3. Confirm required approvals.
4. Confirm checks are successful or explicitly waived by the user.
5. Confirm no conflicts.
6. Use the provider-supported merge method.
7. Call `merge_code_review` once.
8. Refresh and report the final provider state.

Do not repeatedly call merge after a timeout. Refresh first.

Use `close_code_review` only when the user clearly intends to decline/close the review. Use `reopen_code_review` for the inverse transition. These state tools are idempotent when the provider state can be checked.

## Session-linked review behavior

When a review is opened through the Coding UI:

- Continue the existing review-linked Coding session when one exists.
- Preserve the session's workspace or project scope.
- Treat new `get_code_review` results as fresher than review context embedded in earlier chat messages.
- Refresh after any mutation so the chat and side panel converge on provider state.

Do not create a second review session merely because an extra session capability tag was added.

## Final response

Lead with the decision and current state. Report:

1. Review verdict: approve, request changes, comment-only, or blocked
2. Required findings with file/line evidence
3. Suggestions separately
4. Checks, approvals, conflicts, and mergeability
5. Remote actions actually completed
6. Unsupported or unverified provider behavior

Never claim that a comment, approval, merge, close, or update succeeded unless the tool returned success or a refresh confirmed the state.
