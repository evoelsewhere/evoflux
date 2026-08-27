# EASD traceability workspace — sampleproject audit

Date: 2026-08-27

Run: `06a8f23b-694f-7301-8000-de637997f5a7`

Repository: `evoflux-easd-ux-audit.qr9KP5/sampleproject`

## Scope

The audit used the live EvoFlux development application and the existing
repository-owned Run **Add a usage example** in `planned` state. No lifecycle
action was executed and no sampleproject artifact was modified.

## Repository evidence inspected

- one accepted Spec revision with five ACs;
- one accepted Plan revision with three mission contracts;
- seven append-only events from `intent_created` through `plan_accepted`;
- repository generation 7;
- no dispatched mission attempts or evidence yet, as expected before
  implementation starts.

The API projection produced 11 nodes, 26 typed edges, and seven ordered events.
Legacy events without explicit entity references were retained and associated
with the Run; Spec/Plan draft and acceptance events were deterministically
associated with their revision nodes.

## Interaction audit

### Narrow side panel

- Overview/Trace tabs fit without horizontal scrolling.
- Trace summary and AC filter remain visible before the ledger.
- Activity is intentionally first; the relationship map and inspector follow
  below the fold.
- All seven events show sequence, actor, phase transition, and timestamp when
  present. The initial legacy event has no timestamp and degrades without a
  fabricated value.

### Maximized panel

- Activity, Relationships, and Inspector render as three columns.
- Long workspace/session identities wrap rather than overflow.
- Run, Spec, five ACs, Plan, and three mission contracts are discoverable and
  selectable.

### AC filtering

- Filtering `AC_EXPECTED_RESULT` reduced the visible relationship set from 26
  to 13 and retained the owning implementation, review, and verification
  mission contracts.
- The first implementation incorrectly kept the Run selected in the inspector
  after filtering. The audit caught this; the UI now selects the filtered AC by
  default.

## Findings and disposition

| Finding | Severity | Disposition |
|---|---:|---|
| AC filter initially left Inspector on Run | Medium | Fixed and covered by component test |
| Legacy `intent_created` lacks `created_at` | Low | Preserve honestly; new server events include timestamps |
| Legacy events lack entity references | Low | Projection infers Spec/Plan references; new events persist stable refs |
| No mission attempts/evidence in this Run yet | Expected | Re-audit these nodes during Recovery slice execution |
| Polling remains the refresh mechanism | Expected | Owned by Slice 4 Realtime |

## Verification conclusion

The Trace workspace is usable in both narrow and maximized layouts and answers
the pre-implementation lineage questions for the real Run. Mission-attempt,
failed-evidence, retry lineage, reconnect replay, and collaborator conflict
states remain explicit audit targets for Slices 3 and 4.
