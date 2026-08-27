# EASD realtime and collaboration — sampleproject audit

Date: 2026-08-27

Run: `06a8fa49-a1c8-7ffb-8000-5aa016dc8d25`

Repository: `evoflux-easd-ux-audit.qr9KP5/sampleproject`

## Setup

The live EvoFlux UI was the first subscriber. A second independent SSE client
connected to the same Recovery audit Run. A same-phase recovery event was then
persisted through the public API. No model prompt or product-file mutation ran.

## Presence audit

- UI initially showed `Live · 1 viewer`.
- Second client joined and both received presence count 2.
- UI changed to `Live · 2 viewers` without refresh.
- Disconnecting the second client returned the UI to one viewer.
- Presence contained only random client IDs and was not written to Run files.

## Live event and projection audit

- Before the event, UI showed repository generation 3.
- Recovery persisted `specification_authoring_retried` at sequence 4 and
  repository generation 4.
- The second client received the event live with sequence and generation.
- The UI realtime hook invalidated Run projections; the header changed to
  generation 4 and Trace displayed the additional retry without polling.

The first implementation revealed that post-commit repository writes updated
the SSE envelope but not the shared `serialize_run()` generation cache. This
would have left the UI on generation 3 after realtime refresh. Projection
metadata was moved into a shared module updated before event publication; the
live audit then showed generation 4 correctly.

## Replay and reconnect audit

A new client connected with `after_sequence=3`. It received only sequence 4,
then current presence. Older sequences 1–3 were not replayed. Hook tests verify
that reconnect uses the highest delivered sequence and ignores duplicate
replay/live overlap.

## Failure and resource audit

- Broker queues are capped at 256 events.
- Overflow clears the slow queue and emits one `easd_resync_required` message.
- Run isolation tests confirmed events do not reach subscribers of another Run.
- Repository CAS and Recovery generation checks remained authoritative.

## Conclusion

Local multi-window collaboration, presence, live projection refresh, bounded
delivery, and reconnect replay are implemented and verified on sampleproject.
Cross-host transport, collaborative editing, comments, and user identity are
not part of this slice.
