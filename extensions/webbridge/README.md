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
3. Click the WebBridge icon in the toolbar to open the popup and configure the
   connection (below).

## Popup configuration

- **Relay URL** — base URL of the EvoFlux backend, default
  `ws://127.0.0.1:8000`. `http(s)://` bases are accepted and normalized to
  `ws(s)://`. The extension appends `/api/team/webbridge/relay` itself.
- **Access token** — required whenever the backend enforces authentication
  (desktop app mode, or a server started with `--key`). Leave empty for a
  local dev backend without a key.

Both fields are saved automatically (persisted in `chrome.storage.local`) and
saving triggers an immediate reconnect.

The popup also shows how many tabs are currently attached to the Chrome
debugger. **Release browser control** detaches all of them without disabling
the relay connection; disconnecting the extension releases them automatically.

### Where to find the token

The token is the same credential the EvoFlux web UI uses:

- **Server started with `--key`** (CLI / self-hosted): the token is that key —
  the same one entered under **Settings → Connection → Access key** in the app.
- **Desktop app** (bundled backend): the token is a per-launch random value the
  shell injects into the app window. It is not displayed in the UI; reveal it
  from the app window's DevTools console with `window.__OAD_TOKEN__`.

If the token is wrong or missing when one is required, the relay closes the
socket with code **4401** and the popup shows **"Auth failed — check the access
token."**

## Security notes

- The access token is required in desktop mode; without a valid `?_token=` the
  relay rejects the connection (close code 4401). The token is stored locally
  in `chrome.storage.local` and sent only to the configured relay URL.
- Commands arrive **only** from the configured relay — point it at your own
  local EvoFlux backend (the default is loopback, `127.0.0.1`). Anyone who can
  reach the relay with a valid token can drive your browser, so keep the
  default loopback binding unless you know what you're doing.
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
policy on top of the token. Configure it under a `webbridge:` block in
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
```

Domain matching is suffix-based, so `example.com` also covers
`app.example.com`. Navigations to a blocked (or non-allowlisted) domain are
refused before anything reaches the browser, and every command — allowed or
refused — is recorded in the audit trail at
`GET /api/team/webbridge/audit`.

## Troubleshooting

- **Extension shows "Connected" but the agent says no extension is connected.**
  The extension and the agent must talk to the *same* relay — check the Relay
  URL in the popup matches the backend the app is using. Also make sure you
  loaded the extension in the same browser profile you're checking from; the
  sidebar status (`WebBridge` item in the app) lists every registered
  extension.
- **"Auth failed — check the access token."** The relay closed the connection
  with 4401. Re-copy the token (see above); note the desktop token changes
  every time the desktop app restarts.
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
node --check extensions/webbridge/popup.js
node --test tests/webbridge_extension.test.cjs
```
