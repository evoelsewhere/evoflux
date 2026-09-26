# Events and errors

## Contents

- What the user sees and can do
- Permission prompts
- Events during a turn
- Errors and what to do
- macOS

## What the user sees and can do

While an app is attached, a preview card in the chat shows it live, with a
glowing frame and a virtual cursor that travels to each point just before
the input lands. The card has four controls:

| Control | Effect on you |
|---|---|
| **Stop** | Revokes control for this chat and interrupts the turn. Every later action fails until the user presses **Allow again**. |
| **Allow again** | Lifts a Stop. |
| **Show the app** | Brings the real window forward and hands it to the user for good. |
| **Close** | Detaches the app. `attach` is refused for the rest of the turn. |

The app may be parked off-screen while it is attached; it keeps running and
keeps its taskbar button. Detach, Stop, Close and the end of the turn put it
back where it was.

## Permission prompts

Settings decide whether each call asks first (**Ask every time**, the
default) or runs straight away (**Allow without asking**). A prompt lists
every action of the call as it will run (`click e12`, `type "Dear team…" (240
chars) into e5`, `key ctrl+s`), so plan calls the user can approve at a
glance: one purpose per call, no surprises inside it. A refusal blocks those
same actions for the rest of the run; ask the user rather than rephrasing
the call to get around it. Calls made only of `status`, `wait` and `detach`
never ask.

## Events during a turn

| Event | What you see | What to do |
|---|---|---|
| The user pressed Stop | `The user stopped Computer App Control in this chat…` | Stop driving the app. Say where you got to and ask whether to continue. |
| The user closed the card | `The user closed the app preview during this turn…` | Do not attach again this turn. Finish without the app, or ask. |
| The app was blocked in Settings after you attached it | `… is blocked in Settings …` or `… is not in the … allowlist. The setting changed after it was attached, so it was handed back.` | Leave it. Tell the user the change stopped the work. |
| The user is typing in the same app | `The user is typing or clicking in this app right now…` | Wait and retry, or use `invoke` by ref, which needs no held keys. |
| A modal dialog opened | Results name the dialog's window; screenshots say a dialog is open | Work in the dialog, or close it with Escape or Cancel before going back. |
| A menu or drop-down opened | The next snapshot lists it first; a click that opened one says so | Pick the item by ref, or press Escape to close it. |
| The turn ended | The app is detached automatically | Attach again in the next turn if the task continues. |

## Errors and what to do

| Error | Cause | Next step |
|---|---|---|
| `Computer App Control is turned off.` | Disabled in Settings | Ask the user to enable it in Settings → Computer App Control. |
| `Computer App Control needs this chat open in EvoFlux Desktop…` | The chat is open in a browser, not the desktop app | Ask the user to open the chat in EvoFlux Desktop on Windows or macOS. |
| `No app is attached.` | Nothing attached, or it was detached | `list_windows`, then `attach`. |
| `No controllable window matches.` | The window closed or the id is stale | `list_windows` again. |
| `Unknown ref …` | A newer snapshot retired it, or the control is gone | Take a snapshot or find and use a ref from it. |
| `… waiting on the dialog …` / `… has closed …` | A ref behind an open modal dialog, or into a dialog that closed | Snapshot again and use refs from the window that is in front now. |
| `That point is on the window's frame or title bar…` | The point is not content | Use a shortcut or `invoke` for window-level commands. |
| `… is not visible on screen; try invoke instead.` | The ref's element has no position (scrolled out, collapsed) | `invoke` it, or scroll it into view first. |
| `Refused <key>: …` | A system shortcut | Do not retry; there is no in-app equivalent to send. |
| `Windows blocked input to this app…` | The app runs as administrator | Tell the user; it cannot be driven from a normal EvoFlux. |
| `Windows would not let EvoFlux hold Ctrl/Shift/Alt…` | The shortcut could not be delivered with its modifiers | `find` the command and `invoke` it. |
| `Skipped N action(s) … because <action> failed.` | An earlier action in the batch failed | Look at the app, then send the remaining steps again. |

Apps that read raw input (many games), UWP surfaces and administrator apps
ignore background mouse and keyboard input; accessibility actions (`invoke`,
`set_value`) are the way in when they expose the control.

## macOS

- Shortcuts use `cmd` (`cmd+s`, `cmd+a`), not `ctrl`.
- `find` also searches the app's menu bar, so any menu command can be
  invoked by ref.
- EvoFlux needs Accessibility and Screen Recording permission. When
  `list_windows` reports either as missing, ask the user to allow EvoFlux in
  System Settings → Privacy & Security; Settings → Computer App Control in
  EvoFlux has an Allow button for each, and Screen Recording takes effect
  after EvoFlux restarts.
