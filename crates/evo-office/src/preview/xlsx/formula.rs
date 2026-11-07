//! Deterministic, dependency-free evaluator for the XLSX viewer subset (v3
//! `xlsx_formula.py`), and openpyxl's shared-formula translation
//! (`openpyxl.formula.translate`, `openpyxl.formula.tokenizer`).
//!
//! Excel remains the authority for recalculation when a workbook is opened. The
//! viewer still needs concrete display values, so this evaluates a bounded,
//! whitelisted subset (IF, IFERROR, SUM, AVERAGE, MIN, MAX, COUNT, COUNTA, ABS,
//! ROUND, AND, OR, NOT, operators and references) and reports the rest.

use std::collections::{HashMap, HashSet};
use std::sync::OnceLock;

use super::value::{casefold, py_round, py_sum, Value};

/// Why a formula could not be evaluated.
#[derive(Debug, Clone, PartialEq)]
pub struct FormulaError {
    pub message: String,
    /// `ZeroDivisionError` / `OverflowError` in v3: caught per cell, but not by
    /// `IFERROR` (which only catches the evaluator's own errors).
    pub arithmetic: bool,
}

impl FormulaError {
    fn new(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
            arithmetic: false,
        }
    }
    fn arithmetic(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
            arithmetic: true,
        }
    }
}

/// What the evaluator sees of a cell (openpyxl `workbook[sheet][coordinate]`).
#[derive(Debug, Clone, PartialEq)]
pub struct CellView {
    pub value: Value,
    /// The formula text (with `=`) when the cell is a formula, or a string
    /// value starting with `=`. `Some(None)` is a formula v3 could not parse
    /// (array / data-table formulas, which openpyxl returns as objects).
    pub formula: Option<Option<String>>,
}

/// The workbook the evaluator reads (openpyxl `workbook[sheet][coordinate]`;
/// unlike openpyxl, reading a cell never grows the sheet).
pub trait Book {
    fn sheet_exists(&self, name: &str) -> bool;
    fn cell(&self, sheet: &str, row: u32, column: u32) -> Result<CellView, FormulaError>;
    /// Worksheet titles in order, with their used size (rows, columns), for
    /// `evaluate_all`. A sheet without cells reports `None`.
    fn worksheet_extents(&self) -> Vec<(String, Option<(u32, u32)>)>;
}

// ---------------------------------------------------------------- tokens

#[derive(Debug, Clone, PartialEq)]
enum Kind {
    Reference,
    Number,
    Str,
    Identifier,
    Operator,
    Eof,
}

#[derive(Debug, Clone)]
struct Token {
    kind: Kind,
    value: String,
}

fn token_regex() -> &'static regex::Regex {
    static RE: OnceLock<regex::Regex> = OnceLock::new();
    RE.get_or_init(|| {
        regex::Regex::new(concat!(
            r"^\s*(?:",
            r"(?P<reference>(?:(?:'(?:[^']|'')+'|[A-Za-z_][A-Za-z0-9_.]*)!)?",
            r"\$?[A-Za-z]{1,3}\$?[1-9][0-9]*(?::\$?[A-Za-z]{1,3}\$?[1-9][0-9]*)?)|",
            r"(?P<number>(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[Ee][+-]?[0-9]+)?)|",
            r#"(?P<string>"(?:[^"]|"")*")|"#,
            r"(?P<identifier>[A-Za-z_][A-Za-z0-9_.]*)|",
            r"(?P<operator><=|>=|<>|[+\-*/^&=<>%,():])",
            r")"
        ))
        .expect("formula token regex")
    })
}

fn tokenize(formula: &str) -> Result<Vec<Token>, FormulaError> {
    let source = formula.strip_prefix('=').unwrap_or(formula);
    let re = token_regex();
    let mut tokens = Vec::new();
    let mut position = 0;
    while position < source.len() {
        let rest = &source[position..];
        let Some(caps) = re.captures(rest) else {
            let near: String = rest.chars().take(24).collect();
            return Err(FormulaError::new(format!(
                "unsupported token near {near:?}"
            )));
        };
        let (kind, name) = [
            (Kind::Reference, "reference"),
            (Kind::Number, "number"),
            (Kind::Str, "string"),
            (Kind::Identifier, "identifier"),
            (Kind::Operator, "operator"),
        ]
        .into_iter()
        .find(|(_, name)| caps.name(name).is_some())
        .expect("one alternative matched");
        tokens.push(Token {
            kind,
            value: caps[name].to_string(),
        });
        position += caps.get(0).expect("match").end();
    }
    tokens.push(Token {
        kind: Kind::Eof,
        value: String::new(),
    });
    Ok(tokens)
}

// ---------------------------------------------------------------- parser

#[derive(Debug, Clone)]
enum Node {
    Number(Value),
    Str(String),
    Boolean(bool),
    Reference(String),
    Unary(String, Box<Node>),
    Percent(Box<Node>),
    Binary(String, Box<Node>, Box<Node>),
    Function(String, Vec<Node>),
}

struct Parser {
    tokens: Vec<Token>,
    index: usize,
}

impl Parser {
    fn new(formula: &str) -> Result<Self, FormulaError> {
        Ok(Self {
            tokens: tokenize(formula)?,
            index: 0,
        })
    }

    fn token(&self) -> &Token {
        &self.tokens[self.index]
    }

    fn accept(&mut self, value: &str) -> bool {
        if self.token().value != value {
            return false;
        }
        self.index += 1;
        true
    }

    fn require(&mut self, value: &str) -> Result<(), FormulaError> {
        if self.accept(value) {
            Ok(())
        } else {
            Err(FormulaError::new(format!(
                "expected {value:?}, got {:?}",
                self.token().value
            )))
        }
    }

    fn parse(&mut self) -> Result<Node, FormulaError> {
        let node = self.comparison()?;
        if self.token().kind != Kind::Eof {
            return Err(FormulaError::new(format!(
                "unexpected token {:?}",
                self.token().value
            )));
        }
        Ok(node)
    }

