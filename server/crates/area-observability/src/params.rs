//! FastAPI `Query(..., ge=, le=)` validation for the three routes, with
//! pydantic's `int` parsing and error bodies (`{"detail":[{type,loc,msg,input,ctx}]}`).

use axum::http::StatusCode;
use evoflux_core::ApiError;
use serde_json::{json, Value};

/// One integer query parameter with its default and bounds.
pub struct IntParam {
    pub name: &'static str,
    pub default: i64,
    pub min: i64,
    pub max: Option<i64>,
}

/// Percent-decoding of a query component (`+` is a space), lossy on bad UTF-8.
fn decode(raw: &str) -> String {
    let mut rest = raw.as_bytes();
    let mut out = Vec::with_capacity(rest.len());
    while let Some((&byte, tail)) = rest.split_first() {
        rest = tail;
        match byte {
            b'+' => out.push(b' '),
            b'%' => {
                let pair = tail
                    .get(..2)
                    .and_then(|hex| std::str::from_utf8(hex).ok())
                    .and_then(|hex| u8::from_str_radix(hex, 16).ok());
                if let Some(value) = pair {
                    out.push(value);
                    rest = tail.get(2..).unwrap_or_default();
                } else {
                    out.push(b'%');
                }
            }
            other => out.push(other),
        }
    }
    String::from_utf8_lossy(&out).into_owned()
}

/// The last value of `key` (Starlette's `query_params[key]`), decoded.
pub fn query_last(query: Option<&str>, key: &str) -> Option<String> {
    let mut found = None;
    for pair in query.unwrap_or_default().split('&') {
        if pair.is_empty() {
            continue;
        }
        let (name, value) = pair.split_once('=').unwrap_or((pair, ""));
        if decode(name) == key {
            found = Some(decode(value));
        }
    }
    found
}

/// pydantic lax `int` from a string: surrounding whitespace, optional sign and
/// digits, or a whole number written as `12.0`. `None` is `int_parsing`.
fn parse_int(raw: &str) -> Option<i128> {
    let text = raw.trim();
    let (negative, digits) = match text.strip_prefix('-') {
        Some(rest) => (true, rest),
        None => (false, text.strip_prefix('+').unwrap_or(text)),
    };
    let (whole, fraction) = match digits.split_once('.') {
        Some((whole, fraction)) => (whole, Some(fraction)),
        None => (digits, None),
    };
    if let Some(fraction) = fraction {
        if !fraction.chars().all(|c| c == '0') {
            return None;
        }
    }
    if whole.is_empty() || !whole.chars().all(|c| c.is_ascii_digit()) {
        return None;
    }
    let value: i128 = whole.parse().ok()?;
    Some(if negative { -value } else { value })
}

fn error(kind: &str, name: &str, msg: String, input: &str, ctx: Option<Value>) -> Value {
    let mut entry = json!({"type": kind, "loc": ["query", name], "msg": msg, "input": input});
    if let (Some(ctx), Some(map)) = (ctx, entry.as_object_mut()) {
        map.insert("ctx".to_owned(), ctx);
    }
    entry
}

/// Validate `params` in order. All errors are reported together, like FastAPI.
pub fn validate(query: Option<&str>, params: &[IntParam]) -> Result<Vec<i64>, ApiError> {
    let mut values = Vec::with_capacity(params.len());
    let mut errors = Vec::new();
    for param in params {
        let Some(raw) = query_last(query, param.name) else {
            values.push(param.default);
            continue;
        };
        let Some(parsed) = parse_int(&raw) else {
            errors.push(error(
                "int_parsing",
                param.name,
                "Input should be a valid integer, unable to parse string as an integer".to_owned(),
                &raw,
                None,
            ));
            continue;
        };
        if parsed < i128::from(param.min) {
            errors.push(error(
                "greater_than_equal",
                param.name,
                format!("Input should be greater than or equal to {}", param.min),
                &raw,
                Some(json!({"ge": param.min})),
            ));
        } else if let Some(max) = param.max.filter(|max| parsed > i128::from(*max)) {
            errors.push(error(
                "less_than_equal",
                param.name,
                format!("Input should be less than or equal to {max}"),
                &raw,
                Some(json!({"le": max})),
            ));
        } else {
            values.push(i64::try_from(parsed).unwrap_or(param.default));
        }
    }
    if errors.is_empty() {
        Ok(values)
    } else {
        Err(ApiError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            Value::Array(errors),
        ))
    }
}

