# Events and errors

## Contents

- What the user sees and can do
- Permission prompts
- Events during a turn
- Errors and what to do
- Setup: Settings and macOS permissions

Every failed action comes back as `Error (<action>): <message>`. Messages
are quoted below as they start.

## What the user sees and can do

While an app is attached, a preview card floats over the conversation. It
shows the app live, with a glowing frame and a virtual cursor that travels
to each point just before the input lands. Its controls:

| Control | Effect on you |
|---|---|
| **Stop app control** | Revokes control for this chat and interrupts your turn. The action running at that moment ends with `Interrupted: the user stopped…`; nothing after it runs. Until the user presses **Allow again**, `attach` is refused. |
| **Allow again** (on the card after a Stop) | Lifts the Stop. It does not attach anything: attach again in a later turn if the user wants you to continue. |
| **Close and end app control** | Detaches the app. Later actions fail with `No app is attached`, and `attach` is refused for the rest of the turn. |
| **Show the app** | Brings the real window into view for the user. The app stays attached, but the user may now be working in it: stop and ask before driving it further. |
| **Show larger / smaller**, drag, resize | Only change the card. |

With "Keep the app off-screen" on in Settings (the default), the app is
parked out of sight while attached. It keeps running, and detach, Stop,
Close and the end of the turn put it back where it was (a maximized window
may come back minimized, ready to restore maximized).

## Permission prompts

Settings decide whether each call asks first (**Ask every time**, the
default) or runs straight away (**Allow without asking**). A prompt shows up
to 12 of the call's actions as they will run (`click e12`, `type "Dear
team…" (240 chars) into e5`, `key ctrl+s`); `wait` is not shown. Plan calls
the user can approve at a glance: one purpose per call, no surprises inside
it. Calls made only of `status`, `wait` and `detach` never ask; a call that
only looks (`list_windows`, `screenshot`, `snapshot`, `find`) still does.

A refusal comes back as `The user rejected permission request …`, and the
same call sent again as `The user already refused this exact 'computer_app'
call…`. Do not retry it or reach the same effect another way: stop and ask
the user how to proceed.

## Events during a turn

| Event | What you see | What to do |
|---|---|---|
| The user pressed Stop | The running action: `Interrupted: the user stopped Computer App Control (or the action was cancelled)…`; your turn is interrupted | Nothing more this turn. Next turn, say where you got to and ask whether to continue; an `attach` before they allow it again says `The user stopped Computer App Control in this chat…`. |
| The user closed the card | `No app is attached…`; `attach` says `The user closed the app preview during this turn…` | Do not attach again this turn, even though the error suggests it. Finish without the app, or ask. |
| The app was blocked in Settings after you attached it | `… is blocked in Settings …` or `… is not in the … allowlist. The setting changed after it was attached, so it was handed back.` | Leave it. Tell the user the change stopped the work. |
| The user is typing in the same app (Windows) | `The user is typing or clicking in this app right now…` | Wait and retry, or use `invoke` by ref, which needs no held keys. |
| The app window was closed | `The attached window (…) was closed…` | Do not reattach on your own: the user may have closed it on purpose. Ask. |
| A modal dialog opened | Results name the dialog's window; screenshots show the dialog and say so | Work in the dialog, or close it with Escape or Cancel before going back. |
| A menu or drop-down opened | A click result notes it; the next snapshot lists it first | Pick the item by ref, or press Escape to close it. |
| The app is busy with what you sent | `Note: The app is still handling this…` | Take a snapshot to see the menu or dialog it opened. Do not repeat the action. |
| The turn ended | The app is detached automatically | Attach again in the next turn if the task continues. |

## Errors and what to do

