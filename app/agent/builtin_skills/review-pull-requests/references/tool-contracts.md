# Code-review tool contracts

Read this before the first remote mutation or whenever a code-review tool argument, ID, or state transition is unclear.

## Contents

1. Activation and repository selection
2. Read tools
3. Discussion tools
4. Decision and metadata tools
5. Lifecycle tools
6. Identifier and inline-position rules
7. Idempotency, refresh, and error handling
8. Permission and safety policy

## 1. Activation and repository selection

Code-review tools are deferred. Activate only the tool needed for the current step:

```text
load_tool(tool_name="get_code_review")
```

If batching, `tool_names` must be a native list value. Never pass a quoted JSON array.

Repository selectors may be exact repository names, remote paths, workspace paths, or workspace IDs returned by EvoFlux. PR/MR numbers are repository-local.

Never invent a selector. When several repositories contain the same number, resolve the repository through `list_code_reviews` or ask the user.

## 2. Read tools

### `list_code_reviews`

```text
list_code_reviews(repository?, state="open")
```

Omit `repository` to search every repository allowed by the active project session. `state` is `open`, `closed`, or `merged`. For graph actions, an exact repository selector disambiguates the root symbol while authorized siblings remain available for cross-repository traversal.

### `get_code_review`

```text
get_code_review(
  number,
  repository?,
  include_changes=true,
  include_comments=true
)
```

This is the normalized source of truth for:

- review metadata and provider-native context
- changed files and inline positions
- comments, replies, and threads
- approvals and reviewer identity
- checks and pipeline state
- conflicts and mergeability
- permissions and live capabilities

Refresh it before any position-sensitive or state-changing action.

### `get_code_review_checks`

```text
get_code_review_checks(number, repository?)
```

Use when fresh checks are needed independently of the full review. Unknown, unavailable, skipped, or stale checks are not successful checks.

## 3. Discussion tools

### `add_code_review_comment`

```text
add_code_review_comment(
  number,
  body,
  repository?,
  idempotency_key?
)
```

Use for a general conversation comment or as the safe fallback when an inline position is stale or unsupported.

### `add_code_review_inline_comment`

```text
add_code_review_inline_comment(
  number,
  body,
  path,
  line,
  repository?,
  old_path?,
  side="RIGHT",
  commit_id?,
  base_commit_id?,
  start_commit_id?
)
```

Copy `path`, `old_path` (for renamed/deleted left-side lines), `line`, `side`, and commit coordinates from the latest normalized review context. Never calculate a provider line solely from the local working tree.

### `reply_code_review_thread`

```text
reply_code_review_thread(number, thread_id, body, repository?)
```

Call only when the normalized comment/thread reports `can_reply=true`.

### `resolve_code_review_thread`

```text
resolve_code_review_thread(number, thread_id, repository?)
```

Call only when `can_resolve=true` and the finding is actually addressed or explicitly concluded.

### `reopen_code_review_thread`

```text
reopen_code_review_thread(number, thread_id, repository?)
```

Use when a resolved concern is still applicable to the current source/head commit.

Refresh the review after every discussion mutation.

## 4. Decision and metadata tools

### `submit_code_review`

```text
submit_code_review(
  number,
  event,
  repository?,
  body="",
  reviewer_id?
)
```

`event` is exactly one of:

- `approve`
- `request_changes`
- `comment`

Use a provider reviewer identity only when returned by normalized context. Never guess `reviewer_id`.

### `update_code_review`

```text
update_code_review(
  number,
  repository?,
  title?,
  body?,
  draft?,
  labels?,
  reviewers?,
  assignees?
)
```

Send only fields explicitly requested by the user. Check each matching capability because providers may support only part of an update.

Do not silently omit unsupported fields. Report each field that was not applied.

## 5. Lifecycle tools

### `merge_code_review`

```text
merge_code_review(
  number,
  repository?,
  method?,
  commit_title?
)
```

Merge is an important action and requires confirmation by default. Use only a merge method supported by live capabilities and repository policy.

### `close_code_review`

```text
close_code_review(number, repository?)
```

Closing or declining a review is an important action and requires confirmation by default.

### `reopen_code_review`

```text
reopen_code_review(number, repository?)
```

Use only for an explicit request to restore a closed review. Refresh first to avoid an unnecessary state transition.

## 6. Identifier and inline-position rules

Normalized comment context distinguishes:

- `stable_id`: durable display and correlation
- `id`: provider comment/note identifier
- `thread_id`: discussion/thread identifier used by reply and resolution tools
- `parent_id`: reply relationship
- `path`, `line`, `side`: provider-normalized inline target
- `commit_id`: commit context for the inline position
- `resolved`, `can_reply`, `can_resolve`: current state and permissions

Use `thread_id` for reply, resolve, and reopen. Do not substitute `stable_id`.

Inline positions belong to a particular diff and commit. After a force-push or new source commit, refresh and use new coordinates.

GitLab inline positions may require all of `commit_id`, `base_commit_id`, and `start_commit_id`. Use exactly the values returned by the adapter.

## 7. Idempotency, refresh, and error handling

An idempotency key represents one logical action:

- reuse it when safely retrying that same action
- use a different key for a different comment or mutation
- do not create a new key to blindly retry an ambiguous timeout

After an ambiguous timeout:

1. Refresh `get_code_review`.
2. Check whether the intended state or comment exists.
3. Retry only when absence is proven and the action is safe to repeat.

After every mutation, refresh and verify provider state. A successful transport response is not enough when the returned state is ambiguous.

When a capability is unsupported:

1. Do not call the mutation.
2. Explain the provider limitation.
3. Offer the closest safe supported action.
4. Never fall back to a CLI, raw HTTP, GraphQL, browser automation, or token handling.

## 8. Permission and safety policy

- Reads can run automatically.
- Comments and replies follow the configured tool permission policy.
- Approve, request changes, update, resolve, reopen, and other mutations require their configured mutation permission.
- Merge and close are important actions and require confirmation by default.
- A request to review does not authorize publishing feedback.
- Never read, print, log, persist, or transmit a saved token outside the provider adapter.
- Never report a remote action as complete until the tool succeeds or refreshed state confirms it.
