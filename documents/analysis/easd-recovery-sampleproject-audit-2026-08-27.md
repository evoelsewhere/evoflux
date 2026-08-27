# EASD Recovery UX — sampleproject audit

Date: 2026-08-27

Audit Run: `06a8fa49-a1c8-7ffb-8000-5aa016dc8d25`

Repository: `evoflux-easd-ux-audit.qr9KP5/sampleproject`

## Isolation

A separate Run named **Recovery UX audit** and a separate tagged Coding session
were created so the existing **Add a usage example** Run remained `planned` and
unchanged. The audit did not send a model prompt and did not edit product files.

## UI audit

- Recovery appeared beside Overview and Trace in the narrow Run panel.
- Draft state offered only **Redraft specification**.
- Preview displayed repository generation 1, full Spec hash, bound Coding
  session, `draft → authoring`, and all preserved history categories.
- Confirmation repeated phase impact and stated that authoring chat opens only
  after persistence.
- Cancel closed the dialog without changing Run state.

## Persistence and failure-path audit

The recovery was executed directly through the API to avoid auto-sending the
chat prompt:

- first execution returned `200` and moved `draft → authoring`;
- repeating the same idempotency key returned an identical `200` response;
- a second action with the old generation returned `409` with an explicit stale
  generation message;
- Trace contained exactly one new `specification_authoring_retried` event at
  sequence 2 with actor `human` and the correct phase transition;
- the previous Spec draft remained in the Run and no evidence/deviation was
  deleted.

## Findings

| Finding | Severity | Disposition |
|---|---:|---|
| Recovery confirmation and preview fit narrow panel | — | Passed |
| Duplicate idempotency key could have appended two events | High | Prevented; identical cached result and one event |
| Stale generation could race a collaborator | High | Prevented before mutation with `409` |
| Rework from Review/Verify to implementation needs evidence invalidation | High | Explicitly out of scope; no unsafe action exposed |
| Recovery created a new chat prompt automatically during API audit | — | Did not occur; API used directly |

## Conclusion

Safe current-phase recovery, durable lineage, idempotency, and stale-state UX
are implemented. Rework that changes product files after Review/Verify must be
specified separately with downstream evidence invalidation before it can be
offered.