| Error | Cause | Next step |
|---|---|---|
| `Computer App Control is turned off.` | Disabled in Settings | Ask the user to enable it in Settings → Computer App Control. |
| `Computer App Control needs this chat open in EvoFlux Desktop…` / `Open this chat in EvoFlux Desktop…` | The chat is open in a browser, or not the chat on screen in EvoFlux Desktop | Ask the user to open this chat in EvoFlux Desktop on Windows or macOS. |
| `Desktop app control disconnected` / `reconnected` | The chat's connection to the desktop dropped mid-action | Look at the app before sending the action again. |
| `This EvoFlux Desktop does not support '…'` | The desktop app is older than the backend | Ask the user to update EvoFlux Desktop; use other actions meanwhile. |
| `App control command timed out after …` | The action ran out of time; the desktop stopped it where it was | Read back what already happened before sending anything again; split long `type` text into parts. |
| `No app is attached.` | Nothing attached, detached, or the card was closed | `list_windows`, then `attach`, unless the user closed the card this turn. |
| `No controllable window matches.` | The id is stale, or the app is never listed (blocked or protected) | `list_windows` again; a window that is not listed cannot be attached. |
| `"…" is already controlled from another chat.` | Another chat has it | Pick another window or ask the user. |
| `Unknown ref …` / `… no longer exists…` / `… has closed…` | A newer snapshot retired the ref, the app replaced the control, or its dialog or menu closed | Take a snapshot or `find`, and use a ref from it. |
| `… is waiting on the dialog …` (Windows) | A ref behind an open modal dialog | Deal with the dialog first. |
| `(x, y) is outside the … screenshot` | Coordinates from an older or different-sized screenshot | Take a screenshot and use its pixels. |
| `That point is on the window's frame or title bar…` (Windows) | The point is not content | Use a shortcut or `invoke` for window-level commands. |
| `… is not visible on screen; try invoke instead.` | The ref's element has no position (scrolled out, collapsed) | `invoke` it, or scroll it into view first. |
| `… has no invoke/toggle/select/expand action` / `… refused the action` | The element offers no accessibility action, or the app declined it | Click it by ref or coordinates, or use its keyboard shortcut. |
| `… does not accept a value…` / `… is read-only` | `set_value` on a control without a writable value | Click it and `type`, or leave it. |
| `Unknown key name …` | A key name the tool does not know | Use names such as `enter`, `pagedown`, `f2`, `ctrl+shift+s`. |
| `Refused <key>: …` | A system shortcut | Do not retry; there is no in-app equivalent to send. |
| `The app is not responding.` | The app is hung or busy | `wait`, then look again; tell the user if it stays hung. |
| `Windows blocked input to this app…` | The app runs as administrator | Tell the user; it cannot be driven from a normal EvoFlux. |
| `Windows would not let EvoFlux hold Ctrl/Shift/Alt…` | The shortcut could not be delivered with its modifiers | `find` the command and `invoke` it. |
| `That window is not reachable through accessibility…` / `… did not answer through accessibility just now…` (macOS) | The window is on another Space, full screen or busy | Try again in a moment, or ask the user to bring it to this desktop. |
| `Skipped N action(s) … because <action> failed.` | An earlier action in the batch failed | Look at the app, then send the remaining steps again. |

Apps that read raw input (many games), some UWP surfaces and administrator
apps ignore background mouse and keyboard input; accessibility actions
(`invoke`, `set_value`) are the way in when they expose the control.

## Setup: Settings and macOS permissions

- Settings → Computer App Control holds the on switch (saved with Save), the
  permission mode, "Keep the app off-screen", and the allow and block lists
  (the block list wins). Some team members are not given the tool at all.
- macOS: EvoFlux needs Accessibility permission to read and drive apps, and
  Screen Recording permission for screenshots and the preview (`snapshot`,
  `find`, `invoke` and `set_value` work without it). When `list_windows`
  reports either as missing, ask the user to allow EvoFlux in System
  Settings → Privacy & Security; Settings → Computer App Control in EvoFlux
  has an Allow button for each, and Screen Recording takes effect after
  EvoFlux restarts.