    fn comparison(&mut self) -> Result<Node, FormulaError> {
        let mut node = self.concat()?;
        while ["=", "<>", "<", ">", "<=", ">="].contains(&self.token().value.as_str()) {
            let op = self.token().value.clone();
            self.index += 1;
            node = Node::Binary(op, Box::new(node), Box::new(self.concat()?));
        }
        Ok(node)
    }

    fn concat(&mut self) -> Result<Node, FormulaError> {
        let mut node = self.additive()?;
        while self.accept("&") {
            node = Node::Binary("&".into(), Box::new(node), Box::new(self.additive()?));
        }
        Ok(node)
    }

    fn additive(&mut self) -> Result<Node, FormulaError> {
        let mut node = self.multiplicative()?;
        while ["+", "-"].contains(&self.token().value.as_str()) {
            let op = self.token().value.clone();
            self.index += 1;
            node = Node::Binary(op, Box::new(node), Box::new(self.multiplicative()?));
        }
        Ok(node)
    }

    fn multiplicative(&mut self) -> Result<Node, FormulaError> {
        let mut node = self.power()?;
        while ["*", "/"].contains(&self.token().value.as_str()) {
            let op = self.token().value.clone();
            self.index += 1;
            node = Node::Binary(op, Box::new(node), Box::new(self.power()?));
        }
        Ok(node)
    }

    fn power(&mut self) -> Result<Node, FormulaError> {
        let node = self.unary()?;
        if self.accept("^") {
            return Ok(Node::Binary(
                "^".into(),
                Box::new(node),
                Box::new(self.power()?),
            ));
        }
        Ok(node)
    }

    fn unary(&mut self) -> Result<Node, FormulaError> {
        if ["+", "-"].contains(&self.token().value.as_str()) {
            let op = self.token().value.clone();
            self.index += 1;
            return Ok(Node::Unary(op, Box::new(self.unary()?)));
        }
        let mut node = self.primary()?;
        while self.accept("%") {
            node = Node::Percent(Box::new(node));
        }
        Ok(node)
    }

    fn primary(&mut self) -> Result<Node, FormulaError> {
        let token = self.token().clone();
        if self.accept("(") {
            let node = self.comparison()?;
            self.require(")")?;
            return Ok(node);
        }
        match token.kind {
            Kind::Number => {
                self.index += 1;
                let value: f64 = token.value.parse().unwrap_or(0.0);
                let number = if value.fract() == 0.0 && value.abs() < 1e38 {
                    Value::Int(value as i128)
                } else {
                    Value::Float(value)
                };
                Ok(Node::Number(number))
            }
            Kind::Str => {
                self.index += 1;
                let inner = &token.value[1..token.value.len() - 1];
                Ok(Node::Str(inner.replace("\"\"", "\"")))
            }
            Kind::Reference => {
                self.index += 1;
                Ok(Node::Reference(token.value))
            }
            Kind::Identifier => {
                self.index += 1;
                let name = token.value.to_uppercase();
                if name == "TRUE" || name == "FALSE" {
                    return Ok(Node::Boolean(name == "TRUE"));
                }
                if !self.accept("(") {
                    return Err(FormulaError::new(format!(
                        "unsupported name {:?}",
                        token.value
                    )));
                }
                let mut arguments = Vec::new();
                if !self.accept(")") {
                    loop {
                        arguments.push(self.comparison()?);
                        if self.accept(")") {
                            break;
                        }
                        if !(self.accept(",") || self.accept(":")) {
                            return Err(FormulaError::new(format!(
                                "expected function separator, got {:?}",
                                self.token().value
                            )));
                        }
                    }
                }
                Ok(Node::Function(name, arguments))
            }
            _ => Err(FormulaError::new(format!(
                "unexpected token {:?}",
                token.value
            ))),
        }
    }
}

// ---------------------------------------------------------------- values

fn flatten(values: &[Value]) -> Vec<Value> {
    let mut out = Vec::new();
    for value in values {
        match value {
            Value::List(items) => out.extend(flatten(items)),
            other => out.push(other.clone()),
        }
    }
    out
}

fn type_name(value: &Value) -> &'static str {
    match value {
        Value::None => "NoneType",
        Value::Bool(_) => "bool",
        Value::Int(_) => "int",
        Value::Float(_) => "float",
        Value::Str(_) => "str",
        Value::Date(_) => "date",
        Value::DateTime(_) => "datetime",
        Value::Time(_) => "time",
        Value::Duration(_) => "timedelta",
        Value::List(_) => "list",
    }
}

/// v3 `_number`.
fn number(value: &Value) -> Result<f64, FormulaError> {
    match value {
        Value::None => Ok(0.0),
        Value::Str(s) if s.is_empty() => Ok(0.0),
        Value::Bool(b) => Ok(if *b { 1.0 } else { 0.0 }),
        Value::Int(_) | Value::Float(_) => {
            let f = value.py_float().unwrap_or(f64::NAN);
            if f.is_finite() {
                Ok(f)
            } else {
                Err(FormulaError::new(format!(
                    "{} is not numeric",
                    type_name(value)
                )))
            }
        }
        Value::Str(s) => super::value::parse_py_float(s)
            .ok_or_else(|| FormulaError::new(format!("{s:?} is not numeric"))),
        other => Err(FormulaError::new(format!(
            "{} is not numeric",
            type_name(other)
        ))),
    }
}

fn numeric_values(values: &[Value]) -> Vec<f64> {
    flatten(values)
        .iter()
        .filter(|v| !(v.is_blank() || matches!(v, Value::Bool(_))))
        .filter_map(|v| number(v).ok())
        .collect()
}

fn truthy(value: &Value) -> bool {
    match value {
        Value::List(_) => flatten(std::slice::from_ref(value)).iter().any(truthy),
        Value::Str(s) => !matches!(casefold(s).as_str(), "" | "false" | "0"),
        other => other.truthy(),
    }
}

