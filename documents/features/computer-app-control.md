# Computer App Control

Computer App Control lets an agent drive **one desktop application window** on
Windows through the `computer_app` tool, while the user watches it in a
floating preview card with a virtual cursor. It is the desktop counterpart of
the persistent in-app browser: the agent works inside one app, never across the
whole desktop, and the user's own mouse, keyboard focus and foreground window
are never taken.

Available in EvoFlux Desktop on Windows only. Off by default.

## User flow

1. The user enables it in **Settings → Computer App Control**, chooses whether
   each action asks first (**Ask every time**, the default) or runs straight
   away (**Allow without asking**), and may pick allowed and blocked apps. The
   picker lists the apps open now and the Start menu's programs with their
   icons (`app_computer_list_apps`); a name typed there that matches nothing
   can be added as an executable name.
2. In a chat, the agent calls `computer_app` `list_windows`, then `attach` with
   a `window_id`. The backend checks the app against the policy before anything
   attaches; a successful attach opens the session's preview card.
3. The agent observes with `screenshot` (PNG of the window) or `snapshot`/`find`
   (the UI Automation tree, with refs such as `e12`), and acts with `click`,
   `hover`, `scroll`, `drag`, `type`, `key`, `invoke` and `set_value`.
4. The card shows the app live (about 6 fps while the agent acts, slower when
   idle), a glowing frame, and a small cursor that travels to each point
   about 200 ms before the input lands there.
5. The user can press **Stop** (revokes control for the chat and interrupts the
   turn), **Allow again**, **Show the app** (brings the real window forward for
   manual takeover) or **Close** (detaches). The agent can only act while an app
   is attached, which is exactly while the card is open.

Every call goes through the normal permission service. With **Ask every
time** it prompts in every session permission mode except Bypass — including
Auto, the default, which would otherwise wave it through — the same way
merging a pull request always asks. **Allow without asking** skips the prompt.
Both are checked after the rules, so an explicit deny rule, or an "Always"
the user gave in this session, still wins. It is denied to `trivial` and `simple` tier members.

## How input stays inside the app

| Action | Mechanism |
|---|---|
| Capture | `PrintWindow(PW_RENDERFULLCONTENT)`, cropped to the DWM visible frame; works while the app is behind other windows |
| Pointer (`click`, `hover`, `scroll`, `drag`) | `PostMessage` of mouse messages to the deepest child window under the point, in that window's client coordinates |
| Text (`type`) | `WM_CHAR` posted to the app thread's own focus (`GetGUIThreadInfo`), which Windows tracks per thread even in the background |
| Shortcuts (`key`) | posted `WM_KEYDOWN`/`WM_KEYUP` (`WM_SYSKEY*` for Alt); Ctrl/Shift/Alt are held in the app thread's key-state table via `AttachThreadInput` + `SetKeyboardState`, then restored |
| `invoke`, `set_value` | UI Automation patterns (Invoke, Toggle, SelectionItem, ExpandCollapse, LegacyIAccessible, Value) |

Web content (Chromium, Electron, WebView2 — Teams, VS Code, Slack…) needs its
own path, chosen automatically when the window hosts Chromium. Input always
goes to the Chromium widget (`Chrome_WidgetWin_1`) that handles it: for Edge
or an Electron app that is the top-level window; for a WebView2 app it is a
window of the WebView2 process inside the app's own — new Teams is
`TeamsWebView` → `Chrome_WidgetWin_0` → WebView2's `Chrome_WidgetWin_1` — and
keys sent to the app's host window would never reach the page.

| Action | Web content |
|---|---|
| Read (`snapshot`, `find`) | the page tree lives under the `Chrome_RenderWidgetHostHWND` render host, which is walked as a root of its own; accessibility is activated on attach |
| `click` | UI Automation first — the element's Invoke/Toggle/Select/ExpandCollapse or Chromium's default action — for a ref, and for coordinates via the element under the point in the window's own tree; posted mouse only as a fallback |
| `type`, `set_value` | UIA `SetFocus` on the field (does not activate the window), `ctrl+end` or `ctrl+a`, then characters posted to the Chromium window: the page gets real `beforeinput`/`input` events, which rich editors such as the Teams compose box need. A line break is sent as Shift+Enter so a chat message is not sent. `set_value` with `direct: true` writes through the Value pattern instead (no events) |
| `key` | posted to the top-level Chromium window, which routes it to the focused element |
| `hover`, double-click, right-click | mouse messages posted to the top-level Chromium window (its render-host child only serves accessibility) |
| `scroll` | UIA `ScrollPattern` on the nearest scrollable element under the point: Chromium sends posted wheel messages to whatever window is under the user's real cursor |
| `drag` | posted mouse. A Chromium top-level window (Edge, Electron) that is parked or completely covered paints no frames, and Chromium then drops every pointer move; for the gesture only it is put at the top of the z-order but fully transparent and click-through, so it paints while the user sees and clicks straight through it, then its style, z-order and position are restored. A WebView2 control keeps painting when hidden and needs none of this |
| `set_value` on a slider | UIA `RangeValue` |

