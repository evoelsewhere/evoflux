# Browser and WebBridge

EvoFlux has two browser integrations with different trust and lifecycle
boundaries: a persistent browser owned by the desktop application, and
WebBridge for the user's existing Chrome/Edge profile.

## Persistent in-app browser

The Browser workbench opens a desktop-owned browser surface whose profile can
persist across sessions. A session presence channel lets the backend ask the UI
to mount an agent-owned floating browser preview; the workbench remains under
the user's control. Multiple agent previews can stay open at once and stack
with the newest preview on top. A separate WebSocket carries versioned command
requests and responses. Commands are serialized per visible browser connection
and fail pending requests when the panel reconnects or closes.

The built-in browser policy can independently allow/block domains and control
JavaScript evaluation, storage, cookie-value access, HTTP requests, clipboard,
uploads, downloads and agent acceptance of browser permission prompts. The
agent must have the Browser panel available; the backend cannot create an
invisible desktop browser session.

Primary code: `app/services/direct_browser_bridge.py`, team browser routes,
`BrowserViewer/` and Tauri desktop browser commands.

### Dev-server launcher

In Coding mode the browser's new-tab page lists the workspace's `launch.json`
configurations instead of a blank page: each row shows its port and starts,
opens or stops that dev server. Rows are joined with live port state, so a
server already listening — started by the agent's `preview` tool, or outside
EvoFlux entirely — shows as running and opens rather than starting a second
copy. A server tracked under a name that is no longer configured still gets a
row. Startup failures are shown with the captured log tail.

The launcher and the `preview` tool share one registry and one config file, so
neither side spawns a second server on a port the other owns. Its React content
sits in the viewport the native WebView covers, and is only visible while that
view is hidden — the same arrangement the browser settings view uses.

Primary code: `app/api/routes/team/preview.py`,
`app/agent/tools/builtin/preview.py` (`launch_targets`, `start_launch_target`),
`BrowserViewer/BrowserLauncher.tsx`.

## WebBridge

WebBridge connects EvoFlux to the user's real logged-in Chrome/Edge session
through the independently distributed `evo-webbridge` extension.

```text
agent tool / browser side panel
        ↕
FastAPI WebBridge routes and manager
        ↕ policy-checked WebSocket relay
Chrome/Edge extension
        ↕ CDP
real browser tabs
```

Implemented capabilities include:

- native discovery and scoped pairing;
- one-time relay tickets and persistent extension connections;
- explicit browser selection per EvoFlux chat when multiple paired browsers are
  connected; the selected connection remains pinned for later tool calls;
- session/model management and full agent chat in the browser side panel;
- tab-to-session binding without stealing focus;
- page navigation, semantic read/write/select and bounded browser actions;
- intentional selection/page/screenshot sharing with provenance;
- questions, permissions, plan review, attachments, queues and live SSE in the
  browser panel;
- interaction ingestion, Teach drafts, approval, replay and step resolution;
- appearance synchronization, status and audit views.

Agent-facing behavior of the `webbridge` tool:

- The model receives the full tool guide (ref-first work, chaining actions in
  one call, `snapshot {diff: true}`, background tabs, crawl recipes).
- `navigate`, `back`, `forward` and `reload` wait for the page to load and
  report the address reached (including a redirect), its title and whether
  the load timed out. When one of them ends a call, a compact snapshot (first
  40 interactive elements) of the new page is returned with it.
- Coding sessions drive the pointer without the human-paced glide the
  extension draws for Work sessions; one `mouseMoved` still reaches the
  target, so hover state and the on-page cursor are unchanged.
- A batched run of clicks, fills and keys stays on the session's bound tab and
  its origin pin, like each of those actions sent alone.
- In a WebBridge session, `preview start` points the agent at
  `webbridge open_tab` instead of the excluded `browser_use`.
