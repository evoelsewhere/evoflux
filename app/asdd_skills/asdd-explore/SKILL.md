---
name: asdd-explore
description: Fill a freshly installed ASDD catalogue from the repository it was installed into — project.md, and the architecture and reference pages the code already justifies. Use right after ASDD setup, or when project.md is still placeholders; do not use to write capability specs or to run a change.
---

# Explore a repository into its ASDD catalogue

Setup writes the catalogue's shape. You write its first contents: what this
repository is, what a change here has to respect, and the pages that describe
what already exists.

**IMPORTANT: you are describing, not deciding.** Everything you write states
something already true of this repository on this commit. You change no product
file, you propose no work, and you write no capability spec — `specs/` is the
normative layer, and filling it from code would contract whatever the code does
today, bugs included.

This is the one time these pages are written outside a change, because there is
no behavior change to propose: the repository already is what it is. From your
last line onward, every durable page ships inside the change that makes it true
(rule 18).

---

## Read before you write

1. `.evoflux/asdd/config.json` — where the catalogue lives (`data_directory`).
2. `.evoflux/asdd/RULES.md` — normative; it outranks this Skill.
3. Each catalogue directory's `README.md` — `architecture/`,
   `architecture/decisions/`, `reference/`, `analysis/`, `specs/`. They state
   what belongs in each one, and you are about to write into them.
4. **Every `AGENTS.md` in the repository**, root and nested. If they exist they
   are already this repository's voice; your job is to point at them, not to
   paraphrase them into a second copy that will drift.
5. `README`, the build and test configuration, CI workflows, and the top-level
   layout.

---

## Check the gate

| What you find | What to do |
|---|---|
| `project.md` still holds the shipped placeholders | Write it. The normal case. |
| `project.md` is filled in | Do not rewrite it. Report what looks stale, name the file, and stop. |
| No `.evoflux/asdd/config.json` | **Stop.** ASDD is not installed here; setup comes first. |
| No `AGENTS.md` anywhere | Note it and carry on — then recommend `/init` in your report. It writes AGENTS.md properly, at every level that needs one, and this Skill does not duplicate it. |

---

## Step 1 — Say what you can and cannot infer

Before asking anything, read. Then tell the user, in the chat, what the
repository answered by itself and what it did not:

```text
Read: 3 AGENTS.md, pyproject.toml, Makefile, .github/workflows/ci.yml,
12 top-level packages.

Inferred: Python 3.12 + FastAPI sidecar, React/TS UI, Tauri shell. Tests are
`uv run pytest -q` and `bun run test:unit` — both in the Makefile and CI.
Durable logic lives under app/services/ (37 modules; routes are thin).

Could not infer: what must not break for your users, when a change here needs
a design beyond the tier default, and what a proposal must always state.
```

A claim you could not evidence does not go into the catalogue. Say it out loud
instead.

---

## Step 2 — Ask only what the repository cannot answer

One `ask_user` call, batched, four to six questions, each with a
recommendation. These are the questions `project.md` exists to answer:

| Ask | Because it lands in |
|---|---|
| What must this repository never break — who depends on it and how? | `## Context` |
| Which commands prove a change works here? (confirm what you inferred) | `## Conventions` |
| Where does durable logic belong, and where must it not? | `## Conventions` |
| What must every proposal here state — affected component, user impact, breaking-change status? | `## Rules → Proposal` |
| When does a change here need a design beyond the risk-tier default? | `## Rules → Design` |
| Which scenarios must every spec cover — migration, rollback, failure? | `## Rules → Specs` |

Do not ask what you already read. Do not ask for preferences the method
already decides. If the user answers none of them, write what you evidenced
and leave the rest as the placeholder that says what is missing — an honest
gap beats an invented rule that every later phase will obey.

---

## Step 3 — Write `project.md`

Replace the placeholders, keeping the headings. Every claim carries where it
came from, in parentheses, so the next reader can check it rather than trust
it:

