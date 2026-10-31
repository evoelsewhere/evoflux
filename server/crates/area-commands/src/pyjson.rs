//! The error `json.loads` would raise (`JSONDecodeError.pos` and `.msg`),
//! used to word FastAPI's `json_invalid` 422. Python 3.12 rules.

type Scan<T> = Result<T, (usize, &'static str)>;

const MAX_DEPTH: usize = 400;

/// `(character offset, message)` of the first error, or `None` when Python
/// would accept the text.
pub(crate) fn first_error(text: &str) -> Option<(usize, &'static str)> {
    let scanner = Scanner {
        chars: text.chars().collect(),
    };
    let start = scanner.skip_space(0);
    match scanner.value(start, 0) {
        Err(error) => Some(error),
        Ok(end) => {
            let end = scanner.skip_space(end);
            (end != scanner.chars.len()).then_some((end, "Extra data"))
        }
    }
}

struct Scanner {
    chars: Vec<char>,
}

impl Scanner {
    fn at(&self, index: usize) -> Option<char> {
        self.chars.get(index).copied()
    }

    fn skip_space(&self, index: usize) -> usize {
        let spaces = self.chars.get(index..).map_or(0, |rest| {
            rest.iter()
                .take_while(|c| matches!(c, ' ' | '\t' | '\n' | '\r'))
                .count()
        });
        index + spaces
    }

    fn literal(&self, index: usize, word: &str) -> Scan<usize> {
        let end = index + word.chars().count();
        let matches = self
            .chars
            .get(index..end)
            .is_some_and(|found| found.iter().copied().eq(word.chars()));
        if matches {
            Ok(end)
        } else {
            Err((index, "Expecting value"))
        }
    }

    fn digits(&self, index: usize) -> usize {
        let digits = self.chars.get(index..).map_or(0, |rest| {
            rest.iter().take_while(|c| c.is_ascii_digit()).count()
        });
        index + digits
    }

    /// `-?(0|[1-9]\d*)(\.\d+)?([eE][-+]?\d+)?`
    fn number(&self, start: usize) -> Scan<usize> {
        let mut index = start + usize::from(self.at(start) == Some('-'));
        match self.at(index) {
            Some('0') => index += 1,
            Some('1'..='9') => index = self.digits(index),
            _ => return Err((start, "Expecting value")),
        }
        if self.at(index) == Some('.') && self.digits(index + 1) > index + 1 {
            index = self.digits(index + 1);
        }
        if matches!(self.at(index), Some('e' | 'E')) {
            let sign = usize::from(matches!(self.at(index + 1), Some('-' | '+')));
            let end = self.digits(index + 1 + sign);
            if end > index + 1 + sign {
                index = end;
            }
        }
        Ok(index)
    }

    /// `begin` is the offset just after the opening quote.
    fn string(&self, begin: usize) -> Scan<usize> {
        let unterminated = (begin.saturating_sub(1), "Unterminated string starting at");
        let mut index = begin;
        // Every step consumes a character, so the document length bounds the loop.
        for _ in 0..=self.chars.len() {
            match self.at(index) {
                None => return Err(unterminated),
                Some('"') => return Ok(index + 1),
                Some('\\') => match self.at(index + 1) {
                    None => return Err(unterminated),
                    Some('u') => {
                        let hex = self.chars.get(index + 2..index + 6);
                        if !hex.is_some_and(|h| h.iter().all(char::is_ascii_hexdigit)) {
                            return Err((index + 1, "Invalid \\uXXXX escape"));
                        }
                        index += 6;
                    }
                    Some('"' | '\\' | '/' | 'b' | 'f' | 'n' | 'r' | 't') => index += 2,
                    Some(_) => return Err((index, "Invalid \\escape")),
                },
                Some(c) if u32::from(c) < 0x20 => {
                    return Err((index, "Invalid control character at"))
                }
                Some(_) => index += 1,
            }
        }
        Err(unterminated)
    }

    fn object(&self, start: usize, depth: usize) -> Scan<usize> {
        let mut index = self.skip_space(start);
        if self.at(index) == Some('}') {
            return Ok(index + 1);
        }
        for _ in 0..=self.chars.len() {
            if self.at(index) != Some('"') {
                return Err((index, "Expecting property name enclosed in double quotes"));
            }
            index = self.skip_space(self.string(index + 1)?);
            if self.at(index) != Some(':') {
                return Err((index, "Expecting ':' delimiter"));
            }
            index = self.skip_space(index + 1);
            index = self.skip_space(self.value(index, depth + 1)?);
            match self.at(index) {
                Some('}') => return Ok(index + 1),
                Some(',') => index = self.skip_space(index + 1),
                _ => return Err((index, "Expecting ',' delimiter")),
            }
        }
        Err((index, "Expecting ',' delimiter"))
    }

    fn array(&self, start: usize, depth: usize) -> Scan<usize> {
        let mut index = self.skip_space(start);
        if self.at(index) == Some(']') {
            return Ok(index + 1);
        }
        for _ in 0..=self.chars.len() {
            index = self.skip_space(self.value(index, depth + 1)?);
            match self.at(index) {
                Some(']') => return Ok(index + 1),
                Some(',') => index = self.skip_space(index + 1),
                _ => return Err((index, "Expecting ',' delimiter")),
            }
        }
        Err((index, "Expecting ',' delimiter"))
    }

    fn value(&self, index: usize, depth: usize) -> Scan<usize> {
        if depth > MAX_DEPTH {
            return Err((index, "Expecting value"));
        }
        match self.at(index) {
            Some('"') => self.string(index + 1),
            Some('{') => self.object(index + 1, depth),
            Some('[') => self.array(index + 1, depth),
            Some('n') => self.literal(index, "null"),
            Some('t') => self.literal(index, "true"),
            Some('f') => self.literal(index, "false"),
            Some('N') => self.literal(index, "NaN"),
            Some('I') => self.literal(index, "Infinity"),
            Some('-') => self
                .literal(index, "-Infinity")
                .or_else(|_| self.number(index)),
            Some('0'..='9') => self.number(index),
            _ => Err((index, "Expecting value")),
        }
    }
}

#[cfg(test)]
#[allow(clippy::unwrap_used, clippy::expect_used, clippy::indexing_slicing)]
mod tests {
    use super::*;

    #[test]
    fn matches_cpython_for_invalid_documents() {
        let cases: [(&str, usize, &str); 31] = [
            (
                "{not json",
                1,
                "Expecting property name enclosed in double quotes",
            ),
            ("{\"a\" 1}", 5, "Expecting ':' delimiter"),
            ("{\"a\":1 \"b\":2}", 7, "Expecting ',' delimiter"),
            ("[1 2]", 3, "Expecting ',' delimiter"),
            ("{} x", 3, "Extra data"),
            ("[,]", 1, "Expecting value"),
            ("{\"a\":\"b", 5, "Unterminated string starting at"),
            ("\"a\nb\"", 2, "Invalid control character at"),
            ("\"\\q\"", 1, "Invalid \\escape"),
            ("nul", 0, "Expecting value"),
            ("{", 1, "Expecting property name enclosed in double quotes"),
            ("[", 1, "Expecting value"),
            ("{\"a\"", 4, "Expecting ':' delimiter"),
            ("{\"a\":1", 6, "Expecting ',' delimiter"),
            ("{\"a\":", 5, "Expecting value"),
            ("[1,", 3, "Expecting value"),
            ("tru", 0, "Expecting value"),
            ("01", 1, "Extra data"),
            ("-", 0, "Expecting value"),
            (
                "{\"a\":1,}",
                7,
                "Expecting property name enclosed in double quotes",
            ),
            ("[1,]", 3, "Expecting value"),
            ("\"\\u12\"", 2, "Invalid \\uXXXX escape"),
            ("  ", 2, "Expecting value"),
            ("{\"a\":1}}", 7, "Extra data"),
            ("{\"a\" : }", 7, "Expecting value"),
            ("[ ,1]", 2, "Expecting value"),
            ("\"abc", 0, "Unterminated string starting at"),
            ("1.", 1, "Extra data"),
            ("{\"a\":1,\"b\"}", 10, "Expecting ':' delimiter"),
            ("é x", 0, "Expecting value"),
            ("{\"é\":}", 5, "Expecting value"),
        ];
        for (text, position, message) in cases {
            assert_eq!(first_error(text), Some((position, message)), "{text:?}");
        }
    }

    #[test]
    fn incomplete_exponents_and_fractions_are_extra_data() {
        for (text, position) in [("1e", 1), ("1e+", 1), ("1E-", 1), ("1.5e", 3), ("1.5e+", 3)] {
            assert_eq!(
                first_error(text),
                Some((position, "Extra data")),
                "{text:?}"
            );
        }
        for text in ["1e5", "1e-5", "1E+5", "1.5e+10", "[1e1,2]"] {
            assert_eq!(first_error(text), None, "{text:?}");
        }
    }

    #[test]
    fn spaces_inside_strings_are_fine_and_nesting_is_bounded() {
        assert_eq!(first_error("\"a b\""), None);
        let nested = |open: &str, close: &str, count: usize| {
            format!("{}0{}", open.repeat(count), close.repeat(count))
        };
        assert_eq!(first_error(&nested("[", "]", 400)), None);
        assert_eq!(
            first_error(&nested("[", "]", 401)),
            Some((401, "Expecting value"))
        );
        assert_eq!(first_error(&nested("{\"a\":", "}", 400)), None);
        assert_eq!(
            first_error(&nested("{\"a\":", "}", 401)),
            Some((401 * 5, "Expecting value"))
        );
    }

    #[test]
    fn accepts_what_python_accepts() {
        for text in [
            "{}",
            "[]",
            " [1, 2.5e3, -0, true, false, null, \"x\"] ",
            "{\"a\": {\"b\": [1, {\"c\": \"\\u00e9\\n\\/\"}]}}",
            "\"\\ud800\"",
            "NaN",
            "[Infinity, -Infinity]",
            "-1.5E+2",
            "{\"k\":\"\\\"\\\\\\b\\f\\r\\t\"}",
        ] {
            assert_eq!(first_error(text), None, "{text:?}");
        }
    }
}
