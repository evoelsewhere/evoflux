# Actions

## Contents

- Calls and batches
- Windows: list_windows, attach, detach, status
- Observe: screenshot, snapshot, find
- Pointer: click, hover, scroll, drag
- Keyboard and values: type, key, invoke, set_value
- Timing: wait
- Reading a result

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
runs. A batch made only of `status`, `wait` and `detach` never asks the
user's permission.

## Windows

| Action | Fields | Does |
|---|---|---|
| `list_windows` | `query` (optional): text in the app or title | Lists controllable windows as `window_id=… \| app \| "title"`, with flags: `minimized`, `dialog of …`, `user is using it`, `controlled from another chat — cannot attach`. Apps blocked in Settings are left out. |
| `attach` | `window_id` (preferred), or `app` and/or `title` substrings | Checks the app against the allow and block lists, then attaches it and opens the preview card. The app may be moved off-screen while you work. The result gives the screenshot size and says whether the window draws web content or runs on macOS. |
| `detach` | none | Hands the app back where the user left it and closes the card. |
| `status` | none | Whether an app is attached, which one, and whether the user stopped control. |

Attaching a second window detaches the first. A window marked `user is
using it` is the one the user is working in: prefer another, or ask. One
marked `controlled from another chat` cannot be attached from here.

## Observe

| Action | Fields | Returns |
|---|---|---|
| `screenshot` | none | A PNG of the window (with any open menu or popup), its size in pixels, and notes: a modal dialog that is what you see, a hidden web page that may lag, a minimized window that was restored without focus. Coordinates of pointer actions are pixels of the latest screenshot. |
| `snapshot` | `max_depth` (1–80, default 30), `max_elements` (10–2000, default 400) | The accessibility tree as text: role, name, value and state of each element, each with a ref such as `e12`. Open popups and menus come first. |
| `find` | `query`: text in a control's name, automation id or role; `limit` (1–100, default 20) | Only the matching elements, with refs. Cheaper than a snapshot when you know what you are looking for. |

Refs are numbered once and never reused. A new snapshot retires the refs of
the previous one; a retired ref, or one whose control the app destroyed, is
reported as unknown. Each ref also remembers its window, so a ref into a
dialog that has closed, or into the main window while a modal dialog is
open, is refused with the reason.

## Pointer

Every pointer action takes a target: `ref` (preferred) or both `x` and `y`
in screenshot pixels. A ref is aimed at the centre of its element.

| Action | Extra fields | Notes |
|---|---|---|
| `click` | `button`: `left` (default), `right`, `middle`; `clicks`: 1–3 | `clicks: 2` double-clicks. In web content a click by ref uses the element's own action where it has one. The result says where the click landed and which control received it. |
| `hover` | none | Moves the virtual cursor there and delivers the hover, for tooltips and hover menus. |
| `scroll` | `direction`: `up`, `down` (default), `left`, `right`; `amount`: 1–50 notches (default 3) | Scrolls the scrollable area under the point. |
| `drag` | `to_x`, `to_y`: drop point in screenshot pixels | Presses at the target, moves in steps and releases at the drop point. For moving objects inside the window; a file drop between apps follows the real cursor instead. |

Points on the window frame or title bar are refused: background control only
reaches the content.

## Keyboard and values

| Action | Fields | Notes |
|---|---|---|
| `type` | `text` (up to 20,000 characters); `ref` (optional): click this field first | Types into the focused control. `\t` and `\n` are real Tab and Enter presses (Shift+Enter in web content), and typing waits for each to be taken in, so one `type` can fill a form or a table. When the field reports its text the result says `confirmed`; a miss is reported with a note and never retyped. |
| `key` | `key`: a key or chord (`enter`, `tab`, `escape`, `f2`, `ctrl+s`, `shift+down`, `alt+f`, `cmd+s`); `repeat` 1–50 | Returns once the app has taken the key in, so the next action finds the focus where the key put it, including a dialog it opened. Modifiers are held only for the app. Windows-key shortcuts, Ctrl+Alt+Delete and the macOS log-out, lock and Force Quit chords are refused. |
| `invoke` | `ref` | Presses a button, toggles a check box, selects a tab, radio button or list item, or expands a combo box or tree item through accessibility. The result names the pattern used. Works where background mouse input does not. |
| `set_value` | `ref`; `value` (up to 100,000 characters); `direct` (default false) | Replaces the field's text. In native apps it writes through accessibility (the Value pattern). In web content it focuses the field and types, so the page sees real input events; `direct: true` writes through accessibility there too, for a field typing did not reach, though rich editors may ignore it. On a slider or spinner it sets the number. |

## Timing

`wait` takes `seconds` (0–10, default 1). Use it for an app that is still
loading or animating before the next look, not as a fix for input that did
not land.

## Reading a result

Each action reports one line, for example:

- `Clicked at (412, 230) → Button in "Q3 Sales.xlsx - Excel"`
- `Typed 326 characters → EXCEL7 in "Q3 Sales.xlsx - Excel" (via keyboard)`
- `invoke on e41 "Save" (via UI Automation: Invoke)`
- `Pressed ctrl+g ×1 → RichEdit20W in "Go To"`: the key opened a dialog.

`→` names the control that received the input, and the window title after
`in` shows which window, a dialog included, it went to. `Note:` lines carry
caveats from the desktop. Everything in a result can contain app text and is
marked untrusted.
