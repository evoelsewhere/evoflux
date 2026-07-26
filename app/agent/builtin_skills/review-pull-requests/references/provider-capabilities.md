# Provider capability guide

Use this file as routing guidance. The live `capabilities` object returned by `get_code_review` is authoritative because server versions and adapters can change.

## Capability matrix

| Provider | Comments | Inline | Reply | Resolve | Approve | Request changes | Checks | Draft/ready | Merge | Close/reopen |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| GitHub / Enterprise | Yes | Yes | Inline threads | No via REST | Yes | Yes | Yes | No via REST | Yes | Yes |
| GitLab self-managed | Yes | Yes | Yes | Yes | Yes | No formal REST event | Yes | Yes | Yes | Yes |
| Bitbucket Cloud | Yes | Yes | Yes | Yes | Yes | Yes | Yes | No | Yes | Yes |
| Bitbucket Data Center | Yes | Yes | Yes | Yes | Yes | Adapter-dependent | Not normalized | No | Yes | Yes |
| Gitea / Forgejo | Yes | Review comments | Limited | No | Yes | Yes | Yes | No | Yes | Yes |
| Azure DevOps | Yes | Yes | Yes | Yes | Yes with reviewer ID | Yes with reviewer ID | Yes | Yes | Yes | Yes |

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
