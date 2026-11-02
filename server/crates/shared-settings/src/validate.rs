//! The pydantic v2 lax-mode rules (python input) the settings models use:
//! coercions, constraint checks, and the error `type`, `loc`, `msg` and `ctx`
//! pydantic reports, in field order, one error per field.

use evoflux_shared_yaml::{Mapping, Value};

/// One element of an error location: a field or dict key, or a list index.
#[derive(Debug, Clone, PartialEq)]
pub enum Loc {
    Key(Value),
    Index(usize),
}

impl Loc {
    pub fn field(name: &str) -> Loc {
        Loc::Key(Value::Str(name.to_owned()))
    }

    /// `str(part)` in Python, as `IgnoredSetting.field` joins them.
    pub fn python_str(&self) -> String {
        match self {
            Loc::Index(i) => i.to_string(),
            Loc::Key(Value::Str(s)) => s.clone(),
            Loc::Key(Value::Null) => "None".to_owned(),
            Loc::Key(Value::Bool(b)) => (if *b { "True" } else { "False" }).to_owned(),
            Loc::Key(Value::Int(i)) => i.to_string(),
            Loc::Key(Value::Float(f)) => evoflux_shared_yaml::python_float_repr(*f),
            Loc::Key(Value::Timestamp(t)) => t.isoformat(' '),
            Loc::Key(_) => String::new(),
        }
    }

    pub fn to_json(&self) -> serde_json::Value {
        match self {
            Loc::Index(i) => serde_json::Value::from(*i),
            Loc::Key(key) => key.to_json(),
        }
    }
}

/// One pydantic error (`ValidationError.errors()` item without `url`).
#[derive(Debug, Clone, PartialEq)]
pub struct ValidationError {
    pub kind: &'static str,
    pub loc: Vec<Loc>,
    pub msg: String,
    pub input: Value,
    pub ctx: Option<serde_json::Value>,
}

impl ValidationError {
    /// The dotted path `load_runtime_settings_report` reports.
    pub fn dotted_loc(&self) -> String {
        self.loc
            .iter()
            .map(Loc::python_str)
            .collect::<Vec<_>>()
            .join(".")
    }
}

/// The input of one model plus where errors go.
pub struct Fields<'a> {
    map: &'a Mapping,
    loc: Vec<Loc>,
    pub(crate) errors: &'a mut Vec<ValidationError>,
}

/// A number constraint as pydantic prints it: integral floats without `.0`.
#[derive(Clone, Copy)]
pub enum Bound {
    Int(i128),
    Float(f64),
}

impl Bound {
    fn as_f64(self) -> f64 {
        match self {
            #[allow(clippy::cast_precision_loss)]
            Bound::Int(i) => i as f64,
            Bound::Float(f) => f,
        }
    }

    fn display(self) -> String {
        match self {
            Bound::Int(i) => i.to_string(),
            Bound::Float(f) if f.fract() == 0.0 && f.abs() < 1e16 => format!("{f:.0}"),
            Bound::Float(f) => evoflux_shared_yaml::python_float_repr(f),
        }
    }

    fn json(self) -> serde_json::Value {
        match self {
            Bound::Int(i) => i64::try_from(i).map_or(serde_json::Value::Null, Into::into),
            Bound::Float(f) => {
                serde_json::Number::from_f64(f).map_or(serde_json::Value::Null, Into::into)
            }
        }
    }
}

#[derive(Clone, Copy, Default)]
pub struct Range {
    pub ge: Option<Bound>,
    pub le: Option<Bound>,
}

pub const ANY: Range = Range { ge: None, le: None };

pub fn int_range(ge: i128, le: i128) -> Range {
    Range {
        ge: Some(Bound::Int(ge)),
        le: Some(Bound::Int(le)),
    }
}

pub fn float_range(ge: f64, le: f64) -> Range {
    Range {
        ge: Some(Bound::Float(ge)),
        le: Some(Bound::Float(le)),
    }
}

/// pydantic's message list for a `Literal`: `'a', 'b' or 'c'`.
fn expected(choices: &[&str]) -> String {
    let quoted: Vec<String> = choices.iter().map(|c| format!("'{c}'")).collect();
    match quoted.split_last() {
        Some((last, rest)) if !rest.is_empty() => format!("{} or {last}", rest.join(", ")),
        Some((last, _)) => last.clone(),
        None => String::new(),
    }
}