#[cfg(test)]
#[allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::indexing_slicing,
    clippy::disallowed_methods
)]
mod tests {
    use super::*;

    const DAYS: IntParam = IntParam {
        name: "days",
        default: 7,
        min: 1,
        max: Some(90),
    };
    const OFFSET: IntParam = IntParam {
        name: "offset",
        default: 0,
        min: 0,
        max: None,
    };

    fn first_error(query: &str, params: &[IntParam]) -> Value {
        let error = validate(Some(query), params).unwrap_err();
        assert_eq!(error.status, StatusCode::UNPROCESSABLE_ENTITY);
        error.detail
    }

    #[test]
    fn defaults_apply_without_a_query() {
        assert_eq!(validate(None, &[DAYS, OFFSET]).unwrap(), [7, 0]);
        assert_eq!(validate(Some("other=1"), &[DAYS]).unwrap(), [7]);
    }

    #[test]
    fn bounds_are_inclusive() {
        assert_eq!(validate(Some("days=1"), &[DAYS]).unwrap(), [1]);
        assert_eq!(validate(Some("days=90"), &[DAYS]).unwrap(), [90]);
        assert_eq!(
            validate(Some("offset=999999"), &[OFFSET]).unwrap(),
            [999_999]
        );
    }

    #[test]
    fn days_zero_and_91_are_python_422_bodies() {
        assert_eq!(
            first_error("days=0", &[DAYS]),
            json!([{
                "type": "greater_than_equal", "loc": ["query", "days"],
                "msg": "Input should be greater than or equal to 1",
                "input": "0", "ctx": {"ge": 1}
            }])
        );
        assert_eq!(
            first_error("days=91", &[DAYS]),
            json!([{
                "type": "less_than_equal", "loc": ["query", "days"],
                "msg": "Input should be less than or equal to 90",
                "input": "91", "ctx": {"le": 90}
            }])
        );
        assert_eq!(
            first_error("offset=-1", &[OFFSET])[0]["msg"],
            "Input should be greater than or equal to 0"
        );
    }

    #[test]
    fn non_integers_are_int_parsing_without_ctx() {
        for given in ["abc", "1.5", "", " ", "1e1", "--1", "_1", "1_0", "0x10"] {
            let body = first_error(&format!("days={given}"), &[DAYS]);
            assert_eq!(
                body,
                json!([{
                    "type": "int_parsing", "loc": ["query", "days"],
                    "msg": "Input should be a valid integer, unable to parse string as an integer",
                    "input": given
                }]),
                "{given:?}"
            );
        }
    }

    #[test]
    fn lenient_integer_spellings_are_accepted() {
        for (given, expected) in [
            ("+5", 5),
            (" 5 ", 5),
            ("%205%20", 5),
            ("5.0", 5),
            ("5.000", 5),
            ("007", 7),
        ] {
            assert_eq!(
                validate(Some(&format!("days={given}")), &[DAYS]).unwrap(),
                [expected],
                "{given:?}"
            );
        }
    }

    #[test]
    fn huge_integers_are_range_errors_not_parse_errors() {
        let body = first_error("days=99999999999999999999999", &[DAYS]);
        assert_eq!(body[0]["type"], "less_than_equal");
        assert_eq!(body[0]["input"], "99999999999999999999999");
    }

    #[test]
    fn several_errors_come_back_in_parameter_order() {
        let limit = IntParam {
            name: "limit",
            default: 50,
            min: 1,
            max: Some(200),
        };
        let body = first_error("offset=-1&limit=0&days=91", &[DAYS, limit, OFFSET]);
        let names: Vec<_> = body
            .as_array()
            .unwrap()
            .iter()
            .map(|entry| entry["loc"][1].as_str().unwrap().to_owned())
            .collect();
        assert_eq!(names, ["days", "limit", "offset"]);
    }

    #[test]
    fn the_last_duplicate_wins_and_values_are_decoded() {
        assert_eq!(validate(Some("days=3&days=4"), &[DAYS]).unwrap(), [4]);
        assert_eq!(query_last(Some("a%20b=c%2Bd+e"), "a b").unwrap(), "c+d e");
        assert_eq!(query_last(Some("flag"), "flag").unwrap(), "");
        assert_eq!(query_last(Some("a=%zz"), "a").unwrap(), "%zz");
        assert_eq!(query_last(Some("&&"), "a"), None);
        assert_eq!(query_last(None, "a"), None);
    }
}
