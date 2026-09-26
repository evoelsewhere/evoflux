# Computer App Control

Computer App Control lets an agent drive **one desktop application window** on
Windows or macOS through the `computer_app` tool, while the user watches it in
a floating preview card with a virtual cursor. It is the desktop counterpart of
the persistent in-app browser: the agent works inside one app, never across the
whole desktop, and the user's own mouse, keyboard focus and foreground window
are never taken.

Available in EvoFlux Desktop on Windows and macOS. Off by default. The macOS
backend is described in [macOS](#macos); everything else on this page applies
to both unless it names Windows mechanisms.

## User flow

1. The user enables it in **Settings → Computer App Control**, chooses whether
   each action asks first (**Ask every time**, the default) or runs straight
   away (**Allow without asking**), and may pick allowed and blocked apps. The
   picker lists the apps open now and the installed ones — the Start menu's
   programs on Windows, the Applications folders on macOS — with their icons
   (`app_computer_list_apps`); a name typed there that matches nothing can be
   added as an executable name.
2. In a chat, the agent calls `computer_app` `list_windows`, then `attach` with
   a `window_id`. The backend checks the app against the policy before anything
   attaches; a successful attach opens the session's preview card.
3. The agent observes with `screenshot` (PNG of the window) or `snapshot`/`find`
   (the accessibility tree — UI Automation on Windows, the Accessibility API on
   macOS — with refs such as `e12`), and acts with `click`,
   `hover`, `scroll`, `drag`, `type`, `key`, `invoke` and `set_value`.
4. The card shows the app live (about 6 fps while the agent acts, slower when
   idle), a glowing frame, and a small cursor that travels to each point
   about 200 ms before the input lands there.
5. The user can press **Stop** (revokes control for the chat and interrupts the
   turn), **Allow again**, **Show the app** (brings the real window forward for
   manual takeover) or **Close** (detaches). The agent can only act while an app
   is attached, which is exactly while the card is open.

   Stop and Close also end the action in progress, not only the ones after
   it: every action takes a ticket for its session when it arrives, Stop and a
   detach invalidate it, and long actions check it between steps — each
   character typed, each drag step, wheel notch, repeated key or click, and
   the cursor's approach before any input. A drag that is stopped half-way
   releases the mouse button, a stopped key combo releases its modifiers, an
   attach that was parking the window hands it back, and a window that was
   only made visible for a drag is not hidden again once it was handed back.

A `computer_app` call carries an ordered batch of actions. When one fails,
the rest of the batch is skipped and reported as skipped, because it was
planned on that action working: typing after a refused `attach` would land in
the previously attached app, typing after a failed click wherever focus
happens to be. A `detach` later in the batch still runs, since it only hands
the app back.

The permission prompt lists every action of the call as it will run —
`click e12`, `type "Dear team…" (240 chars) into e5`, `key ctrl+s`, `attach 44`
— so the user approves what is about to be done to the app, not just the
tool's name. A refusal blocks those same actions for the rest of the run; a
different action asks again. A call made only of `status`, `wait` and
`detach` is never prompted, since refusing it would only keep the app parked.

Every call goes through the normal permission service. With **Ask every
time** it prompts in every session permission mode except Bypass — including
Auto, the default, which would otherwise wave it through — the same way
merging a pull request always asks. **Allow without asking** skips the prompt.
Both are checked after the rules, so an explicit deny rule, or an "Always"
the user gave in this session, still wins. It is denied to `trivial` and `simple` tier members.

## How input stays inside the app (Windows)

| Action | Mechanism |
|---|---|
| Capture | `PrintWindow(PW_RENDERFULLCONTENT)`, cropped to the DWM visible frame; works while the app is behind other windows |
| Pointer (`click`, `hover`, `scroll`, `drag`) | `PostMessage` of mouse messages to the deepest child window under the point, in that window's client coordinates |
| Text (`type`) | `WM_CHAR` posted to the app thread's own focus (`GetGUIThreadInfo`), which Windows tracks per thread even in the background |
| Shortcuts (`key`) | posted `WM_KEYDOWN`/`WM_KEYUP` (`WM_SYSKEY*` for Alt); Ctrl/Shift/Alt are held in the app thread's key-state table via `AttachThreadInput` + `SetKeyboardState`, then restored |
| `invoke`, `set_value` | UI Automation patterns (Invoke, Toggle, SelectionItem, ExpandCollapse, LegacyIAccessible, Value) |

Web content (Chromium, Electron, WebView2 — Teams, VS Code, Slack…) needs its
own path, chosen automatically when the window is Chromium (or a WebView2
host class) or a Chromium widget covers at least half of it. A native app that
only hosts a small web pane — an Office add-in or Copilot pane — stays on the
native path, so its keys go to its own focused control. Input always
goes to the Chromium widget (`Chrome_WidgetWin_1`) that handles it: for Edge
or an Electron app that is the top-level window; for a WebView2 app it is a
window of the WebView2 process inside the app's own — new Teams is
`TeamsWebView` → `Chrome_WidgetWin_0` → WebView2's `Chrome_WidgetWin_1` — and
keys sent to the app's host window would never reach the page.

| Action | Web content |
|---|---|
| Read (`snapshot`, `find`) | the page tree lives under the `Chrome_RenderWidgetHostHWND` render host, which is walked as a root of its own; accessibility is activated on attach |
| `click` | UI Automation first — the element's Invoke/Toggle/Select/ExpandCollapse or Chromium's default action — for a ref, and for coordinates via the element under the point in the window's own tree; posted mouse only as a fallback |
| `type`, `set_value` | UIA `SetFocus` on the field (does not activate the window), `ctrl+end` or `ctrl+a`, then characters posted to the Chromium window: the page gets real `beforeinput`/`input` events, which rich editors such as the Teams compose box need. A line break is sent as Shift+Enter so a chat message is not sent. `set_value` with `direct: true` writes through the Value pattern instead (no events). Without a ref, `type` goes to the field last clicked — until focus moves on (a click on anything else, an `invoke`, Tab, Enter, Escape, F6); then it goes wherever the page's focus is |
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

EvoFlux measures everything in physical pixels (it is per-monitor DPI aware),
but Windows gives a DPI-unaware or system-aware app on a scaled display
logical coordinates, and a posted message is not translated on the way. Mouse
messages therefore carry client coordinates scaled by the window's DPI over
its monitor's DPI, and the wheel and hit-test carry screen coordinates
converted with `PhysicalToLogicalPointForPerMonitorDPI`. For per-monitor
aware apps, and on an unscaled display, nothing changes. Not yet verified on a
scaled display: whether `PrintWindow` captures such an app at its physical
size.

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

## macOS

The macOS backend (`desktop/src-tauri/src/computer_app/mac.rs`) keeps the same
commands and result shapes. AppKit only hands keyboard events to the key window
of the active app, so a background app is driven mainly through accessibility,
and posted events are the fallback.

EvoFlux needs two permissions, granted by the user in **System Settings →
Privacy & Security**: **Accessibility**, for the element tree and every action
(macOS shows its prompt on the first `attach`), and **Screen & System Audio
Recording**, for screenshots and the preview card. `list_windows` reports any
that are missing, and the tool tells the agent to ask the user.

**Settings → Computer App Control** shows a **macOS permissions** card with
the state of both (`app_computer_permissions`, re-checked every two seconds
while one is missing and whenever EvoFlux regains focus). **Allow** calls the
system request, which adds EvoFlux to the pane's list, and opens that exact
pane (`x-apple.systempreferences:…?Privacy_Accessibility` /
`?Privacy_ScreenCapture`) through `app_computer_request_permission`. macOS
applies Screen Recording only to a process started after it was granted, so
once it has been requested the card offers **Restart EvoFlux**
(`app_computer_restart`, which releases controlled apps and stops the sidecar
first). These commands are only invoked by the user's clicks, never by the
agent.

| Action | Mechanism |
|---|---|
| List windows | `CGWindowListCopyWindowInfo`, matched to the app's accessibility windows through `_AXUIElementGetWindow`; only normal-level windows the app also reports through accessibility are listed |
| Capture | `CGWindowListCreateImageFromArray` of the window and the app's sheets, alerts and menus above it, at nominal resolution (one screenshot pixel is one point); works while the app is behind other windows |
| Read (`snapshot`, `find`) | the window's `AXUIElement` tree, one `AXUIElementCopyMultipleAttributeValues` round trip per element. `find` also searches the app's menu bar, so menu commands can be invoked by ref |
| `click` | accessibility first: the innermost element under the point (or the ref) with `AXPress`, `AXConfirm`, `AXPick` or `AXOpen`, a disclosable row, or a selectable item; a text field gets `AXFocused`. Otherwise mouse events posted with `CGEventPostToPid`, stamped with the window number so AppKit routes them to that window |
| right-click | `AXShowMenu` on the element, else posted events |
| `type`, `set_value` | `AXSelectedText` replaced in the field (after selecting all for `set_value`), then read back through `AXValue`; if the field did not change, Unicode key events are posted to the app instead. A line break in web content is Shift+Return. `direct: true` writes `AXValue` |
| `key` | a shortcut the app's menu bar carries (`AXMenuItemCmdChar` / `AXMenuItemCmdModifiers`) presses that menu item. Return and Escape use the focused control's `AXConfirm`/`AXCancel` or the window's default and cancel buttons. Anything else is a key event posted to the app |
| `scroll` | wheel events posted to the app; when the scroll area's scroll bar did not move, its `AXValue` is stepped instead |
| `hover`, `drag` | mouse events posted to the app |
| `set_value` on a slider or stepper | `AXValue` as a number, clamped to `AXMinValue`/`AXMaxValue` |

Shortcuts use Command: `cmd+s` is ⌘S on macOS, while elsewhere `cmd` means
Ctrl. Chromium and Electron apps (detected by their framework in the app
bundle) keep their page out of the accessibility tree until asked, so attaching
sets `AXManualAccessibility` and `AXEnhancedUserInterface` and waits for the
web area to fill in. The second is turned off again on release.

**Keep the app off-screen** on macOS moves the window to the bottom-right
corner of the display furthest down and to the right, where only a point of it
shows: macOS does not let a window leave the displays completely. A minimized
window is brought back from the Dock first, since it cannot be captured, and
goes back there on release. An app hidden with ⌘H is shown again without being
activated.

Known limits: a window on another Space is not in the app's accessibility
window list and cannot be attached until the user brings it to the current
desktop. Posted mouse and key events may be ignored by an app in the
background or may bring it forward, which is why they are only the fallback.
Chromium may stop repainting a window it considers covered, so a parked
browser's picture can lag behind; snapshot reads the live state. Run
`cargo test computer_app -- --ignored --nocapture` on a Mac (with the terminal
allowed Accessibility and Screen Recording) for the live TextEdit test, which
types into a document, saves it with ⌘S through the menu bar, and checks the
frontmost app never changed.

## Safety boundaries

- One attached window per chat session; only that window and its same-process
  modal dialogs receive input. A window is controlled from one chat at a time:
  attaching a window another chat holds is refused, and `list_windows` marks
  it `controlled_elsewhere`.
- Never attachable: EvoFlux's own windows, Windows shell and security processes
  (`explorer.exe`, `lsass.exe`, `winlogon.exe`, `consent.exe`, …) and processes
  EvoFlux cannot inspect (typically elevated). On macOS: Finder, Dock,
  WindowServer, loginwindow, SecurityAgent and the other system UI processes,
  plus System Settings, Keychain Access and Passwords — System Settings is where
  apps are granted Accessibility access, so an agent could otherwise grant
  itself more.
- Windows-key shortcuts and Ctrl+Alt+Delete are refused; on macOS so are
  Control+Command+Q (lock), Shift+Command+Q (log out) and Option+Command+Esc
  (Force Quit). The Apple menu is never searched or pressed.
- `settings.yaml` `computer_app`: `enabled`, `permission` (`ask` | `allow`),
  `keep_hidden`, `allowed_apps`, `blocked_apps` (blocklist wins; matching
  ignores case and `.exe`, and uses the executable name — `TextEdit`,
  `MSTeams` — on macOS).
- Stop is enforced natively: the desktop refuses `attach` for that session until
  the user presses Allow again in the card. The agent cannot lift it. If the
  card was closed after Stop, a refused attach opens it again in its stopped
  state, so the user always has the Allow again the agent asks about.
- Every `computer_app` result that reached the app is marked as untrusted app
  content, once for the whole result: not only listings, snapshots and
  screenshots but also action summaries (window and dialog titles, the
  control named in `delivered_to`, notes) and error messages, which can quote
  a window title. Only a batch of nothing but `wait` is left unmarked.

## Architecture

```text
computer_app tool ──► direct_computer_bridge ──WS /api/team/{sid}/computer/agent──►
  chat UI (computerAppBridge.ts) ──invoke app_computer_action──► Tauri computer_app/
                                                                    │
  ComputerAppPipHost ◄── app_computer_frame (JPEG poll) ────────────┤
                     ◄── "computer-app:pointer" events ─────────────┘
```

The chat keeps one bridge WebSocket per session that is on screen or has a
preview card, and the set is kept up to date rather than rebuilt: switching
chats only opens and closes the sockets that changed, and a session that
leaves the set keeps its socket until the commands it already received have
been answered, so a reply is never lost while the desktop still carries the
input out. A command sent while its session's socket is reconnecting waits up
to three seconds for it. Each command goes to the session's own native worker
thread, which owns its
element refs (UI Automation COM objects on Windows, `AXUIElement`s on macOS)
and runs its actions one at a time. A hung app or a slow snapshot therefore
only holds up the chat driving it; the Settings app picker has a worker of its
own, and a worker retires after ten idle minutes once its session has nothing
attached. Preview frames are captured on a separate blocking task so they
never queue behind a long action.

The backend waits 60 s for an action (plus 20 ms per character for `type` and
`set_value`). When it gives up it sends `cancel` over the bridge, and the
desktop interrupts the action (`app_computer_interrupt`, the same interruption
as Stop, without revoking control), so a retry cannot repeat input that was
still being delivered.
`computer_app/mod.rs` holds the Tauri commands and the platform-neutral parts
(key parsing, blocked shortcuts, protected processes, screenshot scaling) and
dispatches to `win.rs` or `mac.rs`.

Primary code: `app/agent/tools/builtin/computer_app_tool.py`,
`app/services/direct_computer_bridge.py`, `app/api/routes/team/computer.py`,
`desktop/src-tauri/src/computer_app/`, `web/src/components/ComputerAppViewer/`,
`web/src/routes/settings.computer-apps.tsx`.

The Windows capture, window listing, UI Automation walk and key names were
ported from the `evo-computer-use` project; its global `SendInput` input path
was deliberately not.
