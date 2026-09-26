# Grids and spreadsheets

## Contents

- How a grid takes input
- Enter data
- Select and apply commands
- Read values back
- Spreadsheets
- Traps

## How a grid takes input

A grid has an active cell. Typing into it opens an editor for that cell;
committing (usually Enter or Tab) moves to a neighbouring cell. Grids differ
in where each key moves, and whether typing replaces or edits the cell, so
find out with a small block first and read it back.

How much one `type` can do depends on the input channel
([input-channels.md](input-channels.md)):

- **Native window on Windows:** `\t` and `\n` are real Tab and Enter presses
  and the tool waits for each cell change, so a block of rows can go in one
  `type`, with `\t` between cells and `\n` at the end of each row.
- **Web content or macOS:** `\t` is a character and nothing moves between
  cells. Enter one cell per step: select the cell (by ref, or with the
  grid's navigation keys), type its content, commit it, read it back.

## Enter data

- Start from a known cell: move there by ref, by the grid's "go to start"
  key, or by its go-to command, and confirm where the active cell is before
  typing.
- End every entry by committing it. A cell still being edited takes every
  key that follows, so a command sent after an unfinished entry acts on that
  cell's text instead of the grid.
- Write the rows in a known order and keep the source values in your notes,
  so every cell can be compared with its source afterwards.
- For a large table, enter a few rows, read them back, then continue. A
  mistake found after ten rows costs ten rows to fix.

## Select and apply commands

- Select with the keyboard: arrow keys with Shift extend the selection from
  the active cell, with a repeat count for long ranges. On macOS these are
  posted keys that a background app may ignore; check the selection.
- To select by address, look for the grid's go-to command or its reference
  box. `type` with the box's ref may open its drop-down instead of placing
  the caret, and a click may not move the focus in the background: prefer
  the command's own shortcut, which opens it with the focus inside, and
  check that the next result names the box or the dialog.
- Formatting, sorting and inserting are commands: `find` them by name, or
  use the shortcut shown in their tooltip or menu, then read back the
  effect.

## Read values back

Many grids expose no cell values through accessibility, and a snapshot
skips rows scrolled out of view. Ways to read what is really there:

- Select a cell and read the field that shows the selected cell's content,
  if the app has one: its text is in the snapshot, formulas included.
- Select a range and read what the app computes about it (a count, sum or
  average in a status area), and compare with the same figure worked out
  from the source. No count or sum at all for a range means its cells are
  empty or hold no numbers.
- A screenshot shows displayed values, which may be rounded or formatted;
  never trust a number you cannot read clearly in it, and never decide from
  a screenshot alone that cells are already filled.

Check every value you computed and at least one full row of entered values
against the source before building on them.

## Spreadsheets

When the grid computes (formulas start with a sign such as `=`):

- Write formulas against the rows and columns the cells will occupy after
  entry, counting header and blank rows.
- Read a formula back from the content field, not from the displayed
  result: the display hides a wrong reference that happens to give a
  plausible number.
- An error value in a cell (division by zero, a bad reference) means the
  formula or the cells it refers to are wrong: fix the cause, not the
  display.

## Traps

- A command, name or address that shows up as cell content: the focus was
  in the grid, not in the box you meant. Undo, then reach the box another
  way.
- A cell whose first characters are missing, or a formula that shows as
  text: input was lost at the start of the entry. Retype that cell and read
  it back.
- Rows shifted by one: a line break was lost or doubled. Read back the
  first column and fix the rows before adding anything that refers to them.
- Text that autocompleted from an earlier entry in the column, or a number
  the grid turned into a date or a percentage: compare the read-back with
  the source.
- Charts, shapes and pictures on a sheet are objects, not cells:
  [canvas-and-objects.md](canvas-and-objects.md).
