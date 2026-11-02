//! Port of python-dotenv 1.2.2: parser.py, variables.py and main.resolve_variables.

use crate::DotenvError;
use indexmap::IndexMap;
use std::path::Path;

// Python's Unicode \s includes the four information separators, unlike Rust.
pub(crate) fn whitespace(c: char) -> bool {
    c.is_whitespace() || matches!(c, '\u{1c}'..='\u{1f}')
}

fn horizontal(c: char) -> bool {
    whitespace(c) && !matches!(c, '\r' | '\n')
}

pub(crate) fn universal_newlines(text: &str) -> String {
    text.replace("\r\n", "\n").replace('\r', "\n")
}

struct Reader<'a> {
    rest: &'a str,
}

impl<'a> Reader<'a> {
    fn take(&mut self, predicate: impl Fn(char) -> bool) -> &'a str {
        let end = self.rest.find(|c| !predicate(c)).unwrap_or(self.rest.len());
        let (part, rest) = self.rest.split_at(end);
        self.rest = rest;
        part
    }

    fn prefix(&mut self, prefix: &str) -> bool {
        if let Some(rest) = self.rest.strip_prefix(prefix) {
            self.rest = rest;
            true
        } else {
            false
        }
    }

    fn quoted_value(&mut self, quote: char) -> Option<String> {
        let body = self.rest.strip_prefix(quote)?;
        let mut chars = body.char_indices().peekable();
        let mut fallback = None;
        let mut closing = None;
        while let Some((index, c)) = chars.next() {
            if c == '\\' && chars.peek().is_some_and(|(_, c)| *c == quote) {
                // Regex backtracking can use the last escaped quote as the terminator
                // if the greedy (\\quote|[^quote])* has no unescaped closing quote.
                fallback = chars.next().map(|(index, _)| index);
            } else if c == quote {
                closing = Some(index);
                break;
            }
        }
        let (value, tail) = body.split_at(closing.or(fallback)?);
        self.rest = tail.strip_prefix(quote)?;
        Some(decode(value, quote))
    }

    fn binding(&mut self) -> Result<Option<(String, Option<String>)>, ()> {
        self.take(whitespace);
        if let Some(tail) = self.rest.strip_prefix("export") {
            if tail.starts_with(horizontal) {
                self.rest = tail;
                self.take(horizontal);
            }
        }
        let key = if self.rest.starts_with('#') {
            None
        } else if let Some(body) = self.rest.strip_prefix('\'') {
            let (key, tail) = body.split_once('\'').ok_or(())?;
            if key.is_empty() {
                return Err(());
            }
            self.rest = tail;
            Some(key.to_owned())
        } else {
            let key = self.take(|c| c != '=' && c != '#' && !whitespace(c));
            if key.is_empty() {
                return Err(());
            }
            Some(key.to_owned())
        };
        self.take(horizontal);
        let value = if self.prefix("=") {
            self.take(horizontal);
            Some(match self.rest.chars().next() {
                Some(quote @ ('\'' | '"')) => self.quoted_value(quote).ok_or(())?,
                _ => unquoted(self.take(|c| !matches!(c, '\r' | '\n'))),
            })
        } else {
            None
        };
        self.take(horizontal);
        if self.prefix("#") {
            self.take(|c| !matches!(c, '\r' | '\n'));
        }
        self.take(horizontal);
        if !self.rest.is_empty() && !self.prefix("\n") {
            return Err(());
        }
        Ok(key.map(|key| (key, value)))
    }
}

fn decode(text: &str, quote: char) -> String {
    let mut result = String::new();
    let mut chars = text.chars().peekable();
    while let Some(c) = chars.next() {
        if c == '\\' {
            let decoded = match chars.peek() {
                Some('\\') => Some('\\'),
                Some('\'') => Some('\''),
                Some('"') if quote == '"' => Some('"'),
                Some('a') if quote == '"' => Some('\u{7}'),
                Some('b') if quote == '"' => Some('\u{8}'),
                Some('f') if quote == '"' => Some('\u{c}'),
                Some('n') if quote == '"' => Some('\n'),
                Some('r') if quote == '"' => Some('\r'),
                Some('t') if quote == '"' => Some('\t'),
                Some('v') if quote == '"' => Some('\u{b}'),
                _ => None,
            };
            if let Some(decoded) = decoded {
                chars.next();
                result.push(decoded);
                continue;
            }
        }
        result.push(c);
    }
    result
}

fn unquoted(text: &str) -> String {
    let mut previous_space = false;
    for (index, c) in text.char_indices() {
        if c == '#' && previous_space {
            return text
                .get(..index)
                .unwrap_or_default()
                .trim_end_matches(whitespace)
                .to_owned();
        }
        previous_space = whitespace(c);
    }
    text.trim_end_matches(whitespace).to_owned()
}

fn variable(text: &str) -> Option<(&str, &str, &str)> {
    let end = text.find([':', '}'])?;
    let (name, tail) = text.split_at(end);
    if let Some(rest) = tail.strip_prefix('}') {
        Some((name, "", rest))
    } else {
        let (default, rest) = tail.strip_prefix(":-")?.split_once('}')?;
        Some((name, default, rest))
    }
}

fn interpolate(
    text: &str,
    values: &IndexMap<String, Option<String>>,
    env: &dyn Fn(&str) -> Option<String>,
) -> String {
    let mut rest = text;
    let mut result = String::new();
    while let Some((literal, tail)) = rest.split_once("${") {
        result.push_str(literal);
        if let Some((name, default, tail)) = variable(tail) {
            let value = match values.get(name) {
                Some(value) => value.clone().unwrap_or_default(),
                None => env(name).unwrap_or_else(|| default.to_owned()),
            };
            result.push_str(&value);
            rest = tail;
        } else {
            result.push_str("${");
            rest = tail;
        }
    }
    result.push_str(rest);
    result
}

/// `dotenv_values(path, interpolate=True)` with override=True: earlier bindings
/// shadow the injected environment, including bare (`None`) and empty values.
/// Like Python's file reader, normalize CRLF/CR to LF; a BOM stays in the key.
pub fn parse(text: &str, env: &dyn Fn(&str) -> Option<String>) -> IndexMap<String, Option<String>> {
    let text = universal_newlines(text);
    let mut reader = Reader { rest: &text };
    let mut values = IndexMap::new();
    while !reader.rest.is_empty() {
        match reader.binding() {
            Ok(Some((key, value))) => {
                let resolved = value.map(|value| interpolate(&value, &values, env));
                values.insert(key, resolved);
            }
            Ok(None) => {}
            Err(()) => {
                // parse_binding recovers at its CURRENT position, even after a
                // multiline quoted value, rather than at the start of the statement.
                reader.take(|c| c != '\n');
                reader.prefix("\n");
            }
        }
    }
    values
}

/// Read UTF-8 without changing process environment. Missing files and unsupported
/// file types are empty, matching Python's `_is_file_or_fifo` stream selection.
pub async fn read(
    path: &Path,
    env: &dyn Fn(&str) -> Option<String>,
) -> Result<IndexMap<String, Option<String>>, DotenvError> {
    let metadata = match tokio::fs::metadata(path).await {
        Ok(metadata) => metadata,
        Err(_) => return Ok(IndexMap::new()),
    };
    let supported = metadata.is_file();
    #[cfg(unix)]
    let supported = {
        use std::os::unix::fs::FileTypeExt;
        supported || metadata.file_type().is_fifo()
    };
    if !supported {
        return Ok(IndexMap::new());
    }
    let text = tokio::fs::read_to_string(path).await?;
    Ok(parse(&text, env))
}
