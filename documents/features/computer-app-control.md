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
   attaches; a successful attach opens the session's preview card. While an
   allow or block list is set, every `computer_app` call that reads or drives
   the app checks the attached app again (one `status` round trip), so an app
   blocked in Settings mid-run is handed back rather than driven on.
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
   is attached, which is exactly while the card is open. Close also tells the
   backend (`POST /api/team/{sid}/computer/closed`), which refuses `attach`
   until the turn ends, so the agent cannot reopen the card the user just
   closed; the next turn may attach again. The desktop keeps an
   app attached across a reload of the UI, so each window keeps its open cards
   in sessionStorage (`oa.computer-app.open-cards`) and reopens, after a
   reload, those whose session the desktop still has attached or stopped.

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
| Text (`type`) | `WM_CHAR` posted to the app thread's own focus (`GetGUIThreadInfo`), which Windows tracks per thread even in the background. A line break or a tab is a real Enter or Tab key press instead, since dialogs, WPF, Qt and Java act on the key-down (the default button, focus moving on); an edit control still gets its character when the app translates the key. A field that reports its text (UI Automation Value, not a password, under 200,000 characters) is read before and after: `confirmed` says whether the text arrived as typed, and a miss is reported, never retyped, since the letters may be there out of order. After every Enter or Tab, and after the first character that follows one, typing waits until the app has taken the input in (`WM_NULL` round trips to its thread, plus 60 ms after the key, since Excel drops characters while it recalculates a committed cell yet still answers sent messages) and looks the focus up again: a grid such as Excel's moves to the next cell on the key and opens an editor for it on the first character, and characters posted to the window focused before were lost — a table typed in one go arrived with letters and whole cells missing (`types_across_cells_that_open_their_own_editor`) |
| Shortcuts (`key`) | posted `WM_KEYDOWN`/`WM_KEYUP` (`WM_SYSKEY*` for Alt combos, F10 and Alt on its own, the keys that open a menu bar); Ctrl/Shift/Alt are held in the app thread's key-state table via `AttachThreadInput` + `SetKeyboardState`, then restored. When Windows refuses to share the key state, the shortcut is not sent and the agent is told to invoke the command instead. When the app is the one the user is working in, that table is also the real keyboard's, so held keys would turn the user's own "s" into Ctrl+S: holding waits for 400 ms without user input (up to three seconds, then the action is refused with the reason); drags, which hold a mouse button the same way, wait too. Key names include the letters, digits, F1–F24, `numpad0`–`numpad9`, and `alt`, `ctrl` or `shift` alone. The action returns once the app has taken the key in (the same `WM_NULL` round trips), so the next action finds the focus where the key put it: text typed after a shortcut that opens a dialog (Excel's Ctrl+G) goes into the dialog instead of landing before it opens |
| `invoke`, `set_value` | UI Automation patterns (Invoke, Toggle, SelectionItem, ExpandCollapse, LegacyIAccessible, Value). A Win32 or WinForms push button gets a posted `BM_CLICK` instead of Invoke: WinForms clicks synchronously, so Invoke on a button that opens a modal dialog did not return, and blocked every other UI Automation call into the app, until the dialog closed. Other actions run on a thread of their own; one still running after 1.5 seconds is reported as delivered, with a note to take a snapshot rather than repeat it |
| Refs | Numbered once and never reused, so a ref from an earlier snapshot is unknown rather than naming whichever control got its number next. Each remembers the window it was listed in; a ref into the main window while a modal dialog is open, or into a dialog or menu since closed, is refused with the reason, and so is one whose control the app destroyed (`refuses_refs_behind_a_modal_dialog`) |

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
| `click` | UI Automation first — the element's Invoke/Toggle/Select/ExpandCollapse or Chromium's default action — for a ref, and for coordinates via the element under the point in the window's own tree; posted mouse only as a fallback. The element under a point is the end of the deepest chain of elements containing it, every containing child explored; among equally deep chains the later sibling wins, because it is drawn on top (`clicks_the_element_drawn_on_top`) |
| `type`, `set_value` | the field focused inside the page through MSAA (`accSelect` with `SELFLAG_TAKEFOCUS`; UIA `SetFocus` only when the window is in front already), `ctrl+end` or `ctrl+a`, then characters posted to the Chromium window: the page gets real `beforeinput`/`input` events, which rich editors such as the Teams compose box need. A line break is sent as Shift+Enter so a chat message is not sent. `set_value` with `direct: true` writes through the Value pattern instead (no events). Without a ref, `type` goes to the field last clicked — until focus moves on (a click on anything else, an `invoke`, Tab, Enter, Escape, F6); then it goes wherever the page's focus is |
| `key` | posted to the top-level Chromium window, which routes it to the focused element |
| `hover`, double-click, right-click | mouse messages posted to the top-level Chromium window (its render-host child only serves accessibility) |
| `scroll` | IAccessible2 `scrollToPoint` on the first child of the nearest scrollable element under the point, moved by the distance to scroll (about 100 px a notch): posted wheels are rerouted by Chromium to the window under the point, and a hidden Edge page ignores them. UIA `ScrollPattern` only where IAccessible2 cannot be reached |
| `drag` | posted mouse. A Chromium top-level window (Edge, Electron) that is parked or completely covered paints no frames, and Chromium then drops every pointer move; for the gesture only it is put at the top of the z-order but fully transparent and click-through, so it paints while the user sees and clicks straight through it, then its style, z-order and position are restored. A window that was layered already gets its own opacity or colour key back; one drawn with `UpdateLayeredWindow`, which has none to read, is left alone and the gesture goes ahead without it. A WebView2 control keeps painting when hidden and needs none of this |
| `set_value` on a slider | MSAA `put_accValue` (LegacyIAccessible), UIA `RangeValue` if refused |

