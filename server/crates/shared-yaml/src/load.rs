//! Port of PyYAML's `yaml.safe_load` (`composer.py`, `resolver.py`,
//! `constructor.py` `SafeConstructor`), YAML 1.1 rules.
//!
//! The text is scanned and parsed by `yaml-rust2`; composing nodes, resolving
//! implicit tags with PyYAML's YAML 1.1 regular expressions and constructing
//! values follow PyYAML. Error messages are not PyYAML's.

use std::collections::HashMap;
use std::rc::Rc;
use std::sync::LazyLock;

use regex::Regex;
use yaml_rust2::parser::{Event, MarkedEventReceiver, Parser, Tag};
use yaml_rust2::scanner::{Marker, Scanner, TScalarStyle, TokenType};

use crate::value::{Mapping, Time, Timestamp, Value};
use crate::YamlError;

pub(crate) const TAG_NULL: &str = "tag:yaml.org,2002:null";
pub(crate) const TAG_BOOL: &str = "tag:yaml.org,2002:bool";
pub(crate) const TAG_INT: &str = "tag:yaml.org,2002:int";
pub(crate) const TAG_FLOAT: &str = "tag:yaml.org,2002:float";
pub(crate) const TAG_STR: &str = "tag:yaml.org,2002:str";
pub(crate) const TAG_TIMESTAMP: &str = "tag:yaml.org,2002:timestamp";
const TAG_MERGE: &str = "tag:yaml.org,2002:merge";
const TAG_VALUE: &str = "tag:yaml.org,2002:value";
const TAG_SEQ: &str = "tag:yaml.org,2002:seq";
const TAG_MAP: &str = "tag:yaml.org,2002:map";

/// Nesting deeper than this is refused (PyYAML hits CPython's recursion limit
/// near 300 levels; the native stack of a debug build is the limit here).
pub const MAX_DEPTH: usize = 256;
/// Aliases may expand a document to at most this many values.
pub const MAX_NODES: usize = 1_000_000;

type Pattern = LazyLock<Result<Regex, regex::Error>>;

// `resolver.py`, `Resolver.add_implicit_resolver` calls, in registration order.
static BOOL: Pattern = LazyLock::new(|| {
    Regex::new(r"^(?:yes|Yes|YES|no|No|NO|true|True|TRUE|false|False|FALSE|on|On|ON|off|Off|OFF)$")
});
static FLOAT: Pattern = LazyLock::new(|| {
    Regex::new(
        r"^(?:[-+]?(?:[0-9][0-9_]*)\.[0-9_]*(?:[eE][-+][0-9]+)?|\.[0-9][0-9_]*(?:[eE][-+][0-9]+)?|[-+]?[0-9][0-9_]*(?::[0-5]?[0-9])+\.[0-9_]*|[-+]?\.(?:inf|Inf|INF)|\.(?:nan|NaN|NAN))$",
    )
});
static INT: Pattern = LazyLock::new(|| {
    Regex::new(
        r"^(?:[-+]?0b[0-1_]+|[-+]?0[0-7_]+|[-+]?(?:0|[1-9][0-9_]*)|[-+]?0x[0-9a-fA-F_]+|[-+]?[1-9][0-9_]*(?::[0-5]?[0-9])+)$",
    )
});
static MERGE: Pattern = LazyLock::new(|| Regex::new(r"^(?:<<)$"));
static NULL: Pattern = LazyLock::new(|| Regex::new(r"^(?:~|null|Null|NULL|)$"));
static TIMESTAMP: Pattern = LazyLock::new(|| {
    Regex::new(
        r"^(?:[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]|[0-9][0-9][0-9][0-9]-[0-9][0-9]?-[0-9][0-9]?(?:[Tt]|[ \t]+)[0-9][0-9]?:[0-9][0-9]:[0-9][0-9](?:\.[0-9]*)?(?:[ \t]*(?:Z|[-+][0-9][0-9]?(?::[0-9][0-9])?))?)$",
    )
});
static VALUE: Pattern = LazyLock::new(|| Regex::new(r"^(?:=)$"));
// `SafeConstructor.timestamp_regexp`.
static TIMESTAMP_PARTS: Pattern = LazyLock::new(|| {
    Regex::new(
        r"^(?P<year>[0-9][0-9][0-9][0-9])-(?P<month>[0-9][0-9]?)-(?P<day>[0-9][0-9]?)(?:(?:[Tt]|[ \t]+)(?P<hour>[0-9][0-9]?):(?P<minute>[0-9][0-9]):(?P<second>[0-9][0-9])(?:\.(?P<fraction>[0-9]*))?(?:[ \t]*(?P<tz>Z|(?P<tz_sign>[-+])(?P<tz_hour>[0-9][0-9]?)(?::(?P<tz_minute>[0-9][0-9]))?))?)?$",
    )
});

