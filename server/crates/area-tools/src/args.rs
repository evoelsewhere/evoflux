//! Argument validation with Pydantic's lax-mode coercions and error text.
//!
//! Python validates a tool call with a generated Pydantic model before the tool
//! runs; the model sees the resulting message, so it is reproduced for the field
//! types these tools use.

use serde_json::Value;

use crate::pyfmt::{repr_str, repr_value, type_name};

const PYDANTIC_DOCS: &str = "https://errors.pydantic.dev/2.13/v";

#[derive(Clone, Copy)]
pub(crate) enum Kind {
    Str,
    Int,
    OptInt,
    Bool,
    Literal(&'static [&'static str]),
}

#[derive(Clone, Debug, PartialEq)]
pub(crate) enum Val {
    Str(String),
    Int(i64),
    Bool(bool),
    None,
}

pub(crate) struct Field {
    pub(crate) name: &'static str,
    pub(crate) kind: Kind,
    /// `None` marks a required field.
    pub(crate) default: Option<Val>,
}

impl Field {
    pub(crate) const fn required(name: &'static str, kind: Kind) -> Self {
        Self {
            name,
            kind,
            default: None,
        }
    }

    pub(crate) const fn optional(name: &'static str, kind: Kind, default: Val) -> Self {
        Self {
            name,
            kind,
            default: Some(default),
        }
    }
}

pub(crate) struct Parsed {
    values: Vec<(&'static str, Val)>,
}

impl Parsed {
    fn get(&self, name: &str) -> Option<&Val> {
        self.values
            .iter()
            .find(|(field, _)| *field == name)
            .map(|(_, value)| value)
    }

    pub(crate) fn str(&self, name: &str) -> String {
        match self.get(name) {
            Some(Val::Str(s)) => s.clone(),
            _ => String::new(),
        }
    }

    pub(crate) fn int(&self, name: &str) -> i64 {
        match self.get(name) {
            Some(Val::Int(i)) => *i,
            _ => 0,
        }
    }

    pub(crate) fn opt_int(&self, name: &str) -> Option<i64> {
        match self.get(name) {
            Some(Val::Int(i)) => Some(*i),
            _ => None,
        }
    }

    pub(crate) fn flag(&self, name: &str) -> bool {
        matches!(self.get(name), Some(Val::Bool(true)))
    }
}

struct Issue {
    loc: &'static str,
    kind: &'static str,
    message: String,
    input: String,
    input_type: &'static str,
}

/// Pydantic shows at most 50 characters of the offending input.
fn truncated_repr(value: &Value) -> String {
    let text = repr_value(value);
    let chars: Vec<char> = text.chars().collect();
    if chars.len() <= 50 {
        return text;
    }
    let head: String = chars.iter().take(25).collect();
    let tail: String = chars.iter().skip(chars.len() - 24).collect();
    format!("{head}...{tail}")
}

fn issue(loc: &'static str, kind: &'static str, message: &str, input: &Value) -> Issue {
    Issue {
        loc,
        kind,
        message: message.to_owned(),
        input: truncated_repr(input),
        input_type: type_name(input),
    }
}

/// `"7"`, `"+7"`, `"1_000"` and `"3.0"` read as integers; `"1.5"`, `"5."` and `"1e3"` do not.
fn parse_int_text(text: &str) -> Option<i64> {
    let digits = text.strip_prefix(['+', '-']).unwrap_or(text);
    let plain = |part: &str| !part.is_empty() && part.bytes().all(|b| b.is_ascii_digit());
    let grouped = digits.split('_').all(plain);
    if grouped {
        return text.replace('_', "").parse().ok();
    }
    let (whole, fraction) = digits.split_once('.')?;
    if plain(whole) && plain(fraction) && fraction.bytes().all(|b| b == b'0') {
        let sign = if text.starts_with('-') { "-" } else { "" };
        return format!("{sign}{whole}").parse().ok();
    }
    None
}

fn coerce_int(loc: &'static str, value: &Value) -> Result<i64, Issue> {
    match value {
        Value::Bool(b) => Ok(i64::from(*b)),
        Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                return Ok(i);
            }
            // Only an integer above `i64::MAX` is a `u64`.
            if n.is_u64() {
                return Ok(i64::MAX);
            }
            // JSON has no NaN or infinity, so the rest are finite floats.
            match n.as_f64() {
                Some(f) if f.fract() == 0.0 => Ok(f as i64),
                _ => Err(issue(
                    loc,
                    "int_from_float",
                    "Input should be a valid integer, got a number with a fractional part",
                    value,
                )),
            }
        }
        Value::String(s) => parse_int_text(s.trim()).ok_or_else(|| {
            issue(
                loc,
                "int_parsing",
                "Input should be a valid integer, unable to parse string as an integer",
                value,
            )
        }),
        _ => Err(issue(
            loc,
            "int_type",
            "Input should be a valid integer",
            value,
        )),
    }
}

