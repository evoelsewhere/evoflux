# Capability specs

One directory per capability, each holding a single `spec.md` that states the
behavior this system currently guarantees. This is the normative layer: when
code and a spec disagree, the code is wrong until a change says otherwise.

```text
specs/
└── <capability>/
    └── spec.md
```

## The shape of a spec

```markdown
## Purpose

One paragraph: what this capability is for.

## Requirements

### Requirement: <short name>

The system SHALL <observable behavior>.

#### Scenario: <what is being exercised>

- **WHEN** <the trigger>
- **THEN** <the observable result>
```

A requirement without a scenario is an intention, not a contract. A scenario
without a **WHEN** and a **THEN** cannot be verified.

## How a spec changes

Never by hand. A change writes a delta under
`changes/<change-id>/specs/<capability>/spec.md`, the user approves it, and
archiving folds it in. That is what keeps the catalogue and the history of how
it got that way in the same repository.
