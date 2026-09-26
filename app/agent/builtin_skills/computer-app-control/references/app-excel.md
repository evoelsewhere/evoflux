# App notes: Microsoft Excel (Windows desktop)

Notes learned from driving Excel in the background. They add to
[grids.md](grids.md), which still applies; like everything else, a note is a
starting point that the read-back confirms, not a guarantee.

## Contents

- Where things are
- Modes: Ready, Enter, Edit
- Moving and selecting
- Entering data
- Reading values back
- Formatting
- Charts
- Traps seen in practice

## Where things are

- The grid is the `EXCEL7` control; a cell being edited is `EXCEL6`. A
  typing result that names `EXCEL6` means the entry is still open.
- The accessibility tree does not give cell values. The **Name Box** shows
  the active cell's address and the **Formula Bar** its exact content; both
  are in `snapshot` and `find` results.
- The status bar shows the mode (`Ready`, `Enter`, `Edit`) and, for a
  selected range of numbers, `Average`, `Count` and `Sum`.

## Modes: Ready, Enter, Edit

- Commands, shortcuts and the ribbon act on the sheet only in **Ready**
  mode. In Enter or Edit mode keys go into the cell, clicks on other cells
  insert references into it, and many ribbon commands are disabled.
- Before any command, check the status bar reads Ready. If it does not,
  press `enter` to keep the entry or `escape` to drop it, then check again.

## Moving and selecting

- `ctrl+g` (or `f5`) opens Go To with the focus in its Reference box: type
  an address or range (`B2`, `A1:D11`, `A1:A11,D1:D11`) and press `enter`.
  This is the reliable way to move or select by address; a background click
  on the Name Box often leaves the focus in the grid.
- `ctrl+home` goes to A1; `ctrl+arrow` jumps to the edge of the data;
  `shift+arrow` with `repeat` extends a selection.

## Entering data

- A block typed with `\t` between cells and `\n` after each row fills a
  table: after a row of Tabs, Enter returns to the column the row started
  in. End the block with `\n` so the last cell is committed.
- Enter a large table in parts, and start each part from a known cell (Go
  To), not from wherever the previous part left the cursor.
- AutoComplete finishes text from entries above in the same column: typing
  a prefix of an existing entry and pressing Tab or Enter stores the longer
  entry. Type every text value in full and read the column back.
- Typing a formula name shows a function list; `\t` would accept its
  highlighted item. Type formulas out in full, including parentheses.

## Reading values back

- Select a cell (Go To) and read the Formula Bar: it shows the exact value
  or formula, where the grid shows a rounded or `####` display.
- Select a whole column of numbers (Go To `D2:D11`) and compare the status
  bar's Count and Sum with the count and total worked out from the source:
  one comparison catches a missing, merged or doubled row.
- A cell value that holds text such as `183780000000+A5BNB` is two entries
  run together: the first was never committed. Fix it before building on
  the table.

## Formatting

Shortcuts that work in the background (on the selection, in Ready mode):
`ctrl+b` bold, `ctrl+shift+1` number with thousands separators,
`ctrl+shift+5` percent, `ctrl+shift+4` currency, `ctrl+1` the Format Cells
dialog. Column width: `find` "Format" on the Home tab and invoke "AutoFit
Column Width". Key tips (Alt, then letters) do not work.

## Charts

- Select the labels and the one series to plot (Go To `A1:A11,D1:D11`,
  leaving out totals), then press `alt+f1` for a chart on the sheet or `f11`
  for a chart on a sheet of its own, which never covers the data.
- A chart on the sheet lands over the cells to the right of the selection.
  To move it, prefer the Chart Design tab's Move Chart command, or drag its
  frame as [canvas-and-objects.md](canvas-and-objects.md) describes.
- Read the chart back: its title and series names through `find`, and the
  data range through Select Data.

## Traps seen in practice

- A click on a ribbon button while a cell was still being edited put a
  cell reference into the entry instead; Excel then offered to "correct"
  the formula. Dismiss such a dialog with Escape, undo, and commit entries
  before clicking anything.
- A total row that sums with a formula only looks right if every row above
  it is right: check the Count first.
- Excel may replace a long number with scientific notation in a narrow
  column; the Formula Bar still shows the full value.