Before typing, the widget is told it has focus (a posted `WM_SETFOCUS`; the
system's focus does not move) and a lone Shift press wakes its input
pipeline: a window that was never activated otherwise dropped the first keys
it got.

Measured with live tests on a page parked off-screen, both in Edge
(`probes_chromium_*`) and in a WebView2 host laid out like Teams
(`probes_webview2_*`), plus a drag in a page completely covered by another
window (`drags_in_a_covered_page`): inputs, textareas and `contenteditable`
editors receive the text with input events; hover, double-click, right-click,
scroll, a pointer-driven drag and a slider all reach the page; the user's
foreground window does not change.

Nothing calls `SendInput`, `SetCursorPos` or `SetForegroundWindow` for the
agent. A minimized app is restored with `SW_SHOWNOACTIVATE`; a window disabled
by a modal dialog is transparently replaced by that dialog for capture and
input. Coordinates are always pixels of the latest screenshot of the attached
window; windows larger than 1568 px on their long edge are scaled down and
mapped back.

### Keeping the app off-screen

With **Keep the app off-screen** (on by default), attaching moves the window
just outside the virtual desktop: it keeps running and keeps its taskbar
button, but does not cover the user's work. Its exact placement is saved and
restored on detach, Stop, closing the card, the end of the agent's turn, or
EvoFlux exiting. A window that was minimized or maximized comes back minimized
(restoring to maximized) rather than being activated behind the user's back.
If the user brings it back from the taskbar while it is controlled, the next
action parks it again; **Show the app** in the card hands it back for good.

Edge and Electron apps have one catch: Chromium stops repainting and stops
updating its accessibility values while its own window is hidden. Input still
arrives, but the card's picture, screenshots and snapshot values can lag
behind the real page until the window is visible again. WebView2 apps (Teams)
keep both live. Accessibility is activated before parking, because Chromium
will not start exposing a page that is already off-screen.

Limits: posted input does not reach apps that read raw input (many games),
UWP/CoreWindow surfaces or apps running as administrator (UIPI). Points on the
window frame or title bar are refused. For those, UI Automation actions are the
fallback.

## Safety boundaries

- One attached window per chat session; only that window and its same-process
  modal dialogs receive input.
- Never attachable: EvoFlux's own windows, Windows shell and security processes
  (`explorer.exe`, `lsass.exe`, `winlogon.exe`, `consent.exe`, …) and processes
  EvoFlux cannot inspect (typically elevated).
- Windows-key shortcuts and Ctrl+Alt+Delete are refused.
- `settings.yaml` `computer_app`: `enabled`, `permission` (`ask` | `allow`),
  `keep_hidden`, `allowed_apps`, `blocked_apps` (blocklist wins; matching
  ignores case and `.exe`).
- Stop is enforced natively: the desktop refuses `attach` for that session until
  the user presses Allow again in the card. The agent cannot lift it.
- Window titles, accessibility labels and screenshots are marked as untrusted
  app content in tool results.

## Architecture

```text
computer_app tool ──► direct_computer_bridge ──WS /api/team/{sid}/computer/agent──►
  chat UI (computerAppBridge.ts) ──invoke app_computer_action──► Tauri computer_app/
                                                                    │
  ComputerAppPipHost ◄── app_computer_frame (JPEG poll) ────────────┤
                     ◄── "computer-app:pointer" events ─────────────┘
```

The chat keeps one bridge WebSocket per open session in the Windows desktop app
and relays each command to a native worker thread that owns the UI Automation
COM objects and element refs. Preview frames are captured on a separate
blocking task so they never queue behind a long action.

Primary code: `app/agent/tools/builtin/computer_app_tool.py`,
`app/services/direct_computer_bridge.py`, `app/api/routes/team/computer.py`,
`desktop/src-tauri/src/computer_app/`, `web/src/components/ComputerAppViewer/`,
`web/src/routes/settings.computer-apps.tsx`.

The Windows capture, window listing, UI Automation walk and key names were
ported from the `evo-computer-use` project; its global `SendInput` input path
was deliberately not.
