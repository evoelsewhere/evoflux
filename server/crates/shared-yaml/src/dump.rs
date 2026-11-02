//! Port of PyYAML's `yaml.safe_dump` (`representer.py` `SafeRepresenter`,
//! `serializer.py`, `emitter.py`) with `default_flow_style=False`, width 80,
//! indent 2 and `\n` line breaks, byte for byte.
//!
//! Only the paths `safe_dump` can reach are ported: block collections, empty
//! collections as `[]` / `{}`, and plain, single-quoted or double-quoted
//! scalars. `Value` has no shared identity, so anchors are never written.

use crate::load::{resolve_plain, TAG_BOOL, TAG_FLOAT, TAG_INT, TAG_NULL, TAG_STR, TAG_TIMESTAMP};
use crate::value::{python_float_repr, Mapping, Value};

/// `safe_dump` keyword arguments. `Default` is PyYAML's default except
/// `sort_keys`, which every EvoFlux caller sets to `False`.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct DumpOpts {
    pub sort_keys: bool,
    pub allow_unicode: bool,
}

/// `yaml.safe_dump(value, sort_keys=..., allow_unicode=...)`.
pub fn dump(value: &Value, opts: DumpOpts) -> String {
    let mut emitter = Emitter {
        opts,
        out: String::new(),
        column: 0,
        whitespace: true,
        indention: true,
        indent: None,
        indents: Vec::new(),
        open_ended: false,
        flow_level: 0,
    };
    emitter.node(value, Context::ROOT);
    // `expect_document_end` (implicit end) and `expect_document_start` at
    // the stream end.
    emitter.write_indent();
    if emitter.open_ended {
        emitter.write_indicator("...", true, false, false);
        emitter.write_indent();
    }
    emitter.out
}

const BEST_INDENT: usize = 2;
const BEST_WIDTH: usize = 80;

#[derive(Clone, Copy)]
struct Context {
    root: bool,
    mapping: bool,
    simple_key: bool,
}

