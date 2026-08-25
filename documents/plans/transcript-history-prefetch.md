# Transcript history prefetch

Status: implemented

## Outcome

Fast upward scrolling should not reach the earlier-history loader before the
next local render window or server page is ready. This is a frontend
performance change; cursor semantics, durable history, and visible transcript
content remain unchanged.

## Invariants

- The newest transcript remains the initial viewport target.
- Prepending loaded or newly rendered turns preserves the reader's visible
  anchor and does not reattach bottom-follow.
- Cursor requests stay serial and idempotent through the existing team store.
- DOM work remains windowed; the change does not render the complete durable
  transcript at once.
- Errors remain retryable through `TranscriptHistoryControl`.

## Measurable change

- Begin the earlier-history path at three viewport heights from the top, with a
  1600px minimum, instead of 300px.
- Prime one older server page after session mount when the loaded transcript
  contains less than that upward buffer.
- Increase the initial rendered window from 48 to 72 turns.
- Increase each local reveal from 12 to 24 turns.
- Rearm preloading after the reader moves one viewport beyond the load
  threshold, rather than requiring twice the threshold.

## Verification

- Unit-test viewport-derived load/rearm thresholds and prime eligibility.
- Component-test that a short session primes one older page only once.
- Preserve the existing store pagination, stale-session, retry, and prepend
  anchor tests.
- Run frontend unit tests, typecheck, lint, production build, and
  `git diff --check`.

## Ownership

- `web/src/utils/transcript-history.ts`
- `web/src/components/AgentView.tsx`
- `web/src/__tests__/utils/transcript-history.test.ts`
- `web/src/__tests__/components/AgentView.initial-scroll.test.tsx`
