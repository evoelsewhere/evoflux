# WebBridge Side Chat architecture audit

Date: 2026-08-01

## Scope

This audit covers the Chrome/Edge WebBridge service worker, the Side Chat panel,
its pairing-scoped HTTP/SSE API, and parity with the canonical EvoFlux Work chat.

## Architectural invariants

1. Side Chat and EvoFlux render the same top-level `ChatSession`; the extension
   does not own a parallel transcript.
2. Browser evidence is persisted in the canonical user message sent to the
   agent, but UI surfaces render the original user-authored request.
3. Side Chat history and streaming may expose tool names and lifecycle only;
   tool arguments, results, credentials, and raw reasoning stay private.
4. A tab/session switch invalidates every older history, question, and stream
   mutation before it can update the visible panel.
5. At most one stream lifecycle owns a selected session. A transient disconnect
   retries with bounded exponential backoff and jitter; authorization and other
   non-retryable HTTP failures stop visibly.
6. Browser-control visuals are best-effort and must never block the underlying
   CDP command path.

## Findings and resolution

### High: stale relay attempts could win after disconnect or config change

The previous connect flow reset `manualDisconnect` inside an asynchronous
attempt. A ticket request already in flight could therefore create a socket
after Disconnect, or use a credential scoped to the old relay address.

Resolved with generation-scoped attempts, relay-scoped credential snapshots,
stalled-handshake timeout, and pushed connection state.

### High: stale Side Chat history could overwrite a newly selected tab session

`loadHistory()` and pending-question refreshes had no request identity. A slow
response for tab A could clear and repaint the transcript after tab B became
active.

Resolved with per-resource generations plus captured session IDs. Tests cover
the out-of-order response case.

### Medium: reconnect ownership was represented only by an AbortController

During retry backoff the controller was null, allowing the two-second running
poll to start a second lifecycle. Retries were fixed at 300 ms and stopped after
roughly nine seconds.

Resolved with explicit `streamTask`/`streamingSessionId` ownership, indefinite
transient recovery with a five-second cap, jitter, and fail-fast handling for
non-retryable HTTP responses.

### Medium: Side Chat and EvoFlux displayed the transport prompt

Browser contexts are correctly fenced into the canonical persisted content,
but this caused users to see internal `[Untrusted browser ...]` envelopes in
their own message bubbles.

Resolved by persisting `webbridge_side_panel.user_content`. Both the React chat
parser and the pairing-scoped Side Chat history projection use it for display,
while the agent still receives the complete fenced evidence.

### Medium: historical Side Chat omitted agent activity

Live streams showed sanitized tool state, but reloading the panel removed that
context entirely.

Resolved by projecting tool name, pending/done state, and duration into history.
Tool arguments and results are explicitly excluded and covered by regression
tests. Summary rows, model identity, response duration, and timestamps are now
projected as well.

### Low: session title updates targeted the browser page title

The `title_update` SSE handler wrote to `pageTitle`, causing the page label to
change while the conversation title remained stale.

Resolved by updating the Side Chat session title and local session cache.

### Medium: Side Chat model selection drifted from Desktop Chat

The extension exposed only a flat model list and persisted only the model ID.
Desktop Chat treats model, supported thinking effort, and Codex response speed
as one composer control, so capability reconciliation and turn behavior could
diverge between the two surfaces.

Resolved with the same model-settings contract: provider-aware searchable
catalog, thinking levels derived from registry metadata, automatic thinking
reconciliation when the model changes, and Standard/Fast turn selection. Model
and thinking are persisted on the canonical session and polled back into the
panel; Fast is carried on each message, matching Desktop Chat.

## Residual risks

- Chromium can suspend the MV3 service worker between 30-second alarms. Relay
  recovery is eventual rather than instantaneous while the Side Panel is closed.
- Tool activity can appear `pending` if a tool call and its result land on
  different history pages. A later page/reload reconciles it; no unsafe output is
  exposed to force eager cross-page joins.
- The control glow surrounds the webpage viewport. Chromium extensions cannot
  draw over native tab-strip or title-bar chrome.
- Full visual parity is intentionally constrained by the Side Panel width and by
  its stricter data-exposure policy. The canonical session and user-visible
  conversation content are shared; raw tool details and reasoning are not.

## Verification

- `node --test tests/webbridge_extension.test.cjs`
- `uv run pytest tests/api/test_webbridge.py -q --no-cov`
- `bun run test:unit -- src/utils/messages.test.ts`
- `bun run typecheck`
- `bun run lint`