fn matches(pattern: &Pattern, text: &str) -> bool {
    pattern.as_ref().is_ok_and(|re| re.is_match(text))
}

/// The tag PyYAML's resolver gives a plain scalar.
pub(crate) fn resolve_plain(value: &str) -> &'static str {
    let first = value.chars().next();
    let table: [(&Pattern, &str, &str); 7] = [
        (&BOOL, TAG_BOOL, "yYnNtTfFoO"),
        (&FLOAT, TAG_FLOAT, "-+0123456789."),
        (&INT, TAG_INT, "-+0123456789"),
        (&MERGE, TAG_MERGE, "<"),
        (&NULL, TAG_NULL, "~nN"),
        (&TIMESTAMP, TAG_TIMESTAMP, "0123456789"),
        (&VALUE, TAG_VALUE, "="),
    ];
    for (pattern, tag, firsts) in table {
        let keyed = match first {
            None => tag == TAG_NULL,
            Some(c) => firsts.contains(c),
        };
        if keyed && matches(pattern, value) {
            return tag;
        }
    }
    TAG_STR
}

type Pair = (Rc<Node>, Rc<Node>);

#[derive(Debug)]
enum Node {
    Scalar {
        tag: String,
        value: String,
        mark: Marker,
    },
    Seq {
        tag: String,
        items: Vec<Rc<Node>>,
        mark: Marker,
    },
    Map {
        tag: String,
        pairs: Vec<Pair>,
        mark: Marker,
    },
}

impl Node {
    fn tag(&self) -> &str {
        match self {
            Node::Scalar { tag, .. } | Node::Seq { tag, .. } | Node::Map { tag, .. } => tag,
        }
    }

    fn mark(&self) -> Marker {
        match self {
            Node::Scalar { mark, .. } | Node::Seq { mark, .. } | Node::Map { mark, .. } => *mark,
        }
    }

    fn kind(&self) -> &'static str {
        match self {
            Node::Scalar { .. } => "scalar",
            Node::Seq { .. } => "sequence",
            Node::Map { .. } => "mapping",
        }
    }
}

enum Frame {
    Seq {
        tag: String,
        anchor: usize,
        items: Vec<Rc<Node>>,
        mark: Marker,
    },
    Map {
        tag: String,
        anchor: usize,
        pairs: Vec<Pair>,
        key: Option<Rc<Node>>,
        mark: Marker,
    },
}

#[derive(Default)]
struct Composer {
    stack: Vec<Frame>,
    anchors: HashMap<usize, Rc<Node>>,
    documents: Vec<Rc<Node>>,
    error: Option<YamlError>,
}

fn full_tag(tag: &Option<Tag>) -> Option<String> {
    tag.as_ref()
        .map(|t| format!("{}{}", t.handle, t.suffix))
        // `!` alone is the non-specific tag: resolve as if untagged.
        .filter(|t| t != "!")
}

impl Composer {
    fn fail(&mut self, error: YamlError) {
        if self.error.is_none() {
            self.error = Some(error);
        }
    }

    fn add(&mut self, node: Rc<Node>, anchor: usize) {
        if anchor > 0 {
            self.anchors.insert(anchor, node.clone());
        }
        match self.stack.last_mut() {
            None => self.documents.push(node),
            Some(Frame::Seq { items, .. }) => items.push(node),
            Some(Frame::Map { pairs, key, .. }) => match key.take() {
                None => *key = Some(node),
                Some(k) => pairs.push((k, node)),
            },
        }
    }
}