impl Context {
    const ROOT: Context = Context {
        root: true,
        mapping: false,
        simple_key: false,
    };
    const SEQUENCE: Context = Context {
        root: false,
        mapping: false,
        simple_key: false,
    };
    const MAPPING: Context = Context {
        root: false,
        mapping: true,
        simple_key: false,
    };
    const KEY: Context = Context {
        root: false,
        mapping: true,
        simple_key: true,
    };
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Style {
    Plain,
    Single,
    Double,
}

/// A represented scalar: its text, tag and `implicit` pair (serializer.py).
struct Scalar {
    text: String,
    tag: &'static str,
    implicit: (bool, bool),
}

fn represent(value: &Value) -> Option<Scalar> {
    let (text, tag) = match value {
        Value::Null => ("null".to_owned(), TAG_NULL),
        Value::Bool(b) => ((if *b { "true" } else { "false" }).to_owned(), TAG_BOOL),
        Value::Int(i) => (i.to_string(), TAG_INT),
        Value::Float(f) => (represent_float(*f), TAG_FLOAT),
        Value::Str(s) => (s.clone(), TAG_STR),
        Value::Timestamp(t) => (t.isoformat(' '), TAG_TIMESTAMP),
        Value::Seq(_) | Value::Map(_) => return None,
    };
    let implicit = (resolve_plain(&text) == tag, tag == TAG_STR);
    Some(Scalar {
        text,
        tag,
        implicit,
    })
}

/// `SafeRepresenter.represent_float`.
fn represent_float(f: f64) -> String {
    if f.is_nan() {
        return ".nan".to_owned();
    }
    if f.is_infinite() {
        return if f > 0.0 { ".inf" } else { "-.inf" }.to_owned();
    }
    let value = python_float_repr(f).to_lowercase();
    if !value.contains('.') && value.contains('e') {
        value.replacen('e', ".0e", 1)
    } else {
        value
    }
}

/// `Emitter.prepare_tag` for the default `!!` handle.
fn prepare_tag(tag: &str) -> String {
    match tag.strip_prefix("tag:yaml.org,2002:") {
        Some(suffix) => format!("!!{suffix}"),
        None => format!("!<{tag}>"),
    }
}

/// `ScalarAnalysis` fields the emitter reads.
struct Analysis {
    empty: bool,
    multiline: bool,
    allow_flow_plain: bool,
    allow_block_plain: bool,
    allow_single_quoted: bool,
}

fn is_break(ch: char) -> bool {
    matches!(ch, '\n' | '\u{85}' | '\u{2028}' | '\u{2029}')
}

fn is_space_or_break(ch: char) -> bool {
    matches!(
        ch,
        '\0' | ' ' | '\t' | '\r' | '\n' | '\u{85}' | '\u{2028}' | '\u{2029}'
    )
}

/// `Emitter.analyze_scalar`.
fn analyze(text: &[char], allow_unicode: bool) -> Analysis {
    if text.is_empty() {
        return Analysis {
            empty: true,
            multiline: false,
            allow_flow_plain: false,
            allow_block_plain: true,
            allow_single_quoted: true,
        };
    }
    let mut block_indicators = false;
    let mut flow_indicators = false;
    let mut line_breaks = false;
    let mut special_characters = false;
    let mut leading_space = false;
    let mut leading_break = false;
    let mut trailing_space = false;
    let mut trailing_break = false;
    let mut break_space = false;
    let mut space_break = false;

    if text.starts_with(&['-', '-', '-']) || text.starts_with(&['.', '.', '.']) {
        block_indicators = true;
        flow_indicators = true;
    }
    let mut preceded_by_whitespace = true;
    let mut followed_by_whitespace =
        text.len() == 1 || text.get(1).is_some_and(|c| is_space_or_break(*c));
    let mut previous_space = false;
    let mut previous_break = false;

    for (index, &ch) in text.iter().enumerate() {
        if index == 0 {
            if "#,[]{}&*!|>'\"%@`".contains(ch) {
                flow_indicators = true;
                block_indicators = true;
            }
            if ch == '?' || ch == ':' {
                flow_indicators = true;
                if followed_by_whitespace {
                    block_indicators = true;
                }
            }
            if ch == '-' && followed_by_whitespace {
                flow_indicators = true;
                block_indicators = true;
            }
        } else {
            if ",?[]{}".contains(ch) {
                flow_indicators = true;
            }
            if ch == ':' {
                flow_indicators = true;
                if followed_by_whitespace {
                    block_indicators = true;
                }
            }
            if ch == '#' && preceded_by_whitespace {
                flow_indicators = true;
                block_indicators = true;
            }
        }

        if is_break(ch) {
            line_breaks = true;
        }
        if !(ch == '\n' || (' '..='~').contains(&ch)) {
            let unicode = (ch == '\u{85}'
                || ('\u{A0}'..='\u{D7FF}').contains(&ch)
                || ('\u{E000}'..='\u{FFFD}').contains(&ch)
                || ('\u{10000}'..'\u{10FFFF}').contains(&ch))
                && ch != '\u{FEFF}';
            if !unicode || !allow_unicode {
                special_characters = true;
            }
        }

        if ch == ' ' {
            if index == 0 {
                leading_space = true;
            }
            if index == text.len() - 1 {
                trailing_space = true;
            }
            if previous_break {
                break_space = true;
            }
            previous_space = true;
            previous_break = false;
        } else if is_break(ch) {
            if index == 0 {
                leading_break = true;
            }
            if index == text.len() - 1 {
                trailing_break = true;
            }
            if previous_space {
                space_break = true;
            }
            previous_space = false;
            previous_break = true;
        } else {
            previous_space = false;
            previous_break = false;
        }

        preceded_by_whitespace = is_space_or_break(ch);
        followed_by_whitespace =
            index + 2 >= text.len() || text.get(index + 2).is_some_and(|c| is_space_or_break(*c));
    }

    let mut allow_flow_plain = true;
    let mut allow_block_plain = true;
    let mut allow_single_quoted = true;
    if leading_space || leading_break || trailing_space || trailing_break {
        allow_flow_plain = false;
        allow_block_plain = false;
    }
    if break_space {
        allow_flow_plain = false;
        allow_block_plain = false;
        allow_single_quoted = false;
    }
    if space_break || special_characters {
        allow_flow_plain = false;
        allow_block_plain = false;
        allow_single_quoted = false;
    }
    if line_breaks {
        allow_flow_plain = false;
        allow_block_plain = false;
    }
    if flow_indicators {
        allow_flow_plain = false;
    }
    if block_indicators {
        allow_block_plain = false;
    }
    Analysis {
        empty: false,
        multiline: line_breaks,
        allow_flow_plain,
        allow_block_plain,
        allow_single_quoted,
    }
}

struct Emitter {
    opts: DumpOpts,
    out: String,
    column: usize,
    whitespace: bool,
    indention: bool,
    indent: Option<usize>,
    indents: Vec<Option<usize>>,
    open_ended: bool,
    flow_level: usize,
}

impl Emitter {
    fn write(&mut self, data: &str) {
        self.column += data.chars().count();
        self.out.push_str(data);
    }

