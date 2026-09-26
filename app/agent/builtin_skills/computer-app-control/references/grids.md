# Grids and spreadsheets

## Contents

- How grids take input
- Enter a table
- Select a range
- Format
- Charts
- Check and save
- Common mistakes

## How grids take input

A spreadsheet or data grid has an active cell. Typing into it opens an
editor for that cell; Tab commits and moves right, Enter commits and moves
down. The tool waits for each cell change, so a whole table can go in one
`type`. Shortcuts below are the Excel ones; most spreadsheet apps share the
movement and selection keys, and the rest can be confirmed in their menus
with `find`.

## Enter a table

Start from a known cell and type the whole block in one action:

```json
{"actions": [
  {"action": "key", "key": "ctrl+home"},
  {"action": "type", "text": "Region\tJul\tAug\tQ3 Total\nNorth\t188\t201\t=SUM(B2:C2)\nSouth\t154\t162\t=SUM(B3:C3)\nTotal\t=SUM(B2:B3)\t=SUM(C2:C3)\t=SUM(D2:D3)\n"}
]}
```

- End the block with `\n`, as above. A cell still being edited takes every
  key that follows: selecting a range, `ctrl+b` and `alt+f1` then go into
  that cell's text instead of acting on the sheet.
- `\t` moves one cell right. In Excel `\n` commits the row and returns to the
  column the row started in; in a plain data grid Enter may only move down,
  so type one row per `type` and move back with `home` if the next row
  starts in the wrong column.
- Formulas are typed like any other cell. Write them against the rows as
  they will be after the block is typed, counting the header row.
- To start elsewhere, move from `ctrl+home` with arrow keys and a repeat
  count (`{"action": "key", "key": "down", "repeat": 3}`).

## Select a range

Extend the selection from the active cell with the keyboard:

```json
{"action": "key", "key": "ctrl+home"},
{"action": "key", "key": "shift+down", "repeat": 5},
{"action": "key", "key": "shift+right", "repeat": 3}
```

That selects A1:D6. To select by address, `find` the Name Box (or the app's
cell reference box), click its ref, `type` the address and press `enter`;
Excel's `ctrl+g` (Go To) works the same way. Never type an address while a
cell is active: it becomes the cell's content.

## Format

| Excel shortcut | Effect on the selection |
|---|---|
| `ctrl+b` | Bold |
| `ctrl+shift+5` | Percent |
| `ctrl+shift+4` | Currency |
| `ctrl+shift+1` | Number with thousands separator |

To fit a column to its content, double-click the border to the right of its
letter in the column header row, at screenshot coordinates of the line
between the two letters.

## Charts

1. Select the data with its header row and label column, without total rows
   or percentage columns that would dwarf or flatten the rest.
2. In Excel `alt+f1` inserts a column chart on the sheet and `f11` puts one
   on a sheet of its own. Elsewhere, `find` the insert-chart command and
   `invoke` it.
3. A new chart often lands over the data. Take a screenshot, then drag from
   an empty spot inside the chart (not the title, legend or bars) to a free
   area beside the data.
4. To rename it, click the chart title, `type` the new title, press `enter`,
   then `escape` to leave the chart.

## Check and save

Take one screenshot of the finished sheet and compare it with the request:
every value, every formula result, the chart's series. Excel's status bar
shows Sum and Count for the selection, a quick check of a typed column
against its source. `ctrl+s` saves.

## Common mistakes

- Clicking near the top-left of a spreadsheet window: the Paste button sits
  there and pastes whatever the user last copied.
- Typing a cell address into a cell instead of the reference box.
- Ribbon key tips (`alt`, then letters): in the background the letters are
  typed into the active cell.
- Chart data that includes a total row or a percentage column.
- Formulas that point at the wrong rows because the header row was not
  counted.
