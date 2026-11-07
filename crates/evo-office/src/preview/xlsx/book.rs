//! The workbook as v3 saw it through openpyxl (`load_workbook`, not read-only):
//! cells with their Python values (formula text, or the cached value of a
//! `data_only` load), the style tables, dimensions, merges, hyperlinks,
//! comments, conditional formatting, sheet views, charts and images.
//!
//! openpyxl's value semantics are kept (the display strings depend on them);
//! its v3-visible bugs are not: `<col>` ranges cover every column, reading a
//! cell never grows the sheet, a hyperlink does not write its text into an
//! empty cell, and theme / indexed colours resolve (see `features::Palette`).

use std::collections::HashMap;

use super::features::Palette;
use super::formula::{
    parse_cell, range_boundaries, translate_shared, Book, CellView, FormulaError,
};
use super::numfmt::{
    builtin_format, cast_number, from_excel, from_iso8601, is_date_format, is_timedelta_format,
};
use super::value::Value;
use crate::preview::html::parse_xml;
use crate::preview::package::Package;

/// Excel's default column width (characters) and row height (points) when the
/// sheet does not set them (v3 used openpyxl's 13 characters and 18.75 pt).
pub const DEFAULT_COLUMN_WIDTH: f64 = 8.43;
pub const DEFAULT_ROW_HEIGHT: f64 = 15.0;

const SHARED_STRINGS_TYPE: &str =
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml";

/// Why openpyxl would have refused the package (triggers the sanitized retry).
#[derive(Debug, Clone)]
pub struct LoadError(pub String);

// ---------------------------------------------------------------- styles

#[derive(Debug, Clone, PartialEq)]
pub enum ColorKind {
    Rgb(String),
    Indexed(u32),
    Theme(u32),
    Auto,
}

/// An openpyxl `Color`.
#[derive(Debug, Clone, PartialEq)]
pub struct Color {
    pub kind: ColorKind,
    pub tint: f64,
}

impl Default for Color {
    fn default() -> Self {
        Self {
            kind: ColorKind::Rgb("00000000".into()),
            tint: 0.0,
        }
    }
}

impl Color {
    fn from_node(node: roxmltree::Node) -> Self {
        let tint = node
            .attribute("tint")
            .and_then(|t| t.parse().ok())
            .unwrap_or(0.0);
        let kind = if let Some(i) = node.attribute("indexed") {
            ColorKind::Indexed(i.trim().parse().unwrap_or(0))
        } else if let Some(t) = node.attribute("theme") {
            ColorKind::Theme(t.trim().parse().unwrap_or(0))
        } else if node.attribute("auto").is_some() {
            ColorKind::Auto
        } else {
            let rgb = node.attribute("rgb").unwrap_or("00000000");
            ColorKind::Rgb(if rgb.len() == 6 {
                format!("00{rgb}")
            } else {
                rgb.to_string()
            })
        };
        Self { kind, tint }
    }

    /// `color.rgb` as v3 `_css_color` reads it: openpyxl answers a non-RGB
    /// colour's `.rgb` with an error message, which is no colour.
    pub fn rgb(&self) -> Option<&str> {
        match &self.kind {
            ColorKind::Rgb(rgb) => Some(rgb),
            _ => None,
        }
    }
}

#[derive(Debug, Clone, Default, PartialEq)]
pub struct Font {
    pub name: Option<String>,
    pub size: Option<f64>,
    pub bold: bool,
    pub italic: bool,
    pub strike: bool,
    pub underline: Option<String>,
    pub color: Option<Color>,
}

#[derive(Debug, Clone, Default, PartialEq)]
pub struct Fill {
    pub pattern: Option<String>,
    pub fg: Color,
    pub bg: Color,
    /// A `gradientFill` (openpyxl `GradientFill` has no colours v3 read).
    pub gradient: bool,
}

#[derive(Debug, Clone, Default, PartialEq)]
pub struct Side {
    pub style: Option<String>,
    pub color: Option<Color>,
}

#[derive(Debug, Clone, Default, PartialEq)]
pub struct Border {
    pub left: Side,
    pub right: Side,
    pub top: Side,
    pub bottom: Side,
}

#[derive(Debug, Clone, Default, PartialEq)]
pub struct Alignment {
    pub horizontal: Option<String>,
    pub vertical: Option<String>,
    pub wrap_text: bool,
}

/// One `cellXfs` entry resolved like openpyxl's `StyleArray`.
#[derive(Debug, Clone, Default)]
pub struct Xf {
    pub font: usize,
    pub fill: usize,
    pub border: usize,
    pub number_format: String,
    pub is_date: bool,
    pub is_timedelta: bool,
    pub alignment: Alignment,
}

/// A differential style (conditional formatting).
#[derive(Debug, Clone, Default)]
pub struct Dxf {
    pub font: Option<Font>,
    pub fill: Option<Fill>,
}

#[derive(Debug, Clone)]
pub struct Styles {
    pub fonts: Vec<Font>,
    pub fills: Vec<Fill>,
    pub borders: Vec<Border>,
    pub xfs: Vec<Xf>,
    pub dxfs: Vec<Dxf>,
    pub palette: Palette,
}

impl Default for Styles {
    /// openpyxl's defaults for a workbook without a usable stylesheet.
    fn default() -> Self {
        Self {
            fonts: vec![Font {
                name: Some("Calibri".into()),
                size: Some(11.0),
                color: Some(Color {
                    kind: ColorKind::Theme(1),
                    tint: 0.0,
                }),
                ..Font::default()
            }],
            fills: vec![
                Fill::default(),
                Fill {
                    pattern: Some("gray125".into()),
                    ..Fill::default()
                },
            ],
            borders: vec![Border::default()],
            xfs: vec![Xf {
                number_format: "General".into(),
                ..Xf::default()
            }],
            dxfs: Vec::new(),
            palette: Palette::default(),
        }
    }
}

impl Styles {
    pub fn xf(&self, index: usize) -> &Xf {
        self.xfs
            .get(index)
            .or_else(|| self.xfs.first())
            .expect("at least one xf")
    }
    pub fn font(&self, xf: &Xf) -> Font {
        self.fonts.get(xf.font).cloned().unwrap_or_default()
    }
    pub fn fill(&self, xf: &Xf) -> Fill {
        self.fills.get(xf.fill).cloned().unwrap_or_default()
    }
    pub fn border(&self, xf: &Xf) -> Border {
        self.borders.get(xf.border).cloned().unwrap_or_default()
    }
}