    fn write_chars(&mut self, data: &[char]) {
        self.column += data.len();
        self.out.extend(data);
    }

    fn increase_indent(&mut self, flow: bool, indentless: bool) {
        self.indents.push(self.indent);
        self.indent = match self.indent {
            None if flow => Some(BEST_INDENT),
            None => Some(0),
            Some(indent) if !indentless => Some(indent + BEST_INDENT),
            same => same,
        };
    }

    fn pop_indent(&mut self) {
        self.indent = self.indents.pop().flatten();
    }

    fn write_indicator(
        &mut self,
        indicator: &str,
        need_whitespace: bool,
        whitespace: bool,
        indention: bool,
    ) {
        if self.whitespace || !need_whitespace {
            self.write(indicator);
        } else {
            self.write(&format!(" {indicator}"));
        }
        self.whitespace = whitespace;
        self.indention = self.indention && indention;
        self.open_ended = false;
    }

    fn write_indent(&mut self) {
        let indent = self.indent.unwrap_or(0);
        if !self.indention || self.column > indent || (self.column == indent && !self.whitespace) {
            self.write_line_break(None);
        }
        if self.column < indent {
            self.whitespace = true;
            let pad = " ".repeat(indent - self.column);
            self.column = indent;
            self.out.push_str(&pad);
        }
    }

    fn write_line_break(&mut self, data: Option<char>) {
        self.whitespace = true;
        self.indention = true;
        self.column = 0;
        self.out.push(data.unwrap_or('\n'));
    }

    fn node(&mut self, value: &Value, ctx: Context) {
        match value {
            Value::Seq(items) => {
                if self.flow_level > 0 || items.is_empty() {
                    self.empty_flow("[", "]");
                } else {
                    let indentless = ctx.mapping && !self.indention;
                    self.increase_indent(false, indentless);
                    for item in items {
                        self.write_indent();
                        self.write_indicator("-", true, false, true);
                        self.node(item, Context::SEQUENCE);
                    }
                    self.pop_indent();
                }
            }
            Value::Map(map) => {
                if self.flow_level > 0 || map.is_empty() {
                    self.empty_flow("{", "}");
                } else {
                    self.increase_indent(false, false);
                    for (key, value) in self.ordered(map) {
                        self.write_indent();
                        if self.is_simple_key(key) {
                            self.node(key, Context::KEY);
                            self.write_indicator(":", false, false, false);
                        } else {
                            self.write_indicator("?", true, false, true);
                            self.node(key, Context::MAPPING);
                            self.write_indent();
                            self.write_indicator(":", true, false, true);
                        }
                        self.node(value, Context::MAPPING);
                    }
                    self.pop_indent();
                }
            }
            scalar => {
                if let Some(scalar) = represent(scalar) {
                    self.scalar(&scalar, ctx);
                }
            }
        }
    }

    /// Only empty collections reach flow style with `default_flow_style=False`.
    fn empty_flow(&mut self, open: &str, close: &str) {
        self.write_indicator(open, true, true, false);
        self.flow_level += 1;
        self.increase_indent(true, false);
        self.pop_indent();
        self.flow_level -= 1;
        self.write_indicator(close, false, false, false);
    }