fn coerce_bool(loc: &'static str, value: &Value) -> Result<bool, Issue> {
    const UNREADABLE: &str = "Input should be a valid boolean, unable to interpret input";
    match value {
        Value::Bool(b) => Ok(*b),
        Value::Number(n) => match n.as_f64() {
            Some(0.0) => Ok(false),
            Some(1.0) => Ok(true),
            _ => Err(issue(loc, "bool_parsing", UNREADABLE, value)),
        },
        Value::String(s) => match s.to_lowercase().as_str() {
            "0" | "off" | "f" | "false" | "n" | "no" => Ok(false),
            "1" | "on" | "t" | "true" | "y" | "yes" => Ok(true),
            _ => Err(issue(loc, "bool_parsing", UNREADABLE, value)),
        },
        _ => Err(issue(
            loc,
            "bool_type",
            "Input should be a valid boolean",
            value,
        )),
    }
}

fn literal_message(allowed: &[&str]) -> String {
    let quoted: Vec<String> = allowed.iter().map(|a| repr_str(a)).collect();
    match quoted.split_last() {
        Some((last, rest)) if !rest.is_empty() => {
            format!("Input should be {} or {last}", rest.join(", "))
        }
        Some((last, _)) => format!("Input should be {last}"),
        None => "Input should be".to_owned(),
    }
}

fn coerce(field: &Field, value: &Value) -> Result<Val, Issue> {
    let loc = field.name;
    match field.kind {
        Kind::Str => match value {
            Value::String(s) => Ok(Val::Str(s.clone())),
            _ => Err(issue(
                loc,
                "string_type",
                "Input should be a valid string",
                value,
            )),
        },
        Kind::Int => coerce_int(loc, value).map(Val::Int),
        Kind::OptInt => match value {
            Value::Null => Ok(Val::None),
            other => coerce_int(loc, other).map(Val::Int),
        },
        Kind::Bool => coerce_bool(loc, value).map(Val::Bool),
        Kind::Literal(allowed) => match value {
            Value::String(s) if allowed.contains(&s.as_str()) => Ok(Val::Str(s.clone())),
            _ => Err(issue(
                loc,
                "literal_error",
                &literal_message(allowed),
                value,
            )),
        },
    }
}

fn render(tool: &str, issues: &[Issue], args: &Value) -> String {
    let count = issues.len();
    let noun = if count == 1 { "error" } else { "errors" };
    let mut text = format!(
        "Invalid arguments for tool '{tool}': {count} validation {noun} for {tool}_parameters"
    );
    for found in issues {
        let input = if found.kind == "missing" {
            truncated_repr(args)
        } else {
            found.input.clone()
        };
        let input_type = if found.kind == "missing" {
            "dict"
        } else {
            found.input_type
        };
        text.push_str(&format!(
            "\n{}\n  {} [type={}, input_value={input}, input_type={input_type}]\n    For further information visit {PYDANTIC_DOCS}/{}",
            found.loc, found.message, found.kind, found.kind
        ));
    }
    text
}

