# Architecture

How this system is put together: process and storage boundaries, concurrency,
trust, and the seams a change has to respect. A spec says what the system
guarantees; this says what it is made of and why crossing a line here is a
bigger decision than it looks.

```text
architecture/
├── <topic>.md          # one boundary, subsystem or flow
└── decisions/          # the durable decisions behind them
```

## What belongs here

- Process and deployment boundaries — what runs where, and what may not.
- Storage: what is durable, what is cache, and who owns each store.
- Concurrency: what is ordered, what is idempotent, and what may retry.
- Trust: which inputs are untrusted, where they are bounded, and by what.
- The seams between subsystems, named the way the code names them.

## What does not

- Behavior a capability guarantees — that is `specs/<capability>/spec.md`.
- Exact field names, flags and payloads — that is `reference/`.
- One change's plan — that is `changes/<change-id>/design.md`.
- An investigation that informed a decision — that is `analysis/`.

## How it changes

A change that moves a boundary updates the page that describes it, in the same
change as the code, and records the decision under `decisions/`. Architecture
that lags the code is worse than none: it is read as current.