fn local<'a>(node: &roxmltree::Node<'a, '_>) -> &'a str {
    node.tag_name().name()
}

fn children<'a, 'i>(
    node: roxmltree::Node<'a, 'i>,
    name: &'static str,
) -> impl Iterator<Item = roxmltree::Node<'a, 'i>> {
    node.children()
        .filter(move |c| c.is_element() && c.tag_name().name() == name)
}

fn child<'a, 'i>(
    node: roxmltree::Node<'a, 'i>,
    name: &'static str,
) -> Option<roxmltree::Node<'a, 'i>> {
    children(node, name).next()
}

/// openpyxl `Bool` descriptor for attribute text.
pub fn ox_bool(text: &str) -> bool {
    !matches!(text, "false" | "f" | "0")
}

/// A `NoneSet` value (`"none"` reads as unset).
fn none_set(text: Option<&str>) -> Option<String> {
    text.filter(|t| *t != "none").map(str::to_string)
}

fn parse_font(node: roxmltree::Node) -> Font {
    let mut font = Font::default();
    for c in node.children().filter(|c| c.is_element()) {
        let flag = || c.attribute("val").is_none_or(ox_bool);
        match local(&c) {
            "name" => font.name = c.attribute("val").map(str::to_string),
            "sz" => font.size = c.attribute("val").and_then(|v| v.trim().parse().ok()),
            "b" => font.bold = flag(),
            "i" => font.italic = flag(),
            "strike" => font.strike = flag(),
            "u" => font.underline = Some(c.attribute("val").unwrap_or("single").to_string()),
            "color" => font.color = Some(Color::from_node(c)),
            _ => {}
        }
    }
    font
}

fn parse_fill(node: roxmltree::Node) -> Fill {
    if let Some(pattern) = child(node, "patternFill") {
        let mut fill = Fill {
            pattern: none_set(pattern.attribute("patternType")),
            ..Fill::default()
        };
        if let Some(fg) = child(pattern, "fgColor") {
            fill.fg = Color::from_node(fg);
        }
        if let Some(bg) = child(pattern, "bgColor") {
            fill.bg = Color::from_node(bg);
        }
        return fill;
    }
    Fill {
        gradient: child(node, "gradientFill").is_some(),
        ..Fill::default()
    }
}

fn parse_border(node: roxmltree::Node) -> Border {
    let side = |name: &'static str| {
        child(node, name)
            .map(|s| Side {
                style: none_set(s.attribute("style")),
                color: child(s, "color").map(Color::from_node),
            })
            .unwrap_or_default()
    };
    Border {
        left: side("left"),
        right: side("right"),
        top: side("top"),
        bottom: side("bottom"),
    }
}

fn parse_styles(text: &str) -> Result<Styles, LoadError> {
    let doc = parse_xml(text).map_err(|e| LoadError(format!("styles: {e}")))?;
    let root = doc.root_element();
    if root
        .descendants()
        .any(|n| n.is_element() && local(&n) == "AlternateContent")
    {
        return Err(LoadError("styles use markup compatibility".into()));
    }
    let mut styles = Styles::default();
    if let Some(indexed) = child(root, "colors").and_then(|c| child(c, "indexedColors")) {
        let colors: Vec<String> = children(indexed, "rgbColor")
            .map(|c| c.attribute("rgb").unwrap_or_default().to_string())
            .collect();
        styles.palette = styles.palette.with_indexed(&colors);
    }
    let custom: HashMap<u32, String> = child(root, "numFmts")
        .map(|n| {
            children(n, "numFmt")
                .filter_map(|f| {
                    Some((
                        f.attribute("numFmtId")?.trim().parse().ok()?,
                        f.attribute("formatCode")?.to_string(),
                    ))
                })
                .collect()
        })
        .unwrap_or_default();
    if let Some(cell_styles) = child(root, "cellStyles") {
        for style in children(cell_styles, "cellStyle") {
            if style.attribute("name").is_none_or(str::is_empty) {
                return Err(LoadError("unnamed cell style".into()));
            }
        }
    }
    let xfs: Vec<Xf> = child(root, "cellXfs")
        .map(|n| {
            children(n, "xf")
                .map(|xf| {
                    let id = |name| {
                        xf.attribute(name)
                            .and_then(|v| v.trim().parse::<usize>().ok())
                            .unwrap_or(0)
                    };
                    let num_id = id("numFmtId") as u32;
                    let (format, for_detection) = match custom.get(&num_id) {
                        Some(code) => (code.clone(), Some(code.clone())),
                        None => (
                            if num_id < 164 {
                                builtin_format(num_id).unwrap_or("General").to_string()
                            } else {
                                "General".to_string()
                            },
                            builtin_format(num_id).map(str::to_string),
                        ),
                    };
                    let alignment = child(xf, "alignment")
                        .map(|a| Alignment {
                            horizontal: none_set(a.attribute("horizontal")),
                            vertical: none_set(a.attribute("vertical")),
                            wrap_text: a.attribute("wrapText").is_some_and(ox_bool),
                        })
                        .unwrap_or_default();
                    Xf {
                        font: id("fontId"),
                        fill: id("fillId"),
                        border: id("borderId"),
                        is_date: for_detection.as_deref().is_some_and(is_date_format),
                        is_timedelta: for_detection.as_deref().is_some_and(is_timedelta_format),
                        number_format: format,
                        alignment,
                    }
                })
                .collect()
        })
        .unwrap_or_default();
    if xfs.is_empty() {
        // openpyxl keeps its defaults when the stylesheet has no cell styles.
        return Ok(styles);
    }
    styles.xfs = xfs;
    styles.fonts = child(root, "fonts")
        .map(|n| children(n, "font").map(parse_font).collect())
        .unwrap_or_default();
    styles.fills = child(root, "fills")
        .map(|n| children(n, "fill").map(parse_fill).collect())
        .unwrap_or_default();
    styles.borders = child(root, "borders")
        .map(|n| children(n, "border").map(parse_border).collect())
        .unwrap_or_default();
    styles.dxfs = child(root, "dxfs")
        .map(|n| {
            children(n, "dxf")
                .map(|d| Dxf {
                    font: child(d, "font").map(parse_font),
                    fill: child(d, "fill").map(parse_fill),
                })
                .collect()
        })
        .unwrap_or_default();
    Ok(styles)
}

// ---------------------------------------------------------------- cells and sheets

