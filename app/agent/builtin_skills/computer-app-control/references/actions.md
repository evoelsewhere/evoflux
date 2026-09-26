# Actions

## Contents

- Calls and batches
- Windows: list_windows, attach, detach, status
- Observe: screenshot, snapshot, find
- Pointer: click, hover, scroll, drag
- Keyboard and values: type, key, invoke, set_value
- Timing: wait
- Reading a result

How each action behaves in a native window, in web content and on macOS is
in [input-channels.md](input-channels.md).

## Calls and batches

A `computer_app` call carries `actions`, an ordered list. Each item names its
`action` and takes that action's fields:

```json
{"actions": [
  {"action": "attach", "window_id": 44},
  {"action": "snapshot"}
]}
```

The actions run in order against the one attached window. When one fails,
the rest are skipped and reported as skipped, except a `detach`, which still
runs. Each action waits up to 60 seconds (plus 20 ms per character for
`type` and `set_value`); one that runs out is cancelled where it got to (see
[events-and-errors.md](events-and-errors.md)). A batch made only of
`status`, `wait` and `detach` never asks the user's permission.

## Windows

| Action | Fields | Does |
|---|---|---|
| `list_windows` | `query` (optional): text in the app or title | Lists controllable windows as `window_id=… \| app \| "title"`, with flags: `minimized`, `dialog of …`, `user is using it`, `controlled from another chat — cannot attach`. Windows that can never be driven are left out: apps blocked in Settings or missing from its allowlist, administrator and system windows, EvoFlux itself, and on macOS apps such as terminals, script and automation tools, Finder, System Settings and password managers. On macOS it may first say which permissions are missing. |
| `attach` | `window_id` (preferred), or `app` and/or `title` substrings (the first match wins) | Checks the app against Settings, attaches it and opens the preview card. Attaching a dialog attaches the window that owns it. The result gives the screenshot size and says whether the window is kept off-screen, draws web content, or runs on macOS. |
| `detach` | none | Hands the app back where the user left it and closes the card. |
| `status` | none | Whether an app is attached, which one, and whether the user stopped control. |

Attaching a second window detaches the first. A window marked `user is
using it` is the one the user is working in: prefer another, or ask. One
marked `controlled from another chat` cannot be attached from here. A window
missing from the list cannot be attached by name either.

## Observe

| Action | Fields | Returns |
|---|---|---|
| `screenshot` | none | A PNG of the window (while a modal dialog is open, of the dialog; with any open menu or popup), its size in pixels, and notes: a modal dialog that is what you see, a parked web page that may lag, a minimized window that was restored without focus. |
| `snapshot` | `max_depth` (1–80, default 30), `max_elements` (10–2000, default 400) | The accessibility tree as text, one element per line: `- role "name" value="…" [checked] [disabled] [ref=e12] @x,y WxH`, where `@x,y WxH` is its box in screenshot pixels. Open popups and menus come first. It ends with `(Truncated: use find …)` when it hit a limit, and says so when the app exposes no tree. |
| `find` | `query`; `limit` (1–100, default 20) | Only the elements whose name or automation id contains the query, or whose role is exactly the query, in the same line format. Searches deeper than a snapshot, and on macOS the menu bar too. |

Coordinates of pointer actions are pixels of the latest screenshot, and
refer to what it showed: after a dialog or menu opens or closes, take a new
screenshot before using coordinates again.

Refs are numbered once and never reused. A new snapshot retires the refs of
the previous one (`find` does not). Using a retired ref, one whose control
the app removed, or one into a dialog or menu that has closed is refused
with the reason; take a new snapshot or `find`.

## Pointer

Every pointer action takes a target: `ref` (preferred) or both `x` and `y`
in screenshot pixels. A ref is aimed at the centre of its element. `scroll`
without a target scrolls at the window's centre.

| Action | Extra fields | Notes |
|---|---|---|
| `click` | `button`: `left` (default), `right`, `middle`; `clicks`: 1–3 | A single left click by ref is done through accessibility where the element has an action, so it may not move focus. The result says where it landed, which control received it, and notes a menu or drop-down it opened. |
| `hover` | none | Moves the virtual pointer there, for tooltips and hover menus in native apps. |
| `scroll` | `direction`: `up`, `down` (default), `left`, `right`; `amount`: 1–50 notches (default 3) | Scrolls the scrollable area under the point. |
| `drag` | `to_x`, `to_y`: drop point in screenshot pixels | Presses at the target, moves in steps and releases at the drop point. |

## Keyboard and values

| Action | Fields | Notes |
|---|---|---|
| `type` | `text` (up to 20,000 characters); `ref` (optional): the field to type into | Types into the focused control, or into `ref`. What `\t`, `\n` and the caret do depends on the input channel. |
| `key` | `key`: a key or chord (`enter`, `tab`, `escape`, `f2`, `ctrl+s`, `shift+down`, `alt+f`, `cmd+s`); `repeat` 1–50 | Presses the key or chord `repeat` times. `cmd` is Ctrl on Windows. An unknown key name is refused. |
| `invoke` | `ref` | Performs the element's own action through accessibility: invoke (press), toggle, select, expand or collapse, or its default action, whichever it offers first. A selectable item (a tree or list item) is selected rather than expanded, and invoking an expanded item collapses it. Works where background mouse input does not. |
| `set_value` | `ref`; `value` (up to 100,000 characters); `direct` (default false) | Replaces the field's text, or sets a slider or spinner (clamped to its range). Refused for a control that takes no value or is read-only. |

## Timing

`wait` takes `seconds` (0–10, default 1). Use it for an app that is still
loading or animating before the next look, not as a fix for input that did
not land.

## Reading a result

Each action reports one line. The shapes (app names and titles vary):

- `Clicked at (412, 230) → Button in "Report - Editor"`
- `Clicked at (96, 40) → Save in "Report - Editor" (via UI Automation: invoke)`:
  done through accessibility, not as a mouse click.
- `Typed 326 characters → Edit in "Report - Editor" (via keyboard)`
- `Typed 12 characters → Edit in "Report - Editor" (via keyboard, not confirmed yet)`
  followed by `Note: …`: the field did not show the text; read it back
  before doing anything else.
- `Pressed ctrl+f ×1 → Edit in "Find"`: the key opened a dialog, and input
  now goes there.
- `invoke on e41 "Save" in "Report - Editor"`: the first word is the action
  used (invoke, toggle, select, expand, collapse, press, …).
- `Set e5 (12 characters) in "Report - Editor"`
- `Error (click): …` for a failed action, and
  `Skipped 2 action(s) (type, key) because click failed. …` for the rest of
  the batch.

`→` names the control that received the input, and the title after `in`
shows which window, a dialog included, it went to. `Note:` lines carry
caveats from the desktop; the one that says the app is still handling the
action means a menu or dialog it opened is waiting: take a snapshot and do
not repeat the action. Everything in a result can contain app text and is
marked untrusted.