- Debugging actions read a per-tab devtools log the extension keeps from CDP
  events: `console` (every level, uncaught exceptions and browser log entries,
  with source location and stack), `network` (method, status, resource type,
  timing, failures, redirect hops), `network_body` (a recorded response body,
  up to 100k chars) and `debug_summary` (the current page's errors, warnings
  and failed requests in one call). Reads default to the current page; `scope:
  "all"` includes earlier pages of the tab. The log keeps the newest 300
  console entries and 300 requests per tab and survives navigation.
- Coding sessions start that log with their first command. Work sessions start
  it only on the first console/network read, because `Runtime.enable` is
  visible to page scripts on the everyday sites a Work session drives. A read
  that started recording, or a navigation away from a page the debugger cannot
  record, says so and suggests a reload.
- Console text and URLs keep paths, query parameter names and identifiers;
  credential-shaped values (Bearer tokens, JWTs, cookies, secret-named query
  parameters and JSON keys) are redacted before they leave the extension.
  Results are marked untrusted browser content.
- `inspect` reports one element's box, computed styles (a layout/visibility
  set, or the properties asked for), attributes and — in development builds —
  the component chain that rendered it with source locations: React
  `_debugSource` (≤18) or owner stacks (19), Vue `__file`, Svelte
  `__svelte_meta`, and source-locator plugin data attributes.
- `mock` answers or fails requests matching a URL glob (optionally one
  method), with a status, body, headers, delay and hit limit, through CDP
  `Fetch` interception scoped to the tab; `emulate` applies network presets
  (offline, slow/fast 3G, fast 4G), CPU slowdown, geolocation, time zone and
  locale; `performance` reports navigation timing, FCP/LCP/CLS, the slowest
  interaction and resources, and heap/DOM/layout counters.
- `storage` and `cookies` list keys and cookie names/flags. Values, writes and
  `mock add` are gated by `webbridge.allow_evaluate`, since each is as strong
  as running script in the page; HttpOnly cookie values are returned only on
  loopback pages.
- In Coding sessions console stacks, uncaught-exception locations and React 19
  owner-stack locations from `inspect` are mapped through the scripts' source
  maps (inline `data:` or fetched, cached per map) back to the original files,
  and marked `(source-mapped)`. The extension enables CDP `Debugger` only to
  learn which script carries which map, with every pause skipped so a
  `debugger;` statement cannot stall the page. Work sessions never enable it.
- `upload_file` puts files into an `<input type=file>` through
  `DOM.setFileInputFiles`; paths must resolve inside the session's workspace
  roots or its uploads.

## Policy and trust

The manager enforces allow/block domain suffix policies, can disable arbitrary
`evaluate`, binds sessions to extensions/tabs, correlates every request ID and
records a bounded audit trail. Content read from a page is untrusted input.

Sharing policy is separate from control policy. It decides whether selection,
readable page or screenshots are allowed/asked/blocked and caps artifact size
and retention. Background interactions are disabled unless enabled and are
rate-limited. Sensitive fields and raw keystrokes are excluded from Teach
capture; drafts require review before approval/replay.

Revoking a pairing closes its live relay and invalidates outstanding tickets.
Stale extensions are reaped and pending requests fail explicitly. The extension
source, installation and release lifecycle are outside this repository.

## Interfaces and persistence

WebBridge owns pairings, browser-panel sessions, queued messages, attachments,
tab bindings, interactions, Teach drafts/replays and relay state. Durable rows
use WebBridge SQLModel tables; live socket/request correlation stays in memory.

Routes live below `/api/team/webbridge`, including HTTP, SSE and two WebSocket
relays. The `webbridge` agent tool calls the same manager directly inside the
sidecar and still passes normal tool permission checks.

## Source and tests

Primary code: `app/api/routes/team/webbridge.py`, `app/models/webbridge.py`,
`app/services/webbridge_*`, `app/agent/tools/builtin/webbridge_tool.py`, desktop
native messaging and WebBridge UI components.

Focused tests cover manager policy/routing, pairing/artifact/appearance
services, route and WebSocket behavior, direct browser bridging, UI status and a
cross-repository Office/browser smoke harness.
