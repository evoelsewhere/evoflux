# Architecture decisions (ADR)

An ADR records one architecture decision: the context, the decision, its
consequences and the alternatives rejected. The
[ADD](../README.md) describes the system as it is; ADRs explain why.

## Index

| # | Decision | Status | Date |
| --- | --- | --- | --- |
| [0001](0001-desktop-app-is-the-only-front-end.md) | The desktop app is the only front end | Accepted | 2026-11-05 |
| [0002](0002-models-dev-is-the-model-database.md) | models.dev is the model database | Accepted | 2026-11-05 |
| [0003](0003-engine-runs-as-a-child-process-per-chat.md) | The engine runs as a child process, one per open chat | Accepted | 2026-11-06 |
| [0004](0004-bun-for-desktop-javascript.md) | bun is the only JavaScript package manager for the desktop | Accepted | 2026-11-06 |
| [0005](0005-real-engine-and-live-reload.md) | The app always runs the real engine; configuration reloads live | Accepted | 2026-11-06 |
| [0006](0006-documentation-follows-add-and-sdd.md) | Design documentation follows ADD, SDD and ADR | Accepted | 2026-11-06 |

## Rules

- **When:** any change listed under "When the ADD changes" in
  [docs/README.md](../../README.md), or any decision a future contributor
  would otherwise reverse without knowing why.
- **How:** copy [../../templates/adr.md](../../templates/adr.md) to
  `NNNN-<kebab-slug>.md` with the next free number (four digits), add a row
  to the index above, and edit the ADD sections it affects in the same commit.
- **One decision per ADR.** The title states the decision, not the topic
  ("The engine runs as a child process", not "Engine process model").
- **Status:** `Proposed` while under review, then `Accepted`. Once accepted the
  body is not edited except for typos and links. To change a decision, write a
  new ADR and set the old one to `Superseded by NNNN` (both index rows too).
- Numbers are never reused, even for rejected proposals (keep them with status
  `Rejected`).
