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

A grid is in one of two states: ready (keys and commands act on the
selected cells) or editing a cell (keys go into that cell, a click on
another cell may insert a reference to it, and many commands are
disabled). An app often shows which in a status area. Before any command,
commit or abandon the entry (Enter or Escape) and check the grid is ready.

Each cell is an item in the snapshot (`DataItem` on Windows, `Cell` on
macOS) with its position, so aim at a cell from `find` (its name is often
its address or its text) rather than from a screenshot.

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
- Select with the mouse: click a cell; `drag` from inside the first cell to
  the last (on Windows the tool does this as a click and a shift+click,
  which every grid takes); or click the first and click the last with
  `modifiers: ["shift"]`. Add a separate cell with `["ctrl"]` (`cmd` on
  macOS). A drag that starts on a cell's edge moves or fills the selection
  instead, in grids that have such handles.
- To select by address, use the grid's go-to command, by its shortcut,
  which opens it with the focus inside; type the address or range and press
  Enter. A reference box above the grid often does not take the focus from
  a background click: what is typed next goes into the active cell.
- Formatting, sorting and inserting are commands: `find` them by name, or
  use the shortcut shown in their tooltip or menu, then read back the
  effect.

## Read values back

A snapshot shows each visible cell's value (`value="…"`) where the grid
exposes it, and marks the selected cells `[selected]`; it skips rows
scrolled out of view. Ways to read what is really there:

- The cells' own values in a `snapshot`, or `find` for a cell by its name.
  This is the displayed value, which may be rounded or formatted.
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
  the source. Type every text value in full.
- A suggestion list that opened while typing (function names, earlier
  entries) takes Tab or Enter as "accept the highlighted item". Type
  formulas and names out in full, including brackets.
- Two entries run together in one cell (`1200Total`): the first was never
  committed. Fix it before building on the table.
- A long number shown in scientific notation or as `####` in a narrow
  column: the content field still holds the full value.
- Charts, shapes and pictures on a sheet are objects, not cells:
  [canvas-and-objects.md](canvas-and-objects.md).
