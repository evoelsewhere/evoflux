# Forms, dialogs and menus

Native windows (Win32, WinForms, WPF, Qt, macOS AppKit) expose their controls
through the accessibility tree, so most work here is by ref and needs no
coordinates at all.

## Fields and buttons

- `snapshot` lists each field with its label, role and current value. Match
  a field by its label, not by its position.
- `set_value` fills a text field in one step and is the most reliable way to
  replace its content. `type` after clicking the field also works and is
  what apps that validate keystroke by keystroke need.
- A form can be filled in one `type` from its first field: `\t` moves to the
  next field, as a person tabbing through it would.
- `invoke` presses buttons, ticks check boxes, selects radio buttons and
  tabs, and expands combo boxes and tree items. After expanding a combo box,
  take a snapshot and `invoke` or click the option's ref.

## Dialogs

- A dialog opened by a click or a shortcut becomes the target of the next
  action; its refs come from a new snapshot. Refs into the window behind a
  modal dialog are refused until it closes.
- Read a dialog before pressing anything in it. Confirm, Save, Replace,
  Delete and Don't Save buttons change the user's data: press them only when
  the task is that change.
- `escape` or the dialog's Cancel button closes it without effect.
- File dialogs: type the file name into the name field by ref and press the
  dialog's Save or Open button. Keep the folder the user chose unless told
  otherwise.

## Menus and toolbars

- `find` the command by its name ("Insert", "Bold", "Export") and `invoke`
  its ref. Menus that open as separate windows are included in the snapshot
  while they are open.
- Office ribbons: `find` the command's button by name, `invoke` it. Key tips
  (Alt, then letters) do not work in the background.
- A right-click menu opens with `click` and `"button": "right"`; pick its item
  by ref from the next snapshot.

## When a control does not respond

Some apps ignore background mouse input for certain controls. Try `invoke`
by ref, then the control's keyboard shortcut, before falling back to
coordinates, and say which one worked.