```markdown
## Conventions

- Python 3.12, FastAPI sidecar; React 19 + TypeScript for the UI
  (`pyproject.toml`, `web/package.json`).
- Durable logic belongs in `app/services/`; routes stay thin
  (`AGENTS.md:31`, confirmed by the user).
- `uv run pytest -q` and `bun run test:unit` prove a change
  (`Makefile:44`, `.github/workflows/ci.yml:60`).
```

Where AGENTS.md already says something, **cite it instead of restating it**.
Two files saying the same thing in different words is two files that disagree
a month from now.

---

## Step 4 — Write the base pages the code justifies

This is the substance: a catalogue with nothing in it teaches an agent
nothing, and the first change should not have to invent the map.

### `architecture/`

One page per boundary you can evidence, named for the boundary rather than for
the folder: `process-boundaries.md`, `storage.md`, `trust-and-permissions.md`,
`concurrency.md`. Each says what runs where, what owns which store, what is
ordered or idempotent, which inputs are untrusted and what bounds them — and
cites the code that shows it.

**Cap it at five pages.** A page per package is a directory listing, not an
architecture; if you cannot say why a boundary matters, leave it out.

### `reference/`

One page per surface that actually exists — `api.md`, `configuration.md`,
`cli.md`, `events.md`. Exact names, defaults, units, limits and error codes,
read out of the code rather than remembered. If a surface has no stable
consumers yet, skip it: an invented reference page is the one document readers
will not double-check.

### `architecture/decisions/`

**Write none.** An ADR states the alternative that was rejected and why, and
neither survives in code — reconstructing them is archaeology presented as
record. Instead, list in your report the decisions you can see were made
(a storage engine, a protocol, an ordering guarantee) so the user can write
the ones worth writing, or let the next change that touches one write it then.

### `analysis/` and `specs/`

Leave both empty. `analysis/` is dated investigation, and you have not run one.
`specs/` is the normative layer: it changes by archiving an approved delta, and
seeding it from code would contract the current behavior — bugs included — with
nobody having agreed to any of it.

---

## Step 5 — Hand off to a real change

The catalogue is not finished by more documents; it is finished by use. End by
pointing at the next thing:

> The map is in place. The best next step is one small real change — it will
> exercise every phase and produce its own documents. Start one and I will
> propose it.

---

## Tools

- `code_context` — the discovery tool here. One `action="search"` to expose a
  declared identifier, then the exact-symbol action on it; `action="callers"`
  to establish that a boundary is real rather than apparent. Depth 1 unless
  the question is transitive. Never bulk scan.
  `references/code-context-contract.md` is normative and carries the full rules.
- `ask_user` — Step 2, once, batched.
- `shell` — read-only: `git log --oneline -20` for what this repository has
  been doing lately, and the build files that name its commands. Run a
  documented test command once if you can, so `project.md` does not promise a
  command that does not work.
- `memory_search` — what this workspace has already decided about itself.

---

## Stop, and report

```text
documents/asdd — explored.

project.md: written. Context and conventions from AGENTS.md + Makefile;
"must not break" and the design rule are yours, from Step 2.

architecture/: 3 pages — process-boundaries, storage, trust-and-permissions.
reference/: 2 pages — configuration (41 settings), cli (9 commands).
specs/, analysis/, decisions/: left empty, deliberately.

Decisions I can see were made but did not write up: SQLite as the single
local store; the sidecar handshake protocol; one-writer-per-session ordering.
Each needs its rejected alternative, which the code does not carry — write
them when a change touches one.

No AGENTS.md at the repository root. Run `/init` before the first change;
it writes those properly and every phase reads them.
```

Name every file you wrote, every directory you deliberately left empty and
why, the decisions you saw but did not record, and anything the user still
owes the catalogue.

---

## Guardrails

- **Don't write `specs/`.** Not one requirement. It is the normative layer and
  it changes by archiving an approved delta.
- **Don't write ADRs.** A decision without its rejected alternative is a
  record of nothing.
- **Don't paraphrase AGENTS.md.** Cite it. A second copy is a future
  contradiction.
- **Don't write a claim you cannot cite.** An uncited line in `project.md`
  steers every later phase and nobody knows where it came from.
- **Don't touch product files.** Explore describes; it does not change.
- **Don't fill every directory** because it exists. Empty and explained beats
  full and invented.
