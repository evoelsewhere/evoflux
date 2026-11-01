//! Python's `json.dumps(value)` with its defaults: `", "` and `": "`
//! separators and `ensure_ascii=True`. SSE `data:` lines (`StreamEnvelope.to_wire`)
//! and SQLAlchemy JSON columns are written this way, so the bytes match.

use serde_json::Value;

/// `json.dumps(value)`.
pub(crate) fn dumps(value: &Value) -> String {
    let mut out = String::new();
    write_value(&mut out, value);
    out
}

fn write_value(out: &mut String, value: &Value) {
    match value {
        Value::Null => out.push_str("null"),
        Value::Bool(true) => out.push_str("true"),
        Value::Bool(false) => out.push_str("false"),
        Value::Number(n) => out.push_str(&n.to_string()),
        Value::String(s) => write_str(out, s),
        Value::Array(items) => {
            out.push('[');
            for (i, item) in items.iter().enumerate() {
                if i > 0 {
                    out.push_str(", ");
                }
                write_value(out, item);
            }
            out.push(']');
        }
        Value::Object(map) => {
            out.push('{');
            for (i, (key, item)) in map.iter().enumerate() {
                if i > 0 {
                    out.push_str(", ");
                }
                write_str(out, key);
                out.push_str(": ");
                write_value(out, item);
            }
            out.push('}');
        }
    }
}

fn write_str(out: &mut String, s: &str) {
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{08}' => out.push_str("\\b"),
            '\u{0c}' => out.push_str("\\f"),
            c if c.is_ascii() && !c.is_ascii_control() => out.push(c),
            c => {
                let mut units = [0u16; 2];
                for unit in c.encode_utf16(&mut units) {
                    out.push_str(&format!("\\u{unit:04x}"));
                }
            }
        }
    }
    out.push('"');
}

#[cfg(test)]
#[allow(
    clippy::unwrap_used,
    clippy::indexing_slicing,
    clippy::disallowed_methods
)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn matches_python_json_dumps() {
        // json.dumps({"a": [1, 2.5, None, True, False], "b": "x\"\\\n\r\t\b\f\x01", "c": {}})
        let value =
            json!({"a": [1, 2.5, null, true, false], "b": "x\"\\\n\r\t\u{8}\u{c}\u{1}", "c": {}});
        assert_eq!(
            dumps(&value),
            r#"{"a": [1, 2.5, null, true, false], "b": "x\"\\\n\r\t\b\f\u0001", "c": {}}"#
        );
    }

    #[test]
    fn escapes_non_ascii_like_ensure_ascii() {
        // json.dumps("é — 😀\x7f")
        assert_eq!(
            dumps(&json!("\u{e9} \u{2014} \u{1f600}\u{7f}")),
            format!("\"{0}u00e9 {0}u2014 {0}ud83d{0}ude00{0}u007f\"", '\\')
        );
        assert_eq!(dumps(&json!([])), "[]");
    }

    #[test]
    fn floats_keep_their_fraction() {
        assert_eq!(dumps(&json!(734.0)), "734.0");
        assert_eq!(dumps(&json!(16.125)), "16.125");
    }
}
