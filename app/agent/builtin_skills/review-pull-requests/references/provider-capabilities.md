# Provider capability guide

Use this file as routing guidance. The live `capabilities` object returned by `get_code_review` is authoritative because server versions and adapters can change.

## Capability matrix

| Provider | Comments / inline | Threads | Decision | Checks | Metadata update | Draft/ready | Merge | Close/reopen |
|---|---|---|---|---|---|---|---|---|
| GitHub / Enterprise | Yes / yes | Reply; no REST resolve | Approve and request changes | Yes | Title, body, labels, reviewers, assignees | No via REST | Yes | Yes |
| GitLab self-managed | Yes / yes | Reply and resolve | Approve; no formal request-changes event | Yes | Title, body, labels, reviewers, assignees | Yes | Yes | Yes |
| Bitbucket Cloud | Yes / yes | Reply and resolve | Approve and request changes | Yes | Title, body, reviewers; others vary | No | Yes | Yes |
| Bitbucket Data Center | Yes / yes | Reply and resolve | Adapter/version-dependent | Often unavailable | Title, body, reviewers; version-dependent | No | Yes | Yes |
| Gitea / Forgejo | Yes / review comments | Version-limited | Approve and request changes when supported | Yes when supported | Title, body, labels, reviewers, assignees; version-dependent | No | Yes | Yes |
| Azure DevOps | Yes / yes | Reply and resolve | Approve and request changes with reviewer ID | Yes | Title, body, labels, reviewers; assignees vary | Yes | Yes | Yes |

## Important semantic differences

### GitHub / Enterprise

- Conversation comments and inline review comments are different REST resources.
- Thread resolution and draft/ready transitions require GraphQL, so the REST adapter reports them unsupported.
- Reply only when the normalized inline comment reports `can_reply=true`.

### GitLab self-managed

- Discussions contain notes; use `thread_id` from the normalized discussion.
- Inline positions require `head_sha`, `base_sha`, and `start_sha`.
- Approval is a formal action. Request changes is not a symmetrical formal REST action; post findings as discussions/comments instead.

### Bitbucket Cloud

- Comment bodies use rich content objects internally, but the normalized tools accept plain text.
- Replies and resolution operate on comment/thread IDs.

### Bitbucket Data Center

- PR updates and state transitions may require the current PR version. Refresh immediately before mutations.
- Build status APIs vary by installed version and plugin, so checks may be unavailable.

### Gitea / Forgejo

- Capabilities vary more across server versions.
- Inline feedback may be submitted as a review rather than a replyable discussion thread.
- Follow the live capability response and surface version limitations.

### Azure DevOps

- Threads carry file and line context separately from comments.
- Approval/request-changes mutations require the reviewer's identity ID.
- Merge completion uses the latest source commit and completion options; refresh immediately before merge.

## Unsupported behavior

When a live capability is false:

1. Do not call the mutation tool.
2. State which provider REST limitation blocks the action.
3. Offer the closest safe supported action, such as a conversation comment.
4. Do not fall back to `gh`, `glab`, raw HTTP, GraphQL, browser automation, or shell commands.

“Full support” means the normalized workflow covers every capability exposed by the connected server and reports genuine REST limitations precisely. It does not mean pretending that every provider implements the same review model.