impl MarkedEventReceiver for Composer {
    fn on_event(&mut self, event: Event, mark: Marker) {
        if self.error.is_some() {
            return;
        }
        match event {
            Event::Scalar(value, style, anchor, tag) => {
                // PyYAML: a plain scalar, or any scalar tagged `!`, is
                // resolved implicitly; any other untagged scalar is a str.
                let explicit_bang = tag
                    .as_ref()
                    .is_some_and(|t| format!("{}{}", t.handle, t.suffix) == "!");
                let tag = match full_tag(&tag) {
                    Some(tag) => tag,
                    None if style == TScalarStyle::Plain || explicit_bang => {
                        resolve_plain(&value).to_owned()
                    }
                    None => TAG_STR.to_owned(),
                };
                self.add(Rc::new(Node::Scalar { tag, value, mark }), anchor);
            }
            Event::SequenceStart(anchor, tag) => {
                if self.stack.len() >= MAX_DEPTH {
                    self.fail(YamlError::TooDeep(MAX_DEPTH));
                    return;
                }
                self.stack.push(Frame::Seq {
                    tag: full_tag(&tag).unwrap_or_else(|| TAG_SEQ.to_owned()),
                    anchor,
                    items: Vec::new(),
                    mark,
                });
            }
            Event::MappingStart(anchor, tag) => {
                if self.stack.len() >= MAX_DEPTH {
                    self.fail(YamlError::TooDeep(MAX_DEPTH));
                    return;
                }
                self.stack.push(Frame::Map {
                    tag: full_tag(&tag).unwrap_or_else(|| TAG_MAP.to_owned()),
                    anchor,
                    pairs: Vec::new(),
                    key: None,
                    mark,
                });
            }
            Event::SequenceEnd | Event::MappingEnd => match self.stack.pop() {
                Some(Frame::Seq {
                    tag,
                    anchor,
                    items,
                    mark,
                }) => self.add(Rc::new(Node::Seq { tag, items, mark }), anchor),
                Some(Frame::Map {
                    tag,
                    anchor,
                    pairs,
                    mark,
                    ..
                }) => self.add(Rc::new(Node::Map { tag, pairs, mark }), anchor),
                None => self.fail(YamlError::Syntax("unbalanced collection end".to_owned())),
            },
            Event::Alias(id) => match self.anchors.get(&id).cloned() {
                Some(node) => self.add(node, 0),
                None => self.fail(YamlError::Syntax(format!(
                    "found undefined alias at line {} column {}",
                    mark.line(),
                    mark.col() + 1
                ))),
            },
            Event::DocumentStart => self.anchors.clear(),
            Event::Nothing | Event::StreamStart | Event::StreamEnd | Event::DocumentEnd => {}
        }
    }
}

/// `yaml.safe_load(text)`: `Value::Null` for an empty stream; an error for a
/// stream of more than one document.
pub fn load(text: &str) -> Result<Value, YamlError> {
    // YAML 1.1 (PyYAML) reads these as line breaks, YAML 1.2 (`yaml-rust2`)
    // as content: refuse rather than load a different value.
    if let Some(ch) = text
        .chars()
        .find(|c| matches!(c, '\u{85}' | '\u{2028}' | '\u{2029}'))
    {
        return Err(YamlError::Syntax(format!(
            "unsupported line break character U+{:04X}",
            u32::from(ch)
        )));
    }
    check_tabs(text)?;
    let mut composer = Composer::default();
    let mut parser = Parser::new_from_str(text);
    // Pull events one by one: `Parser::load` recurses once per nesting level.
    loop {
        let (event, mark) = parser
            .next_token()
            .map_err(|e| YamlError::Syntax(e.to_string()))?;
        if event == Event::StreamEnd {
            break;
        }
        composer.on_event(event, mark);
        if let Some(error) = composer.error.take() {
            return Err(error);
        }
        if composer.documents.len() > 1 {
            return Err(YamlError::MultipleDocuments);
        }
    }
    let mut documents = composer.documents.into_iter();
    let Some(root) = documents.next() else {
        return Ok(Value::Null);
    };
    if documents.next().is_some() {
        return Err(YamlError::MultipleDocuments);
    }
    let mut budget = MAX_NODES;
    construct(&root, &mut budget, 0)
}

