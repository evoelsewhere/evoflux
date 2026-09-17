# Output template — asdd-archive

This phase writes nothing to the repository. The fold is a server operation —
the product performs it when the user clicks Archive — and this Skill's output
is the report that tells them whether to.

## In the chat

```markdown
`add-note-search` is ready to archive.

**Gates**
- proposal — approved by the user 2026-09-17
- specs — cleared by autopilot 2026-09-17
- tasks — approved by the user 2026-09-17

**Evidence** — 2 pages, 2 passed, 0 failed, 0 inconclusive.

**Tasks** — 4 of 4 ticked.

**The fold will**
- create `specs/note-search/spec.md` with 2 requirements
- move the folder to `changes/archive/2026-09-17-add-note-search/`

**Nothing blocks it.**
```

When something does block it, replace the last line with what and why, one
line each, naming the file the user has to fix.

## Rejected if

- It reports a gate as approved without saying whether a person or autopilot
  cleared it — for `cross_layer` and `critical` the design must be the user's.
- It archives anything itself, sets `status: archived`, or edits a capability
  spec. The fold is the product's, and only the user starts it.