/// `str(value or "")`.
fn or_empty_str(value: &Value) -> String {
    if value.truthy() {
        value.py_str()
    } else {
        String::new()
    }
}

fn split_reference(reference: &str, current_sheet: &str) -> (String, String) {
    match reference.rsplit_once('!') {
        None => (
            current_sheet.to_string(),
            reference.replace('$', "").to_uppercase(),
        ),
        Some((sheet, address)) => {
            let sheet = if sheet.len() >= 2 && sheet.starts_with('\'') && sheet.ends_with('\'') {
                sheet[1..sheet.len() - 1].replace("''", "'")
            } else {
                sheet.to_string()
            };
            (sheet, address.replace('$', "").to_uppercase())
        }
    }
}

/// A1 column letters → 1-based index.
pub fn column_index(letters: &str) -> Option<u32> {
    if letters.is_empty() || letters.len() > 3 {
        return None;
    }
    let mut index = 0u32;
    for c in letters.chars() {
        if !c.is_ascii_alphabetic() {
            return None;
        }
        index = index * 26 + (c.to_ascii_uppercase() as u32 - 'A' as u32 + 1);
    }
    Some(index)
}

/// 1-based column index → letters (openpyxl `get_column_letter`, 1..=18278).
pub fn column_letter(mut index: u32) -> String {
    let mut letters = Vec::new();
    while index > 0 {
        let rem = (index - 1) % 26;
        letters.push((b'A' + rem as u8) as char);
        index = (index - 1) / 26;
    }
    letters.iter().rev().collect()
}

/// Split `A1` into (column, row).
pub fn parse_cell(text: &str) -> Option<(u32, u32)> {
    let text = text.replace('$', "");
    let split = text.find(|c: char| c.is_ascii_digit())?;
    let column = column_index(&text[..split])?;
    let row: u32 = text[split..].parse().ok()?;
    (row > 0).then_some((column, row))
}

/// openpyxl `range_boundaries` for `A1` / `A1:B2` / `A:B` / `1:2`:
/// (min_col, min_row, max_col, max_row), `None` for open edges.
pub type Bounds = (Option<u32>, Option<u32>, Option<u32>, Option<u32>);

pub fn range_boundaries(text: &str) -> Option<Bounds> {
    let text = text.replace('$', "");
    let (first, second) = match text.split_once(':') {
        Some((a, b)) => (a.to_string(), Some(b.to_string())),
        None => (text.clone(), None),
    };
    let part = |s: &str| -> Option<(Option<u32>, Option<u32>)> {
        let split = s.find(|c: char| c.is_ascii_digit()).unwrap_or(s.len());
        let (letters, digits) = s.split_at(split);
        let column = if letters.is_empty() {
            None
        } else {
            Some(column_index(letters)?)
        };
        let row = if digits.is_empty() {
            None
        } else {
            Some(digits.parse::<u32>().ok().filter(|r| *r > 0)?)
        };
        if column.is_none() && row.is_none() {
            return None;
        }
        Some((column, row))
    };
    let (c1, r1) = part(&first)?;
    let (c2, r2) = match second {
        Some(s) => part(&s)?,
        None => (c1, r1),
    };
    Some((c1, r1, c2, r2))
}

// ---------------------------------------------------------------- evaluation

/// One formula that could not be evaluated.
#[derive(Debug, Clone, PartialEq)]
pub struct Issue {
    pub code: &'static str,
    pub message: String,
    pub sheet: String,
    pub cell: String,
}

/// v3 `FormulaEvaluation`.
pub struct Evaluation<'a, B: Book + ?Sized> {
    book: &'a B,
    pub values: HashMap<(String, String), Value>,
    pub issues: Vec<Issue>,
    pub formula_count: usize,
    pub evaluated_count: usize,
    visiting: HashSet<(String, String)>,
    failed: HashSet<(String, String)>,
}

/// Cells a single reference may cover before evaluation gives up (v3 had no
/// bound; a whole-sheet range would hang it).
const MAX_RANGE_CELLS: u64 = 5_000_000;

impl<'a, B: Book + ?Sized> Evaluation<'a, B> {
    pub fn new(book: &'a B) -> Self {
        Self {
            book,
            values: HashMap::new(),
            issues: Vec::new(),
            formula_count: 0,
            evaluated_count: 0,
            visiting: HashSet::new(),
            failed: HashSet::new(),
        }
    }

    /// v3 `evaluate_workbook_formulas`: evaluate every formula, row by row.
    pub fn evaluate_all(mut self) -> Self {
        for (title, extent) in self.book.worksheet_extents() {
            let Some((max_row, max_column)) = extent else {
                continue;
            };
            for row in 1..=max_row {
                for column in 1..=max_column {
                    let Ok(cell) = self.book.cell(&title, row, column) else {
                        continue;
                    };
                    if cell.formula.is_some() {
                        self.formula_count += 1;
                        let coordinate = format!("{}{row}", column_letter(column));
                        let _ = self.cell_value(&title, &coordinate);
                    }
                }
            }
        }
        self.evaluated_count = self.formula_count.saturating_sub(self.failed.len());
        self
    }

    pub fn cell_value(&mut self, sheet: &str, coordinate: &str) -> Result<Value, FormulaError> {
        let key = (
            sheet.to_string(),
            coordinate.replace('$', "").to_uppercase(),
        );
        if let Some(value) = self.values.get(&key) {
            return Ok(value.clone());
        }
        if self.visiting.contains(&key) {
            self.record_failure(&key, "formula-cycle", "circular reference");
            return Err(FormulaError::new("circular reference"));
        }
        if !self.book.sheet_exists(sheet) {
            return Err(FormulaError::new(format!(
                "worksheet {sheet:?} does not exist"
            )));
        }
        let (column, row) = parse_cell(&key.1)
            .ok_or_else(|| FormulaError::new(format!("{} is not a valid coordinate", key.1)))?;
        let cell = self.book.cell(sheet, row, column)?;
        let Some(formula) = cell.formula else {
            return Ok(cell.value);
        };
        self.visiting.insert(key.clone());
        let result = match formula {
            Some(text) => Parser::new(&text)
                .and_then(|mut p| p.parse())
                .and_then(|node| self.evaluate(&node, sheet)),
            None => Err(FormulaError::new("unsupported token near '<'")),
        };
        self.visiting.remove(&key);
        match result {
            Ok(value) => {
                self.values.insert(key, value.clone());
                Ok(value)
            }
            Err(error) => {
                self.record_failure(&key, "formula-evaluation-failed", &error.message);
                Err(FormulaError::new(error.message))
            }
        }
    }