/// PyYAML's scanner skips only spaces between tokens, so a tab is accepted
/// only inside a quoted scalar, a block scalar body or a comment;
/// `yaml-rust2` also takes tabs as separation. Each tab is placed in the span
/// of the token it follows.
fn check_tabs(text: &str) -> Result<(), YamlError> {
    if !text.contains('\t') {
        return Ok(());
    }
    let chars: Vec<char> = text.chars().collect();
    let mut starts: Vec<(usize, bool)> = Scanner::new(chars.iter().copied())
        .map(|token| {
            let quoted = matches!(
                token.1,
                TokenType::Scalar(
                    TScalarStyle::SingleQuoted
                        | TScalarStyle::DoubleQuoted
                        | TScalarStyle::Literal
                        | TScalarStyle::Folded,
                    _
                )
            );
            (token.0.index(), quoted)
        })
        .collect();
    starts.sort_by_key(|&(index, quoted)| (index, quoted));
    let mut line_start = 0;
    let mut comment = false;
    for (index, &ch) in chars.iter().enumerate() {
        match ch {
            '\n' | '\r' => {
                line_start = index + 1;
                comment = false;
            }
            '#' if index == line_start
                || chars
                    .get(index.wrapping_sub(1))
                    // After a tab the tab itself is the error.
                    .is_some_and(|c| *c == ' ') =>
            {
                // A `#` inside a quoted or block scalar is content; the
                // token check below still lets its tabs through.
                comment = true;
            }
            '\t' if !comment => {
                let owner = starts.partition_point(|&(start, _)| start <= index);
                let in_scalar = owner
                    .checked_sub(1)
                    .and_then(|at| starts.get(at))
                    .is_some_and(|&(_, quoted)| quoted);
                if !in_scalar {
                    return Err(YamlError::Syntax(format!(
                        "found character '\\t' that cannot start any token at line {} column {}",
                        text.get(..byte_offset(text, index))
                            .map_or(0, |t| t.matches('\n').count())
                            + 1,
                        index - line_start + 1
                    )));
                }
            }
            _ => {}
        }
    }
    Ok(())
}

fn byte_offset(text: &str, char_index: usize) -> usize {
    text.char_indices()
        .nth(char_index)
        .map_or(text.len(), |(at, _)| at)
}

fn at(mark: Marker) -> String {
    format!("line {} column {}", mark.line(), mark.col() + 1)
}

fn invalid(tag: &str, node: &Node) -> YamlError {
    YamlError::Construct(format!(
        "invalid value for tag '{tag}' at {}",
        at(node.mark())
    ))
}

fn scalar<'a>(tag: &str, node: &'a Node) -> Result<&'a str, YamlError> {
    match node {
        Node::Scalar { value, .. } => Ok(value),
        other => Err(YamlError::Construct(format!(
            "expected a scalar node for tag '{tag}', but found {} at {}",
            other.kind(),
            at(other.mark())
        ))),
    }
}

