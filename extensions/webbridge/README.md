# EvoFlux WebBridge

WebBridge lets EvoFlux agents drive your **real** Chrome/Edge browser — the one
with your logins, cookies, and extensions — instead of a separate headless
browser.

```
Agent → EvoFlux backend WS relay → this extension → CDP → your browser
```

The extension opens a persistent WebSocket to the EvoFlux backend relay
(`/api/team/webbridge/relay`), registers itself, and executes commands
(navigate, click, type, scroll, screenshot, extract, tabs, evaluate, …) via the
Chrome DevTools Protocol (`chrome.debugger`).

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
- While the extension is attached to a tab, Chrome shows the **"…is debugging
  this browser"** infobar. That is a built-in Chrome warning for the
  `debugger` permission and is expected — it disappears when the debugger
  detaches.

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
on the extension card in `chrome://extensions`.