    /// The evaluated value, else `fallback`.
    pub fn display_value(&mut self, sheet: &str, coordinate: &str, fallback: Value) -> Value {
        self.cell_value(sheet, coordinate).unwrap_or(fallback)
    }

    fn reference_values(
        &mut self,
        reference: &str,
        current: &str,
    ) -> Result<Vec<Value>, FormulaError> {
        let (sheet, address) = split_reference(reference, current);
        if !self.book.sheet_exists(&sheet) {
            return Err(FormulaError::new(format!(
                "worksheet {sheet:?} does not exist"
            )));
        }
        let Some((Some(c1), Some(r1), Some(c2), Some(r2))) = range_boundaries(&address) else {
            return Err(FormulaError::new(format!("{address} is not a valid range")));
        };
        // openpyxl accepts reversed ranges (`B2:A1`); they cover no cells.
        if c1 <= c2 && r1 <= r2 && (c2 - c1 + 1) as u64 * (r2 - r1 + 1) as u64 > MAX_RANGE_CELLS {
            return Err(FormulaError::new(format!("{address} is too large")));
        }
        let mut values = Vec::new();
        for row in r1..=r2 {
            for column in c1..=c2 {
                self.book.cell(&sheet, row, column)?;
                let coordinate = format!("{}{row}", column_letter(column));
                values.push(self.cell_value(&sheet, &coordinate)?);
            }
        }
        Ok(values)
    }

    fn record_failure(&mut self, key: &(String, String), code: &'static str, detail: &str) {
        if !self.failed.insert(key.clone()) {
            return;
        }
        self.issues.push(Issue {
            code,
            message: format!("{}!{} could not be evaluated: {detail}", key.0, key.1),
            sheet: key.0.clone(),
            cell: key.1.clone(),
        });
    }

    fn evaluate(&mut self, node: &Node, sheet: &str) -> Result<Value, FormulaError> {
        match node {
            Node::Number(v) => Ok(v.clone()),
            Node::Str(s) => Ok(Value::Str(s.clone())),
            Node::Boolean(b) => Ok(Value::Bool(*b)),
            Node::Reference(reference) => {
                let values = self.reference_values(reference, sheet)?;
                if reference.contains(':') {
                    Ok(Value::List(values))
                } else {
                    Ok(values.into_iter().next().unwrap_or(Value::None))
                }
            }
            Node::Unary(op, inner) => {
                let value = number(&self.evaluate(inner, sheet)?)?;
                Ok(Value::Float(if op == "+" { value } else { -value }))
            }
            Node::Percent(inner) => {
                Ok(Value::Float(number(&self.evaluate(inner, sheet)?)? / 100.0))
            }
            Node::Binary(op, left, right) => {
                let left = self.evaluate(left, sheet)?;
                let right = self.evaluate(right, sheet)?;
                binary(op, &left, &right)
            }
            Node::Function(name, arguments) => self.function(name, arguments, sheet),
        }
    }

    fn function(
        &mut self,
        name: &str,
        arguments: &[Node],
        sheet: &str,
    ) -> Result<Value, FormulaError> {
        if name == "IF" {
            if !(2..=3).contains(&arguments.len()) {
                return Err(FormulaError::new("IF expects two or three arguments"));
            }
            let condition = self.evaluate(&arguments[0], sheet)?;
            return if truthy(&condition) {
                self.evaluate(&arguments[1], sheet)
            } else if arguments.len() == 3 {
                self.evaluate(&arguments[2], sheet)
            } else {
                Ok(Value::Bool(false))
            };
        }
        if name == "IFERROR" {
            if arguments.len() != 2 {
                return Err(FormulaError::new("IFERROR expects two arguments"));
            }
            return match self.evaluate(&arguments[0], sheet) {
                Err(error) if !error.arithmetic => self.evaluate(&arguments[1], sheet),
                other => other,
            };
        }
        let mut values = Vec::with_capacity(arguments.len());
        for argument in arguments {
            values.push(self.evaluate(argument, sheet)?);
        }
        let flattened = flatten(&values);
        let numbers = numeric_values(&values);
        match name {
            "SUM" => Ok(py_sum(&numbers)),
            "AVERAGE" => {
                if numbers.is_empty() {
                    return Err(FormulaError::new("AVERAGE has no numeric values"));
                }
                let total = py_sum(&numbers).py_float().unwrap_or(0.0);
                Ok(Value::Float(total / numbers.len() as f64))
            }
            "MIN" | "MAX" => {
                if numbers.is_empty() {
                    return Err(FormulaError::new(format!("{name} has no numeric values")));
                }
                let mut best = numbers[0];
                for &n in &numbers[1..] {
                    if (name == "MIN" && n < best) || (name == "MAX" && n > best) {
                        best = n;
                    }
                }
                Ok(Value::Float(best))
            }
            "COUNT" => Ok(Value::Int(numbers.len() as i128)),
            "COUNTA" => Ok(Value::Int(
                flattened.iter().filter(|v| !v.is_blank()).count() as i128,
            )),
            "ABS" if flattened.len() == 1 => Ok(Value::Float(number(&flattened[0])?.abs())),
            "ROUND" if flattened.len() == 2 => {
                let value = number(&flattened[0])?;
                let digits = number(&flattened[1])?;
                if !digits.is_finite() {
                    return Err(FormulaError::arithmetic("cannot convert float to integer"));
                }
                Ok(Value::Float(py_round(value, digits.trunc() as i64)))
            }
            "AND" => Ok(Value::Bool(flattened.iter().all(truthy))),
            "OR" => Ok(Value::Bool(flattened.iter().any(truthy))),
            "NOT" if flattened.len() == 1 => Ok(Value::Bool(!truthy(&flattened[0]))),
            _ => Err(FormulaError::new(format!("unsupported function {name}"))),
        }
    }
}

