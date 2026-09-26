# Forms, dialogs and menus

Native windows expose their controls through the accessibility tree, so most
work here is by ref and needs no coordinates at all.

## Fields and buttons

- `snapshot` lists each field with its label, role and current value. Match
  a field by its label, not by its position.
- `set_value` replaces a text field's content in one step. `type` after
  clicking the field works too, and is what fields that react to every
  keystroke need.
- A form can be filled in one `type` from its first field, `\t` moving to
  the next field as a person tabbing through it would. Read the fields back
  afterwards: a field that reformats or rejects input shows it there.
- `invoke` presses buttons, ticks check boxes, selects radio buttons and
  tabs, and expands combo boxes and tree items. After expanding a list, take
  a snapshot and pick the item by ref.

## Dialogs

- A dialog opened by a click or a shortcut becomes the target of the next
  action; its refs come from a new snapshot. Refs into the window behind a
  modal dialog are refused until it closes.
- Read a dialog before pressing anything in it. Confirm, Replace, Delete and
  Don't Save change the user's data: press them only when the task is that
  change.
- Escape or the dialog's Cancel button closes it without effect.
- File dialogs: fill the file name field by ref and press the dialog's own
  button. Keep the folder the user chose unless told otherwise.

## Menus and toolbars

- `find` the command by its name and `invoke` its ref. Menus that open as
  separate windows are included in the snapshot while they are open.
- Ribbon-style toolbars: find the button by name and invoke it. Key tips
  (Alt, then letters) do not work in the background.
- A right-click menu opens with `click` and `"button": "right"`; pick its item
  by ref from the next snapshot.

## When a control does not respond

Some apps ignore background mouse input for certain controls. Try `invoke`
by ref, then the control's keyboard shortcut, before coordinates, and read
back which one had an effect.