fn construct(node: &Node, budget: &mut usize, depth: usize) -> Result<Value, YamlError> {
    if depth > MAX_DEPTH {
        return Err(YamlError::TooDeep(MAX_DEPTH));
    }
    *budget = budget
        .checked_sub(1)
        .ok_or(YamlError::TooLarge(MAX_NODES))?;
    let tag = node.tag();
    match tag {
        TAG_NULL => scalar(tag, node).map(|_| Value::Null),
        TAG_BOOL => match scalar(tag, node)?.to_lowercase().as_str() {
            "yes" | "true" | "on" => Ok(Value::Bool(true)),
            "no" | "false" | "off" => Ok(Value::Bool(false)),
            _ => Err(invalid(tag, node)),
        },
        TAG_INT => construct_int(scalar(tag, node)?)
            .map(Value::Int)
            .ok_or_else(|| invalid(tag, node)),
        TAG_FLOAT => construct_float(scalar(tag, node)?)
            .map(Value::Float)
            .ok_or_else(|| invalid(tag, node)),
        TAG_STR => scalar(tag, node).map(|s| Value::Str(s.to_owned())),
        TAG_TIMESTAMP => construct_timestamp(scalar(tag, node)?)
            .map(Value::Timestamp)
            .ok_or_else(|| invalid(tag, node)),
        TAG_SEQ => match node {
            Node::Seq { items, .. } => items
                .iter()
                .map(|item| construct(item, budget, depth + 1))
                .collect::<Result<Vec<_>, _>>()
                .map(Value::Seq),
            other => Err(YamlError::Construct(format!(
                "expected a sequence node, but found {} at {}",
                other.kind(),
                at(other.mark())
            ))),
        },
        TAG_MAP => match node {
            Node::Map { pairs, .. } => {
                let mut mapping = Mapping::new();
                for (key_node, value_node) in flatten(pairs)? {
                    let key = if key_node.tag() == TAG_VALUE {
                        // `flatten_mapping` retags a `=` key as a str.
                        Value::Str(scalar(TAG_STR, &key_node)?.to_owned())
                    } else {
                        construct(&key_node, budget, depth + 1)?
                    };
                    if !Mapping::is_hashable(&key) {
                        return Err(YamlError::Construct(format!(
                            "found unhashable key at {}",
                            at(key_node.mark())
                        )));
                    }
                    let value = construct(&value_node, budget, depth + 1)?;
                    mapping.insert(key, value);
                }
                Ok(Value::Map(mapping))
            }
            other => Err(YamlError::Construct(format!(
                "expected a mapping node, but found {} at {}",
                other.kind(),
                at(other.mark())
            ))),
        },
        other => Err(YamlError::Construct(format!(
            "could not determine a constructor for the tag '{other}' at {}",
            at(node.mark())
        ))),
    }
}

/// `SafeConstructor.flatten_mapping`: merged pairs first (a list of merges in
/// reverse order), then the mapping's own pairs; later pairs win on insert.
fn flatten(pairs: &[Pair]) -> Result<Vec<Pair>, YamlError> {
    let mut merged = Vec::new();
    let mut own = Vec::new();
    for (key, value) in pairs {
        if key.tag() != TAG_MERGE {
            own.push((key.clone(), value.clone()));
            continue;
        }
        match value.as_ref() {
            Node::Map { pairs, .. } => merged.extend(flatten(pairs)?),
            Node::Seq { items, .. } => {
                let mut subs = Vec::new();
                for item in items {
                    match item.as_ref() {
                        Node::Map { pairs, .. } => subs.push(flatten(pairs)?),
                        other => {
                            return Err(YamlError::Construct(format!(
                                "expected a mapping for merging, but found {} at {}",
                                other.kind(),
                                at(other.mark())
                            )))
                        }
                    }
                }
                for sub in subs.into_iter().rev() {
                    merged.extend(sub);
                }
            }
            Node::Scalar { mark, .. } => {
                return Err(YamlError::Construct(format!(
                    "expected a mapping or list of mappings for merging, but found scalar at {}",
                    at(*mark)
                )))
            }
        }
    }
    merged.extend(own);
    Ok(merged)
}

/// `SafeConstructor.construct_yaml_int`.
fn construct_int(text: &str) -> Option<i128> {
    let value: String = text.chars().filter(|&c| c != '_').collect();
    let (sign, digits) = match value.strip_prefix('-') {
        Some(rest) => (-1, rest),
        None => (1, value.strip_prefix('+').unwrap_or(&value)),
    };
    if value.is_empty() {
        return None;
    }
    let magnitude = if digits == "0" {
        0
    } else if let Some(bin) = digits.strip_prefix("0b") {
        python_int(bin, 2)?
    } else if let Some(hex) = digits.strip_prefix("0x") {
        python_int(hex, 16)?
    } else if digits.starts_with('0') {
        // `int(value, 8)` also takes an `0o` prefix.
        let octal = digits
            .strip_prefix("0o")
            .or_else(|| digits.strip_prefix("0O"))
            .unwrap_or(digits);
        python_int(octal, 8)?
    } else if digits.contains(':') {
        let mut total: i128 = 0;
        let mut base: i128 = 1;
        for part in digits.rsplit(':') {
            total = total.checked_add(python_int(part, 10)?.checked_mul(base)?)?;
            base = base.checked_mul(60)?;
        }
        total
    } else {
        python_int(digits, 10)?
    };
    magnitude.checked_mul(sign)
}