fn binary(op: &str, left: &Value, right: &Value) -> Result<Value, FormulaError> {
    if op == "&" {
        let text = |v: &Value| {
            if v.is_none() {
                String::new()
            } else {
                v.py_str()
            }
        };
        return Ok(Value::Str(format!("{}{}", text(left), text(right))));
    }
    if ["=", "<>", "<", ">", "<=", ">="].contains(&op) {
        let ordering = match (number(left), number(right)) {
            (Ok(a), Ok(b)) => a.partial_cmp(&b),
            _ => Some(casefold(&or_empty_str(left)).cmp(&casefold(&or_empty_str(right)))),
        };
        use std::cmp::Ordering::*;
        let result = match (op, ordering) {
            ("=", o) => o == Some(Equal),
            ("<>", o) => o != Some(Equal),
            ("<", o) => o == Some(Less),
            (">", o) => o == Some(Greater),
            ("<=", o) => matches!(o, Some(Less | Equal)),
            (">=", o) => matches!(o, Some(Greater | Equal)),
            _ => false,
        };
        return Ok(Value::Bool(result));
    }
    let first = number(left)?;
    let second = number(right)?;
    match op {
        "+" => Ok(Value::Float(first + second)),
        "-" => Ok(Value::Float(first - second)),
        "*" => Ok(Value::Float(first * second)),
        "/" => {
            if second == 0.0 {
                return Err(FormulaError::new("division by zero"));
            }
            Ok(Value::Float(first / second))
        }
        "^" => {
            if first == 0.0 && second < 0.0 {
                return Err(FormulaError::arithmetic(
                    "0.0 cannot be raised to a negative power",
                ));
            }
            if first < 0.0 && second.fract() != 0.0 && second.is_finite() {
                // Python returns a complex number here; the viewer cannot show it.
                return Err(FormulaError::arithmetic("complex result"));
            }
            let result = first.powf(second);
            if result.is_infinite() && first.is_finite() && second.is_finite() {
                return Err(FormulaError::arithmetic("Numerical result out of range"));
            }
            Ok(Value::Float(result))
        }
        other => Err(FormulaError::new(format!("unsupported operator {other}"))),
    }
}

// ---------------------------------------------------------------- shared formulas

#[derive(Debug, Clone, Copy, PartialEq)]
enum TokType {
    Literal,
    Operand,
    Func,
    Array,
    Paren,
    Sep,
    OpPre,
    OpIn,
    OpPost,
    WSpace,
}

#[derive(Debug, Clone, Copy, PartialEq)]
enum TokSub {
    None,
    Text,
    Number,
    Logical,
    Error,
    Range,
    Open,
    Close,
    Arg,
    Row,
}

#[derive(Debug, Clone)]
struct XlToken {
    value: String,
    kind: TokType,
    sub: TokSub,
}

impl XlToken {
    fn operand(value: String) -> Self {
        let sub = if value.starts_with('"') {
            TokSub::Text
        } else if value.starts_with('#') {
            TokSub::Error
        } else if value == "TRUE" || value == "FALSE" {
            TokSub::Logical
        } else if super::value::parse_py_float(&value).is_some() {
            TokSub::Number
        } else {
            TokSub::Range
        };
        Self {
            value,
            kind: TokType::Operand,
            sub,
        }
    }

    fn subexp(value: String, func: bool) -> Self {
        let kind = if func {
            TokType::Func
        } else if value == "{" || value == "}" {
            TokType::Array
        } else if value == "(" || value == ")" {
            TokType::Paren
        } else {
            TokType::Func
        };
        let sub = if value == ")" || value == "}" {
            TokSub::Close
        } else {
            TokSub::Open
        };
        Self { value, kind, sub }
    }
}

const ERROR_CODES: [&str; 8] = [
    "#NULL!",
    "#DIV/0!",
    "#VALUE!",
    "#REF!",
    "#NAME?",
    "#NUM!",
    "#N/A",
    "#GETTING_DATA",
];