impl<'a> Fields<'a> {
    pub(crate) fn new(
        map: &'a Mapping,
        loc: Vec<Loc>,
        errors: &'a mut Vec<ValidationError>,
    ) -> Self {
        Self { map, loc, errors }
    }

    fn at(&self, name: &str) -> Vec<Loc> {
        let mut loc = self.loc.clone();
        loc.push(Loc::field(name));
        loc
    }

    pub(crate) fn error(
        &mut self,
        loc: Vec<Loc>,
        kind: &'static str,
        msg: String,
        input: &Value,
        ctx: Option<serde_json::Value>,
    ) {
        self.errors.push(ValidationError {
            kind,
            loc,
            msg,
            input: input.clone(),
            ctx,
        });
    }

    pub(crate) fn loc(&self) -> &[Loc] {
        &self.loc
    }

    pub(crate) fn raw(&self, name: &str) -> Option<&'a Value> {
        self.map.get(name)
    }

    pub fn bool(&mut self, name: &str, default: bool) -> bool {
        let Some(input) = self.raw(name) else {
            return default;
        };
        match coerce_bool(input) {
            Ok(b) => b,
            Err((kind, msg)) => {
                let loc = self.at(name);
                self.error(loc, kind, msg.to_owned(), input, None);
                default
            }
        }
    }

    pub fn int(&mut self, name: &str, default: i128, range: Range) -> i128 {
        self.opt_int_inner(name, range, false)
            .flatten()
            .unwrap_or(default)
    }

    pub fn opt_int(&mut self, name: &str, range: Range) -> Option<i128> {
        self.opt_int_inner(name, range, true).flatten()
    }

    /// `None`: invalid or missing; `Some(None)`: an explicit `null` allowed.
    fn opt_int_inner(&mut self, name: &str, range: Range, nullable: bool) -> Option<Option<i128>> {
        let input = self.raw(name)?;
        if nullable && input.is_null() {
            return Some(None);
        }
        let loc = self.at(name);
        match coerce_int(input) {
            Ok(value) => {
                #[allow(clippy::cast_precision_loss)]
                let as_f = value as f64;
                if let Some(error) = check_range(as_f, range) {
                    let (kind, msg, ctx) = error;
                    self.error(loc, kind, msg, input, Some(ctx));
                    return None;
                }
                Some(Some(value))
            }
            Err((kind, msg)) => {
                self.error(loc, kind, msg.to_owned(), input, None);
                None
            }
        }
    }

    pub fn float(&mut self, name: &str, default: f64, range: Range) -> f64 {
        let Some(input) = self.raw(name) else {
            return default;
        };
        let loc = self.at(name);
        match coerce_float(input) {
            Ok(value) => {
                if let Some((kind, msg, ctx)) = check_range(value, range) {
                    self.error(loc, kind, msg, input, Some(ctx));
                    return default;
                }
                value
            }
            Err((kind, msg)) => {
                self.error(loc, kind, msg.to_owned(), input, None);
                default
            }
        }
    }

    pub fn string(&mut self, name: &str, default: &str) -> String {
        match self.raw(name) {
            None => default.to_owned(),
            Some(Value::Str(s)) => s.clone(),
            Some(input) => {
                let loc = self.at(name);
                self.error(
                    loc,
                    "string_type",
                    "Input should be a valid string".to_owned(),
                    input,
                    None,
                );
                default.to_owned()
            }
        }
    }

    pub fn opt_string(&mut self, name: &str) -> Option<String> {
        match self.raw(name) {
            None | Some(Value::Null) => None,
            Some(Value::Str(s)) => Some(s.clone()),
            Some(input) => {
                let loc = self.at(name);
                self.error(
                    loc,
                    "string_type",
                    "Input should be a valid string".to_owned(),
                    input,
                    None,
                );
                None
            }
        }
    }

    pub fn literal(
        &mut self,
        name: &str,
        default: &'static str,
        choices: &[&'static str],
    ) -> &'static str {
        match self.raw(name) {
            None => default,
            Some(input) => self.literal_value(name, input, choices).unwrap_or(default),
        }
    }

    pub fn opt_literal(&mut self, name: &str, choices: &[&'static str]) -> Option<&'static str> {
        match self.raw(name) {
            None | Some(Value::Null) => None,
            Some(input) => self.literal_value(name, input, choices),
        }
    }

    fn literal_value(
        &mut self,
        name: &str,
        input: &Value,
        choices: &[&'static str],
    ) -> Option<&'static str> {
        if let Value::Str(s) = input {
            if let Some(choice) = choices.iter().find(|c| **c == s) {
                return Some(choice);
            }
        }
        let loc = self.at(name);
        let expected = expected(choices);
        self.error(
            loc,
            "literal_error",
            format!("Input should be {expected}"),
            input,
            Some(serde_json::json!({ "expected": expected })),
        );
        None
    }

    pub fn list_str(&mut self, name: &str) -> Vec<String> {
        let Some(input) = self.raw(name) else {
            return Vec::new();
        };
        let loc = self.at(name);
        let Value::Seq(items) = input else {
            self.error(
                loc,
                "list_type",
                "Input should be a valid list".to_owned(),
                input,
                None,
            );
            return Vec::new();
        };
        let mut out = Vec::new();
        for (index, item) in items.iter().enumerate() {
            match item {
                Value::Str(s) => out.push(s.clone()),
                other => {
                    let mut at = loc.clone();
                    at.push(Loc::Index(index));
                    self.error(
                        at,
                        "string_type",
                        "Input should be a valid string".to_owned(),
                        other,
                        None,
                    );
                }
            }
        }
        out
    }

    /// A nested model field: `model_type` unless the input is a mapping.
    pub fn model<T: Default>(
        &mut self,
        name: &str,
        class_name: &str,
        validate: impl FnOnce(&mut Fields<'_>) -> T,
    ) -> T {
        let Some(input) = self.raw(name) else {
            return T::default();
        };
        let loc = self.at(name);
        model_at(input, loc, class_name, self.errors, validate).unwrap_or_default()
    }
}

/// Validate `input` as a model at `loc`; `None` when it is not a mapping or
/// one of its fields failed.
pub(crate) fn model_at<T>(
    input: &Value,
    loc: Vec<Loc>,
    class_name: &str,
    errors: &mut Vec<ValidationError>,
    validate: impl FnOnce(&mut Fields<'_>) -> T,
) -> Option<T> {
    let Value::Map(map) = input else {
        errors.push(ValidationError {
            kind: "model_type",
            loc,
            msg: format!("Input should be a valid dictionary or instance of {class_name}"),
            input: input.clone(),
            ctx: Some(serde_json::json!({ "class_name": class_name })),
        });
        return None;
    };
    let before = errors.len();
    let mut fields = Fields::new(map, loc, errors);
    let value = validate(&mut fields);
    (errors.len() == before).then_some(value)
}

fn coerce_bool(input: &Value) -> Result<bool, (&'static str, &'static str)> {
    const PARSING: (&str, &str) = (
        "bool_parsing",
        "Input should be a valid boolean, unable to interpret input",
    );
    const TYPE: (&str, &str) = ("bool_type", "Input should be a valid boolean");
    match input {
        Value::Bool(b) => Ok(*b),
        Value::Int(0) => Ok(false),
        Value::Int(1) => Ok(true),
        Value::Int(_) => Err(PARSING),
        Value::Float(f) if *f == 0.0 => Ok(false),
        Value::Float(f) if *f == 1.0 => Ok(true),
        Value::Str(s) => match s.to_lowercase().as_str() {
            "0" | "off" | "f" | "false" | "n" | "no" => Ok(false),
            "1" | "on" | "t" | "true" | "y" | "yes" => Ok(true),
            _ => Err(PARSING),
        },
        _ => Err(TYPE),
    }
}

fn coerce_int(input: &Value) -> Result<i128, (&'static str, &'static str)> {
    const TYPE: (&str, &str) = ("int_type", "Input should be a valid integer");
    const FRACTION: (&str, &str) = (
        "int_from_float",
        "Input should be a valid integer, got a number with a fractional part",
    );
    const PARSING: (&str, &str) = (
        "int_parsing",
        "Input should be a valid integer, unable to parse string as an integer",
    );
    match input {
        Value::Bool(b) => Ok(i128::from(*b)),
        Value::Int(i) => Ok(*i),
        Value::Float(f) if !f.is_finite() => {
            Err(("finite_number", "Input should be a finite number"))
        }
        Value::Float(f) if f.fract() != 0.0 => Err(FRACTION),
        #[allow(clippy::cast_possible_truncation)]
        Value::Float(f) => Ok(*f as i128),
        Value::Str(s) => parse_int_str(s).ok_or(PARSING),
        _ => Err(TYPE),
    }
}

/// pydantic-core's string to int: surrounding whitespace, a sign, `_`
/// between digits, and a `.0…` fraction of zeros.
fn parse_int_str(s: &str) -> Option<i128> {
    let s = s.trim();
    let (negative, digits) = match s.strip_prefix('-') {
        Some(rest) => (true, rest),
        None => (false, s.strip_prefix('+').unwrap_or(s)),
    };
    let digits = match digits.split_once('.') {
        Some((int, frac)) if frac.chars().all(|c| c == '0') => int,
        Some(_) => return None,
        None => digits,
    };
    if digits.is_empty()
        || digits.starts_with('_')
        || digits.ends_with('_')
        || digits.contains("__")
        || !digits.chars().all(|c| c.is_ascii_digit() || c == '_')
    {
        return None;
    }
    let clean: String = digits.chars().filter(|&c| c != '_').collect();
    let value: i128 = clean.parse().ok()?;
    Some(if negative { -value } else { value })
}

fn coerce_float(input: &Value) -> Result<f64, (&'static str, &'static str)> {
    const TYPE: (&str, &str) = ("float_type", "Input should be a valid number");
    const PARSING: (&str, &str) = (
        "float_parsing",
        "Input should be a valid number, unable to parse string as a number",
    );
    match input {
        Value::Bool(b) => Ok(f64::from(u8::from(*b))),
        #[allow(clippy::cast_precision_loss)]
        Value::Int(i) => Ok(*i as f64),
        Value::Float(f) => Ok(*f),
        Value::Str(s) => parse_float_str(s).ok_or(PARSING),
        _ => Err(TYPE),
    }
}

/// Python's `float(str)`: whitespace, `_` between digits, `inf`/`nan`.
fn parse_float_str(s: &str) -> Option<f64> {
    let s = s.trim();
    if s.starts_with('_') || s.ends_with('_') || s.contains("__") {
        return None;
    }
    let mut prev = ' ';
    for (i, c) in s.char_indices() {
        if c == '_' {
            let next = s.get(i + 1..).and_then(|r| r.chars().next()).unwrap_or(' ');
            if !prev.is_ascii_digit() || !next.is_ascii_digit() {
                return None;
            }
        }
        prev = c;
    }
    let clean: String = s.chars().filter(|&c| c != '_').collect();
    clean.parse().ok()
}

/// `ge` then `le`, as pydantic-core checks them; NaN fails `le` only.
fn check_range(value: f64, range: Range) -> Option<(&'static str, String, serde_json::Value)> {
    if let Some(ge) = range.ge {
        if value < ge.as_f64() {
            return Some((
                "greater_than_equal",
                format!("Input should be greater than or equal to {}", ge.display()),
                serde_json::json!({ "ge": ge.json() }),
            ));
        }
    }
    if let Some(le) = range.le {
        if value.is_nan() || value > le.as_f64() {
            return Some((
                "less_than_equal",
                format!("Input should be less than or equal to {}", le.display()),
                serde_json::json!({ "le": le.json() }),
            ));
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn literal_messages_list_the_choices() {
        assert_eq!(expected(&["a"]), "'a'");
        assert_eq!(expected(&["a", "b"]), "'a' or 'b'");
        assert_eq!(expected(&["a", "b", "c"]), "'a', 'b' or 'c'");
    }

    #[test]
    fn int_strings_follow_pydantic() {
        assert_eq!(parse_int_str(" 8080"), Some(8080));
        assert_eq!(parse_int_str("+8_080"), Some(8080));
        assert_eq!(parse_int_str("8080.00"), Some(8080));
        assert_eq!(parse_int_str("-3"), Some(-3));
        assert_eq!(parse_int_str("8080.5"), None);
        assert_eq!(parse_int_str("7e4"), None);
        assert_eq!(parse_int_str("_1"), None);
        assert_eq!(parse_int_str(""), None);
    }

    #[test]
    fn float_strings_follow_python() {
        assert_eq!(parse_float_str(" 1.5 "), Some(1.5));
        assert_eq!(parse_float_str("1_0.5"), Some(10.5));
        assert_eq!(parse_float_str("1e2"), Some(100.0));
        assert_eq!(parse_float_str("inf"), Some(f64::INFINITY));
        assert_eq!(parse_float_str("1__0"), None);
        assert_eq!(parse_float_str("1_.0"), None);
        assert_eq!(parse_float_str("x"), None);
    }

    #[test]
    fn bounds_print_like_pydantic() {
        assert_eq!(Bound::Float(10.0).display(), "10");
        assert_eq!(Bound::Float(0.5).display(), "0.5");
        assert_eq!(Bound::Int(64_000).display(), "64000");
    }
}
