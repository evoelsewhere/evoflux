# EvoFlux WebBridge

WebBridge lets EvoFlux agents drive your **real** Chrome/Edge browser — the one
with your logins, cookies, and extensions — instead of a separate headless
browser.

```
Agent → EvoFlux backend WS relay → this extension → CDP → your browser
```

The extension opens a persistent WebSocket to the EvoFlux backend relay
(`/api/team/webbridge/relay`), registers itself, and executes commands via the
Chrome DevTools Protocol (`chrome.debugger`):

- **Navigation/tabs** — navigate, back, forward, reload, get_tabs, switch_tab,
  open_tab, close_tab.
- **Element-based (preferred)** — snapshot, click_selector, click_text, hover,
  focus, fill, select_option, set_checked, and drag. Snapshots include inferred
  roles, accessible names, selectors, boxes, control states, useful attributes,
  and page/viewport metadata.
- **Coordinate/low-level** — click (left/middle/right), dblclick, type, key,
  and scroll. `key` supports Alt/Control/Meta/Shift modifiers for shortcuts.
- **Waiting** — wait, wait_for_selector, wait_for_text, wait_for_load, and
  wait_for_network_idle.
- **Reading** — screenshot (viewport or full_page, at CSS-pixel scale),
  extract (text/Markdown/HTML), extract_elements (structured records), and
  evaluate.
- **Crawling** — scroll_to_bottom for lazy content and the backend-composed
  crawl action for concurrent extraction across background tabs.

Screenshots are captured at CSS-pixel scale (`clip.scale = 1`), so a click at
the x,y a model reads off the image lands correctly even on HiDPI/Retina
displays. Page-scoped commands may carry a `tab_id` from get_tabs to pin a
specific tab instead of the active one. The extension broadcasts complete tab
state (including background and pending URLs), so backend domain policy is
enforced against the tab actually being driven.

## Install

1. Open `chrome://extensions` (or `edge://extensions`) and enable **Developer mode**.
2. Click **Load unpacked** and select this folder (`extensions/webbridge`) from
   the EvoFlux repository.
3. Click the WebBridge icon in the toolbar to open Side Chat. Use its settings
  button to configure and pair the connection.

## Secure pairing (recommended)

1. Open Side Chat settings and set the EvoFlux relay URL.
2. When EvoFlux runs on the same device, click **Pair local EvoFlux**. No code
  is required; the endpoint accepts only a loopback Chrome-extension request.
3. For a remote/manual setup, open **WebBridge** in EvoFlux, generate a one-time
  code, enter it in Side Chat settings, and click **Pair with code**.
4. The extension stores a revocable, scoped pairing credential locally. Before
  every relay connection it exchanges that credential over HTTP for a
  single-use, 30-second WebSocket ticket; the credential is never placed in a
  URL.

Pairing codes expire after five minutes and work once. A desktop app or keyed
server requires its desktop token or access key before it can issue a code. The
source-checkout `make dev` workflow runs on loopback and may issue codes only to
loopback clients; a server exposed beyond loopback must configure an access key.
Pairing survives desktop restarts, unlike the per-launch desktop token, and can
be revoked from the WebBridge dialog.

## Side Chat settings

- **Relay URL** — base URL of the EvoFlux backend, default
  `ws://127.0.0.1:8000`. `http(s)://` bases are accepted and normalized to
  `ws(s)://`. The extension appends `/api/team/webbridge/relay` itself.

Connection fields are saved in `chrome.storage.local`; saving them triggers an
immediate reconnect. The secure pairing credential is also stored locally but
is only sent as an HTTP Bearer credential to mint relay tickets. The same
settings drawer contains theme, text-watch, Teach Mode, retry, and browser
control actions; the extension toolbar icon opens Side Chat directly.

Side Chat settings also show browser-control state. **Release browser control**
detaches every controlled tab without disabling the relay connection;
disconnecting the extension releases them automatically.