/// openpyxl `Tokenizer`.
fn xl_tokenize(formula: &str) -> Result<Vec<XlToken>, String> {
    let chars: Vec<char> = formula.chars().collect();
    let mut items: Vec<XlToken> = Vec::new();
    if chars.is_empty() {
        return Ok(items);
    }
    if chars[0] != '=' {
        items.push(XlToken {
            value: formula.to_string(),
            kind: TokType::Literal,
            sub: TokSub::None,
        });
        return Ok(items);
    }
    let mut stack: Vec<XlToken> = Vec::new();
    let mut token: Vec<char> = Vec::new();
    let mut offset = 1;
    let err = |what: &str| Err(format!("{what} in {formula}"));
    let save = |token: &mut Vec<char>, items: &mut Vec<XlToken>| {
        if !token.is_empty() {
            items.push(XlToken::operand(token.iter().collect()));
            token.clear();
        }
    };
    let sci = |token: &[char]| {
        let t: String = token.iter().collect();
        let b = t.as_bytes();
        let n = b.len();
        n >= 2
            && (b'1'..=b'9').contains(&b[0])
            && matches!(b[n - 1], b'E' | b'e')
            && (n == 2 || (b[1] == b'.' && n > 3 && b[2..n - 1].iter().all(u8::is_ascii_digit)))
    };
    while offset < chars.len() {
        let c = chars[offset];
        if matches!(c, '+' | '-') && !token.is_empty() && sci(&token) {
            token.push(c);
            offset += 1;
            continue;
        }
        if ",;}) +-*/^&=><%".contains(c) {
            save(&mut token, &mut items);
        }
        match c {
            '"' | '\'' => {
                if token.last().is_some_and(|&l| l != ':') {
                    return err("Unexpected character");
                }
                let mut i = offset + 1;
                let end = loop {
                    let Some(j) = chars[i..].iter().position(|&x| x == c).map(|p| p + i) else {
                        return err("Reached end of formula while parsing string");
                    };
                    if chars.get(j + 1) == Some(&c) {
                        i = j + 2;
                        continue;
                    }
                    break j + 1;
                };
                let text: String = chars[offset..end].iter().collect();
                if c == '"' {
                    items.push(XlToken::operand(text));
                } else {
                    token.extend(text.chars());
                }
                offset = end;
            }
            '[' => {
                let mut depth = 0i32;
                let mut end = None;
                for (i, &ch) in chars.iter().enumerate().skip(offset) {
                    if ch == '[' {
                        depth += 1;
                    } else if ch == ']' {
                        depth -= 1;
                    }
                    if depth == 0 {
                        end = Some(i + 1);
                        break;
                    }
                }
                let Some(end) = end else {
                    return err("Encountered unmatched '['");
                };
                token.extend(&chars[offset..end]);
                offset = end;
            }
            '#' => {
                if token.last().is_some_and(|&l| l != '!') {
                    return err("Unexpected character");
                }
                let rest: String = chars[offset..].iter().collect();
                let Some(code) = ERROR_CODES.iter().find(|e| rest.starts_with(*e)) else {
                    return err("Invalid error code");
                };
                let value: String = token.iter().collect::<String>() + code;
                items.push(XlToken::operand(value));
                token.clear();
                offset += code.chars().count();
            }
            ' ' | '\n' => {
                items.push(XlToken {
                    value: c.to_string(),
                    kind: TokType::WSpace,
                    sub: TokSub::None,
                });
                while offset < chars.len() && matches!(chars[offset], ' ' | '\n') {
                    offset += 1;
                }
            }
            '+' | '-' | '*' | '/' | '^' | '&' | '=' | '>' | '<' | '%' => {
                let two: String = chars[offset..(offset + 2).min(chars.len())]
                    .iter()
                    .collect();
                if [">=", "<=", "<>"].contains(&two.as_str()) {
                    items.push(XlToken {
                        value: two,
                        kind: TokType::OpIn,
                        sub: TokSub::None,
                    });
                    offset += 2;
                    continue;
                }
                let kind = if c == '%' {
                    TokType::OpPost
                } else if "*/^&=><".contains(c) {
                    TokType::OpIn
                } else {
                    let prev = items.iter().rev().find(|t| t.kind != TokType::WSpace);
                    let infix = prev.is_some_and(|p| {
                        p.sub == TokSub::Close
                            || p.kind == TokType::OpPost
                            || p.kind == TokType::Operand
                    });
                    if infix {
                        TokType::OpIn
                    } else {
                        TokType::OpPre
                    }
                };
                items.push(XlToken {
                    value: c.to_string(),
                    kind,
                    sub: TokSub::None,
                });
                offset += 1;
            }
            '{' | '(' => {
                let tok = if c == '{' {
                    if !token.is_empty() {
                        return err("Unexpected character");
                    }
                    XlToken::subexp("{".into(), false)
                } else if !token.is_empty() {
                    let value: String = token.iter().collect::<String>() + "(";
                    token.clear();
                    XlToken::subexp(value, false)
                } else {
                    XlToken::subexp("(".into(), false)
                };
                stack.push(tok.clone());
                items.push(tok);
                offset += 1;
            }
            ')' | '}' => {
                let Some(open) = stack.pop() else {
                    return err("Mismatched ( and { pair");
                };
                let closer = if open.kind == TokType::Array {
                    "}"
                } else {
                    ")"
                };
                let tok = XlToken::subexp(closer.into(), open.kind == TokType::Func);
                if !tok.value.starts_with(c) {
                    return err("Mismatched ( and { pair");
                }
                items.push(tok);
                offset += 1;
            }
            ';' | ',' => {
                let tok = if c == ';' {
                    XlToken {
                        value: ";".into(),
                        kind: TokType::Sep,
                        sub: TokSub::Row,
                    }
                } else if stack.last().is_none_or(|t| t.kind == TokType::Paren) {
                    XlToken {
                        value: ",".into(),
                        kind: TokType::OpIn,
                        sub: TokSub::None,
                    }
                } else {
                    XlToken {
                        value: ",".into(),
                        kind: TokType::Sep,
                        sub: TokSub::Arg,
                    }
                };
                items.push(tok);
                offset += 1;
            }
            other => {
                token.push(other);
                offset += 1;
            }
        }
    }
    save(&mut token, &mut items);
    Ok(items)
}

/// openpyxl `Translator`: a shared formula moved from `origin` to `dest`.
pub fn translate_shared(
    formula: &str,
    origin: (u32, u32),
    dest: (u32, u32),
) -> Result<String, String> {
    let tokens = xl_tokenize(formula)?;
    if tokens.is_empty() {
        return Ok(String::new());
    }
    if tokens[0].kind == TokType::Literal {
        return Ok(tokens[0].value.clone());
    }
    let row_delta = dest.1 as i64 - origin.1 as i64;
    let col_delta = dest.0 as i64 - origin.0 as i64;
    let mut out = String::from("=");
    for token in &tokens {
        if token.kind == TokType::Operand && token.sub == TokSub::Range {
            out.push_str(&translate_range(&token.value, row_delta, col_delta)?);
        } else {
            out.push_str(&token.value);
        }
    }
    Ok(out)
}

