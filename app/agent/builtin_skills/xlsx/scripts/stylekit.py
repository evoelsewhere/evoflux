"""Deterministic style and calculation helpers for EvoFlux XLSX builders."""

from __future__ import annotations

from dataclasses import dataclass

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo


@dataclass(frozen=True)
class WorkbookTheme:
    """A neutral analytical workbook theme."""

    font: str = "Aptos"
    ink: str = "24323D"
    muted: str = "66717C"
    accent: str = "2F6D68"
    header_fill: str = "DDE9E7"
    section_fill: str = "EEF3F2"
    input_fill: str = "FFF2CC"
    border: str = "CCD4D8"


def configure_workbook(workbook: Workbook) -> None:
    """Request a full automatic calculation when Excel opens the file."""
    calculation = workbook.calculation
    calculation.calcMode = "auto"
    calculation.fullCalcOnLoad = True
    calculation.forceFullCalc = True


def style_title(
    sheet,
    cell_range: str,
    title: str,
    *,
    theme: WorkbookTheme = WorkbookTheme(),
) -> None:
    sheet.merge_cells(cell_range)
    cell = sheet[cell_range.split(":")[0]]
    cell.value = title
    cell.font = Font(name=theme.font, size=18, bold=True, color=theme.ink)
    cell.alignment = Alignment(vertical="center")
    sheet.row_dimensions[cell.row].height = 30


def style_header(
    cells,
    *,
    theme: WorkbookTheme = WorkbookTheme(),
) -> None:
    thin = Side(style="thin", color=theme.border)
    for cell in cells:
        cell.font = Font(name=theme.font, size=10, bold=True, color=theme.ink)
        cell.fill = PatternFill("solid", fgColor=theme.header_fill)
        cell.alignment = Alignment(
            horizontal="center",
            vertical="center",
            wrap_text=True,
        )
        cell.border = Border(bottom=thin)


def style_input(cell, *, theme: WorkbookTheme = WorkbookTheme()) -> None:
    cell.font = Font(name=theme.font, color="0000FF")
    cell.fill = PatternFill("solid", fgColor=theme.input_fill)


def set_column_widths(sheet, widths: dict[str | int, float]) -> None:
    for key, width in widths.items():
        letter = get_column_letter(key) if isinstance(key, int) else key
        sheet.column_dimensions[letter].width = min(max(width, 4), 60)


def add_table(
    sheet,
    reference: str,
    *,
    name: str,
    style: str = "TableStyleMedium2",
) -> Table:
    table = Table(displayName=name, ref=reference)
    table.tableStyleInfo = TableStyleInfo(
        name=style,
        showFirstColumn=False,
        showLastColumn=False,
        showRowStripes=True,
        showColumnStripes=False,
    )
    sheet.add_table(table)
    return table


def prepare_data_sheet(
    sheet,
    *,
    freeze: str = "A2",
    auto_filter: str | None = None,
) -> None:
    sheet.freeze_panes = freeze
    sheet.sheet_view.showGridLines = False
    if auto_filter:
        sheet.auto_filter.ref = auto_filter
    sheet.print_options.horizontalCentered = True
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