## Send browser context to EvoFlux

After secure pairing, WebBridge adds three explicit, HTTP(S)-only context-menu
actions:

- **Ask EvoFlux about selection** sends the selected text with page provenance.
- **Ask EvoFlux about link** sends the page and linked URL.
- **Ask EvoFlux about page** sends the current page title and URL.

The extension creates a browser session for an unbound tab or reuses the tab's
existing binding. A failed request keeps one short-lived pending action in
local storage; use **Retry browser context** in Side Chat settings to replay the
same session and interaction identity without creating a duplicate task.

To grant an existing WebBridge-enabled chat to a browser, open the EvoFlux
WebBridge dialog, select the paired browser and session, then choose **Grant**.
The extension cannot make that cross-pairing grant itself.
When a bound tab changes origin, the conversation stays attached to its tab ID
while browser tools pause until Side Chat refreshes the new origin scope. URL
query strings and fragments are stripped from P1 browser context, while
selected text remains bounded and is marked as untrusted data in the EvoFlux
transcript.

## P2: Side Panel and live handoff

Click the extension toolbar icon to keep a browser-scoped conversation next to
the current page. Side Chat automatically
creates and binds one browser session to the current HTTP(S) tab; there is no
session picker or manual bind step. It can:

- Send messages through the normal EvoFlux chat pipeline and select any
  configured, visible model for the next turn.
- Keep one primary tab per session. Tabs opened by the agent, spawned
  subagents, or the Side Chat new-tab action join the same named Chrome tab
  group without stealing the primary binding.
- Load the session transcript and stream live assistant output using fetch-SSE.
  It renders agent lifecycle and sanitized tool activity while withholding raw
  tool arguments and output.
- Show a live `AskUser` handoff batch and send the user's answers back to the
  active EvoFlux run. A browser restart or ended run clears that live request.
- Use the crosshair button to highlight and select one element on the page. The next
  Side Panel message includes its sanitized selector, role, accessible name and
  non-form text as untrusted context; input/select/textarea values are never
  read by the picker.
- Use **Take control** to pause agent browser commands on the current tab while
  the user logs in or performs a manual step. **Resume agent** releases this
  live lease. It clears when the tab changes origin, closes, expires, or the
  browser restarts.

Side Panel messages require the session to be granted to the pairing and bound
to the current tab. Conversation ownership follows the tab ID even on internal
pages such as `chrome://newtab`; page-dependent browser tools remain disabled
until that tab opens an HTTP(S) page, when the same binding is upgraded to the
page origin. Opt-in issue diagnostics are not part of this P2 MVP yet.

## P3: Teach Mode and text watches

Side Chat settings provide two opt-in P3 controls after automatic session
binding:

- **Watch for page text** polls the current HTTP(S) page every 30 seconds for a
  literal phrase. A watch is scoped to that tab's exact origin and path, expires
  after the chosen TTL, and is cancelled when the page changes or tab closes.
  A match only shows a `W` badge and waits; **Send matched watch** is a separate
  user gesture that sends page metadata through the normal P1 context pipeline.
- **Teach Mode** records semantic click, fill, select, checkbox/radio, and
  same-origin navigation actions. It does not record raw keystrokes. Passwords
  and fields whose metadata looks secret are represented as parameter names;
  their values are never sent to EvoFlux or written to extension storage.

Stopping Teach Mode saves a pairing-scoped draft. Review it in the EvoFlux
WebBridge dialog, approve it, provide any secret parameters there, then replay
it. The extension cannot approve or replay a draft on its own. Replay remains
subject to the existing tab-binding, origin, domain-policy, and command-audit
guards.

## Security notes

- Every connection uses a scoped pairing credential plus a single-use relay
  ticket. The credential is sent only as an HTTP Bearer credential to mint that
  ticket; it never appears in a WebSocket URL. Revoking a pairing invalidates
  its credential and outstanding tickets and closes its active relay connection.