/// `int(text, base)` for the ASCII forms PyYAML passes it (a sign is
/// accepted in every base, as Python does).
fn python_int(text: &str, base: u32) -> Option<i128> {
    i128::from_str_radix(text.trim(), base).ok()
}

/// `SafeConstructor.construct_yaml_float`.
fn construct_float(text: &str) -> Option<f64> {
    let value: String = text
        .chars()
        .filter(|&c| c != '_')
        .collect::<String>()
        .to_lowercase();
    let (sign, rest) = match value.strip_prefix('-') {
        Some(rest) => (-1.0, rest),
        None => (1.0, value.strip_prefix('+').unwrap_or(&value)),
    };
    if value.is_empty() {
        return None;
    }
    if rest == ".inf" {
        return Some(sign * f64::INFINITY);
    }
    if rest == ".nan" {
        return Some(f64::NAN);
    }
    if rest.contains(':') {
        let mut total = 0.0;
        let mut base = 1.0;
        for part in rest.rsplit(':') {
            total += python_float(part)? * base;
            base *= 60.0;
        }
        return Some(sign * total);
    }
    Some(sign * python_float(rest)?)
}

/// `float(text)`: Python accepts what Rust does, plus surrounding whitespace.
fn python_float(text: &str) -> Option<f64> {
    text.trim().parse::<f64>().ok()
}

/// `SafeConstructor.construct_yaml_timestamp`, with `datetime`'s range checks.
fn construct_timestamp(text: &str) -> Option<Timestamp> {
    let re = TIMESTAMP_PARTS.as_ref().ok()?;
    let caps = re.captures(text)?;
    let num = |name: &str| caps.name(name).map(|m| m.as_str().parse::<u32>());
    let year = u16::try_from(num("year")?.ok()?).ok()?;
    let month = u8::try_from(num("month")?.ok()?).ok()?;
    let day = u8::try_from(num("day")?.ok()?).ok()?;
    if year == 0 || !(1..=12).contains(&month) || day == 0 || day > days_in_month(year, month) {
        return None;
    }
    let time = match caps.name("hour").filter(|m| !m.as_str().is_empty()) {
        None => None,
        Some(hour) => {
            let hour = u8::try_from(hour.as_str().parse::<u32>().ok()?).ok()?;
            let minute = u8::try_from(num("minute")?.ok()?).ok()?;
            let second = u8::try_from(num("second")?.ok()?).ok()?;
            if hour > 23 || minute > 59 || second > 59 {
                return None;
            }
            let microsecond = match caps.name("fraction").map(|m| m.as_str()) {
                // An empty fraction pads to `000000`, like Python's.
                Some(fraction) => {
                    let mut digits: String = fraction.chars().take(6).collect();
                    while digits.len() < 6 {
                        digits.push('0');
                    }
                    digits.parse::<u32>().ok()?
                }
                _ => 0,
            };
            let offset_minutes = if let Some(sign) = caps.name("tz_sign") {
                let hours = i32::try_from(num("tz_hour")?.ok()?).ok()?;
                let minutes = match num("tz_minute") {
                    Some(m) => i32::try_from(m.ok()?).ok()?,
                    None => 0,
                };
                let total = hours * 60 + minutes;
                // `timezone()` needs strictly less than 24 hours.
                if total >= 24 * 60 {
                    return None;
                }
                let total = if sign.as_str() == "-" { -total } else { total };
                Some(i16::try_from(total).ok()?)
            } else if caps.name("tz").is_some() {
                Some(0)
            } else {
                None
            };
            Some(Time {
                hour,
                minute,
                second,
                microsecond,
                offset_minutes,
            })
        }
    };
    Some(Timestamp {
        year,
        month,
        day,
        time,
    })
}

