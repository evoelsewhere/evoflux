# evo documentation

This folder is the single home for evo's design documentation. It follows two
document types:

- **ADD — Architecture Design Document** (`architecture/`): how the whole
  system is built — processes, crate layers, interfaces, where state lives,
  cross-cutting rules. One living document, plus **ADRs** (Architecture
  Decision Records) for the decisions behind it.
- **SDD — Software Design Document** (`features/<slug>/sdd.md`): how one
  feature is specified, designed, built and verified. One per feature.

The ADD says *what every feature must fit into*; an SDD says *how one feature
fits in*. An SDD links the ADD sections and ADRs it relies on and never
restates them.

## Layout

```text
docs/
  README.md                     this file: map + documentation rules
  architecture/
    README.md                   the ADD
    decisions/
      README.md                 ADR index and rules
      NNNN-<slug>.md            one decision each
  features/
    README.md                   feature catalogue (every SDD, its status and area)
    <feature-slug>/
      sdd.md                    the feature's SDD
      assets/                   optional: diagrams, screenshots used by the SDD
  templates/
    sdd.md                      copy to start a feature
    adr.md                      copy to record a decision
```

Not in this folder:

- `apps/desktop/README.md` — the desktop's UI map and source layout (a code
  map; it links to SDDs for the design).
- Crate `README.md` files — what a crate offers to its users.
- `crates/evo-engine/embedded-docs/` — user and extension-author docs shipped
  inside the engine for the agent's docs tool. Parts still describe the old
  CLI; they are product docs, not design docs.
- `DESIGN.md` at the root — the visual design language.

## The workflow (spec first)

Every feature goes through its SDD before and after the code:

1. **Draft.** Copy `templates/sdd.md` to `features/<slug>/sdd.md`, add a row to
   `features/README.md`, fill sections 1–6 (summary, scope, requirements,
   context, design, alternatives) and 9 (open questions). Status `Draft`.
2. **Accept.** The owner (the user, for agent-written work) reviews the
   design and answers the open questions. Status `Accepted`. Code starts
   here — not before.
3. **Build.** Status `In progress`. Work in the phases of section 7. When the
   design changes while building, change the SDD in the same commit as the
   code; never let the code lead silently.
4. **Ship.** Status `Implemented`. Section 5 now describes the behaviour as it
   is; section 10 records where the build differs from the original design;
   section 8 names the tests and checks that ran.
5. **Later changes** to the feature edit the same SDD (and add a line to its
   History). A redesign that replaces the feature gets a new SDD; the old one
   becomes `Superseded by <link>`.

If a feature changes the architecture (see "When the ADD changes"), the ADD
and an ADR change in the same commit as the SDD.

## When a change needs an SDD

Needs one:

- a new user-visible capability (a page, a panel, a setting group, an agent
  tool, a slash command);
- a change to `evo-protocol`, the mesh envelope, Tauri commands/events used
  across features, the plugin ABI, or the `evo.db` schema;
- a new crate, a new process, or a new place where state is stored;
- anything touching permissions, the sandbox, credentials or project trust.

Does not need one (but update the existing SDD if behaviour it describes
changes): bug fixes, refactors inside one module, copy and styling tweaks,
dependency bumps, tests, CI.

When unsure, write a short SDD — a half-page SDD is fine; a missing one is not.

## When the ADD changes

Update `architecture/README.md` **and** add an ADR when a change:

- adds, removes or merges a crate, or changes which crate may depend on which;
- adds a process, a transport, a protocol plane, or changes who owns a
  responsibility (engine vs shell vs webview);
- adds a persistent store or moves state between stores;
- changes a trust boundary, the permission model or the sandbox;
- adopts or drops a platform, toolchain, framework or external data source;
- reverses an existing ADR.

## SDD rules

- **Fixed structure.** Keep every numbered section of the template in order.
  A section that does not apply says `n/a — <reason>`; it is not deleted. This
  keeps every SDD scannable the same way.
- **Header table first**, right under the title: Status, Area, Created,
  Updated, ADD sections, ADRs, Related. Update `Updated` on every edit.
- **Status values:** `Draft`, `Accepted`, `In progress`, `Implemented`,
  `Superseded by <link>`, `Deprecated`. The catalogue row shows the same value.
- **Requirements are numbered** (`FR-1`, `NFR-1`) and each has an acceptance
  check. Section 8 maps each requirement to the test or manual check that
  proves it. IDs are never renumbered; a dropped requirement is struck out.
- **Present tense for what is built**, future tense only in plans and open
  questions. The top of the document describes the feature as it is now —
  do not stack "Status: phase N built…" paragraphs; phase history goes in
  sections 10 and 11.
- **Name the code.** Section 5.2 lists each component with its
  repository-relative path. Paths are written from the repository root.
- **Link, don't copy.** Refer to the ADD, ADRs and other SDDs by relative
  link; copy a fact only when the reader cannot follow without it.
- **Diagrams as text** — Mermaid or ASCII in the Markdown, so they diff and
  review. Images go in `assets/` only when text cannot show it (UI
  screenshots).
- **One feature per folder.** The slug is kebab-case, short and stable; it is
  never renamed after `Accepted` (code comments link to it).

## ADR rules

See `architecture/decisions/README.md`. In short: numbered, one decision
each, immutable once `Accepted` — a changed mind is a new ADR that supersedes
the old one.

## Writing rules (all docs)

- English, plain and direct; short sentences; no marketing.
- Repository-relative links (`../../architecture/README.md#5-building-blocks`),
  never absolute file paths or machine-specific paths.
- Code, paths, commands, settings keys, RPC/tool names in backticks; UI names
  in bold (**Settings → Sandbox**).
- The product is "evo". Do not name other vendors' assistant products in docs;
  describe a reference behaviour by what it does.
- Dates as `YYYY-MM-DD`.
- No secrets, tokens, real user data or personal paths in examples.

## Code ↔ docs links

Code that implements a design links its SDD in the module doc comment, e.g.
`//! The session mesh hub (docs/features/session-mesh-protocol/sdd.md).`
When an SDD moves or is superseded, update those comments in the same commit
(`git grep 'docs/features/<slug>'`). **Exception:** never edit an applied
migration in `crates/evo-store/src/migrations/` — its SQL is checksummed and
a changed byte breaks existing databases. Old paths in migration comments
(such as `docs/design/…`) stay as they are; a moved doc keeps its slug so the
reader can still find it.

## Review checklist

Before marking an SDD `Accepted`:

- [ ] Goals and non-goals are explicit; every FR/NFR has an acceptance check.
- [ ] The design names each layer it touches (crate, engine, protocol, shell,
      webview) and stays within the ADD's ownership rules.
- [ ] Interfaces (protocol messages, tool schemas, settings keys, tables) are
      written out, with compatibility for older engines/clients.
- [ ] Security and trust (5.7) is filled, not `n/a`, for anything that runs
      tools, reads untrusted content, stores credentials or crosses a process.
- [ ] Alternatives considered, with the reason each was rejected.
- [ ] Phases each have a "done when".
- [ ] Architecture-level changes have an ADR and an ADD edit.

Before marking it `Implemented`:

- [ ] Section 5 matches the code; section 10 lists every deviation.
- [ ] Section 8 lists the tests and checks that actually ran.
- [ ] The catalogue row, `apps/desktop/README.md` UI map (if user-visible) and
      code doc comments link to this SDD.
