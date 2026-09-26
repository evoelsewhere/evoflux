# Forms, dialogs and menus

Native windows expose their controls through the accessibility tree, so most
work here is by ref and needs no coordinates at all.

## Fields and buttons

- `snapshot` lists each field with its label, role and current value. Match
  a field by its label, not by its position.
- `set_value` replaces a text field's content in one step. `type` after
  clicking the field works too, and is what fields that react to every
  keystroke need.
- In a native window on Windows a form can be filled in one `type` from its
  first field, `\t` moving to the next field as a person tabbing through it
  would. Elsewhere `\t` does not move, so fill one field per step. Either
  way, read every field back afterwards: a field that reformats or rejects
  input shows it there.
- `invoke` presses buttons, ticks check boxes, selects radio buttons, tabs
  and list items, and opens combo boxes. After opening a list, take a
  snapshot and pick the item by ref.
- Trees: `invoke` on an item usually selects it rather than expanding it,
  and on an expanded item it collapses it. Expand with the tree's keys
  (Right arrow, or `+`) on the selected item, or by double-clicking it, and
  check the next snapshot.
- A check box or radio button shows `[checked]` or `[unchecked]` in the
  snapshot: read the state back rather than assuming a toggle took.

## Dialogs

- A dialog opened by a click or a shortcut becomes the target of the next
  action; its refs come from a new snapshot. On Windows, refs into the
  window behind a modal dialog are refused until it closes; on macOS they
  are not, so take care to use the dialog's own refs.
- Read a dialog before pressing anything in it. Confirm, Replace, Delete and
  Don't Save change the user's data: press them only when the task is that
  change. Enter presses the dialog's default button, whatever it is.
- Escape or the dialog's Cancel button closes it without effect.
- File dialogs: fill the file name field by ref and press the dialog's own
  button. Keep the folder the user chose unless told otherwise.
- A dialog you did not cause (an update offer, a sign-in, a licence prompt):
  read it, do not accept anything, and tell the user if it blocks the work.

## Menus and toolbars

- `find` the command by its name and `invoke` its ref. Menus that open as
  separate windows are included in the snapshot while they are open; on
  macOS the menu bar is searched by `find`, not listed by `snapshot`.
- Ribbon-style toolbars: find the button by name and invoke it. Key tips
  (Alt, then letters) do not work in the background.
- A right-click menu opens with `click` and `"button": "right"`; pick its
  item by ref from the next snapshot.

## When a control does not respond

Some apps ignore background mouse input for certain controls. Try `invoke`
by ref, then the control's keyboard shortcut, before coordinates, and read
back which one had an effect.
