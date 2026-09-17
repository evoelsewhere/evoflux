# Agent Specification-Driven Development

Agent Specification-Driven Development (ASDD) is EvoFlux's contract-first
workflow for agentic software delivery. It turns intent into a reviewable
specification, binds implementation to named requirements, and asks for evidence
before a change is considered done.

This guide explains how to use it. The normative rules are
[ASDD Core Rules](../../.evoflux/asdd/RULES.md); the lifecycle is
[ASDD methodology](../reference/asdd-methodology.md).

## Why it exists

Agents produce plausible work quickly. Plausible is not the same as correct, and
the gap is only visible when there is something to check the work against.

ASDD gives you that something, and keeps it where you can read it. A change is a
folder of Markdown in your repository: what is proposed, what the system will
guarantee, what has to be built, and what was actually run. You review it with
`git diff`, exactly like code.

Humans decide what is approved and when the work advances. Agents draft, plan,
implement, verify and report within explicit boundaries.

## The seven phases

```text
propose → specify → [design] → plan → implement → verify → archive
```

1. **Propose.** An agent reads the repository and writes `proposal.md`: why the
   change is needed, what observably changes, which capabilities it touches, and
   what it deliberately does not do. You approve it.
2. **Specify.** An agent writes one delta per capability — `ADDED`, `MODIFIED`
   and `REMOVED` requirements, each with scenarios in WHEN/THEN form. You
   approve them. This is the contract.
3. **Design** — only for `cross_layer` and `critical` risk. The approach, the
   rejected alternatives and why, the boundaries crossed, migration and
   rollback. You approve it.
4. **Plan.** An agent turns the approved deltas into `tasks.md`, every task
   pointing at the requirement it serves. You approve it — and that approval is
   what authorizes product-file changes.
5. **Implement.** An agent executes tasks in order and ticks boxes as it goes.
   If the plan turns out to be wrong it says so rather than quietly widening the
   contract.
6. **Verify.** An agent checks each requirement against the implemented system
   and writes evidence pages saying what it ran and what it found. It does not
   fix what it finds; that would be reviewing its own repair.
7. **Archive.** You fold the deltas into `specs/<capability>/spec.md`, and the
   change folder retires to `changes/archive/YYYY-MM-DD-<change-id>/`.

## Getting started

1. Open a Coding workspace and choose **Agent Spec-Driven** in the workbench.
2. **Install** ASDD. It writes a catalogue, the rules and six Skills, all
   tracked, so a collaborator who clones the repository gets the method.
3. Fill in `documents/asdd/project.md` — what the repository is, what a change
   here must respect, and the commands that prove one works. An accurate
   paragraph there saves more agent turns than any other instruction.
4. **New change**, give it a title, and run the phases from the rail.

## Choosing a capability

A capability is a durable slug naming one behavior the system guarantees —
`user-auth`, `jira-snapshot-sync`, `spec-catalogue-layout`.

Reuse one whenever your change alters behavior it already contracts. That
publishes another revision of a single contract instead of two contracts
describing the same thing. Coin a new slug only for behavior the catalogue does
not cover, and say in the proposal which existing ones you ruled out.

## Choosing a risk tier

| Tier | Use it for | Costs |
|---|---|---|
| `trivial` | a contained change crossing no boundary | — |
| `standard` | the default: one boundary, ordinary review | — |
| `cross_layer` | multiple layers or repositories | a design document and an independent review |
| `critical` | security, migration, persistence, public compatibility | a design document and an independent review |

Do not reach for a high tier to signal effort. The tier buys specific extra
work; pick the one that describes the risk.

## Where things live

```text
documents/asdd/
├── project.md
├── specs/<capability>/spec.md          # what the system guarantees now
└── changes/
    ├── <change-id>/
    │   ├── proposal.md                 # front matter carries status + approvals
    │   ├── design.md
    │   ├── tasks.md
    │   ├── specs/<capability>/spec.md  # the delta
    │   └── evidence/<id>.md
    └── archive/
```

Installation creates missing files only. It never copies, moves or claims
documentation the repository already owns.

## When something goes wrong

**A run died halfway.** Open the folder and look. The `status` in `proposal.md`
says where it stopped; fix whichever side is wrong and carry on.

**The rail says the status disagrees with the folder.** That is the product
refusing to guess. It reports the contradiction and changes neither side,
because both are things you might legitimately have meant.

**A requirement turns out to be wrong during implementation.** Stop. Do not
weaken the code to fit it, and do not edit an approved delta. Say what the code
needs and let the user decide whether to revise the change.

**Two agents raced on one file.** They overwrote each other, and `git diff`
shows it. There is no optimistic concurrency here — that is the trade for a
method with no hashes and no session locks.

## Further reading

- [ASDD Core Rules](../../.evoflux/asdd/RULES.md)
- [ASDD methodology](../reference/asdd-methodology.md)
- [Agent Spec-Driven](../features/agent-specs.md)
- [Agent Spec-Driven architecture](../architecture/agent-specs.md)
- [ASDD configuration](../../.evoflux/asdd/config.json)