fn translate_row(row: &str, delta: i64) -> Result<String, String> {
    if row.starts_with('$') {
        return Ok(row.to_string());
    }
    let new = row.parse::<i64>().map_err(|e| e.to_string())? + delta;
    if new <= 0 {
        return Err("Formula out of range".into());
    }
    Ok(new.to_string())
}

fn translate_col(col: &str, delta: i64) -> Result<String, String> {
    if col.starts_with('$') {
        return Ok(col.to_string());
    }
    let index = column_index(col).ok_or("Formula out of range")? as i64 + delta;
    if !(1..=18278).contains(&index) {
        return Err("Formula out of range".into());
    }
    Ok(column_letter(index as u32))
}

fn translate_range(range: &str, row_delta: i64, col_delta: i64) -> Result<String, String> {
    static ROW_RANGE: OnceLock<regex::Regex> = OnceLock::new();
    static COL_RANGE: OnceLock<regex::Regex> = OnceLock::new();
    static CELL: OnceLock<regex::Regex> = OnceLock::new();
    let (ws_part, range) = match range.rsplit_once('!') {
        Some((sheet, rest)) => (format!("{sheet}!"), rest),
        None => (String::new(), range),
    };
    let row_range = ROW_RANGE.get_or_init(|| {
        regex::Regex::new(r"^(\$?[1-9][0-9]{0,6}):(\$?[1-9][0-9]{0,6})$").expect("re")
    });
    if let Some(m) = row_range.captures(range) {
        return Ok(format!(
            "{ws_part}{}:{}",
            translate_row(&m[1], row_delta)?,
            translate_row(&m[2], row_delta)?
        ));
    }
    let col_range = COL_RANGE
        .get_or_init(|| regex::Regex::new(r"^(\$?[A-Za-z]{1,3}):(\$?[A-Za-z]{1,3})$").expect("re"));
    if let Some(m) = col_range.captures(range) {
        return Ok(format!(
            "{ws_part}{}:{}",
            translate_col(&m[1], col_delta)?,
            translate_col(&m[2], col_delta)?
        ));
    }
    if range.contains(':') {
        let pieces: Result<Vec<String>, String> = range
            .split(':')
            .map(|p| translate_range(p, row_delta, col_delta))
            .collect();
        return Ok(format!("{ws_part}{}", pieces?.join(":")));
    }
    let cell = CELL.get_or_init(|| {
        regex::Regex::new(r"^(\$?[A-Za-z]{1,3})(\$?[1-9][0-9]{0,6})$").expect("re")
    });
    let Some(m) = cell.captures(range) else {
        return Ok(range.to_string());
    };
    Ok(format!(
        "{ws_part}{}{}",
        translate_col(&m[1], col_delta)?,
        translate_row(&m[2], row_delta)?
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn translates_shared_formulas_like_openpyxl() {
        assert_eq!(
            translate_shared("=A1*2 +  $A$1", (2, 1), (2, 3)).unwrap(),
            "=A3*2 + $A$1"
        );
        assert_eq!(
            translate_shared("=SUM(A1:B2)+Sheet1!C3", (1, 1), (2, 2)).unwrap(),
            "=SUM(B2:C3)+Sheet1!D4"
        );
        assert_eq!(
            translate_shared("='My Sheet'!A1&\"A1\"", (1, 1), (1, 2)).unwrap(),
            "='My Sheet'!A2&\"A1\""
        );
        assert_eq!(
            translate_shared("=1E+3+a1", (1, 1), (1, 2)).unwrap(),
            "=1E+3+A2"
        );
        assert!(translate_shared("=A1", (1, 2), (1, 1)).is_err());
    }

    #[test]
    fn tokenizes_like_v3() {
        let kinds: Vec<Kind> = tokenize("=SUM('My Sheet'!A1:B2)*2.5%")
            .unwrap()
            .into_iter()
            .map(|t| t.kind)
            .collect();
        assert_eq!(
            kinds,
            vec![
                Kind::Identifier,
                Kind::Operator,
                Kind::Reference,
                Kind::Operator,
                Kind::Operator,
                Kind::Number,
                Kind::Operator,
                Kind::Eof
            ]
        );
        assert!(tokenize("=A1 ").is_err());
        assert!(tokenize("={1,2}").is_err());
    }

    #[test]
    fn ranges_and_letters() {
        assert_eq!(column_letter(1), "A");
        assert_eq!(column_letter(28), "AB");
        assert_eq!(column_index("xfd"), Some(16384));
        assert_eq!(
            range_boundaries("$B$2:$C$9"),
            Some((Some(2), Some(2), Some(3), Some(9)))
        );
        assert_eq!(
            range_boundaries("A:A"),
            Some((Some(1), None, Some(1), None))
        );
        assert_eq!(parse_cell("AA10"), Some((27, 10)));
    }

    type TestCells = std::cell::RefCell<HashMap<(u32, u32), Value>>;

    /// An in-memory workbook like openpyxl's `Workbook()` in v3's tests:
    /// strings starting with `=` are formulas.
    struct TestBook {
        sheets: Vec<(&'static str, TestCells)>,
    }

    impl TestBook {
        fn new(sheets: &[(&'static str, &[(&str, Value)])]) -> Self {
            Self {
                sheets: sheets
                    .iter()
                    .map(|(name, cells)| {
                        let map = cells
                            .iter()
                            .map(|(coordinate, value)| {
                                let (column, row) = parse_cell(coordinate).unwrap();
                                ((row, column), value.clone())
                            })
                            .collect();
                        (*name, std::cell::RefCell::new(map))
                    })
                    .collect(),
            }
        }
    }

    impl Book for TestBook {
        fn sheet_exists(&self, name: &str) -> bool {
            self.sheets.iter().any(|(n, _)| *n == name)
        }

        fn cell(&self, sheet: &str, row: u32, column: u32) -> Result<CellView, FormulaError> {
            let (_, cells) = self
                .sheets
                .iter()
                .find(|(n, _)| *n == sheet)
                .expect("sheet");
            let value = cells.borrow_mut().entry((row, column)).or_default().clone();
            let formula = match &value {
                Value::Str(s) if s.starts_with('=') => Some(Some(s.clone())),
                _ => None,
            };
            Ok(CellView {
                value: if formula.is_some() {
                    Value::None
                } else {
                    value
                },
                formula,
            })
        }

        fn worksheet_extents(&self) -> Vec<(String, Option<(u32, u32)>)> {
            self.sheets
                .iter()
                .map(|(name, cells)| {
                    let cells = cells.borrow();
                    let rows = cells.keys().map(|k| k.0).max();
                    let columns = cells.keys().map(|k| k.1).max();
                    (name.to_string(), rows.zip(columns))
                })
                .collect()
        }
    }

    fn s(text: &str) -> Value {
        Value::Str(text.to_string())
    }

    /// v3 `test_evaluates_cross_sheet_dependencies_ranges_and_core_functions`.
    #[test]
    fn evaluates_cross_sheet_dependencies_ranges_and_core_functions() {
        let book = TestBook::new(&[
            (
                "Assumptions",
                &[("B1", Value::Int(100)), ("B2", Value::Float(0.1))],
            ),
            (
                "Forecast",
                &[
                    ("B1", s("='Assumptions'!B1")),
                    ("B2", s("=B1*(1+'Assumptions'!B2)")),
                    ("B3", s("=B2*(1+'Assumptions'!B2)")),
                ],
            ),
            (
                "Dashboard",
                &[
                    ("B1", s("=SUM('Forecast'!B1:B3)")),
                    ("B2", s("=AVERAGE('Forecast'!B1:B3)")),
                    ("B3", s("=MAX('Forecast'!B1:B3)")),
                    ("B4", s("=IF(B3>120,\"ready\",\"wait\")")),
                ],
            ),
        ]);
        let evaluation = Evaluation::new(&book).evaluate_all();
        assert_eq!(evaluation.formula_count, 7);
        assert_eq!(evaluation.evaluated_count, 7);
        assert!(evaluation.issues.is_empty());
        let value = |sheet: &str, cell: &str| {
            evaluation.values[&(sheet.to_string(), cell.to_string())].clone()
        };
        assert!((value("Forecast", "B3").py_float().unwrap() - 121.0).abs() < 1e-9);
        assert!((value("Dashboard", "B1").py_float().unwrap() - 331.0).abs() < 1e-9);
        assert_eq!(
            super::super::value::py_round(value("Dashboard", "B2").py_float().unwrap(), 4),
            110.3333
        );
        assert_eq!(value("Dashboard", "B4"), s("ready"));
        assert_eq!(
            super::super::numfmt::format_computed_value(&Value::Float(0.125), "0.0%"),
            "12.5%"
        );
    }

    /// v3 `test_reports_unsupported_functions_and_cycles_without_aborting_scan`.
    #[test]
    fn reports_unsupported_functions_and_cycles_without_aborting_scan() {
        let book = TestBook::new(&[(
            "Sheet1",
            &[
                ("A1", s("=A2")),
                ("A2", s("=A1")),
                ("B1", s("=XLOOKUP(1,C1:C2,D1:D2)")),
                ("C1", Value::Int(1)),
                ("D1", Value::Int(2)),
            ],
        )]);
        let evaluation = Evaluation::new(&book).evaluate_all();
        assert_eq!(evaluation.formula_count, 3);
        assert_eq!(evaluation.evaluated_count, 0);
        let codes: HashSet<&str> = evaluation.issues.iter().map(|i| i.code).collect();
        assert_eq!(
            codes,
            HashSet::from(["formula-cycle", "formula-evaluation-failed"])
        );
    }

    #[test]
    fn evaluates_the_whitelisted_functions_and_operators() {
        let book = TestBook::new(&[(
            "S",
            &[
                ("A1", Value::Int(100)),
                ("A2", Value::Float(-7.5)),
                ("A3", s("12")),
                ("A4", Value::Bool(true)),
                ("A5", s("text")),
            ],
        )]);
        let mut evaluation = Evaluation::new(&book);
        let mut eval = |formula: &str| {
            let node = Parser::new(formula).and_then(|mut p| p.parse())?;
            evaluation.evaluate(&node, "S")
        };
        assert_eq!(eval("=SUM(A1:A5)").unwrap(), Value::Float(104.5));
        assert_eq!(eval("=COUNT(A1:A5)").unwrap(), Value::Int(3));
        assert_eq!(eval("=COUNTA(A1:A5,\"\")").unwrap(), Value::Int(5));
        assert_eq!(eval("=MIN(A1:A3)").unwrap(), Value::Float(-7.5));
        assert_eq!(eval("=ABS(A2)").unwrap(), Value::Float(7.5));
        assert_eq!(eval("=ROUND(2.5,0)").unwrap(), Value::Float(2.0));
        assert_eq!(eval("=AND(A4,1)").unwrap(), Value::Bool(true));
        assert_eq!(eval("=OR(0,FALSE)").unwrap(), Value::Bool(false));
        assert_eq!(eval("=NOT(A4)").unwrap(), Value::Bool(false));
        assert_eq!(eval("=IF(A1<50,1)").unwrap(), Value::Bool(false));
        assert_eq!(eval("=IFERROR(1/0,\"div\")").unwrap(), s("div"));
        assert_eq!(eval("=\"a\"&A1&A2").unwrap(), s("a100-7.5"));
        assert_eq!(eval("=A5<>\"TEXT\"").unwrap(), Value::Bool(false));
        assert_eq!(eval("=2^10").unwrap(), Value::Float(1024.0));
        assert_eq!(eval("=50%").unwrap(), Value::Float(0.5));
        assert_eq!(eval("=SUM()").unwrap(), Value::Int(0));
        assert!(eval("=1/0").is_err());
        assert!(eval("=AVERAGE(A5)").is_err());
        assert!(eval("=A5+1").is_err());
        assert!(eval("=XLOOKUP(1)").is_err());
    }
}