Chromium carries out UI Automation's SetFocus, Invoke, Expand, Scroll and
RangeValue by focusing its own widget, and focusing it activates the window:
whenever Windows allowed it (a few minutes without user input), acting on a
page took the foreground from the user's window. So in web content a button,
link or drop-down is clicked through its MSAA default action (the pattern's
action if refused), fields, sliders and scrolling go through MSAA and
IAccessible2 as above, and before any action the page's widgets, an open
popup's included, are told they have focus (a posted `WM_SETFOCUS`), which
keeps a posted mouse press from focusing them. An option of an open `<select>`
list is picked with the keys a person would press (Down or Up from the option
now chosen, then Enter, which Chromium passes on to the open list): its
default action does not pick it, and Invoke still activated the window now and
then. The probes check the
user's foreground window keeps the foreground; the WebView2 host they use
never focuses itself, so that check always runs.

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

### Menus and dropdowns

Context menus (`#32768`), combo box lists (`ComboLBox`), WPF popups and
Chromium `<select>` lists are top-level windows of their own. While one of the
attached window's popups is open (same process, or owned by the window), it
counts as part of the window: the screenshot and the preview cover the window
and its popups together (the coordinate space grows to their union), a click
inside a popup goes to the popup, and snapshot and find walk the popups first.
A parked app's popup opens on the user's screen, because Windows keeps menus
on a monitor; it is moved next to the window, where the agent last clicked,
and a click that opens one says so in its result. Tooltips are left out.
Checked live with a `<select>` in Edge (`works_in_a_select_popup`).

### Keeping the app off-screen

