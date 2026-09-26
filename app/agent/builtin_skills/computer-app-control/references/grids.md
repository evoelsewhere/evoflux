# Grids and spreadsheets

## Contents

- How a grid takes input
- Enter data
- Select and apply commands
- Read values back
- Charts and other objects
- Traps

## How a grid takes input

A grid has an active cell. Typing into it opens an editor for that cell;
Tab usually commits and moves right, Enter commits and moves down. Many
spreadsheets return Enter to the column a row of Tabs started in; plain data
grids often do not. The tool waits for each cell change, so a whole block
can go in one `type` when the grid behaves this way. Find out which way the
grid behaves with a small block first, and read it back.

## Enter data

- Move to a known starting cell first (the grid's "go to start" key, or a
  click by ref on the cell), then type the block: `\t` between cells, `\n`
  at the end of each row.
- End the block with `\n`. A cell still being edited takes every key that
  follows, so commands sent after an unfinished block act on that cell's
  text instead of the sheet.
- Formulas are typed like any other cell. Write them against the rows and
  columns the cells will occupy after the block is typed, counting any
  header or blank rows.
- For a large table, type a few rows, read them back, then continue. A
  mistake found after ten rows costs ten rows to fix.

## Select and apply commands

- Select with the keyboard: arrow keys with Shift extend the selection from
  the active cell, with a repeat count for long ranges.
- To select by address, look for the app's Go To command or its cell
  reference box. A click does not always move the keyboard focus into such a
  box in the background: after clicking it, check the result line shows the
  input going there, or use its own shortcut, which opens it with the focus
  inside.
- Formatting and inserting are commands: `find` them by name, or use the
  shortcut shown in their tooltip or menu, then read back the effect.

## Read values back

A grid often does not expose every cell's value through accessibility.
Ways to read what is really there:

- Select a cell and read the app's value or formula bar (its text is in the
  snapshot) to see the cell's exact content, formula included.
- Select a range and read the status bar, where spreadsheets show sums and
  counts: compare them with the source.
- A screenshot shows displayed values; never trust a number you cannot read
  clearly in it.

Check at least the cells you computed (totals, formulas) and one row of
typed values against the source before moving on.

## Charts and other objects

- Select the data the chart should show (labels and series, not totals or
  percentages that would dwarf or flatten the rest), then run the app's
  insert-chart command.
- A new object may land over the data. Many apps can instead place a chart
  on a sheet of its own; look for that option before moving things by hand.
- To move an object, find its frame with `find` (its bounds are in the
  result) and drag from an empty spot inside the frame, clear of the
  corners and edges (resize handles) and of inner parts such as a plot area,
  title or legend, which move on their own. Read back its new position, and
  undo if it went wrong. If a drag moved nothing, pick another empty spot
  rather than repeating the same one.

## Traps

- A command, name or address that shows up as cell content: the focus was
  in the grid, not in the box you meant. Undo, then reach the box another
  way.
- A formula that shows as text: its first character did not arrive. Retype
  that cell.
- Rows shifted by one: a line break was lost or doubled. Read back the
  first column and fix the rows before adding anything that refers to them.
- A toolbar next to the grid's top-left corner: clicking near it guessing
  where the first cell is can paste or change the sheet.