fn days_in_month(year: u16, month: u8) -> u8 {
    match month {
        2 if year.is_multiple_of(4) && (!year.is_multiple_of(100) || year.is_multiple_of(400)) => {
            29
        }
        2 => 28,
        4 | 6 | 9 | 11 => 30,
        _ => 31,
    }
}

#[cfg(test)]
#[allow(clippy::unwrap_used)]
mod tests {
    use super::*;

    #[test]
    fn every_pattern_compiles() {
        for pattern in [
            &BOOL,
            &FLOAT,
            &INT,
            &MERGE,
            &NULL,
            &TIMESTAMP,
            &VALUE,
            &TIMESTAMP_PARTS,
        ] {
            assert!(pattern.as_ref().is_ok());
        }
    }

    #[test]
    fn plain_resolution_follows_yaml_1_1() {
        assert_eq!(resolve_plain("off"), TAG_BOOL);
        assert_eq!(resolve_plain(""), TAG_NULL);
        assert_eq!(resolve_plain("~"), TAG_NULL);
        assert_eq!(resolve_plain("1e3"), TAG_STR);
        assert_eq!(resolve_plain("1.0e+3"), TAG_FLOAT);
        assert_eq!(resolve_plain("0o17"), TAG_STR);
        assert_eq!(resolve_plain("017"), TAG_INT);
        assert_eq!(resolve_plain("08"), TAG_STR);
        assert_eq!(resolve_plain("1:30"), TAG_INT);
        assert_eq!(resolve_plain("<<"), TAG_MERGE);
        assert_eq!(resolve_plain("="), TAG_VALUE);
        assert_eq!(resolve_plain("2024-01-01"), TAG_TIMESTAMP);
        assert_eq!(resolve_plain("yes please"), TAG_STR);
    }

    #[test]
    fn ints_follow_the_safe_constructor() {
        assert_eq!(construct_int("0b1_01"), Some(5));
        assert_eq!(construct_int("-0x1F"), Some(-31));
        assert_eq!(construct_int("017"), Some(15));
        assert_eq!(construct_int("190:20:30"), Some(685_230));
        assert_eq!(construct_int("+12_345"), Some(12_345));
        assert_eq!(construct_int(""), None);
        assert_eq!(construct_int("0b"), None);
        assert_eq!(construct_int("abc"), None);
        assert_eq!(
            construct_int("99999999999999999999999999999999999999999"),
            None
        );
    }

    #[test]
    fn floats_follow_the_safe_constructor() {
        assert_eq!(construct_float("1."), Some(1.0));
        assert_eq!(construct_float("-.INF"), Some(f64::NEG_INFINITY));
        assert!(construct_float(".NaN").unwrap().is_nan());
        assert_eq!(construct_float("190:20:30.15"), Some(685_230.15));
        assert_eq!(construct_float("6.8523015e+5"), Some(685_230.15));
        assert_eq!(construct_float("1_0.5"), Some(10.5));
        assert_eq!(construct_float("x"), None);
        // `value[1:]` drops one sign; `float("-1")` takes the other.
        assert_eq!(construct_float("+-1"), Some(-1.0));
    }

    #[test]
    fn timestamps_check_calendar_ranges() {
        assert!(construct_timestamp("2024-02-29").is_some());
        assert!(construct_timestamp("2023-02-29").is_none());
        assert!(construct_timestamp("2024-1-1 25:00:00").is_none());
        assert!(construct_timestamp("2024-1-1 10:00:00 +24").is_none());
        let t = construct_timestamp("2001-12-14t21:59:43.10-05").unwrap();
        assert_eq!(t.isoformat(' '), "2001-12-14 21:59:43.100000-05:00");
    }

