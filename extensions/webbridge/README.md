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
- **Semantic productivity surfaces** — semantic_snapshot/read/select/write use
  accessibility-first opaque targets, verified rich-text writes, bounded
  spreadsheet ranges/matrices, and PowerPoint text-object probes. Unsupported
  or view-only operations return structured outcomes; writes never silently
  fall back to coordinates.
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

- **Ask EvoFlux about selection** prepares selected text with page provenance.
- **Ask EvoFlux about link** prepares the page and linked URL.
- **Ask EvoFlux about page** prepares the current page title and URL.

Context-menu actions open an editable Side Chat draft; nothing is submitted
until the user reviews the prompt and presses Send. Opening Side Chat
automatically creates the internal EvoFlux run/session for that primary tab when
needed. The tab remains ungrouped until the session opens a second tab. A failed request keeps one
short-lived pending action for idempotent retry. Drafts are stored per tab and
bound to a navigation instance, so leaving and returning to the same URL cannot
revive stale selected context.

One browser session starts with one primary tab. The primary tab owns the
backend binding and default automation target. When a child tab is added,
WebBridge creates one named Chrome group containing both tabs; later child tabs
join that group and reuse the internal session. Users do not choose, grant, or
rebind desktop chat sessions in Side Chat. When the primary tab changes origin,
the session stays attached to its tab ID
while browser tools pause until Side Chat refreshes the new origin scope. URL
query strings and fragments are stripped from P1 browser context, while
selected text remains bounded and is marked as untrusted data in the EvoFlux
transcript.

## P2: Side Panel and live handoff

Click the extension toolbar icon to keep the tab-group session next to the
current page. Side Chat resolves the current session or creates and binds the
active tab automatically without grouping a lone tab. It can:

- Send messages through the normal EvoFlux chat pipeline and select any
  configured, visible model for the next turn.
- Keep one primary tab per session. Tabs opened by the agent, spawned
  subagents, or the Side Chat new-tab action join the same named Chrome tab
  group without stealing the primary binding.
- Load cursor-paginated lead/member transcript history and stream live assistant
  output using fetch-SSE. It renders safe Markdown, authenticated images/files,
  provider fallback/error state, agent attribution, and sanitized tool activity
  while withholding raw tool arguments/output. **Open in EvoFlux** opens the
  full renderer for unsupported rich blocks/widgets.
  Absolute remote Markdown images are not loaded automatically; Side Chat shows
  an explicit load control with a no-referrer request instead.
- Attach readable page text, selection, files, or a user-dragged screen region.
  Browser artifacts carry source/hash/capture provenance, pairing-scoped media
  authorization, configurable retention, and owner-only delete controls.
- Show live `AskUser` batches and typed browser handoffs (`take_over`,
  `confirm_action`, `provide_secret`, `choose_option`). Secret handoff only
  reports completion after the user enters it directly on the page; the value is
  never read.
- Use the crosshair button to highlight and select one element on the page. The next
  Side Panel message includes its sanitized selector, role, accessible name and
  non-form text as untrusted context; input/select/textarea values are never
  read by the picker.
- Use **Take control** to pause agent browser commands on the current tab while
  the user logs in or performs a manual step. **Resume agent** releases this
  live lease. It clears when the tab changes origin, closes, expires, or the
  browser restarts.

Side Panel messages use the pairing-owned internal session bound to the group's
primary tab. Session ownership follows the primary tab ID even on internal pages
such as `chrome://newtab`; page-dependent browser tools remain disabled until
that tab opens an HTTP(S) page, when the same binding is upgraded to the page
origin. **Report issue evidence** is opt-in and collects only a bounded,
redacted ring of console warnings/errors and failed-network metadata; no
headers, request/response bodies, cookies, query strings, or secrets are stored.

## P3: Teach Mode and text watches

Side Chat settings provide two opt-in P3 controls after explicit session
binding:

- **Watch for page text** polls the current HTTP(S) page every 30 seconds for a
  literal phrase. A watch is scoped to that tab's exact origin and path, expires
  after the chosen TTL, and is cancelled when the page changes or tab closes.
  A match only shows a `W` badge and waits; the multi-watch list exposes Send or
  Cancel per watch plus a profile-wide Stop all kill switch. Sending remains a
  separate user gesture. Watch arm/poll/send/cancel mutations are serialized to
  prevent a cancelled watch from being restored or sent concurrently.
- **Teach Mode** records semantic click, fill, select, checkbox/radio, and
  same-origin navigation actions. It does not record raw keystrokes. Passwords
  and fields whose metadata looks secret are represented as parameter names;
  their values are never sent to EvoFlux or written to extension storage.

Stopping Teach Mode saves a pairing-scoped draft and a valid workflow YAML
artifact. Review/approve it in EvoFlux, provide secret parameters there, then
run one supervised step at a time. Values remain runtime-only. Replay remains
subject to tab-binding, origin, domain/sharing policy, capability negotiation,
and bidirectional audit guards. Execution identity, next-step cursor and each
request's idempotent result are durable. A lost browser response is never
replayed automatically: EvoFlux asks the user to confirm whether the step ran
before it can continue.

## Google Docs, Sheets, Excel Online, and PowerPoint Online

Version 2.0 adds AX-first semantic commands and revisioned positive probes for
these app families. Initial support is intentionally bounded:

- Docs: active selection/caret read/replace and visible semantic document read.
- Sheets/Excel: finite A1 range select/read/write (maximum 100 written cells),
  formulas, and accessibility read-back when the editor exposes it.
- PowerPoint: existing slide/text-object discovery and verified text mutation
  when the accessibility tree exposes a stable object.

Canvas/OOPIF surfaces, merged ranges, charts, comments, advanced formatting,
slide creation/layout/media/animation, and cloud-save confirmation may return
`unsupported`; semantic writes never silently fall back to coordinates. Product
claims for a Google/Microsoft tenant require an authenticated smoke with a
dedicated profile:

```bash
uv run python scripts/webbridge_office_smoke.py google-docs <session-id> --read-only
uv run python scripts/webbridge_office_smoke.py google-sheets <session-id>
uv run python scripts/webbridge_office_smoke.py excel-online <session-id>
uv run python scripts/webbridge_office_smoke.py powerpoint-online <session-id>
```

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
    allow_readable_page: true # still requires an explicit user gesture by default
    allow_screenshot: true    # still requires an explicit user gesture by default
    max_artifact_bytes: 5000000
    artifact_retention_hours: 24
  interactions:
    allow_background_triggers: false
    max_per_minute: 30
```

Domain matching is suffix-based, so `example.com` also covers
`app.example.com`. Navigations to a blocked (or non-allowlisted) domain are
refused before anything reaches the browser, and every command or inbound
browser interaction — allowed or refused — is recorded with direction in
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
