# Reference

The exact surface this system exposes: endpoints and their payloads,
configuration keys and their defaults, schemas, events, and CLI commands. A
spec says the behavior is guaranteed; a reference page says precisely what to
type, send, and expect back.

```text
reference/
├── api.md              # endpoints, payloads, status codes
├── configuration.md    # every setting, its default and its effect
├── cli.md              # commands, flags, exit codes
└── <surface>.md
```

Split by surface, not by subsystem: a reader arrives knowing which one they are
calling, not which module implements it.

## What belongs here

- Names and shapes a caller has to get exactly right, spelled exactly.
- Defaults, units, limits and error codes, stated rather than implied.
- What is stable, what is experimental, and what is deprecated.

## What does not

- Why the surface looks this way — that is `architecture/decisions/`.
- Behavior guarantees and their scenarios — that is `specs/`.
- Tutorials and walkthroughs. A reference is looked up, not read through.

## How it changes

In the same change as the code, never after it. A reference page is the one
document a reader will not double-check against the source, so a stale line
here is not a gap — it is a false statement the product is making.