/// Validate `args` against `fields`; the error is the text the model should see.
pub(crate) fn parse(tool: &str, fields: &[Field], args: &Value) -> Result<Parsed, String> {
    let empty = serde_json::Map::new();
    let object = match args {
        Value::Object(map) => map,
        Value::Null => &empty,
        _ => return Err("Tool arguments must be a JSON object".to_owned()),
    };
    let mut values = Vec::with_capacity(fields.len());
    let mut issues = Vec::new();
    for field in fields {
        match (object.get(field.name), &field.default) {
            (Some(value), _) => match coerce(field, value) {
                Ok(parsed) => values.push((field.name, parsed)),
                Err(found) => issues.push(found),
            },
            (None, Some(default)) => values.push((field.name, default.clone())),
            (None, None) => issues.push(Issue {
                loc: field.name,
                kind: "missing",
                message: "Field required".to_owned(),
                input: String::new(),
                input_type: "dict",
            }),
        }
    }
    if issues.is_empty() {
        Ok(Parsed { values })
    } else {
        Err(render(tool, &issues, &Value::Object(object.clone())))
    }
}

#[cfg(test)]
#[allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::indexing_slicing,
    clippy::panic,
    clippy::disallowed_methods
)]
mod tests {
    use super::*;
    use serde_json::json;

    const MODES: &[&str] = &["content", "files_with_matches", "count"];

    fn fields() -> Vec<Field> {
        vec![
            Field::required("path", Kind::Str),
            Field::optional("offset", Kind::Int, Val::Int(1)),
            Field::optional("limit", Kind::OptInt, Val::None),
            Field::optional("flag", Kind::Bool, Val::Bool(false)),
            Field::optional("mode", Kind::Literal(MODES), Val::Str("content".into())),
        ]
    }

    fn err(args: Value) -> String {
        match parse("read", &fields(), &args) {
            Err(message) => message,
            Ok(_) => panic!("expected an error for {args}"),
        }
    }

    fn ok(args: Value) -> Parsed {
        parse("read", &fields(), &args).unwrap()
    }

    #[test]
    fn defaults_fill_omitted_fields_and_extras_are_ignored() {
        let p = ok(json!({"path": "a", "extra": 1}));
        assert_eq!(p.str("path"), "a");
        assert_eq!(p.int("offset"), 1);
        assert_eq!(p.opt_int("limit"), None);
        assert!(!p.flag("flag"));
        assert_eq!(p.str("mode"), "content");
    }

    #[test]
    fn null_arguments_read_as_empty() {
        let message = err(json!(null));
        assert!(message
            .contains("path\n  Field required [type=missing, input_value={}, input_type=dict]"));
    }

    #[test]
    fn missing_field_reports_the_whole_input() {
        assert_eq!(
            err(json!({"offset": 2})),
            "Invalid arguments for tool 'read': 1 validation error for read_parameters\npath\n  Field required [type=missing, input_value={'offset': 2}, input_type=dict]\n    For further information visit https://errors.pydantic.dev/2.13/v/missing"
        );
    }

    #[test]
    fn non_object_arguments_are_rejected() {
        let message = parse("read", &fields(), &json!([1])).err().unwrap();
        assert_eq!(message, "Tool arguments must be a JSON object");
    }

    #[test]
    fn strings_must_be_strings() {
        assert_eq!(
            err(json!({"path": 1})),
            "Invalid arguments for tool 'read': 1 validation error for read_parameters\npath\n  Input should be a valid string [type=string_type, input_value=1, input_type=int]\n    For further information visit https://errors.pydantic.dev/2.13/v/string_type"
        );
    }

    #[test]
    fn integers_coerce_like_pydantic_lax_mode() {
        assert_eq!(ok(json!({"path": "a", "offset": "2"})).int("offset"), 2);
        assert_eq!(ok(json!({"path": "a", "offset": " 7 "})).int("offset"), 7);
        assert_eq!(ok(json!({"path": "a", "offset": true})).int("offset"), 1);
        assert_eq!(ok(json!({"path": "a", "offset": false})).int("offset"), 0);
        assert_eq!(ok(json!({"path": "a", "offset": 2.0})).int("offset"), 2);
        assert_eq!(ok(json!({"path": "a", "offset": "3.0"})).int("offset"), 3);
        assert_eq!(ok(json!({"path": "a", "offset": -4})).int("offset"), -4);
        assert_eq!(
            ok(json!({"path": "a", "limit": null})).opt_int("limit"),
            None
        );
        assert_eq!(
            ok(json!({"path": "a", "limit": "9"})).opt_int("limit"),
            Some(9)
        );
        assert_eq!(
            ok(json!({"path": "a", "offset": u64::MAX})).int("offset"),
            i64::MAX
        );
    }

