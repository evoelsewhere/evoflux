//! FastAPI request-body parsing and pydantic v2 lax validation for the
//! settings and auth request models (`app/api/schemas/settings.py`,
//! `OAuthCallbackBody` in `app/api/routes/auth.py`).
//!
//! A model is a list of [`Field`]s; validation returns the coerced values in
//! declaration order (defaults filled in) or FastAPI's 422 `detail` list:
//! one entry per bad field in declaration order, then `extra_forbidden` for
//! each unknown key in request order. `tests/body_golden.json`, generated
//! from the real pydantic models, pins every rule here.

use axum::http::StatusCode;
use evoflux_area_commands::support::py_strip;
use evoflux_core::ApiError;
use serde_json::{json, Map, Value};

use crate::pyjson;

/// What a field accepts and how pydantic coerces it in lax mode.
#[derive(Debug, Clone, Copy)]
pub(crate) enum Kind {
    Str,
    Bool,
    /// `int` with optional `ge` / `le`.
    Int(Option<i64>, Option<i64>),
    /// `int | None` with optional `ge` / `le`.
    OptInt(Option<i64>, Option<i64>),
    /// `float` with optional `ge` / `le`.
    Float(Option<f64>, Option<f64>),
    Literal(&'static [&'static str]),
    ListStr,
    DictInt,
    /// `list[<model>]`, the model named for `model_type` errors.
    ListModel(&'static str, &'static [Field]),
}

#[derive(Debug, Clone, Copy)]
pub(crate) struct Field {
    pub name: &'static str,
    pub kind: Kind,
    /// `None`: required.
    pub default: Option<Default>,
}

