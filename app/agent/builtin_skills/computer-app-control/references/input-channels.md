# Input channels

## Contents

- Which channel a window uses
- Typing
- Clicks and the pointer
- Keys
- Setting a value
- Reading the window
- Refusals and safety nets
- A window kept off-screen

## Which channel a window uses

The attach result tells you. A window that draws web content (browsers,
Electron and WebView2 apps, and web panes inside native apps) takes input
through the page; any other window on Windows is native; everything on
macOS goes through its Accessibility API and events posted to the app. The
same action differs between the three, and a guide's advice about Tab,
Enter or the caret holds only where this page says so.

## Typing

| | Native (Windows) | Web content (Windows) | macOS |
|---|---|---|---|
| Where the text goes | The control that has the app's keyboard focus, at its caret | The field given as `type`'s `ref`, else the field last clicked or invoked by ref, else the page's focused element; the tool presses Ctrl+End first, so the text goes **after everything already in the field** | Inserted at the caret of the focused element |
| `\n` | A real Enter press | Shift+Enter, so a chat message is not sent | A line break in the same field (Shift+Return in web content) |
| `\t` | A real Tab press: moves to the next field or cell | A tab character; focus does not move | A tab character in the same field |
| Pace | Waits after every Enter or Tab until the app has taken it in, and follows the focus to the next cell or field | A few milliseconds per character, no waiting | Whole text at once, or in short bursts |
| One `type` can fill | A whole form or table | One field | One field |
| Check | When the field reports its text and the text has no `\t`: a miss shows `not confirmed yet` with a note, and is never retyped | Read back automatically; a field that did not change at all is typed into once more | As native |

So only a native window on Windows fills several fields or cells from one
`type`. Elsewhere, fill one field per step: click or invoke it by ref, type
(or `set_value`), read it back, move on.

A result line without `not confirmed yet` is not proof: a field that does
not report its text cannot be checked, and a note says so. Read it back
yourself.

## Clicks and the pointer

- **A single left click by ref** is performed through accessibility first,
  in every channel: the element's invoke, toggle, select or expand action,
  or its default action. The result then ends with `(via UI Automation: …)`
  or `(via accessibility: …)`. No mouse click happened, so the caret and
  keyboard focus may not move; on a text field the tool only remembers it
  for the next `type` (`focus_for_typing`), or places the caret there on
  macOS.
- **A single left click by coordinates** is a posted mouse click in a native
  window. In web content, and on macOS, the element at that point is tried
  through accessibility first.
- **Right, double and triple clicks** are posted mouse clicks on Windows,
  which web content often ignores; on macOS a right click opens the
  element's menu through accessibility. Prefer `invoke`, or the command's
  keyboard shortcut.
- **Hover** only moves the virtual pointer over the point; web content may
  not react, so a hover menu may not open. Look for the same command in a
  menu or by name.
- **Scroll** acts on the scrollable area under the ref or point, or at the
  window's centre when none is given. In web content it scrolls the nearest
  scrollable container of the ref.
- **Drag** presses at the start, moves in steps and releases at the drop
  point, as posted mouse input. It moves things inside the window; a file
  drop between apps follows the real cursor instead.

## Keys

- **Native (Windows):** posted to the focused control. `key` returns once
  the app has taken the key in, so the next action finds the focus where the
  key put it, including a dialog it opened. Modifiers are held for the app
  only; this can fail while the user is typing in the same app, or when
  Windows will not let EvoFlux hold them.
- **Web content (Windows):** sent to the page, which acts on its own focused
  element. That is not necessarily the field last clicked by ref; click or
  invoke the field before keys that edit it (select all, delete).
- **macOS:** a shortcut that some menu item carries runs through the app's
  menu bar, which works in the background. Other keys (Tab, arrows, Delete,
  function keys, shortcuts on no menu) are posted events that a background
  app may ignore; check their effect. Enter and Escape confirm or cancel the
  focused element, or press the default or cancel button of a sheet or
  dialog: read the dialog before pressing Enter.
- `cmd` means Ctrl on Windows and Command on macOS; on macOS `ctrl` is the
  Control key. `option`/`opt` and `command`/`meta` are accepted names.

## Setting a value

| | Native (Windows) | Web content (Windows) | macOS |
|---|---|---|---|
| `set_value` | Writes through accessibility (the Value pattern); the page or app sees no key events | Focuses the field, selects all and types, so the page sees real input; line breaks become Shift+Enter | Selects all and inserts the text; falls back to select-all and keystrokes if the field did not change |
| `direct: true` | Same as above | Writes through accessibility, for a field typing did not reach; rich editors may ignore it | Writes the element's value directly |

On a slider or spinner the number is clamped to the control's range. A
control that takes no value, or is read-only, is refused. Read the field
back: a written value is not always what the app keeps.

## Reading the window

- `snapshot` lists open menus and popups first. On macOS it leaves the menu
  bar out; `find` searches the menu bar, so any menu command can be invoked
  by ref there.
- Elements outside the window (scrolled out of view) are skipped and get no
  ref. Scroll, then look again.
- Values are shown for text fields, combo boxes, documents, sliders and
  spinners, cut at 200 characters; names are cut at 120. Many grids expose
  no cell values at all. A long text cannot be read back from
  a snapshot in full: read it in the app (scroll, its own find or word
  count) or from screenshots.

## Refusals and safety nets

- **Windows** refuses points on the window frame or title bar, and refs
  into a window that is waiting on a modal dialog, or into a dialog or menu
  that has closed.
- **macOS** does neither: a point near the top of the window can press its
  close or minimize button, and a ref can act on a window behind an open
  sheet. Keep to refs and points inside the content, and snapshot again
  after a sheet opens.
- Blocked everywhere: Windows-key shortcuts, Ctrl+Alt+Delete, and the macOS
  log-out, lock and Force Quit chords. Closing and quitting keys are **not**
  blocked; the ground rules forbid them.

## A window kept off-screen

When "Keep the app off-screen" is on in Settings (the default), the attached
window is parked where the user does not see it: off-screen on Windows,
tucked into a screen corner on macOS. It keeps running and keeps its
taskbar or Dock button, and a window the user drags back is parked again at
the next action. Everything above still works, with one difference: a
parked web page may stop repainting, and both its picture and its
accessibility values can lag behind what the page holds. When a read-back
of web content disagrees with what you just did, wait a moment and read
again before acting on it.
