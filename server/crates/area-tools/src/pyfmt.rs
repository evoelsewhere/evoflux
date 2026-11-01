//! Python text semantics the tool output depends on (`str.isspace`,
//! `str.splitlines`, `repr`, the `:,` format), so the model sees the same bytes.

use serde_json::Value;

/// `str.isspace()` for one code point.
pub(crate) fn is_py_space(c: char) -> bool {
    matches!(
        c,
        '\t'
            | '\n'
            | '\u{0b}'
            | '\u{0c}'
            | '\r'
            | '\u{1c}'..='\u{20}'
            | '\u{85}'
            | '\u{a0}'
            | '\u{1680}'
            | '\u{2000}'..='\u{200a}'
            | '\u{2028}'
            | '\u{2029}'
            | '\u{202f}'
            | '\u{205f}'
            | '\u{3000}'
    )
}

/// `str.strip()`.
pub(crate) fn strip(s: &str) -> &str {
    s.trim_matches(is_py_space)
}

/// `str.rstrip()`.
pub(crate) fn rstrip(s: &str) -> &str {
    s.trim_end_matches(is_py_space)
}

/// `f"{n:,}"`.
pub(crate) fn thousands(n: usize) -> String {
    let digits = n.to_string();
    let mut out = String::with_capacity(digits.len() + digits.len() / 3);
    for (i, c) in digits.chars().enumerate() {
        if i > 0 && (digits.len() - i).is_multiple_of(3) {
            out.push(',');
        }
        out.push(c);
    }
    out
}

/// `text[:n]` — the first `n` code points.
pub(crate) fn char_prefix(s: &str, n: usize) -> &str {
    match s.char_indices().nth(n) {
        Some((end, _)) => s.get(..end).unwrap_or(s),
        None => s,
    }
}

fn is_line_break(c: char) -> bool {
    matches!(
        c,
        '\n' | '\r'
            | '\u{0b}'
            | '\u{0c}'
            | '\u{1c}'
            | '\u{1d}'
            | '\u{1e}'
            | '\u{85}'
            | '\u{2028}'
            | '\u{2029}'
    )
}

/// One piece of `str.splitlines(keepends=True)`.
pub(crate) struct Line<'a> {
    pub(crate) full: &'a str,
    pub(crate) body: &'a str,
}

/// `str.splitlines(keepends=True)`, with the terminator-free body alongside.
pub(crate) fn splitlines(s: &str) -> Vec<Line<'_>> {
    let mut lines = Vec::new();
    let mut start = 0;
    let mut chars = s.char_indices().peekable();
    while let Some((i, c)) = chars.next() {
        if !is_line_break(c) {
            continue;
        }
        let mut end = i + c.len_utf8();
        if c == '\r' {
            if let Some(&(_, '\n')) = chars.peek() {
                chars.next();
                end += 1;
            }
        }
        lines.push(Line {
            full: s.get(start..end).unwrap_or_default(),
            body: s.get(start..i).unwrap_or_default(),
        });
        start = end;
    }
    if start < s.len() {
        let rest = s.get(start..).unwrap_or_default();
        lines.push(Line {
            full: rest,
            body: rest,
        });
    }
    lines
}

/// Code points `str.isprintable()` rejects that `char::is_control` does not.
fn is_unprintable(c: char) -> bool {
    matches!(
        c,
        '\u{a0}'
            | '\u{ad}'
            | '\u{1680}'
            | '\u{2000}'..='\u{200f}'
            | '\u{2028}'..='\u{202f}'
            | '\u{205f}'..='\u{2064}'
            | '\u{3000}'
            | '\u{feff}'
    )
}

/// `repr(str)`.
pub(crate) fn repr_str(s: &str) -> String {
    let quote = if s.contains('\'') && !s.contains('"') {
        '"'
    } else {
        '\''
    };
    let mut out = String::with_capacity(s.len() + 2);
    out.push(quote);
    for c in s.chars() {
        match c {
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if c == quote => {
                out.push('\\');
                out.push(c);
            }
            c if c.is_control() || is_unprintable(c) => {
                let code = u32::from(c);
                match u8::try_from(code) {
                    Ok(byte) => out.push_str(&format!("\\x{byte:02x}")),
                    Err(_) => out.push_str(&format!("\\u{code:04x}")),
                }
            }
            c => out.push(c),
        }
    }
    out.push(quote);
    out
}

/// `repr()` of a decoded JSON value.
pub(crate) fn repr_value(value: &Value) -> String {
    match value {
        Value::Null => "None".to_owned(),
        Value::Bool(true) => "True".to_owned(),
        Value::Bool(false) => "False".to_owned(),
        // Matches Python for ordinary values; very large or tiny floats use
        // an exponent form that differs (`1e20` against `1e+20`).
        Value::Number(n) => n.to_string(),
        Value::String(s) => repr_str(s),
        Value::Array(items) => {
            let inner: Vec<String> = items.iter().map(repr_value).collect();
            format!("[{}]", inner.join(", "))
        }
        Value::Object(map) => {
            let inner: Vec<String> = map
                .iter()
                .map(|(k, v)| format!("{}: {}", repr_str(k), repr_value(v)))
                .collect();
            format!("{{{}}}", inner.join(", "))
        }
    }
}