    /// `SafeRepresenter.represent_mapping`: `sorted(mapping.items())` when
    /// asked, left as is when Python cannot order the keys (`TypeError`).
    fn ordered<'a>(&self, map: &'a Mapping) -> Vec<&'a (Value, Value)> {
        let mut entries: Vec<_> = map.iter().collect();
        if self.opts.sort_keys && entries.len() > 1 {
            if let Some(keys) = sort_keys(&entries) {
                entries = keys;
            }
        }
        entries
    }

    /// `Emitter.check_simple_key` for a represented node: the prepared tag
    /// counts towards the 128-character limit even when it is not written.
    fn is_simple_key(&self, key: &Value) -> bool {
        match key {
            Value::Seq(items) => items.is_empty(),
            Value::Map(map) => map.is_empty(),
            scalar => represent(scalar).is_some_and(|s| {
                let chars: Vec<char> = s.text.chars().collect();
                let analysis = analyze(&chars, self.opts.allow_unicode);
                prepare_tag(s.tag).chars().count() + chars.len() < 128
                    && !analysis.empty
                    && !analysis.multiline
            }),
        }
    }

    fn scalar(&mut self, scalar: &Scalar, ctx: Context) {
        let chars: Vec<char> = scalar.text.chars().collect();
        let analysis = analyze(&chars, self.opts.allow_unicode);
        // `expect_scalar`
        self.increase_indent(true, false);
        let style = self.choose_style(scalar, &analysis, ctx);
        // `process_tag`
        let implicit = match style {
            Style::Plain => scalar.implicit.0,
            Style::Single | Style::Double => scalar.implicit.1,
        };
        if !implicit {
            let tag = prepare_tag(scalar.tag);
            self.write_indicator(&tag, true, false, false);
        }
        // `process_scalar`
        let split = !ctx.simple_key;
        match style {
            Style::Double => self.write_double_quoted(&chars, split),
            Style::Single => self.write_single_quoted(&chars, split),
            Style::Plain => self.write_plain(&chars, split, ctx.root),
        }
        self.pop_indent();
    }

    /// `Emitter.choose_scalar_style` for an event with no requested style.
    fn choose_style(&self, scalar: &Scalar, analysis: &Analysis, ctx: Context) -> Style {
        if scalar.implicit.0
            && !(ctx.simple_key && (analysis.empty || analysis.multiline))
            && ((self.flow_level > 0 && analysis.allow_flow_plain)
                || (self.flow_level == 0 && analysis.allow_block_plain))
        {
            return Style::Plain;
        }
        if analysis.allow_single_quoted && !(ctx.simple_key && analysis.multiline) {
            return Style::Single;
        }
        Style::Double
    }

    /// `Emitter.write_plain`.
    fn write_plain(&mut self, text: &[char], split: bool, root: bool) {
        if root {
            self.open_ended = true;
        }
        if text.is_empty() {
            return;
        }
        if !self.whitespace {
            self.write(" ");
        }
        self.whitespace = false;
        self.indention = false;
        let mut spaces = false;
        let mut breaks = false;
        let mut start = 0;
        let mut end = 0;
        while end <= text.len() {
            let ch = text.get(end).copied();
            if spaces {
                if ch != Some(' ') {
                    if start + 1 == end && self.column > BEST_WIDTH && split {
                        self.write_indent();
                        self.whitespace = false;
                        self.indention = false;
                    } else {
                        self.write_chars(text.get(start..end).unwrap_or_default());
                    }
                    start = end;
                }
            } else if breaks {
                if !ch.is_some_and(is_break) {
                    if text.get(start) == Some(&'\n') {
                        self.write_line_break(None);
                    }
                    for &br in text.get(start..end).unwrap_or_default() {
                        self.write_line_break(if br == '\n' { None } else { Some(br) });
                    }
                    self.write_indent();
                    self.whitespace = false;
                    self.indention = false;
                    start = end;
                }
            } else if ch.is_none_or(|c| c == ' ' || is_break(c)) {
                self.write_chars(text.get(start..end).unwrap_or_default());
                start = end;
            }
            if let Some(c) = ch {
                spaces = c == ' ';
                breaks = is_break(c);
            }
            end += 1;
        }
    }

    /// `Emitter.write_single_quoted`.
    fn write_single_quoted(&mut self, text: &[char], split: bool) {
        self.write_indicator("'", true, false, false);
        let mut spaces = false;
        let mut breaks = false;
        let mut start = 0;
        let mut end = 0;
        while end <= text.len() {
            let ch = text.get(end).copied();
            if spaces {
                if ch != Some(' ') {
                    if start + 1 == end
                        && self.column > BEST_WIDTH
                        && split
                        && start != 0
                        && end != text.len()
                    {
                        self.write_indent();
                    } else {
                        self.write_chars(text.get(start..end).unwrap_or_default());
                    }
                    start = end;
                }
            } else if breaks {
                if !ch.is_some_and(is_break) {
                    if text.get(start) == Some(&'\n') {
                        self.write_line_break(None);
                    }
                    for &br in text.get(start..end).unwrap_or_default() {
                        self.write_line_break(if br == '\n' { None } else { Some(br) });
                    }
                    self.write_indent();
                    start = end;
                }
            } else if ch.is_none_or(|c| c == ' ' || is_break(c) || c == '\'') && start < end {
                self.write_chars(text.get(start..end).unwrap_or_default());
                start = end;
            }
            if ch == Some('\'') {
                self.write("''");
                start = end + 1;
            }
            if let Some(c) = ch {
                spaces = c == ' ';
                breaks = is_break(c);
            }
            end += 1;
        }
        self.write_indicator("'", false, false, false);
    }

    /// `Emitter.write_double_quoted`.
    fn write_double_quoted(&mut self, text: &[char], split: bool) {
        self.write_indicator("\"", true, false, false);
        let allow_unicode = self.opts.allow_unicode;
        let mut start = 0;
        let mut end = 0;
        while end <= text.len() {
            let ch = text.get(end).copied();
            let escape = ch.is_none_or(|c| {
                "\"\\\u{85}\u{2028}\u{2029}\u{FEFF}".contains(c)
                    || !((' '..='~').contains(&c)
                        || (allow_unicode
                            && (('\u{A0}'..='\u{D7FF}').contains(&c)
                                || ('\u{E000}'..='\u{FFFD}').contains(&c))))
            });
            if escape {
                if start < end {
                    self.write_chars(text.get(start..end).unwrap_or_default());
                    start = end;
                }
                if let Some(c) = ch {
                    self.write(&escape_char(c));
                    start = end + 1;
                }
            }
            if 0 < end
                && end + 1 < text.len()
                && (ch == Some(' ') || start >= end)
                // `end - start` is -1 right after an escape.
                && (self.column + end + 1).saturating_sub(start) > BEST_WIDTH + 1
                && split
            {
                let mut data: String = text.get(start..end).unwrap_or_default().iter().collect();
                data.push('\\');
                if start < end {
                    start = end;
                }
                self.write(&data);
                self.write_indent();
                self.whitespace = false;
                self.indention = false;
                if text.get(start) == Some(&' ') {
                    self.write("\\");
                }
            }
            end += 1;
        }
        self.write_indicator("\"", false, false, false);
    }
}

