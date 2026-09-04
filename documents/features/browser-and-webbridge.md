# Browser and WebBridge

EvoFlux has two browser integrations with different trust and lifecycle
boundaries: a persistent browser owned by the desktop application, and
WebBridge for the user's existing Chrome/Edge profile.

## Persistent in-app browser

The Browser workbench opens a desktop-owned browser surface whose profile can
persist across sessions. A session presence channel lets the backend ask the UI
to mount the browser; a separate WebSocket carries versioned command requests
and responses. Commands are serialized per visible browser connection and fail
pending requests when the panel reconnects or closes.

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
- session/model management and full agent chat in the browser side panel;
- tab-to-session binding without stealing focus;
- page navigation, semantic read/write/select and bounded browser actions;
- intentional selection/page/screenshot sharing with provenance;
- questions, permissions, plan review, attachments, queues and live SSE in the
  browser panel;
- interaction ingestion, Teach drafts, approval, replay and step resolution;
- appearance synchronization, status and audit views.

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