#[derive(Debug, Clone, Copy)]
pub(crate) enum Default {
    Null,
    Bool(bool),
    Int(i64),
    Float(f64),
    Str(&'static str),
    EmptyList,
    EmptyDict,
}

impl Default {
    fn value(self) -> Value {
        match self {
            Default::Null => Value::Null,
            Default::Bool(value) => Value::Bool(value),
            Default::Int(value) => Value::from(value),
            Default::Float(value) => json!(value),
            Default::Str(value) => Value::from(value),
            Default::EmptyList => Value::Array(Vec::new()),
            Default::EmptyDict => Value::Object(Map::new()),
        }
    }
}

fn unprocessable(detail: Vec<Value>) -> ApiError {
    ApiError::new(StatusCode::UNPROCESSABLE_ENTITY, Value::Array(detail))
}

/// FastAPI parses the body as JSON only for `application/json` and
/// `application/*+json`; anything else reaches pydantic as raw text.
fn is_json(content_type: Option<&str>) -> bool {
    let Some(content_type) = content_type else {
        return false;
    };
    let media = content_type.split(';').next().unwrap_or_default();
    match media.trim().to_ascii_lowercase().split_once('/') {
        Some(("application", subtype)) => subtype == "json" || subtype.ends_with("+json"),
        _ => false,
    }
}

/// The request body as FastAPI hands it to a required model parameter:
/// an object, or the 400 / 422 FastAPI answers before the model runs.
pub(crate) fn parse_object(
    content_type: Option<&str>,
    bytes: &[u8],
) -> Result<Map<String, Value>, ApiError> {
    let missing = || {
        unprocessable(vec![json!({
            "type": "missing", "loc": ["body"], "msg": "Field required", "input": null,
        })])
    };
    if bytes.is_empty() {
        return Err(missing());
    }
    let body = if is_json(content_type) {
        let text = std::str::from_utf8(bytes).map_err(|_| {
            ApiError::new(
                StatusCode::BAD_REQUEST,
                "There was an error parsing the body",
            )
        })?;
        serde_json::from_str::<Value>(text).map_err(|_| {
            let (position, error) = pyjson::first_error(text).unwrap_or((0, "Expecting value"));
            unprocessable(vec![json!({
                "type": "json_invalid", "loc": ["body", position], "msg": "JSON decode error",
                "input": {}, "ctx": {"error": error},
            })])
        })?
    } else {
        Value::String(String::from_utf8_lossy(bytes).into_owned())
    };
    match body {
        Value::Object(fields) => Ok(fields),
        Value::Null => Err(missing()),
        other => Err(unprocessable(vec![json!({
            "type": "model_attributes_type", "loc": ["body"],
            "msg": "Input should be a valid dictionary or object to extract fields from",
            "input": other,
        })])),
    }
}

/// [`parse_object`] then [`validate`] against `fields`.
pub(crate) fn parse_model(
    content_type: Option<&str>,
    bytes: &[u8],
    fields: &[Field],
) -> Result<Map<String, Value>, ApiError> {
    let object = parse_object(content_type, bytes)?;
    validate(fields, &object, &[Value::from("body")]).map_err(unprocessable)
}

/// Validate one object against a model; `loc` is the object's location.
pub(crate) fn validate(
    fields: &[Field],
    object: &Map<String, Value>,
    loc: &[Value],
) -> Result<Map<String, Value>, Vec<Value>> {
    let mut errors = Vec::new();
    let mut out = Map::new();
    for field in fields {
        let here = with(loc, Value::from(field.name));
        match object.get(field.name) {
            Some(input) => {
                if let Some(value) = coerce(field.kind, input, &here, &mut errors) {
                    out.insert(field.name.to_owned(), value);
                }
            }
            None => match field.default {
                Some(default) => {
                    out.insert(field.name.to_owned(), default.value());
                }
                None => errors.push(error(
                    "missing",
                    &here,
                    "Field required",
                    &Value::Object(object.clone()),
                    None,
                )),
            },
        }
    }
    for (key, input) in object {
        if !fields.iter().any(|field| field.name == key) {
            errors.push(error(
                "extra_forbidden",
                &with(loc, Value::from(key.as_str())),
                "Extra inputs are not permitted",
                input,
                None,
            ));
        }
    }
    if errors.is_empty() {
        Ok(out)
    } else {
        Err(errors)
    }
}

fn with(loc: &[Value], last: Value) -> Vec<Value> {
    let mut here = loc.to_vec();
    here.push(last);
    here
}

fn error(kind: &str, loc: &[Value], msg: &str, input: &Value, ctx: Option<Value>) -> Value {
    let mut entry = json!({"type": kind, "loc": loc, "msg": msg, "input": input});
    if let (Some(ctx), Value::Object(map)) = (ctx, &mut entry) {
        map.insert("ctx".to_owned(), ctx);
    }
    entry
}

/// Coerce one value; on failure push its error(s) and return `None`.
fn coerce(kind: Kind, input: &Value, loc: &[Value], errors: &mut Vec<Value>) -> Option<Value> {
    let result = match kind {
        Kind::Str => match input {
            Value::String(_) => Ok(input.clone()),
            _ => Err(fail("string_type", "Input should be a valid string", None)),
        },
        Kind::Bool => to_bool(input).map(Value::Bool),
        Kind::Int(ge, le) => to_int(input).and_then(|n| int_bounds(n, ge, le)),
        Kind::OptInt(ge, le) => match input {
            Value::Null => Ok(Value::Null),
            _ => to_int(input).and_then(|n| int_bounds(n, ge, le)),
        },
        Kind::Float(ge, le) => to_float(input).and_then(|f| float_bounds(f, ge, le)),
        Kind::Literal(choices) => literal(input, choices),
        Kind::ListStr => {
            return list_of(input, loc, errors, |item, here, errors| {
                coerce(Kind::Str, item, here, errors)
            })
        }
        Kind::DictInt => return dict_int(input, loc, errors),
        Kind::ListModel(name, fields) => {
            return list_of(input, loc, errors, |item, here, errors| match item {
                Value::Object(object) => match validate(fields, object, here) {
                    Ok(value) => Some(Value::Object(value)),
                    Err(mut found) => {
                        errors.append(&mut found);
                        None
                    }
                },
                _ => {
                    errors.push(error(
                        "model_type",
                        here,
                        &format!("Input should be a valid dictionary or instance of {name}"),
                        item,
                        Some(json!({"class_name": name})),
                    ));
                    None
                }
            })
        }
    };
    match result {
        Ok(value) => Some(value),
        Err((kind, msg, ctx)) => {
            errors.push(error(kind, loc, &msg, input, ctx));
            None
        }
    }
}

type Failure = (&'static str, String, Option<Value>);

fn fail(kind: &'static str, msg: &str, ctx: Option<Value>) -> Failure {
    (kind, msg.to_owned(), ctx)
}

fn list_of(
    input: &Value,
    loc: &[Value],
    errors: &mut Vec<Value>,
    item: impl Fn(&Value, &[Value], &mut Vec<Value>) -> Option<Value>,
) -> Option<Value> {
    let Value::Array(items) = input else {
        errors.push(error(
            "list_type",
            loc,
            "Input should be a valid list",
            input,
            None,
        ));
        return None;
    };
    let before = errors.len();
    let mut out = Vec::with_capacity(items.len());
    for (index, value) in items.iter().enumerate() {
        if let Some(value) = item(value, &with(loc, Value::from(index)), errors) {
            out.push(value);
        }
    }
    (errors.len() == before).then_some(Value::Array(out))
}

fn dict_int(input: &Value, loc: &[Value], errors: &mut Vec<Value>) -> Option<Value> {
    let Value::Object(map) = input else {
        errors.push(error(
            "dict_type",
            loc,
            "Input should be a valid dictionary",
            input,
            None,
        ));
        return None;
    };
    let before = errors.len();
    let mut out = Map::new();
    for (key, value) in map {
        let here = with(loc, Value::from(key.as_str()));
        if let Some(value) = coerce(Kind::Int(None, None), value, &here, errors) {
            out.insert(key.clone(), value);
        }
    }
    (errors.len() == before).then_some(Value::Object(out))
}

fn literal(input: &Value, choices: &[&str]) -> Result<Value, Failure> {
    if let Value::String(text) = input {
        if choices.contains(&text.as_str()) {
            return Ok(input.clone());
        }
    }
    let quoted: Vec<String> = choices.iter().map(|choice| format!("'{choice}'")).collect();
    let expected = match quoted.split_last() {
        Some((last, [])) => last.clone(),
        Some((last, rest)) => format!("{} or {last}", rest.join(", ")),
        None => String::new(),
    };
    Err((
        "literal_error",
        format!("Input should be {expected}"),
        Some(json!({ "expected": expected })),
    ))
}

const BOOL_PARSING: &str = "Input should be a valid boolean, unable to interpret input";

fn to_bool(input: &Value) -> Result<bool, Failure> {
    let parsing = || fail("bool_parsing", BOOL_PARSING, None);
    match input {
        Value::Bool(value) => Ok(*value),
        Value::Number(number) => match number.as_f64() {
            Some(value) if value.fract() != 0.0 => {
                Err(fail("bool_type", "Input should be a valid boolean", None))
            }
            Some(0.0) => Ok(false),
            Some(1.0) => Ok(true),
            _ => Err(parsing()),
        },
        Value::String(text) => match text.to_lowercase().as_str() {
            "0" | "off" | "f" | "false" | "n" | "no" => Ok(false),
            "1" | "on" | "t" | "true" | "y" | "yes" => Ok(true),
            _ => Err(parsing()),
        },
        _ => Err(fail("bool_type", "Input should be a valid boolean", None)),
    }
}

const INT_PARSING: &str = "Input should be a valid integer, unable to parse string as an integer";

/// An integer as pydantic reads it; out-of-range strings saturate (Python
/// ints are unbounded, and every bounded field rejects them either way).
fn to_int(input: &Value) -> Result<i128, Failure> {
    match input {
        Value::Bool(value) => Ok(i128::from(*value)),
        Value::Number(number) => {
            if let Some(value) = number.as_i64() {
                return Ok(i128::from(value));
            }
            if let Some(value) = number.as_u64() {
                return Ok(i128::from(value));
            }
            let value = number.as_f64().unwrap_or(f64::NAN);
            if value.fract() != 0.0 {
                return Err(fail(
                    "int_from_float",
                    "Input should be a valid integer, got a number with a fractional part",
                    None,
                ));
            }
            // i64 range: pydantic refuses larger floats.
            if !(-9.223_372_036_854_776e18..9.223_372_036_854_776e18).contains(&value) {
                return Err(fail(
                    "int_parsing_size",
                    "Unable to parse input string as an integer, exceeded maximum size",
                    None,
                ));
            }
            #[allow(clippy::cast_possible_truncation)]
            Ok(value as i128)
        }
        Value::String(text) => {
            parse_int(py_strip(text)).ok_or_else(|| fail("int_parsing", INT_PARSING, None))
        }
        _ => Err(fail("int_type", "Input should be a valid integer", None)),
    }
}

/// `[+-]digits` with single `_` between digits, optionally followed by
/// `.0…` (pydantic strips a zero fraction).
fn parse_int(text: &str) -> Option<i128> {
    let whole = match text.split_once('.') {
        Some((whole, fraction)) => {
            if fraction.is_empty() || !fraction.chars().all(|c| c == '0') {
                return None;
            }
            whole
        }
        None => text,
    };
    let (negative, digits) = match whole.as_bytes().first() {
        Some(b'-') => (true, whole.get(1..)?),
        Some(b'+') => (false, whole.get(1..)?),
        _ => (false, whole),
    };
    let plain = digits_without_underscores(digits)?;
    let magnitude = plain.parse::<i128>().unwrap_or(i128::MAX);
    Some(if negative { -magnitude } else { magnitude })
}

/// ASCII digits with single underscores between them, underscores removed.
fn digits_without_underscores(text: &str) -> Option<String> {
    let mut out = String::with_capacity(text.len());
    let mut previous_digit = false;
    for c in text.chars() {
        if c.is_ascii_digit() {
            out.push(c);
            previous_digit = true;
        } else if c == '_' && previous_digit {
            previous_digit = false;
        } else {
            return None;
        }
    }
    (previous_digit && !out.is_empty()).then_some(out)
}

fn int_bounds(value: i128, ge: Option<i64>, le: Option<i64>) -> Result<Value, Failure> {
    if let Some(le) = le {
        if value > i128::from(le) {
            return Err((
                "less_than_equal",
                format!("Input should be less than or equal to {le}"),
                Some(json!({ "le": le })),
            ));
        }
    }
    if let Some(ge) = ge {
        if value < i128::from(ge) {
            return Err((
                "greater_than_equal",
                format!("Input should be greater than or equal to {ge}"),
                Some(json!({ "ge": ge })),
            ));
        }
    }
    Ok(i64::try_from(value)
        .map(Value::from)
        .or_else(|_| u64::try_from(value).map(Value::from))
        .unwrap_or_else(|_| json!(value as f64)))
}

fn to_float(input: &Value) -> Result<f64, Failure> {
    match input {
        Value::Bool(value) => Ok(if *value { 1.0 } else { 0.0 }),
        Value::Number(number) => Ok(number.as_f64().unwrap_or(f64::NAN)),
        Value::String(text) => parse_float(py_strip(text)).ok_or_else(|| {
            fail(
                "float_parsing",
                "Input should be a valid number, unable to parse string as a number",
                None,
            )
        }),
        _ => Err(fail("float_type", "Input should be a valid number", None)),
    }
}

/// Python `float()` text: decimal or exponent forms, `inf`/`infinity`/`nan`
/// in any case, single underscores between digits.
fn parse_float(text: &str) -> Option<f64> {
    let mut plain = String::with_capacity(text.len());
    let chars: Vec<char> = text.chars().collect();
    for (index, c) in chars.iter().enumerate() {
        if *c == '_' {
            let digit_before = index > 0 && chars.get(index - 1).is_some_and(char::is_ascii_digit);
            let digit_after = chars.get(index + 1).is_some_and(char::is_ascii_digit);
            if !(digit_before && digit_after) {
                return None;
            }
        } else if c.is_ascii() {
            plain.push(*c);
        } else {
            return None;
        }
    }
    plain.parse::<f64>().ok()
}

fn float_bounds(value: f64, ge: Option<f64>, le: Option<f64>) -> Result<Value, Failure> {
    if let Some(le) = le {
        if value.partial_cmp(&le).is_none_or(|order| order.is_gt()) {
            return Err((
                "less_than_equal",
                // Rust prints a whole float without `.0`, as pydantic does (`1800`).
                format!("Input should be less than or equal to {le}"),
                Some(json!({ "le": le })),
            ));
        }
    }
    if let Some(ge) = ge {
        if value.partial_cmp(&ge).is_none_or(|order| order.is_lt()) {
            return Err((
                "greater_than_equal",
                format!("Input should be greater than or equal to {ge}"),
                Some(json!({ "ge": ge })),
            ));
        }
    }
    Ok(json!(value))
}

#[cfg(test)]
#[allow(clippy::unwrap_used, clippy::expect_used, clippy::indexing_slicing)]
mod tests {
    use super::*;

    fn detail(result: Result<Map<String, Value>, ApiError>) -> (u16, Value) {
        let error = result.unwrap_err();
        (error.status.as_u16(), error.detail)
    }

    const ONE: &[Field] = &[Field {
        name: "code",
        kind: Kind::Str,
        default: None,
    }];

    #[test]
    fn empty_and_null_bodies_are_missing() {
        let missing =
            json!([{"type": "missing", "loc": ["body"], "msg": "Field required", "input": null}]);
        for bytes in [&b""[..], b"null", b" null "] {
            assert_eq!(
                detail(parse_model(Some("application/json"), bytes, ONE)),
                (422, missing.clone())
            );
        }
    }

    #[test]
    fn non_objects_are_model_attributes_type() {
        for (content_type, bytes, input) in [
            (Some("application/json"), &b"[]"[..], json!([])),
            (Some("application/json"), b"1", json!(1)),
            (Some("application/json"), b"\"s\"", json!("s")),
            (
                Some("text/plain"),
                b"{\"code\":\"c\"}",
                json!("{\"code\":\"c\"}"),
            ),
            (None, b"{}", json!("{}")),
        ] {
            let (status, found) = detail(parse_model(content_type, bytes, ONE));
            assert_eq!(status, 422);
            assert_eq!(
                found,
                json!([{"type": "model_attributes_type", "loc": ["body"],
                    "msg": "Input should be a valid dictionary or object to extract fields from",
                    "input": input}])
            );
        }
    }

    #[test]
    fn json_content_types_and_decode_errors() {
        for content_type in ["application/json; charset=utf-8", "Application/VND.x+JSON"] {
            let parsed = parse_model(Some(content_type), b"{\"code\":\"c\"}", ONE).unwrap();
            assert_eq!(parsed["code"], "c");
        }
        assert_eq!(
            detail(parse_model(Some("application/json"), b"{bad", ONE)),
            (
                422,
                json!([{"type": "json_invalid", "loc": ["body", 1], "msg": "JSON decode error",
                    "input": {}, "ctx": {"error": "Expecting property name enclosed in double quotes"}}])
            )
        );
        let (status, found) = detail(parse_model(Some("application/json"), b"\xff", ONE));
        assert_eq!(
            (status, found),
            (400, json!("There was an error parsing the body"))
        );
        assert!(!is_json(Some("text/json")));
        assert!(!is_json(Some("application/xml")));
    }

    #[test]
    fn literal_wording_for_three_choices() {
        let (kind, msg, ctx) = literal(&json!("x"), &["a", "b", "c"]).unwrap_err();
        assert_eq!(kind, "literal_error");
        assert_eq!(msg, "Input should be 'a', 'b' or 'c'");
        assert_eq!(ctx, Some(json!({"expected": "'a', 'b' or 'c'"})));
        assert_eq!(literal(&json!("a"), &["a"]).unwrap(), json!("a"));
    }

    #[test]
    fn int_and_float_text_rules() {
        for (text, expected) in [
            ("3", Some(3)),
            ("+3", Some(3)),
            ("-0", Some(0)),
            ("0_3", Some(3)),
            ("1_0.0", Some(10)),
            ("3.00", Some(3)),
            ("3.", None),
            (".0", None),
            ("1__0", None),
            ("_1", None),
            ("1_", None),
            ("+-3", None),
            ("3e0", None),
            ("", None),
            ("-", None),
        ] {
            assert_eq!(parse_int(text), expected, "{text:?}");
        }
        assert_eq!(parse_int("9".repeat(60).as_str()), Some(i128::MAX));
        assert_eq!(parse_int(&format!("-{}", "9".repeat(60))), Some(-i128::MAX));
        for (text, expected) in [
            ("1_0", Some(10.0)),
            ("1_0.5", Some(10.5)),
            (".5", Some(0.5)),
            ("5.", Some(5.0)),
            ("+1.5", Some(1.5)),
            ("1e2", Some(100.0)),
            ("_1", None),
            ("1_", None),
            ("1,5", None),
            ("0x1", None),
            ("1e", None),
            ("\u{661}", None),
        ] {
            assert_eq!(parse_float(text), expected, "{text:?}");
        }
        assert!(parse_float("-Infinity").unwrap().is_infinite());
        assert!(parse_float("NaN").unwrap().is_nan());
        assert_eq!(parse_float("1._5"), None);
        assert_eq!(parse_float("1_.5"), None);
        let (_, msg, _) = float_bounds(1.5, None, Some(1.0)).unwrap_err();
        assert_eq!(msg, "Input should be less than or equal to 1");
        let (_, msg, _) = float_bounds(0.5, Some(1.5), None).unwrap_err();
        assert_eq!(msg, "Input should be greater than or equal to 1.5");
    }

    #[test]
    fn big_numbers() {
        assert_eq!(to_int(&json!(u64::MAX)).unwrap(), i128::from(u64::MAX));
        assert_eq!(to_int(&json!(9.0e18)).unwrap(), 9_000_000_000_000_000_000);
        assert_eq!(to_int(&json!(1e19)).unwrap_err().0, "int_parsing_size");
        assert_eq!(to_int(&json!(-1e19)).unwrap_err().0, "int_parsing_size");
        assert_eq!(
            int_bounds(i128::from(u64::MAX), None, None).unwrap(),
            json!(u64::MAX)
        );
        assert_eq!(
            int_bounds(i128::MAX, None, None).unwrap(),
            json!(i128::MAX as f64)
        );
        assert_eq!(int_bounds(-5, None, None).unwrap(), json!(-5));
    }
}