/// `Emitter.ESCAPE_REPLACEMENTS`, then `\xXX`, `\uXXXX` or `\UXXXXXXXX`.
fn escape_char(c: char) -> String {
    let short = match c {
        '\0' => Some('0'),
        '\u{07}' => Some('a'),
        '\u{08}' => Some('b'),
        '\t' => Some('t'),
        '\n' => Some('n'),
        '\u{0B}' => Some('v'),
        '\u{0C}' => Some('f'),
        '\r' => Some('r'),
        '\u{1B}' => Some('e'),
        '"' => Some('"'),
        '\\' => Some('\\'),
        '\u{85}' => Some('N'),
        '\u{A0}' => Some('_'),
        '\u{2028}' => Some('L'),
        '\u{2029}' => Some('P'),
        _ => None,
    };
    let code = u32::from(c);
    match short {
        Some(s) => format!("\\{s}"),
        None if code <= 0xFF => format!("\\x{code:02X}"),
        None if code <= 0xFFFF => format!("\\u{code:04X}"),
        None => format!("\\U{code:08X}"),
    }
}

/// Python's ordering of `(key, value)` tuples, or `None` where `sorted`
/// raises `TypeError` (keys of types Python does not compare).
fn sort_keys<'a>(entries: &[&'a (Value, Value)]) -> Option<Vec<&'a (Value, Value)>> {
    #[derive(PartialEq)]
    enum Kind {
        Str,
        Number,
        Date,
        Naive,
        Aware,
    }
    let kind = |v: &Value| match v {
        Value::Str(_) => Some(Kind::Str),
        Value::Bool(_) | Value::Int(_) | Value::Float(_) => Some(Kind::Number),
        Value::Timestamp(t) => Some(match t.time {
            None => Kind::Date,
            Some(time) if time.offset_minutes.is_none() => Kind::Naive,
            Some(_) => Kind::Aware,
        }),
        _ => None,
    };
    let first = kind(&entries.first()?.0)?;
    if entries
        .iter()
        .any(|(k, _)| kind(k).as_ref() != Some(&first))
    {
        return None;
    }
    let number = |v: &Value| match v {
        Value::Bool(b) => f64::from(u8::from(*b)),
        #[allow(clippy::cast_precision_loss)]
        Value::Int(i) => *i as f64,
        Value::Float(f) => *f,
        _ => 0.0,
    };
    let mut sorted = entries.to_vec();
    match first {
        Kind::Str => sorted.sort_by(|a, b| a.0.as_str().cmp(&b.0.as_str())),
        Kind::Number => {
            if entries
                .iter()
                .any(|(k, _)| matches!(k, Value::Float(f) if f.is_nan()))
            {
                // Python's sort with NaN keeps an order no rule describes.
                return None;
            }
            sorted.sort_by(|a, b| match (&a.0, &b.0) {
                (Value::Int(x), Value::Int(y)) => x.cmp(y),
                (x, y) => number(x).total_cmp(&number(y)),
            });
        }
        Kind::Date | Kind::Naive | Kind::Aware => sorted.sort_by(|a, b| {
            let stamp = |v: &Value| match v {
                Value::Timestamp(t) => Some(*t),
                _ => None,
            };
            timestamp_order(stamp(&a.0), stamp(&b.0))
        }),
    }
    Some(sorted)
}