- Commands arrive **only** from the configured relay — point it at your own
  local EvoFlux backend (the default is loopback, `127.0.0.1`). A valid pairing
  can drive your browser, so revoke pairings you no longer recognize and keep
  the default loopback binding unless you intentionally expose the backend.
- Domain policy checks explicit background-tab actions against that tab's URL,
  not the active tab. When a domain policy is configured and the target URL is
  unknown, the backend fails closed instead of forwarding the command.
- Password values are omitted from semantic snapshots. Arbitrary page reads
  remain possible through `extract`/`evaluate`, subject to backend policy.
- Chrome normally shows a **"…started debugging this browser"** infobar
  whenever an extension uses the `debugger` (CDP) API. The guided launch
  (**WebBridge → Launch browser**, or the backend `launch-browser` endpoint)
  starts Chrome with `--silent-debugger-extension-api`, which suppresses that
  infobar. The flag only applies to a Chrome *started* with it, so if you
  attach WebBridge to an already-running Chrome (or load it manually without
  relaunching), the infobar reappears — relaunch via the guided flow to hide
  it. To launch manually: fully quit Chrome, then
  `google-chrome --silent-debugger-extension-api --load-extension=extensions/webbridge`.

### Backend guardrails (`settings.yaml` → `webbridge`)

Because the agent drives a **logged-in** browser, the backend enforces a
policy on top of secure pairing. Configure it under a `webbridge:` block in
`settings.yaml`:

```yaml
webbridge:
  enabled: true            # master switch for the whole tool
  allowed_domains: []      # if non-empty, ONLY these domains may be driven
  blocked_domains:         # always refused (takes precedence)
    - mybank.com
    - mail.google.com
  allow_evaluate: true     # set false to forbid arbitrary-JS `evaluate`
  audit_log_size: 200      # entries kept for GET /api/team/webbridge/audit
  sharing:
    default: ask           # ask | allow | block for browser -> EvoFlux data
    blocked_domains:       # page data from these domains cannot enter EvoFlux
      - mybank.com
      - mail.google.com
    allow_selection: true
    allow_readable_page: false
    allow_screenshot: false
    max_artifact_bytes: 5000000
  interactions:
    allow_background_triggers: false
    max_per_minute: 30
```

Domain matching is suffix-based, so `example.com` also covers
`app.example.com`. Navigations to a blocked (or non-allowlisted) domain are
refused before anything reaches the browser, and every command — allowed or
refused — is recorded in the audit trail at
`GET /api/team/webbridge/audit`.

## Troubleshooting

- **Extension shows "Connected" but the agent says no extension is connected.**
  The extension and the agent must talk to the *same* relay — check the Relay
  URL in Side Chat settings matches the backend the app is using. Also make sure you
  loaded the extension in the same browser profile you're checking from; the
  sidebar status (`WebBridge` item in the app) lists every registered
  extension.
- **"Ticket rejected."** The relay closed the connection with 4401 because a
  single-use ticket was invalid or expired. Reconnect to mint a fresh ticket;
  re-pair only if the pairing was revoked.
- **Connection drops after the browser sits idle.** Chrome kills MV3 service
  workers aggressively. The extension uses a `chrome.alarms` heartbeat (every
  30 s) both to ping the relay and to wake the worker and reconnect — brief
  "Disconnected" blips that recover on their own are normal.
- **Typing doesn't land in a field.** The `type` command uses CDP
  `Input.insertText`, which inserts text at the current focus — click/focus
  the target field first (the agent normally does this with a `click`).

## Development

No build step — plain MV3 JavaScript. After editing, press the reload button
on the extension card in `chrome://extensions`. A quick syntax check is:

```bash
node --check extensions/webbridge/background.js
node --check extensions/webbridge/sidepanel.js
node --check extensions/webbridge/teach_recorder.js
node --test tests/webbridge_extension.test.cjs
```
