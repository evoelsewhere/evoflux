# Output template — asdd-specify

`changes/<change-id>/specs/<capability>/spec.md`, one file per capability. A
delta, not a copy of the spec: only what changes.

```markdown
## ADDED Requirements

### Requirement: Find a note by title

The system SHALL return every note whose title contains the query.

#### Scenario: A title matches

- **WHEN** the reader searches for `gro`
- **THEN** the note titled `groceries` is returned

## MODIFIED Requirements

### Requirement: <the exact name in the current spec>

The system SHALL <the full replacement text, not a diff of it>.

#### Scenario: <what is being exercised>

- **WHEN** <the trigger>
- **THEN** <the observable result>

## REMOVED Requirements

### Requirement: <the exact name in the current spec>
```

Omit any section with nothing in it.

## Rejected if

- A requirement has no `#### Scenario:` — the product blocks the specs gate.
- A `MODIFIED` or `REMOVED` name does not exist in the capability's current
  spec — the product reports it as a delta problem.
- A **THEN** states an implementation detail rather than something a reader
  could observe.