With **Keep the app off-screen** (on by default), attaching moves the window
just outside the virtual desktop: it keeps running and keeps its taskbar
button, but does not cover the user's work. Its exact placement is saved and
restored on detach, Stop, closing the card, the end of the agent's turn, or
EvoFlux exiting. The end of a turn is seen by the backend for every session
(a listener on the stream store's `mark_done`), which detaches through the
session's bridge socket, open while its card is; the chat UI's own release
covered only the chat on screen. A window that was minimized or maximized comes back minimized
(restoring to maximized) rather than being activated behind the user's back.
If the user brings it back from the taskbar while it is controlled, the next
action parks it again; **Show the app** in the card hands it back for good.
Moving another app's window waits for that app, so on Windows Stop, **Show
the app** and exit move it from a thread of their own: a hung app cannot
freeze EvoFlux, and holds up exit for at most three seconds. On Windows every
parked window is also recorded in `computer_app_parked.json` in EvoFlux's
local data folder, and taken out once it is back: if EvoFlux crashed, was
killed, or timed out on a hung app at exit, the next start puts back each
recorded window that is still open, still the same process's and still
off-screen (`puts_back_a_window_parked_by_a_run_that_crashed`).

Dialogs are top-level windows of their own, and Windows (and WinForms)
keeps them on a monitor, so a parked app's dialogs used to open on the
user's screen. On Windows a `EVENT_OBJECT_SHOW` hook moves any captioned
window a parked window owns (a dialog, one opened from a dialog, a tool
window) over its parked owner as it is shown; the next action also parks
one that got past it. When the window is handed back, its open dialogs are
centred back over it, so the user never faces an app blocked by a dialog
they cannot see (`keeps_a_parked_apps_dialogs_off_screen`).

Edge and Electron apps have one catch: Chromium stops repainting and stops
updating its accessibility values while its own window is hidden. Input still
arrives, but the card's picture, screenshots and snapshot values can lag
behind the real page until the window is visible again. WebView2 apps (Teams)
keep both live. Accessibility is activated before parking, because Chromium
will not start exposing a page that is already off-screen. A Chromium window
that opened completely covered has no render host at all (Chromium keeps its
page hidden, and only rechecks whether a window shows when it moves), so its
page had no tree whatever was asked of it: attaching then puts the window above
everything for a moment, fully transparent and click-through, nudges it by a
pixel, waits for the render host, and puts place, z-order and style back.

Limits: posted input does not reach apps that read raw input (many games),
UWP/CoreWindow surfaces or apps running as administrator (UIPI). Points on the
window frame or title bar are refused. For those, UI Automation actions are the
fallback. OLE drag and drop (`DoDragDrop`: files onto a window, text between
apps) follows the real cursor, not posted mouse messages, so such a drop can
land where the user's pointer is. Progressive web apps installed from Edge all
run as `msedge.exe`, so the allow and block lists cannot tell them apart from
each other or from Edge.

Store (UWP) apps: every one's window belongs to `ApplicationFrameHost.exe`, so
by that name allowing Calculator in Settings would allow Settings too. A
Store app's window is named after the process behind its CoreWindow instead
(`CalculatorApp.exe`, `SystemSettings.exe`), in `list_windows`, the policy
check and the app picker (`names_store_apps_by_their_own_process`). A
minimized Store app takes its CoreWindow out of the frame, so it cannot be
identified: it is left out of `list_windows` and the picker, and attaching it
is refused until the user restores it.

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
applies Screen Recording only to a process started after it was granted, and
reports it as missing until then, so while it is missing the card offers
**Restart EvoFlux**, however it was allowed (macOS's own prompt, System
Settings directly, or **Allow** here)
(`app_computer_restart`, which releases controlled apps and stops the sidecar
first). These commands are only invoked by the user's clicks, never by the
agent.

| Action | Mechanism |
|---|---|
| List windows | `CGWindowListCopyWindowInfo`, matched to the app's accessibility windows through `_AXUIElementGetWindow`; only normal-level windows the app also reports through accessibility are listed |
| Capture | `CGWindowListCreateImageFromArray` of the window and, above it, the app's menus, popovers and panels (above the normal window level) and its own sheets (matched by their accessibility frame) — not another document window of the app that overlaps it — at nominal resolution (one screenshot pixel is one point); works while the app is behind other windows |
| Read (`snapshot`, `find`) | the window's `AXUIElement` tree, one `AXUIElementCopyMultipleAttributeValues` round trip per element, plus one for `AXValue` where a line shows it (text, check boxes, sliders, pop-ups). A text over 1,000 characters (a Terminal's scrollback, an Xcode file) is read only as its first 200 characters through `AXStringForRange`, never whole. `find` also searches the app's menu bar, so menu commands can be invoked by ref |
| `click` | accessibility first: the innermost element under the point (or the ref) with `AXPress`, `AXConfirm`, `AXPick` or `AXOpen`, a disclosable row, or a selectable item; a text field gets `AXFocused`, and a click at a point (not on a ref) also puts the caret under it (`AXRangeForPosition`, then `AXSelectedTextRange`). Otherwise mouse events posted with `CGEventPostToPid`, stamped with the window number so AppKit routes them to that window. A pop-up or menu button answers `AXPress` (and anything answers `AXShowMenu`) only when its menu closes, and a button running a modal dialog only when the dialog is dismissed: a timeout from an app that still answers right after is reported as delivered with a note to take a snapshot, and menu openers get a 0.5 s timeout. An open menu is walked by `snapshot` and `find` wherever it is drawn, and a context menu (the app's, not the window's) is walked first |
| right-click | `AXShowMenu` on the element, else posted events |
| `type`, `set_value` | `AXSelectedText` replaced in the field (after selecting all for `set_value`), then read back through `AXValue`; if the field did not change, Unicode key events are posted to the app instead. A line break in web content is Shift+Return. `direct: true` writes `AXValue` |
| `key` | a shortcut the app's menu bar carries (`AXMenuItemCmdChar` / `AXMenuItemCmdModifiers`) presses that menu item; a special key (⌘⌫, ⌘←, ⌘Return, F-keys) is matched by its function-key character, `AXMenuItemCmdGlyph` or `AXMenuItemCmdVirtualKey`. A menu command acts on the app's main window, so the attached window is made main first (`AXMain`, which does not activate the app); an app that will not switch while it has another window is refused, rather than ⌘S saving another document. Return and Escape use the focused control's `AXConfirm`/`AXCancel` or the window's default and cancel buttons. Anything else is a key event posted to the app |
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

