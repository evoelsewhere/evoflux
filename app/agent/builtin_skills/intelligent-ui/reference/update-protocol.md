# Updating rendered blocks in place

A `ui_block` call renders one complete frame — it is never delta-streamed.
When the user's request changes something a rendered group already shows,
update that group in place instead of appending a second one.

## The two ids

The `ui_block` tool accepts two optional arguments alongside `blocks`:

- `block_id` — stable identity for this block group (e.g. `"metrics"`,
  `"pomodoro"`). Later calls with the same `block_id` update the group in
  place instead of appending a new one. Omit it for one-off groups.
- `replace_id` — the identity of an existing group to replace. The resolved
  identity order is `replace_id` → `block_id` → `tool_call_id`; the latest
  write wins, and if the target is not found the call renders a fresh group.

Both ids are at most 128 characters and match
`^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$` — start with a letter or digit, then
letters, digits, `.`, `_`, `-`.

Because the identity is part of the persisted tool arguments, a history
reload or replay upserts the same block rather than duplicating it. The
block payload *is* the tool's arguments, so history reconstruction is
lossless — always resend the complete block set, not a diff.

## Protocol

1. On first render, give the group a `block_id` derived from its purpose —
   `"ci_migration_plan"`, `"bill_split"`, `"pomodoro"` — and reuse the same
   `title`.
2. On a follow-up that changes the group (a phase finished, the checklist
   gained an item, the widget's mode switched), call `ui_block` again with
   the **same** `block_id` and the full updated `blocks` array. The
   conversation gets one updated group, not a duplicate.
3. When the user asks for a different view of the same area — swap the
   comparison table for a chart layout, replace the plan with a revised
   plan — pass `replace_id` set to the old group's id. The new group takes
   the old one's place.
4. Never reuse one `block_id` for unrelated groups; the id is what makes
   "update, don't append" work.

## Example

First turn renders the plan with `block_id: "ci_migration_plan"` (see
`worked-examples.md`, example 2). The user later says "wave 1 is done".
Second turn:

```json
{
  "blocks": [ { "type": "steps", "steps": [ { "title": "Inventory current pipelines", "status": "done" }, { "title": "Stand up the new runner fleet", "status": "done" }, { "title": "Port pipelines in two waves", "status": "active" }, { "title": "Decommission the old CI", "status": "pending" } ] } ],
  "title": "ci_migration_plan",
  "block_id": "ci_migration_plan"
}
```

Same id, same title, complete updated payload — the on-screen group updates
in place.

## State caution

Interactive blocks (flashcards, checklist, calculator) keep their live
state in the browser: checked items, the current card, the current input
values. Resending a block through `block_id` resets that state to the new
payload's defaults, so only update when the underlying content actually
changed — not to "refresh" a widget whose state the user may have moved.