fn timestamp_order(
    a: Option<crate::value::Timestamp>,
    b: Option<crate::value::Timestamp>,
) -> std::cmp::Ordering {
    let key = |t: Option<crate::value::Timestamp>| {
        t.map(|t| {
            let time = t.time.unwrap_or(crate::value::Time {
                hour: 0,
                minute: 0,
                second: 0,
                microsecond: 0,
                offset_minutes: None,
            });
            let minutes = i64::from(time.hour) * 60 + i64::from(time.minute)
                - i64::from(time.offset_minutes.unwrap_or(0));
            (
                t.year,
                t.month,
                t.day,
                minutes,
                time.second,
                time.microsecond,
            )
        })
    };
    key(a).cmp(&key(b))
}

#[cfg(test)]
#[allow(clippy::unwrap_used)]
mod tests {
    use super::*;

    #[test]
    fn floats_get_a_point_before_the_exponent() {
        assert_eq!(represent_float(1e16), "1.0e+16");
        assert_eq!(represent_float(1e-5), "1.0e-05");
        assert_eq!(represent_float(1.5e16), "1.5e+16");
        assert_eq!(represent_float(60.0), "60.0");
        assert_eq!(represent_float(f64::NEG_INFINITY), "-.inf");
    }

    #[test]
    fn escapes_use_the_short_forms_first() {
        assert_eq!(escape_char('\u{e9}'), "\\xE9");
        assert_eq!(escape_char('\u{2014}'), "\\u2014");
        assert_eq!(escape_char('\u{1F600}'), "\\U0001F600");
        assert_eq!(escape_char('\u{A0}'), "\\_");
    }
}