/// A formula cell's source as openpyxl returned it.
#[derive(Debug, Clone, PartialEq)]
pub enum Formula {
    /// `=...` text (shared formulas already translated).
    Text(String),
    /// An array formula (`ArrayFormula`): its text.
    Array(String),
    /// A data-table formula (`DataTableFormula`).
    DataTable,
}

impl Formula {
    /// The `data-formula` text.
    pub fn text(&self) -> String {
        match self {
            Formula::Text(t) | Formula::Array(t) => t.clone(),
            Formula::DataTable => "=".to_string(),
        }
    }
}

#[derive(Debug, Clone, Default)]
pub struct CellData {
    /// The value of a `data_only=False` load (`None` for formula cells).
    pub value: Value,
    /// The value of a `data_only=True` load (the cached result for formulas).
    pub cached: Value,
    pub formula: Option<Formula>,
    pub style: usize,
    /// Covered by a merge (openpyxl `MergedCell`).
    pub merged: bool,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct ColumnDim {
    pub width: f64,
    pub hidden: bool,
    /// The column's default cell format (`<col style>`).
    pub style: Option<usize>,
}

#[derive(Debug, Clone, Copy, PartialEq, Default)]
pub struct RowDim {
    pub height: Option<f64>,
    pub hidden: bool,
    /// The row's default cell format (`<row s customFormat="1">`).
    pub style: Option<usize>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct CellRange {
    pub min_col: u32,
    pub min_row: u32,
    pub max_col: u32,
    pub max_row: u32,
}

impl CellRange {
    pub fn parse(text: &str) -> Option<Self> {
        let (c1, r1, c2, r2) = range_boundaries(text)?;
        Some(Self {
            min_col: c1?,
            min_row: r1?,
            max_col: c2?,
            max_row: r2?,
        })
    }
}

/// A conditional formatting value object (`cfvo`).
#[derive(Debug, Clone, Default)]
pub struct Cfvo {
    pub kind: Option<String>,
    pub val: Option<String>,
}

#[derive(Debug, Clone, Default)]
pub struct Rule {
    pub kind: String,
    pub priority: i64,
    pub dxf: Option<Dxf>,
    pub operator: Option<String>,
    pub text: Option<String>,
    pub rank: Option<i64>,
    pub percent: bool,
    pub bottom: bool,
    pub above_average: Option<bool>,
    pub equal_average: bool,
    pub formula: Vec<String>,
    pub color_scale: Option<(Vec<Cfvo>, Vec<Color>)>,
    pub data_bar: Option<DataBar>,
    pub icon_set: Option<IconSet>,
}

#[derive(Debug, Clone, Default)]
pub struct DataBar {
    pub cfvo: Vec<Cfvo>,
    pub color: Option<Color>,
    pub min_length: Option<i64>,
    pub max_length: Option<i64>,
    pub show_value: Option<bool>,
}

#[derive(Debug, Clone, Default)]
pub struct IconSet {
    pub name: Option<String>,
    pub cfvo: Vec<Cfvo>,
    pub show_value: Option<bool>,
    pub reverse: bool,
}

/// Rules sharing one `sqref` (openpyxl merges blocks with equal ranges).
#[derive(Debug, Clone)]
pub struct CfBlock {
    pub ranges: Vec<CellRange>,
    pub rules: Vec<Rule>,
}

/// A cell marker of a drawing anchor (zero-based column/row, EMU offsets).
#[derive(Debug, Clone, Copy, Default, PartialEq)]
pub struct Marker {
    pub col: i64,
    pub row: i64,
    pub col_off: f64,
    pub row_off: f64,
}

/// A drawing anchor: `from` marker, and the `to` marker (two-cell), `ext`
/// (one-cell / absolute) or `pos` (absolute), all in EMU.
#[derive(Debug, Clone, Default)]
pub struct Anchor {
    pub kind: String,
    pub from: Marker,
    pub to: Option<Marker>,
    pub ext: Option<(f64, f64)>,
    pub pos: Option<(f64, f64)>,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum ChartKind {
    Bar,
    Line,
    Area,
    Pie,
    Doughnut,
}

#[derive(Debug, Clone, Default)]
pub struct Series {
    pub val_ref: Option<String>,
    pub val_lit: Option<Vec<Option<String>>>,
    pub cat_ref: Option<String>,
}

#[derive(Debug, Clone)]
pub struct Chart {
    pub kind: ChartKind,
    pub title: Option<String>,
    pub series: Vec<Series>,
    pub anchor: Anchor,
}

#[derive(Debug, Clone)]
pub struct Picture {
    pub mime: &'static str,
    pub data: Vec<u8>,
    pub width: f64,
    pub height: f64,
    pub anchor: Anchor,
}

#[derive(Debug)]
pub struct Worksheet {
    pub title: String,
    pub state: String,
    pub cells: HashMap<(u32, u32), CellData>,
    /// (max_row, max_column) of the content: cells with a value, a formula, a
    /// non-default format or a note, and merges. `None` for an empty sheet.
    bounds: Option<(u32, u32)>,
    /// `<col min max>` ranges in document order (later ones win).
    pub columns: Vec<(u32, u32, ColumnDim)>,
    pub rows: HashMap<u32, RowDim>,
    /// `<sheetFormatPr>` defaults (character widths, points).
    pub default_width: f64,
    pub default_height: f64,
    pub merges: Vec<CellRange>,
    pub hyperlinks: HashMap<(u32, u32), String>,
    pub comments: HashMap<(u32, u32), (Option<String>, String)>,
    pub conditional: Vec<CfBlock>,
    pub pane: Option<String>,
    pub show_grid_lines: Option<bool>,
    pub charts: Vec<Chart>,
    pub images: Vec<Picture>,
}

impl Worksheet {
    fn new(title: String) -> Self {
        Self {
            title,
            state: "visible".into(),
            cells: HashMap::new(),
            bounds: None,
            columns: Vec::new(),
            rows: HashMap::new(),
            default_width: DEFAULT_COLUMN_WIDTH,
            default_height: DEFAULT_ROW_HEIGHT,
            merges: Vec::new(),
            hyperlinks: HashMap::new(),
            comments: HashMap::new(),
            conditional: Vec::new(),
            pane: None,
            show_grid_lines: None,
            charts: Vec::new(),
            images: Vec::new(),
        }
    }

    fn grow(&mut self, row: u32, column: u32) {
        let (r, c) = self.bounds.unwrap_or((0, 0));
        self.bounds = Some((r.max(row), c.max(column)));
    }