    #[test]
    fn timestamps_reject_each_invalid_calendar_and_clock_component() {
        for text in [
            "0000-01-01",
            "2024-00-01",
            "2024-13-01",
            "2024-01-00",
            "2024-01-32",
            "2024-04-31",
            "1900-02-29",
            "2100-02-29",
            "2024-01-01T24:00:00",
            "2024-01-01T00:60:00",
            "2024-01-01T00:00:60",
            "2024-01-01T00:00:00+24:00",
        ] {
            assert_eq!(construct_timestamp(text), None, "{text}");
        }
        for (text, expected) in [
            ("2024-01-31T23:59:59+23:59", "2024-01-31T23:59:59+23:59"),
            ("2024-01-01T00:00:00+05:30", "2024-01-01T00:00:00+05:30"),
            ("2024-01-01T00:00:00.Z", "2024-01-01T00:00:00+00:00"),
        ] {
            assert_eq!(construct_timestamp(text).unwrap().isoformat('T'), expected);
        }
        assert_eq!(
            construct_timestamp("2024-01-01T00:00:00+05:30")
                .unwrap()
                .time
                .unwrap()
                .offset_minutes,
            Some(330)
        );
    }

    #[test]
    fn errors_describe_node_kind_and_position() {
        let error = load("a:\n  !!str [x]").unwrap_err().to_string();
        assert_eq!(error, "expected a scalar node for tag 'tag:yaml.org,2002:str', but found sequence at line 2 column 9");
        assert!(load("a:\n  *missing")
            .unwrap_err()
            .to_string()
            .ends_with("line 2 column 3"));
        assert_eq!(
            load("é: x\n  \tx").unwrap_err().to_string(),
            "found character '\\t' that cannot start any token at line 2 column 3"
        );
        assert_eq!(byte_offset("é\na", 2), 3);
        assert_eq!(byte_offset("é\na", 3), 4);
    }

    #[test]
    fn comments_do_not_allow_tabs_in_later_lines_or_plain_content() {
        for text in ["a: 1 # c\nb:\tx", "a: x#\ty", "a: 1 # c\rb:\tx"] {
            assert!(check_tabs(text).is_err(), "{text:?}");
            assert!(load(text).is_err(), "{text:?}");
        }
        assert!(load("#\tcomment\na: x").is_ok());
    }

    #[test]
    fn depth_limit_accepts_exact_boundary_and_rejects_alias_depth() {
        // yaml-rust2's scanner has a separate u8 limit on flow nesting.
        // Block nesting reaches the public construction/composition boundary.
        let text = format!("{}x", "- ".repeat(MAX_DEPTH));
        assert!(load(&text).is_ok(), "{:?}", load(&text));
        let text = format!("- {text}");
        assert!(matches!(load(&text), Err(YamlError::TooDeep(MAX_DEPTH))));
        // Each parsed line is shallow; only alias expansion makes this deep.
        let mut text = String::from("a0: &a0 x\n");
        for i in 1..=MAX_DEPTH + 1 {
            text.push_str(&format!("a{i}: &a{i} [*a{}]\n", i - 1));
        }
        assert!(matches!(load(&text), Err(YamlError::TooDeep(MAX_DEPTH))));
    }

    #[test]
    fn mapping_keys_and_values_both_count_towards_constructed_depth() {
        let nested: String = (0..MAX_DEPTH)
            .map(|i| format!("{}k:\n", "  ".repeat(i)))
            .chain(std::iter::once(format!("{}x\n", "  ".repeat(MAX_DEPTH))))
            .collect();
        assert!(load(&nested).is_ok(), "{:?}", load(&nested));
        let nested: String = (0..MAX_DEPTH - 1)
            .map(|i| format!("{}k:\n", "  ".repeat(i + 1)))
            .chain(std::iter::once(format!("{}x\n", "  ".repeat(MAX_DEPTH))))
            .collect();
        let text = format!("a: &a\n{nested}b: {{k: *a}}\n");
        assert!(matches!(load(&text), Err(YamlError::TooDeep(MAX_DEPTH))));
        let text = format!("a: &a\n{nested}b: {{? *a : v}}\n");
        assert!(matches!(load(&text), Err(YamlError::TooDeep(MAX_DEPTH))));
    }

    #[test]
    fn quoted_tabs_are_content_even_when_tokens_share_a_start() {
        for text in [
            "'x\ty': value",
            "['x\ty']",
            "{'x\ty': v}",
            "'x\ty'",
            "a:\n  'x\ty'",
        ] {
            assert!(load(text).is_ok(), "{text:?}: {:?}", load(text));
        }
    }
}