/// `type(value).__name__` for a decoded JSON value.
pub(crate) fn type_name(value: &Value) -> &'static str {
    match value {
        Value::Null => "NoneType",
        Value::Bool(_) => "bool",
        Value::Number(n) if n.is_f64() => "float",
        Value::Number(_) => "int",
        Value::String(_) => "str",
        Value::Array(_) => "list",
        Value::Object(_) => "dict",
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

    #[test]
    fn thousands_groups_by_three() {
        assert_eq!(thousands(0), "0");
        assert_eq!(thousands(999), "999");
        assert_eq!(thousands(1000), "1,000");
        assert_eq!(thousands(21_345), "21,345");
        assert_eq!(thousands(1_234_567), "1,234,567");
    }

    #[test]
    fn char_prefix_counts_code_points() {
        assert_eq!(char_prefix("héllo", 2), "hé");
        assert_eq!(char_prefix("abc", 3), "abc");
        assert_eq!(char_prefix("abc", 10), "abc");
        assert_eq!(char_prefix("abc", 0), "");
    }

    #[test]
    fn space_set_matches_python() {
        for c in [
            '\t', '\n', '\u{0b}', '\u{0c}', '\r', '\u{1c}', '\u{1f}', ' ', '\u{85}', '\u{a0}',
            '\u{1680}', '\u{2000}', '\u{200a}', '\u{2028}', '\u{2029}', '\u{202f}', '\u{205f}',
            '\u{3000}',
        ] {
            assert!(is_py_space(c), "{c:?}");
        }
        for c in ['a', '\u{1b}', '\u{200b}', '\u{feff}', '\u{180e}', '\0', '!'] {
            assert!(!is_py_space(c), "{c:?}");
        }
        assert_eq!(rstrip("ab \u{1c}\n"), "ab");
        assert_eq!(rstrip(" ab"), " ab");
        assert_eq!(strip("\u{a0} ab\t"), "ab");
    }

    fn bodies(s: &str) -> Vec<(&str, &str)> {
        splitlines(s)
            .into_iter()
            .map(|l| (l.full, l.body))
            .collect()
    }

    #[test]
    fn splitlines_follows_python_boundaries() {
        assert!(bodies("").is_empty());
        assert_eq!(bodies("a\nb"), vec![("a\n", "a"), ("b", "b")]);
        assert_eq!(
            bodies("a\n\nb\n"),
            vec![("a\n", "a"), ("\n", ""), ("b\n", "b")]
        );
        assert_eq!(
            bodies("a\r\nb\rc"),
            vec![("a\r\n", "a"), ("b\r", "b"), ("c", "c")]
        );
        assert_eq!(
            bodies("a\u{0b}b\u{0c}c\u{1c}d\u{1d}e\u{1e}f\u{85}g\u{2028}h\u{2029}i"),
            vec![
                ("a\u{0b}", "a"),
                ("b\u{0c}", "b"),
                ("c\u{1c}", "c"),
                ("d\u{1d}", "d"),
                ("e\u{1e}", "e"),
                ("f\u{85}", "f"),
                ("g\u{2028}", "g"),
                ("h\u{2029}", "h"),
                ("i", "i"),
            ]
        );
        assert_eq!(bodies("\r"), vec![("\r", "")]);
        assert_eq!(bodies("\n\r"), vec![("\n", ""), ("\r", "")]);
    }

    #[test]
    fn repr_str_picks_quotes_and_escapes() {
        assert_eq!(repr_str("abc"), "'abc'");
        assert_eq!(repr_str("it's"), "\"it's\"");
        assert_eq!(repr_str("a\"b'c"), "'a\"b\\'c'");
        assert_eq!(repr_str("a\\b\n\r\t"), "'a\\\\b\\n\\r\\t'");
        assert_eq!(
            repr_str("\u{1}\u{7f}\u{85}\u{2028}"),
            "'\\x01\\x7f\\x85\\u2028'"
        );
        assert_eq!(repr_str("é"), "'é'");
    }

    #[test]
    fn repr_value_matches_python() {
        let v = json!({"a": 1, "b": [true, null, 1.5, 2.0, "x"], "c": {}});
        assert_eq!(
            repr_value(&v),
            "{'a': 1, 'b': [True, None, 1.5, 2.0, 'x'], 'c': {}}"
        );
        assert_eq!(repr_value(&json!(false)), "False");
        assert_eq!(repr_value(&json!(-3)), "-3");
    }

    #[test]
    fn type_names_match_python() {
        assert_eq!(type_name(&json!(null)), "NoneType");
        assert_eq!(type_name(&json!(true)), "bool");
        assert_eq!(type_name(&json!(1)), "int");
        assert_eq!(type_name(&json!(1.5)), "float");
        assert_eq!(type_name(&json!("s")), "str");
        assert_eq!(type_name(&json!([])), "list");
        assert_eq!(type_name(&json!({})), "dict");
    }
}