    pub fn max_row(&self) -> u32 {
        self.bounds.map_or(1, |e| e.0.max(1))
    }

    pub fn max_column(&self) -> u32 {
        self.bounds.map_or(1, |e| e.1.max(1))
    }

    pub fn has_cells(&self) -> bool {
        self.bounds.is_some()
    }

    pub fn cell(&self, row: u32, column: u32) -> Option<&CellData> {
        self.cells.get(&(row, column))
    }

    /// The column's dimension: the last `<col>` range covering it.
    pub fn column(&self, column: u32) -> ColumnDim {
        self.columns
            .iter()
            .rev()
            .find(|(min, max, _)| (*min..=*max).contains(&column))
            .map(|(_, _, dim)| *dim)
            .unwrap_or(ColumnDim {
                width: self.default_width,
                hidden: false,
                style: None,
            })
    }

    /// The format of the cell at (row, column): its own, else the row's, else
    /// the column's default format.
    pub fn style_at(&self, row: u32, column: u32) -> usize {
        if let Some(cell) = self.cell(row, column) {
            return cell.style;
        }
        self.row(row)
            .style
            .or_else(|| self.column(column).style)
            .unwrap_or(0)
    }

    pub fn row(&self, row: u32) -> RowDim {
        self.rows.get(&row).copied().unwrap_or_default()
    }
}

#[derive(Debug)]
pub struct Chartsheet {
    pub title: String,
    pub state: String,
    pub charts: Vec<Chart>,
}

#[derive(Debug)]
pub struct Workbook {
    pub worksheets: Vec<Worksheet>,
    pub chartsheets: Vec<Chartsheet>,
    pub sheetnames: Vec<String>,
    /// Every sheet in tab order.
    pub order: Vec<SheetRef>,
    pub styles: Styles,
}

/// A sheet in tab order.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum SheetRef {
    Worksheet(usize),
    Chartsheet(usize),
}

impl Workbook {
    pub fn worksheet(&self, title: &str) -> Option<&Worksheet> {
        self.worksheets.iter().find(|s| s.title == title)
    }
}

impl Book for Workbook {
    fn sheet_exists(&self, name: &str) -> bool {
        self.sheetnames.iter().any(|n| n == name)
    }

    fn cell(&self, sheet: &str, row: u32, column: u32) -> Result<CellView, FormulaError> {
        let Some(ws) = self.worksheet(sheet) else {
            return Err(FormulaError {
                message: format!("'{sheet}' is not a worksheet"),
                arithmetic: false,
            });
        };
        let Some(cell) = ws.cell(row, column) else {
            return Ok(CellView {
                value: Value::None,
                formula: None,
            });
        };
        let formula = match (&cell.formula, &cell.value) {
            (Some(Formula::Text(text)), _) => Some(Some(text.clone())),
            (Some(_), _) => Some(None),
            (None, Value::Str(s)) if s.starts_with('=') => Some(Some(s.clone())),
            _ => None,
        };
        Ok(CellView {
            value: cell.value.clone(),
            formula,
        })
    }