    #[test]
    fn integer_errors_name_the_reason() {
        let fractional = err(json!({"path": "a", "offset": 2.5}));
        assert!(fractional.contains("offset\n  Input should be a valid integer, got a number with a fractional part [type=int_from_float, input_value=2.5, input_type=float]"));
        assert!(fractional.ends_with("/v/int_from_float"));
        let text = err(json!({"path": "a", "offset": "abc"}));
        assert!(text.contains("Input should be a valid integer, unable to parse string as an integer [type=int_parsing, input_value='abc', input_type=str]"));
        let frac_text = err(json!({"path": "a", "offset": "1.5"}));
        assert!(frac_text.contains("[type=int_parsing, input_value='1.5', input_type=str]"));
        let exp = err(json!({"path": "a", "offset": "1e3"}));
        assert!(exp.contains("[type=int_parsing, input_value='1e3', input_type=str]"));
        let null = err(json!({"path": "a", "offset": null}));
        assert!(null.contains("Input should be a valid integer [type=int_type, input_value=None, input_type=NoneType]"));
        let list = err(json!({"path": "a", "limit": [1]}));
        assert!(list.contains("limit\n  Input should be a valid integer [type=int_type, input_value=[1], input_type=list]"));
    }

    #[test]
    fn booleans_coerce_like_pydantic_lax_mode() {
        for (input, want) in [
            (json!(true), true),
            (json!(1), true),
            (json!(0), false),
            (json!(1.0), true),
            (json!(0.0), false),
            (json!("YES"), true),
            (json!("on"), true),
            (json!("t"), true),
            (json!("y"), true),
            (json!("1"), true),
            (json!("true"), true),
            (json!("No"), false),
            (json!("off"), false),
            (json!("f"), false),
            (json!("n"), false),
            (json!("0"), false),
            (json!("false"), false),
        ] {
            assert_eq!(
                ok(json!({"path": "a", "flag": input.clone()})).flag("flag"),
                want,
                "{input}"
            );
        }
        let maybe = err(json!({"path": "a", "flag": "maybe"}));
        assert!(maybe.contains("flag\n  Input should be a valid boolean, unable to interpret input [type=bool_parsing, input_value='maybe', input_type=str]"));
        assert!(err(json!({"path": "a", "flag": 2}))
            .contains("[type=bool_parsing, input_value=2, input_type=int]"));
        assert!(err(json!({"path": "a", "flag": 0.5})).contains("bool_parsing"));
        assert!(err(json!({"path": "a", "flag": null})).contains("Input should be a valid boolean [type=bool_type, input_value=None, input_type=NoneType]"));
    }

    #[test]
    fn literals_list_the_allowed_values() {
        assert_eq!(
            ok(json!({"path": "a", "mode": "count"})).str("mode"),
            "count"
        );
        assert!(err(json!({"path": "a", "mode": "x"})).contains(
            "mode\n  Input should be 'content', 'files_with_matches' or 'count' [type=literal_error, input_value='x', input_type=str]"
        ));
        assert!(err(json!({"path": "a", "mode": 3}))
            .contains("literal_error, input_value=3, input_type=int"));
        assert_eq!(literal_message(&["a", "b"]), "Input should be 'a' or 'b'");
        assert_eq!(literal_message(&["a"]), "Input should be 'a'");
        assert_eq!(literal_message(&[]), "Input should be");
    }

    #[test]
    fn several_errors_are_counted_and_ordered_by_field() {
        let message = err(json!({"offset": "x", "flag": "maybe"}));
        assert!(message.starts_with(
            "Invalid arguments for tool 'read': 3 validation errors for read_parameters\npath\n"
        ));
        let path = message.find("\npath\n").unwrap();
        let offset = message.find("\noffset\n").unwrap();
        let flag = message.find("\nflag\n").unwrap();
        assert!(path < offset && offset < flag);
    }
}