A window the window server still lists but accessibility cannot reach for a
moment (the app busy past the two-second messaging timeout, full screen,
another Space) keeps its session: the action fails with "try again", instead
of the session being dropped with the window still parked. Only a window that
is gone ends the session. Release asks three times; a window still out of
reach is put back by a background retry every two seconds for two minutes.
While a Chromium app's `AXEnhancedUserInterface` is on, macOS animates
accessibility moves and may drop them, so putting a window back (release,
**Show the app**) turns it off first, checks the window arrived (asking once
more if not), and turns it on again only while the app is still driven.

Known limits: a window on another Space is not in the app's accessibility
window list and cannot be attached until the user brings it to the current
desktop. Posted mouse and key events may be ignored by an app in the
background or may bring it forward, which is why they are only the fallback.
Chromium may stop repainting a window it considers covered, so a parked
browser's picture can lag behind; snapshot reads the live state.

Not yet handled, and to be checked on a Mac:

- The Open and Save panels of a sandboxed app run in a process of their own
  (`com.apple.appkit.xpc.openAndSavePanelService`), so they are neither
  captured with the app nor reachable through its accessibility tree.
- Posted key events are typed through the active input method and keyboard
  layout: Telex or Pinyin may rewrite them, and key codes assume a US layout,
  so a shortcut posted as keys (not through the menu bar) can press another
  key on AZERTY or other layouts. Text inserted through accessibility is not
  affected.
- Enter posted to a background web app (Slack, Teams, VS Code) may not send,
  since AppKit delivers keys only to the key window.
- Capture uses `CGWindowListCreateImage`, deprecated since macOS 14; on
  macOS 15 it can bring back the Screen Recording prompt periodically.
  ScreenCaptureKit is the replacement.

Run `cargo test computer_app -- --ignored --nocapture` on a Mac (with the terminal
allowed Accessibility and Screen Recording) for the live TextEdit test, which
types into a document, saves it with ⌘S through the menu bar while a second
document opened later is TextEdit's main window, and checks the frontmost app
never changed.

## Safety boundaries

- One attached window per chat session; only that window and its same-process
  modal dialogs receive input. A window is controlled from one chat at a time:
  attaching a window another chat holds is refused, and `list_windows` marks
  it `controlled_elsewhere`.
- Never attachable: EvoFlux's own windows, Windows shell and security processes
  (`explorer.exe`, `lsass.exe`, `winlogon.exe`, `consent.exe`, …), processes
  EvoFlux cannot inspect, and processes running at a higher integrity level
  than EvoFlux (elevated or system; also when their token cannot be read):
  Windows' UIPI drops input posted to them, so they are refused at attach and
  left out of `list_windows` instead of silently ignoring every action. On macOS: Finder, Dock,
  WindowServer, loginwindow, SecurityAgent and the other system UI processes,
  plus System Settings, Keychain Access and Passwords — System Settings is where
  apps are granted Accessibility access, so an agent could otherwise grant
  itself more. Also on macOS, apps that run commands or scripts: Terminal,
  iTerm2, Alacritty, kitty, WezTerm, Ghostty, Hyper, Script Editor, Shortcuts
  and Automator. Typing into one runs anything, with that app's permissions
  (a terminal often has Full Disk Access) and outside every EvoFlux sandbox.
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
to three seconds for it. When a second EvoFlux window opens the same session,
the newest socket wins and the older one is closed with code 4409; that window
does not reconnect on its own (the two would take the session from each other
in a loop) but takes it back when the user returns to it (window focus, or it
becomes visible). Each command goes to the session's own native worker
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