    fn worksheet_extents(&self) -> Vec<(String, Option<(u32, u32)>)> {
        self.worksheets
            .iter()
            .map(|ws| {
                (
                    ws.title.clone(),
                    ws.has_cells().then(|| (ws.max_row(), ws.max_column())),
                )
            })
            .collect()
    }
}

// ---------------------------------------------------------------- loading

fn text_content(node: roxmltree::Node) -> String {
    // openpyxl `Text.content`: the plain `t`, then every run's `t`.
    let mut out = String::new();
    if let Some(t) = child(node, "t") {
        out.push_str(t.text().unwrap_or_default());
    }
    for run in children(node, "r") {
        if let Some(t) = child(run, "t") {
            out.push_str(t.text().unwrap_or_default());
        }
    }
    out
}

fn read_text(package: &Package, part: &str) -> Option<String> {
    package.text(part)
}

fn workbook_part(package: &Package) -> String {
    package
        .rels("")
        .into_iter()
        .find(|r| r.kind() == "officeDocument")
        .map(|r| r.target)
        .filter(|t| package.has(t))
        .unwrap_or_else(|| "xl/workbook.xml".to_string())
}

fn shared_strings(package: &Package) -> Vec<String> {
    let mut part = None;
    if let Some(types) = package.text("[Content_Types].xml") {
        if let Ok(doc) = parse_xml(&types) {
            part = doc
                .root_element()
                .children()
                .find(|n| {
                    n.is_element()
                        && local(n) == "Override"
                        && n.attribute("ContentType") == Some(SHARED_STRINGS_TYPE)
                })
                .and_then(|n| n.attribute("PartName"))
                .map(|p| p.trim_start_matches('/').to_string());
        }
    }
    let Some(text) = part.and_then(|p| read_text(package, &p)) else {
        return Vec::new();
    };
    let Ok(doc) = parse_xml(&text) else {
        return Vec::new();
    };
    doc.descendants()
        .filter(|n| n.is_element() && local(n) == "si")
        .map(|si| text_content(si).replace("x005F_", ""))
        .collect()
}

/// Load the workbook like openpyxl `load_workbook` (both value modes at once).
pub fn load(package: &Package) -> Result<Workbook, LoadError> {
    let wb_part = workbook_part(package);
    let wb_text =
        read_text(package, &wb_part).ok_or_else(|| LoadError("no workbook part".into()))?;
    let wb_doc = parse_xml(&wb_text).map_err(|e| LoadError(format!("workbook: {e}")))?;
    let wb_root = wb_doc.root_element();
    let rels = package.rels(&wb_part);
    if let Some(caches) = child(wb_root, "pivotCaches") {
        for cache in children(caches, "pivotCache") {
            let id = cache
                .attributes()
                .find(|a| a.name() == "id")
                .map(|a| a.value())
                .unwrap_or_default();
            let found = rels
                .iter()
                .find(|r| r.id == id)
                .is_some_and(|r| package.has(&r.target));
            if !found {
                return Err(LoadError("pivot cache part missing".into()));
            }
        }
    }
    let epoch1904 = child(wb_root, "workbookPr")
        .and_then(|p| p.attribute("date1904"))
        .is_some_and(ox_bool);
    let mut styles = match read_text(package, "xl/styles.xml") {
        Some(text) => parse_styles(&text)?,
        None => Styles::default(),
    };
    let theme_part = rels
        .iter()
        .find(|r| r.kind() == "theme")
        .map(|r| r.target.clone())
        .unwrap_or_else(|| "xl/theme/theme1.xml".to_string());
    styles.palette = styles
        .palette
        .clone()
        .with_theme(read_text(package, &theme_part).as_deref());
    let strings = shared_strings(package);
    let mut workbook = Workbook {
        worksheets: Vec::new(),
        chartsheets: Vec::new(),
        sheetnames: Vec::new(),
        order: Vec::new(),
        styles,
    };
    let Some(sheets) = child(wb_root, "sheets") else {
        return Ok(workbook);
    };
    for sheet in children(sheets, "sheet") {
        let name = sheet.attribute("name").unwrap_or_default().to_string();
        let state = sheet.attribute("state").unwrap_or("visible").to_string();
        let id = sheet
            .attributes()
            .find(|a| a.name() == "id")
            .map(|a| a.value())
            .unwrap_or_default();
        let Some(rel) = rels.iter().find(|r| r.id == id) else {
            return Err(LoadError(format!("sheet {name} has no relationship")));
        };
        if !package.has(&rel.target) {
            continue;
        }
        if rel.rel_type.contains("chartsheet") {
            let mut charts = Vec::new();
            for drawing in package
                .rels(&rel.target)
                .into_iter()
                .filter(|r| r.kind() == "drawing")
            {
                charts.extend(read_drawing(package, &drawing.target).0);
            }
            workbook.sheetnames.push(name.clone());
            workbook
                .order
                .push(SheetRef::Chartsheet(workbook.chartsheets.len()));
            workbook.chartsheets.push(Chartsheet {
                title: name,
                state,
                charts,
            });
            continue;
        }
        let mut ws = load_worksheet(
            package,
            &rel.target,
            name.clone(),
            &workbook.styles,
            &strings,
            epoch1904,
        )?;
        ws.state = state;
        workbook.sheetnames.push(name);
        workbook
            .order
            .push(SheetRef::Worksheet(workbook.worksheets.len()));
        workbook.worksheets.push(ws);
    }
    Ok(workbook)
}

struct CellParse {
    value: Value,
    cached: Value,
    formula: Option<Formula>,
}

#[allow(clippy::too_many_arguments)]
fn parse_cell_element(
    c: roxmltree::Node,
    coordinate: (u32, u32),
    style: usize,
    styles: &Styles,
    strings: &[String],
    epoch1904: bool,
    shared: &mut HashMap<String, (String, (u32, u32))>,
) -> Result<CellParse, LoadError> {
    let t = c.attribute("t").unwrap_or("n");
    let raw = if t == "inlineStr" {
        None
    } else {
        child(c, "v")
            .and_then(|v| v.text())
            .filter(|s| !s.is_empty())
            .map(str::to_string)
    };
    let xf = styles.xf(style);
    let typed = |raw: Option<String>| -> Value {
        match raw {
            None => {
                if t == "inlineStr" {
                    child(c, "is")
                        .map(|is| Value::Str(text_content(is)))
                        .unwrap_or(Value::None)
                } else {
                    Value::None
                }
            }
            Some(raw) => match t {
                "n" => {
                    let number = cast_number(&raw).unwrap_or(Value::Str(raw.clone()));
                    if xf.is_date {
                        match number
                            .py_float()
                            .map(|f| from_excel(f, epoch1904, xf.is_timedelta))
                        {
                            Some(Ok(v)) => v,
                            _ => Value::Str("#VALUE!".into()),
                        }
                    } else {
                        number
                    }
                }
                "s" => raw
                    .trim()
                    .parse::<usize>()
                    .ok()
                    .and_then(|i| strings.get(i).cloned())
                    .map(Value::Str)
                    .unwrap_or(Value::Str(String::new())),
                "b" => Value::Bool(raw.trim().parse::<i64>().map(|i| i != 0).unwrap_or(false)),
                "d" => from_iso8601(&raw).unwrap_or(Value::Str(raw)),
                _ => Value::Str(raw),
            },
        }
    };
    let cached = typed(raw.clone());
    let Some(f) = child(c, "f") else {
        return Ok(CellParse {
            value: cached.clone(),
            cached,
            formula: None,
        });
    };
    let text = format!("={}", f.text().unwrap_or_default());
    let formula = match f.attribute("t") {
        Some("array") => Formula::Array(text),
        Some("dataTable") => Formula::DataTable,
        Some("shared") => {
            let si = f.attribute("si").unwrap_or_default().to_string();
            if let Some((master, origin)) = shared.get(&si) {
                let translated =
                    translate_shared(master, *origin, coordinate).map_err(LoadError)?;
                Formula::Text(translated)
            } else {
                if text != "=" {
                    shared.insert(si, (text.clone(), coordinate));
                }
                Formula::Text(text)
            }
        }
        _ => Formula::Text(text),
    };
    Ok(CellParse {
        value: Value::None,
        cached,
        formula: Some(formula),
    })
}

/// Attach a link to a cell. An empty cell stays empty, as in Excel (openpyxl's
/// setter wrote the link text into it, which v3 then showed).
fn bind_hyperlink(ws: &mut Worksheet, (row, column): (u32, u32), target: &str) {
    ws.hyperlinks.insert((row, column), target.to_string());
}

fn parse_cfvo(node: roxmltree::Node) -> Cfvo {
    Cfvo {
        kind: node.attribute("type").map(str::to_string),
        val: node.attribute("val").map(str::to_string),
    }
}

fn load_worksheet(
    package: &Package,
    part: &str,
    title: String,
    styles: &Styles,
    strings: &[String],
    epoch1904: bool,
) -> Result<Worksheet, LoadError> {
    let text = read_text(package, part).ok_or_else(|| LoadError(format!("missing {part}")))?;
    let doc = parse_xml(&text).map_err(|e| LoadError(format!("{part}: {e}")))?;
    let root = doc.root_element();
    let mut ws = Worksheet::new(title);
    let rels = package.rels(part);

    if let Some(view) = child(root, "sheetViews").and_then(|v| child(v, "sheetView")) {
        ws.show_grid_lines = view.attribute("showGridLines").map(ox_bool);
        ws.pane = child(view, "pane")
            .and_then(|p| p.attribute("topLeftCell"))
            .map(str::to_string);
    }
    if let Some(format) = child(root, "sheetFormatPr") {
        let number = |name| {
            format
                .attribute(name)
                .and_then(|v| v.trim().parse::<f64>().ok())
                .filter(|v| v.is_finite() && *v >= 0.0)
        };
        ws.default_width = number("defaultColWidth")
            .or_else(|| number("baseColWidth").map(|base| base + 0.43))
            .unwrap_or(DEFAULT_COLUMN_WIDTH);
        ws.default_height = number("defaultRowHeight")
            .filter(|h| *h > 0.0)
            .unwrap_or(DEFAULT_ROW_HEIGHT);
    }
    for cols in children(root, "cols") {
        for col in children(cols, "col") {
            let bound = |name| {
                col.attribute(name)
                    .and_then(|m| m.trim().parse::<u32>().ok())
            };
            let Some(min) = bound("min").filter(|m| *m >= 1) else {
                continue;
            };
            let max = bound("max").unwrap_or(min).clamp(min, 16_384);
            let width = col
                .attribute("width")
                .and_then(|w| w.trim().parse::<f64>().ok())
                .unwrap_or(ws.default_width);
            ws.columns.push((
                min,
                max,
                ColumnDim {
                    width,
                    // Excel hides zero-width columns (v3 drew them 70px wide).
                    hidden: col.attribute("hidden").is_some_and(ox_bool) || width == 0.0,
                    style: col
                        .attribute("style")
                        .and_then(|s| s.trim().parse::<usize>().ok())
                        .filter(|s| *s != 0),
                },
            ));
        }
    }

    let mut shared: HashMap<String, (String, (u32, u32))> = HashMap::new();
    if let Some(data) = child(root, "sheetData") {
        let mut row_counter = 0u32;
        for row in children(data, "row") {
            row_counter = match row.attribute("r") {
                Some(r) => r
                    .trim()
                    .parse::<u32>()
                    .or_else(|_| r.trim().parse::<f64>().map(|f| f as u32))
                    .map_err(|_| LoadError(format!("{r} is not a valid row number")))?,
                None => row_counter + 1,
            };
            let meaningful = row
                .attributes()
                .any(|a| a.namespace().is_none() && a.name() != "r" && a.name() != "spans");
            if meaningful {
                ws.rows.insert(
                    row_counter,
                    RowDim {
                        height: row.attribute("ht").and_then(|h| h.trim().parse().ok()),
                        // A zero-height row is hidden in Excel (v3 drew it at
                        // the default height).
                        hidden: row.attribute("hidden").is_some_and(ox_bool)
                            || row
                                .attribute("ht")
                                .and_then(|h| h.trim().parse::<f64>().ok())
                                == Some(0.0),
                        style: row
                            .attribute("s")
                            .filter(|_| row.attribute("customFormat").is_some_and(ox_bool))
                            .and_then(|s| s.trim().parse::<usize>().ok())
                            .filter(|s| *s != 0),
                    },
                );
            }
            let mut col_counter = 0u32;
            for c in children(row, "c") {
                let (column, row_index) = match c.attribute("r").and_then(parse_cell) {
                    Some((column, row_index)) => (column, row_index),
                    None => (col_counter + 1, row_counter),
                };
                col_counter = column;
                let style = c
                    .attribute("s")
                    .filter(|s| !s.is_empty())
                    .and_then(|s| s.trim().parse::<usize>().ok())
                    .unwrap_or(0);
                let parsed = parse_cell_element(
                    c,
                    (column, row_index),
                    style,
                    styles,
                    strings,
                    epoch1904,
                    &mut shared,
                )?;
                if !parsed.value.is_none() || parsed.formula.is_some() || style != 0 {
                    ws.grow(row_index, column);
                }
                ws.cells.insert(
                    (row_index, column),
                    CellData {
                        value: parsed.value,
                        cached: parsed.cached,
                        formula: parsed.formula,
                        style,
                        merged: false,
                    },
                );
            }
        }
    }

    // Merges: covered cells become empty `MergedCell`s.
    if let Some(merges) = child(root, "mergeCells") {
        for merge in children(merges, "mergeCell") {
            let Some(range) = merge.attribute("ref").and_then(CellRange::parse) else {
                continue;
            };
            ws.grow(range.max_row, range.max_col);
            for r in range.min_row..=range.max_row {
                for c in range.min_col..=range.max_col {
                    if (r, c) == (range.min_row, range.min_col) {
                        continue;
                    }
                    ws.cells.insert(
                        (r, c),
                        CellData {
                            merged: true,
                            ..CellData::default()
                        },
                    );
                }
            }
            ws.merges.push(range);
        }
    }

    // Hyperlinks: the relationship target, else the in-document location.
    if let Some(links) = child(root, "hyperlinks") {
        for link in children(links, "hyperlink") {
            let id = link
                .attributes()
                .find(|a| a.name() == "id" && a.namespace().is_some())
                .map(|a| a.value());
            let target = id
                .and_then(|id| rels.iter().find(|r| r.id == id))
                .map(|r| r.target.clone())
                .filter(|t| !t.is_empty())
                .or_else(|| {
                    link.attribute("location")
                        .filter(|l| !l.is_empty())
                        .map(str::to_string)
                });
            let Some(reference) = link.attribute("ref") else {
                continue;
            };
            let Some(range) = CellRange::parse(reference) else {
                continue;
            };
            let Some(target) = target else {
                continue;
            };
            if reference.contains(':') {
                for r in range.min_row..=range.max_row {
                    for c in range.min_col..=range.max_col {
                        if !ws.cell(r, c).is_some_and(|cell| cell.merged) {
                            bind_hyperlink(&mut ws, (r, c), &target);
                        }
                    }
                }
            } else {
                let mut at = (range.min_row, range.min_col);
                if ws.cell(at.0, at.1).is_some_and(|cell| cell.merged) {
                    if let Some(m) = ws.merges.iter().find(|m| {
                        (m.min_row..=m.max_row).contains(&at.0)
                            && (m.min_col..=m.max_col).contains(&at.1)
                    }) {
                        at = (m.min_row, m.min_col);
                    }
                }
                bind_hyperlink(&mut ws, at, &target);
            }
        }
    }

    // Conditional formatting, grouped by range like openpyxl's list.
    let mut max_priority = 0i64;
    for block in children(root, "conditionalFormatting") {
        let sqref = block.attribute("sqref").unwrap_or_default();
        let mut ranges: Vec<CellRange> = sqref
            .split_whitespace()
            .filter_map(CellRange::parse)
            .collect();
        ranges.sort_by_key(|r| (r.min_col, r.min_row, r.max_col, r.max_row));
        ranges.dedup();
        let mut rules = Vec::new();
        for rule in children(block, "cfRule") {
            max_priority += 1;
            let priority = rule
                .attribute("priority")
                .and_then(|p| p.trim().parse::<i64>().ok())
                .unwrap_or(0);
            let flag = |name| rule.attribute(name).is_some_and(ox_bool);
            rules.push(Rule {
                kind: rule.attribute("type").unwrap_or_default().to_string(),
                priority: if priority != 0 {
                    priority
                } else {
                    max_priority
                },
                dxf: rule
                    .attribute("dxfId")
                    .and_then(|d| d.trim().parse::<usize>().ok())
                    .and_then(|d| styles.dxfs.get(d).cloned()),
                operator: none_set(rule.attribute("operator")),
                text: rule.attribute("text").map(str::to_string),
                rank: rule.attribute("rank").and_then(|r| r.trim().parse().ok()),
                percent: flag("percent"),
                bottom: flag("bottom"),
                above_average: rule.attribute("aboveAverage").map(ox_bool),
                equal_average: flag("equalAverage"),
                formula: children(rule, "formula")
                    .map(|f| f.text().unwrap_or_default().to_string())
                    .collect(),
                color_scale: child(rule, "colorScale").map(|s| {
                    (
                        children(s, "cfvo").map(parse_cfvo).collect(),
                        children(s, "color").map(Color::from_node).collect(),
                    )
                }),
                data_bar: child(rule, "dataBar").map(|b| DataBar {
                    cfvo: children(b, "cfvo").map(parse_cfvo).collect(),
                    color: child(b, "color").map(Color::from_node),
                    min_length: b.attribute("minLength").and_then(|v| v.trim().parse().ok()),
                    max_length: b.attribute("maxLength").and_then(|v| v.trim().parse().ok()),
                    show_value: b.attribute("showValue").map(ox_bool),
                }),
                icon_set: child(rule, "iconSet").map(|i| IconSet {
                    name: none_set(i.attribute("iconSet")),
                    cfvo: children(i, "cfvo").map(parse_cfvo).collect(),
                    show_value: i.attribute("showValue").map(ox_bool),
                    reverse: i.attribute("reverse").is_some_and(ox_bool),
                }),
            });
        }
        match ws.conditional.iter_mut().find(|b| b.ranges == ranges) {
            Some(existing) => existing.rules.extend(rules),
            None => ws.conditional.push(CfBlock { ranges, rules }),
        }
    }

    // Comments (legacy notes) — merged cells cannot hold one.
    for rel in rels.iter().filter(|r| r.kind() == "comments") {
        let Some(text) = read_text(package, &rel.target) else {
            continue;
        };
        let Ok(doc) = parse_xml(&text) else {
            continue;
        };
        let root = doc.root_element();
        let authors: Vec<String> = child(root, "authors")
            .map(|a| {
                children(a, "author")
                    .map(|n| n.text().unwrap_or_default().to_string())
                    .collect()
            })
            .unwrap_or_default();
        let Some(list) = child(root, "commentList") else {
            continue;
        };
        for comment in children(list, "comment") {
            let Some((column, row)) = comment.attribute("ref").and_then(parse_cell) else {
                continue;
            };
            if ws.cell(row, column).is_some_and(|c| c.merged) {
                continue;
            }
            // A note marks its cell in Excel even when the cell is empty.
            ws.grow(row, column);
            let author_id = comment
                .attribute("authorId")
                .and_then(|a| a.trim().parse::<usize>().ok())
                .unwrap_or(0);
            let body = child(comment, "text").map(text_content).unwrap_or_default();
            ws.comments
                .insert((row, column), (authors.get(author_id).cloned(), body));
        }
    }

    for rel in rels.iter().filter(|r| r.kind() == "drawing") {
        let (charts, images) = read_drawing(package, &rel.target);
        ws.charts.extend(charts);
        ws.images.extend(images);
    }
    Ok(ws)
}

// ---------------------------------------------------------------- drawings: charts and images

fn parse_marker(node: Option<roxmltree::Node>) -> Marker {
    let number = |name: &'static str| -> f64 {
        node.and_then(|n| child(n, name))
            .and_then(|n| n.text())
            .and_then(|t| t.trim().parse::<f64>().ok())
            .unwrap_or(0.0)
    };
    Marker {
        col: number("col") as i64,
        row: number("row") as i64,
        col_off: number("colOff"),
        row_off: number("rowOff"),
    }
}

pub fn parse_anchor(anchor: roxmltree::Node) -> Anchor {
    Anchor {
        kind: local(&anchor).to_string(),
        from: parse_marker(child(anchor, "from")),
        to: child(anchor, "to").map(|to| parse_marker(Some(to))),
        ext: if local(&anchor) == "twoCellAnchor" {
            None
        } else {
            child(anchor, "ext").map(|e| {
                (
                    e.attribute("cx")
                        .and_then(|v| v.trim().parse().ok())
                        .unwrap_or(0.0),
                    e.attribute("cy")
                        .and_then(|v| v.trim().parse().ok())
                        .unwrap_or(0.0),
                )
            })
        },
        pos: child(anchor, "pos").map(|p| {
            (
                p.attribute("x")
                    .and_then(|v| v.trim().parse().ok())
                    .unwrap_or(0.0),
                p.attribute("y")
                    .and_then(|v| v.trim().parse().ok())
                    .unwrap_or(0.0),
            )
        }),
    }
}

fn rel_id(node: roxmltree::Node, name: &str) -> Option<String> {
    node.attributes()
        .find(|a| a.name() == name && a.namespace().is_some())
        .map(|a| a.value().to_string())
}

/// openpyxl `find_images`: the drawing's charts and pictures, anchors taken in
/// the order absolute, one-cell, two-cell.
fn read_drawing(package: &Package, part: &str) -> (Vec<Chart>, Vec<Picture>) {
    let Some(text) = read_text(package, part) else {
        return (Vec::new(), Vec::new());
    };
    let Ok(doc) = parse_xml(&text) else {
        return (Vec::new(), Vec::new());
    };
    let rels = package.rels(part);
    let root = doc.root_element();
    let mut anchors = Vec::new();
    for kind in ["absoluteAnchor", "oneCellAnchor", "twoCellAnchor"] {
        anchors.extend(
            root.children()
                .filter(|n| n.is_element() && local(n) == kind),
        );
    }
    let mut charts = Vec::new();
    for anchor in &anchors {
        let Some(chart_ref) = child(*anchor, "graphicFrame")
            .and_then(|g| child(g, "graphic"))
            .and_then(|g| child(g, "graphicData"))
            .and_then(|g| child(g, "chart"))
        else {
            continue;
        };
        let Some(target) =
            rel_id(chart_ref, "id").and_then(|id| rels.iter().find(|r| r.id == id).cloned())
        else {
            continue;
        };
        if let Some(mut chart) = read_chart(package, &target.target) {
            chart.anchor = parse_anchor(*anchor);
            charts.push(chart);
        }
    }
    let mut images = Vec::new();
    for anchor in &anchors {
        let Some(blip) = child(*anchor, "pic")
            .and_then(|p| child(p, "blipFill"))
            .and_then(|b| child(b, "blip"))
        else {
            continue;
        };
        let Some(rel) =
            rel_id(blip, "embed").and_then(|id| rels.iter().find(|r| r.id == id).cloned())
        else {
            continue;
        };
        if rel.kind() != "image" {
            continue;
        }
        let Some(data) = package.bytes(&rel.target) else {
            continue;
        };
        let Some((mime, width, height)) = sniff_image(data) else {
            continue;
        };
        images.push(Picture {
            mime,
            data: data.to_vec(),
            width,
            height,
            anchor: parse_anchor(*anchor),
        });
    }
    (charts, images)
}

fn read_chart(package: &Package, part: &str) -> Option<Chart> {
    let text = read_text(package, part)?;
    let doc = parse_xml(&text).ok()?;
    let chart = child(doc.root_element(), "chart")?;
    let title = child(chart, "title")
        .and_then(|t| child(t, "tx"))
        .and_then(|t| child(t, "rich"))
        .and_then(|r| child(r, "p"))
        .and_then(|p| child(p, "r"))
        .and_then(|r| child(r, "t"))
        .and_then(|t| t.text())
        .filter(|t| !t.is_empty())
        .map(str::to_string);
    let plot = child(chart, "plotArea")?;
    let (node, kind) = plot.children().filter(|n| n.is_element()).find_map(|n| {
        let kind = match local(&n) {
            "barChart" | "bar3DChart" | "scatterChart" | "bubbleChart" | "radarChart"
            | "stockChart" | "surfaceChart" | "surface3DChart" => ChartKind::Bar,
            "lineChart" | "line3DChart" => ChartKind::Line,
            "areaChart" | "area3DChart" => ChartKind::Area,
            "pieChart" | "pie3DChart" | "ofPieChart" => ChartKind::Pie,
            "doughnutChart" => ChartKind::Doughnut,
            _ => return None,
        };
        Some((n, kind))
    })?;
    let formula = |n: Option<roxmltree::Node>| {
        n.and_then(|n| child(n, "f"))
            .and_then(|f| f.text())
            .map(str::to_string)
    };
    let series = children(node, "ser")
        .map(|ser| {
            let val = child(ser, "val").or_else(|| child(ser, "yVal"));
            let cat = child(ser, "cat").or_else(|| child(ser, "xVal"));
            Series {
                val_ref: formula(val.and_then(|v| child(v, "numRef"))),
                val_lit: val.and_then(|v| child(v, "numLit")).map(|lit| {
                    children(lit, "pt")
                        .map(|pt| child(pt, "v").and_then(|v| v.text()).map(str::to_string))
                        .collect()
                }),
                cat_ref: cat.and_then(|c| {
                    formula(child(c, "strRef")).or_else(|| formula(child(c, "numRef")))
                }),
            }
        })
        .collect();
    Some(Chart {
        kind,
        title,
        series,
        anchor: Anchor::default(),
    })
}

/// The picture's MIME type and pixel size (what Pillow reported to openpyxl).
/// Formats a browser cannot show without Pillow's PNG conversion are dropped.
fn sniff_image(data: &[u8]) -> Option<(&'static str, f64, f64)> {
    let be16 = |o: usize| {
        data.get(o..o + 2)
            .map(|b| u16::from_be_bytes([b[0], b[1]]) as f64)
    };
    let be32 = |o: usize| {
        data.get(o..o + 4)
            .map(|b| u32::from_be_bytes([b[0], b[1], b[2], b[3]]) as f64)
    };
    let le16 = |o: usize| {
        data.get(o..o + 2)
            .map(|b| u16::from_le_bytes([b[0], b[1]]) as f64)
    };
    let le32 = |o: usize| {
        data.get(o..o + 4)
            .map(|b| i32::from_le_bytes([b[0], b[1], b[2], b[3]]) as f64)
    };
    if data.starts_with(b"\x89PNG\r\n\x1a\n") {
        return Some(("image/png", be32(16)?, be32(20)?));
    }
    if data.starts_with(b"GIF87a") || data.starts_with(b"GIF89a") {
        return Some(("image/gif", le16(6)?, le16(8)?));
    }
    if data.starts_with(b"BM") {
        return Some(("image/bmp", le32(18)?.abs(), le32(22)?.abs()));
    }
    if data.starts_with(b"\xff\xd8") {
        let mut i = 2;
        while i + 9 < data.len() {
            if data[i] != 0xFF {
                i += 1;
                continue;
            }
            let marker = data[i + 1];
            if (0xC0..=0xCF).contains(&marker) && !matches!(marker, 0xC4 | 0xC8 | 0xCC) {
                return Some(("image/jpeg", be16(i + 7)?, be16(i + 5)?));
            }
            let len = be16(i + 2)? as usize;
            i += 2 + len;
        }
        return None;
    }
    if data.len() > 30 && &data[0..4] == b"RIFF" && &data[8..12] == b"WEBP" {
        let (w, h) = match &data[12..16] {
            b"VP8X" => (
                1.0 + (data[24] as u32 | (data[25] as u32) << 8 | (data[26] as u32) << 16) as f64,
                1.0 + (data[27] as u32 | (data[28] as u32) << 8 | (data[29] as u32) << 16) as f64,
            ),
            b"VP8L" => {
                let b = &data[21..25];
                let bits = u32::from_le_bytes([b[0], b[1], b[2], b[3]]);
                (
                    ((bits & 0x3FFF) + 1) as f64,
                    (((bits >> 14) & 0x3FFF) + 1) as f64,
                )
            }
            _ => (
                le16(26)? as u32 as f64 % 16384.0,
                le16(28)? as u32 as f64 % 16384.0,
            ),
        };
        return Some(("image/webp", w, h));
    }
    None
}
