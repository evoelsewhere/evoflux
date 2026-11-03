//! The values PyYAML's `safe_load` returns and `safe_dump` accepts.
//!
//! Python objects map one to one: `None`, `bool`, `int`, `float`, `str`,
//! `datetime.date` / `datetime.datetime` ([`Timestamp`]), `list` and `dict`
//! ([`Mapping`], which keeps insertion order and Python's key equality).

use std::collections::HashMap;

#[derive(Debug, Clone, PartialEq)]
pub enum Value {
    Null,
    Bool(bool),
    Int(i128),
    Float(f64),
    Str(String),
    Timestamp(Timestamp),
    Seq(Vec<Value>),
    Map(Mapping),
}

/// `datetime.date` (no `time`) or `datetime.datetime`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Timestamp {
    pub year: u16,
    pub month: u8,
    pub day: u8,
    pub time: Option<Time>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Time {
    pub hour: u8,
    pub minute: u8,
    pub second: u8,
    pub microsecond: u32,
    /// UTC offset in minutes; `None` is a naive datetime.
    pub offset_minutes: Option<i16>,
}

impl Timestamp {
    /// Python's `isoformat(sep)`; a date ignores `sep`.
    pub fn isoformat(&self, sep: char) -> String {
        let mut out = format!("{:04}-{:02}-{:02}", self.year, self.month, self.day);
        if let Some(time) = self.time {
            out.push(sep);
            out.push_str(&format!(
                "{:02}:{:02}:{:02}",
                time.hour, time.minute, time.second
            ));
            if time.microsecond != 0 {
                out.push_str(&format!(".{:06}", time.microsecond));
            }
            if let Some(offset) = time.offset_minutes {
                let sign = if offset < 0 { '-' } else { '+' };
                let abs = offset.unsigned_abs();
                out.push_str(&format!("{sign}{:02}:{:02}", abs / 60, abs % 60));
            }
        }
        out
    }

    /// Days since 1970-01-01 of the calendar date (proleptic Gregorian).
    pub(crate) fn days_from_civil(&self) -> i64 {
        let (y, m, d) = (
            i64::from(self.year),
            i64::from(self.month),
            i64::from(self.day),
        );
        let y = if m <= 2 { y - 1 } else { y };
        let era = y.div_euclid(400);
        let yoe = y - era * 400;
        let mp = (m + 9) % 12;
        let doy = (153 * mp + 2) / 5 + d - 1;
        let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
        era * 146_097 + doe - 719_468
    }
}

/// An ordered mapping with Python `dict` semantics: inserting a key that is
/// already present (by Python equality, so `1`, `1.0` and `True` are one key)
/// replaces the value and keeps the first key and its position.
#[derive(Debug, Clone, Default)]
pub struct Mapping {
    entries: Vec<(Value, Value)>,
    index: HashMap<KeyId, usize>,
}

impl PartialEq for Mapping {
    fn eq(&self, other: &Self) -> bool {
        self.entries == other.entries
    }
}

/// The hash identity of a hashable key under Python equality.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
enum KeyId {
    Null,
    Int(i128),
    /// A float that is not an integral value (or NaN, all NaNs being one key:
    /// PyYAML's `.nan` is a single shared object).
    Float(u64),
    Str(String),
    Date(u16, u8, u8),
    Naive(u16, u8, u8, u8, u8, u8, u32),
    /// Aware datetimes compare by instant: microseconds since the epoch.
    Aware(i128),
}

fn key_id(key: &Value) -> Option<KeyId> {
    Some(match key {
        Value::Null => KeyId::Null,
        Value::Bool(b) => KeyId::Int(i128::from(*b)),
        Value::Int(i) => KeyId::Int(*i),
        Value::Float(f) => {
            if f.is_nan() {
                KeyId::Float(f64::NAN.to_bits())
            } else if f.fract() == 0.0 && f.abs() < 1e38 {
                // Exact: an integral f64 below 2^126 converts without loss.
                #[allow(clippy::cast_possible_truncation)]
                KeyId::Int(*f as i128)
            } else {
                KeyId::Float(f.to_bits())
            }
        }
        Value::Str(s) => KeyId::Str(s.clone()),
        Value::Timestamp(t) => match t.time {
            None => KeyId::Date(t.year, t.month, t.day),
            Some(time) => match time.offset_minutes {
                None => KeyId::Naive(
                    t.year,
                    t.month,
                    t.day,
                    time.hour,
                    time.minute,
                    time.second,
                    time.microsecond,
                ),
                Some(offset) => {
                    let seconds = i128::from(t.days_from_civil()) * 86_400
                        + i128::from(time.hour) * 3_600
                        + i128::from(time.minute) * 60
                        + i128::from(time.second)
                        - i128::from(offset) * 60;
                    KeyId::Aware(seconds * 1_000_000 + i128::from(time.microsecond))
                }
            },
        },
        Value::Seq(_) | Value::Map(_) => return None,
    })
}

impl Mapping {
    pub fn new() -> Self {
        Self::default()
    }

    /// Whether `key` can be a `dict` key in Python (lists and dicts cannot).
    pub fn is_hashable(key: &Value) -> bool {
        key_id(key).is_some()
    }

    /// Insert like `dict[key] = value`; returns the replaced value. An
    /// unhashable key is appended without a duplicate check.
    pub fn insert(&mut self, key: Value, value: Value) -> Option<Value> {
        match key_id(&key) {
            Some(id) => {
                if let Some(&at) = self.index.get(&id) {
                    if let Some(entry) = self.entries.get_mut(at) {
                        return Some(std::mem::replace(&mut entry.1, value));
                    }
                }
                self.index.insert(id, self.entries.len());
                self.entries.push((key, value));
                None
            }
            None => {
                self.entries.push((key, value));
                None
            }
        }
    }

    pub fn get_value(&self, key: &Value) -> Option<&Value> {
        let at = *self.index.get(&key_id(key)?)?;
        self.entries.get(at).map(|(_, v)| v)
    }

    pub fn get(&self, key: &str) -> Option<&Value> {
        let at = *self.index.get(&KeyId::Str(key.to_owned()))?;
        self.entries.get(at).map(|(_, v)| v)
    }

    pub fn get_mut(&mut self, key: &str) -> Option<&mut Value> {
        let at = *self.index.get(&KeyId::Str(key.to_owned()))?;
        self.entries.get_mut(at).map(|(_, v)| v)
    }

    pub fn contains_key(&self, key: &str) -> bool {
        self.index.contains_key(&KeyId::Str(key.to_owned()))
    }

    /// Remove like `dict.pop(key)`; later entries keep their order.
    pub fn get_value_mut(&mut self, key: &Value) -> Option<&mut Value> {
        let at = *self.index.get(&key_id(key)?)?;
        self.entries.get_mut(at).map(|(_, v)| v)
    }

    pub fn remove(&mut self, key: &str) -> Option<Value> {
        self.remove_value(&Value::Str(key.to_owned()))
    }

    /// Remove like `dict.pop(key)` for any hashable key.
    pub fn remove_value(&mut self, key: &Value) -> Option<Value> {
        let at = self.index.remove(&key_id(key)?)?;
        if at >= self.entries.len() {
            return None;
        }
        let (_, value) = self.entries.remove(at);
        for slot in self.index.values_mut() {
            if *slot > at {
                *slot -= 1;
            }
        }
        Some(value)
    }

    pub fn len(&self) -> usize {
        self.entries.len()
    }

    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }

    pub fn iter(&self) -> std::slice::Iter<'_, (Value, Value)> {
        self.entries.iter()
    }

    pub fn keys(&self) -> impl Iterator<Item = &Value> {
        self.entries.iter().map(|(k, _)| k)
    }
}

impl<'a> IntoIterator for &'a Mapping {
    type Item = &'a (Value, Value);
    type IntoIter = std::slice::Iter<'a, (Value, Value)>;
    fn into_iter(self) -> Self::IntoIter {
        self.entries.iter()
    }
}

impl IntoIterator for Mapping {
    type Item = (Value, Value);
    type IntoIter = std::vec::IntoIter<(Value, Value)>;
    fn into_iter(self) -> Self::IntoIter {
        self.entries.into_iter()
    }
}

impl FromIterator<(Value, Value)> for Mapping {
    fn from_iter<I: IntoIterator<Item = (Value, Value)>>(iter: I) -> Self {
        let mut mapping = Mapping::new();
        for (k, v) in iter {
            mapping.insert(k, v);
        }
        mapping
    }
}

/// Python's `repr(float)`: the shortest round-trip digits, positional for
/// decimal exponents in `-4..16`, otherwise `d.ddde+XX`.
pub fn python_float_repr(f: f64) -> String {
    if f.is_nan() {
        return "nan".to_owned();
    }
    if f.is_infinite() {
        return if f > 0.0 { "inf" } else { "-inf" }.to_owned();
    }
    // `{:e}` gives the shortest round-trip digits as `d.ddde<exp>`.
    let sci = format!("{f:e}");
    let (mantissa, exp) = sci.split_once('e').unwrap_or((sci.as_str(), "0"));
    let exp: i32 = exp.parse().unwrap_or(0);
    let negative = mantissa.starts_with('-');
    let digits: String = mantissa.chars().filter(char::is_ascii_digit).collect();
    let sign = if negative { "-" } else { "" };
    if (-4..16).contains(&exp) {
        let point = exp + 1;
        let body = if point <= 0 {
            format!("0.{}{}", "0".repeat(point.unsigned_abs() as usize), digits)
        } else {
            let point = point as usize;
            if digits.len() <= point {
                format!("{}{}.0", digits, "0".repeat(point - digits.len()))
            } else {
                let (int, frac) = digits.split_at(point);
                format!("{int}.{frac}")
            }
        };
        format!("{sign}{body}")
    } else {
        let (first, rest) = digits.split_at(digits.len().min(1));
        let mantissa = if rest.is_empty() {
            first.to_owned()
        } else {
            format!("{first}.{rest}")
        };
        let exp_sign = if exp < 0 { '-' } else { '+' };
        format!("{sign}{mantissa}e{exp_sign}{:02}", exp.unsigned_abs())
    }
}

/// How `json.dumps` writes a non-string dict key.
fn json_key(key: &Value) -> String {
    match key {
        Value::Null => "null".to_owned(),
        Value::Bool(b) => b.to_string(),
        Value::Int(i) => i.to_string(),
        Value::Float(f) => {
            if f.is_nan() {
                "NaN".to_owned()
            } else if f.is_infinite() {
                if *f > 0.0 { "Infinity" } else { "-Infinity" }.to_owned()
            } else {
                python_float_repr(*f)
            }
        }
        Value::Str(s) => s.clone(),
        Value::Timestamp(t) => t.isoformat('T'),
        Value::Seq(_) | Value::Map(_) => String::new(),
    }
}

impl Value {
    /// A JSON view: timestamps as ISO 8601 (`T` separator), non-string keys
    /// written as `json.dumps` writes them, non-finite floats as `null`,
    /// integers outside the JSON number range as strings.
    pub fn to_json(&self) -> serde_json::Value {
        use serde_json::Value as J;
        match self {
            Value::Null => J::Null,
            Value::Bool(b) => J::Bool(*b),
            Value::Int(i) => i64::try_from(*i)
                .map(J::from)
                .or_else(|_| u64::try_from(*i).map(J::from))
                .unwrap_or_else(|_| J::String(i.to_string())),
            Value::Float(f) => serde_json::Number::from_f64(*f).map_or(J::Null, J::Number),
            Value::Str(s) => J::String(s.clone()),
            Value::Timestamp(t) => J::String(t.isoformat('T')),
            Value::Seq(items) => J::Array(items.iter().map(Value::to_json).collect()),
            Value::Map(map) => {
                let mut out = serde_json::Map::new();
                for (k, v) in map {
                    out.insert(json_key(k), v.to_json());
                }
                J::Object(out)
            }
        }
    }

    /// The value `json.loads` would give for the same JSON.
    pub fn from_json(json: &serde_json::Value) -> Value {
        use serde_json::Value as J;
        match json {
            J::Null => Value::Null,
            J::Bool(b) => Value::Bool(*b),
            J::Number(n) => {
                if let Some(i) = n.as_i64() {
                    Value::Int(i128::from(i))
                } else if let Some(u) = n.as_u64() {
                    Value::Int(i128::from(u))
                } else {
                    Value::Float(n.as_f64().unwrap_or(f64::NAN))
                }
            }
            J::String(s) => Value::Str(s.clone()),
            J::Array(items) => Value::Seq(items.iter().map(Value::from_json).collect()),
            J::Object(map) => Value::Map(
                map.iter()
                    .map(|(k, v)| (Value::Str(k.clone()), Value::from_json(v)))
                    .collect(),
            ),
        }
    }

    pub fn is_null(&self) -> bool {
        matches!(self, Value::Null)
    }

    pub fn as_str(&self) -> Option<&str> {
        match self {
            Value::Str(s) => Some(s),
            _ => None,
        }
    }

    pub fn as_bool(&self) -> Option<bool> {
        match self {
            Value::Bool(b) => Some(*b),
            _ => None,
        }
    }

    pub fn as_int(&self) -> Option<i128> {
        match self {
            Value::Int(i) => Some(*i),
            _ => None,
        }
    }

    pub fn as_seq(&self) -> Option<&[Value]> {
        match self {
            Value::Seq(items) => Some(items),
            _ => None,
        }
    }

    pub fn as_map(&self) -> Option<&Mapping> {
        match self {
            Value::Map(map) => Some(map),
            _ => None,
        }
    }

    pub fn as_map_mut(&mut self) -> Option<&mut Mapping> {
        match self {
            Value::Map(map) => Some(map),
            _ => None,
        }
    }

    /// `value.get(key)` on a mapping with a string key; `None` otherwise.
    pub fn get(&self, key: &str) -> Option<&Value> {
        self.as_map()?.get(key)
    }
}

impl From<&str> for Value {
    fn from(s: &str) -> Self {
        Value::Str(s.to_owned())
    }
}

impl From<String> for Value {
    fn from(s: String) -> Self {
        Value::Str(s)
    }
}

#[cfg(test)]
#[allow(clippy::unwrap_used, clippy::indexing_slicing)]
mod tests {
    use super::*;

    #[test]
    fn float_repr_matches_python() {
        let cases = [
            (1.0, "1.0"),
            (0.1, "0.1"),
            (-2.5, "-2.5"),
            (1e16, "1e+16"),
            (1.5e16, "1.5e+16"),
            (1e15, "1000000000000000.0"),
            (0.0001, "0.0001"),
            (0.00001, "1e-05"),
            (1.25e-7, "1.25e-07"),
            (123456.789, "123456.789"),
            (1e300, "1e+300"),
            (0.0, "0.0"),
            (-0.0, "-0.0"),
            (60.0, "60.0"),
            (f64::MAX, "1.7976931348623157e+308"),
            (5e-324, "5e-324"),
        ];
        for (f, want) in cases {
            assert_eq!(python_float_repr(f), want, "{f:e}");
        }
    }

    #[test]
    fn dict_semantics_merge_numeric_keys() {
        let mut map = Mapping::new();
        map.insert(Value::Int(1), "a".into());
        map.insert(Value::Bool(true), "b".into());
        map.insert(Value::Float(1.0), "c".into());
        map.insert(Value::Float(1.5), "d".into());
        assert_eq!(map.len(), 2);
        assert_eq!(map.iter().next().unwrap().0, Value::Int(1));
        assert_eq!(map.get_value(&Value::Int(1)), Some(&"c".into()));
    }

    #[test]
    fn aware_datetimes_compare_by_instant() {
        let at = |hour, offset| {
            Value::Timestamp(Timestamp {
                year: 2024,
                month: 1,
                day: 1,
                time: Some(Time {
                    hour,
                    minute: 0,
                    second: 0,
                    microsecond: 0,
                    offset_minutes: offset,
                }),
            })
        };
        let mut map = Mapping::new();
        map.insert(at(10, Some(60)), Value::Int(1));
        map.insert(at(9, Some(0)), Value::Int(2));
        map.insert(at(9, None), Value::Int(3));
        assert_eq!(map.len(), 2);
    }

    #[test]
    fn remove_keeps_the_index_consistent() {
        let mut map: Mapping = [("a", 1), ("b", 2), ("c", 3)]
            .into_iter()
            .map(|(k, v)| (Value::from(k), Value::Int(v)))
            .collect();
        assert_eq!(map.remove("a"), Some(Value::Int(1)));
        assert_eq!(map.get("c"), Some(&Value::Int(3)));
        map.insert("a".into(), Value::Int(4));
        let keys: Vec<_> = map.keys().filter_map(Value::as_str).collect();
        assert_eq!(keys, ["b", "c", "a"]);
        assert_eq!(map.remove("zz"), None);
        let mut numeric: Mapping = [(Value::Int(1), Value::Int(1))].into_iter().collect();
        *numeric.get_value_mut(&Value::Bool(true)).unwrap() = Value::Int(2);
        assert_eq!(
            numeric.remove_value(&Value::Float(1.0)),
            Some(Value::Int(2))
        );
        assert_eq!(numeric.remove_value(&Value::Seq(vec![])), None);
    }

    #[test]
    fn json_round_trip_and_key_stringification() {
        let mut map = Mapping::new();
        map.insert(Value::Bool(true), Value::Int(1));
        map.insert(Value::Null, Value::Float(f64::INFINITY));
        map.insert(Value::Float(1.5), Value::Int(i128::MAX));
        let json = Value::Map(map).to_json();
        assert_eq!(
            json.to_string(),
            r#"{"true":1,"null":null,"1.5":"170141183460469231731687303715884105727"}"#
        );
        let back = Value::from_json(&serde_json::json!({"a": [1, 2.5, null, "x"]}));
        assert_eq!(
            back.get("a").and_then(Value::as_seq).map(<[_]>::len),
            Some(4)
        );
    }

    #[test]
    fn isoformat_matches_python() {
        let t = Timestamp {
            year: 2001,
            month: 12,
            day: 14,
            time: Some(Time {
                hour: 21,
                minute: 59,
                second: 43,
                microsecond: 100_000,
                offset_minutes: Some(-330),
            }),
        };
        assert_eq!(t.isoformat(' '), "2001-12-14 21:59:43.100000-05:30");
        let d = Timestamp {
            year: 999,
            month: 1,
            day: 2,
            time: None,
        };
        assert_eq!(d.isoformat(' '), "0999-01-02");
    }

    #[test]
    fn gregorian_dates_have_known_epoch_days() {
        // Independently checked against datetime.date - date(1970, 1, 1).
        for (year, month, day, days) in [
            (1970, 1, 1, 0),
            (2000, 3, 1, 11_017),
            (2024, 1, 1, 19_723),
            (1900, 2, 28, -25_509),
            (2100, 3, 1, 47_541),
            (1, 1, 1, -719_162),
            (2000, 2, 29, 11_016),
        ] {
            assert_eq!(
                Timestamp {
                    year,
                    month,
                    day,
                    time: None
                }
                .days_from_civil(),
                days
            );
        }
    }

    #[test]
    fn datetime_keys_preserve_instant_and_naive_components() {
        let timestamp = |day, hour, minute, second, microsecond, offset_minutes| Timestamp {
            year: 2024,
            month: 1,
            day,
            time: Some(Time {
                hour,
                minute,
                second,
                microsecond,
                offset_minutes,
            }),
        };
        let local = timestamp(2, 0, 30, 17, 123_456, Some(60));
        let utc = timestamp(1, 23, 30, 17, 123_456, Some(0));
        let mut map = Mapping::new();
        map.insert(Value::Timestamp(local), "first".into());
        assert_eq!(
            map.insert(Value::Timestamp(utc), "second".into()),
            Some("first".into())
        );
        assert_eq!(map.len(), 1);
        assert_eq!(
            key_id(&Value::Timestamp(utc)),
            Some(KeyId::Aware(1_704_151_817_123_456))
        );
        let naive = timestamp(1, 23, 30, 17, 123_456, None);
        assert_eq!(
            key_id(&Value::Timestamp(naive)),
            Some(KeyId::Naive(2024, 1, 1, 23, 30, 17, 123_456))
        );
        assert_ne!(
            key_id(&Value::Timestamp(naive)),
            key_id(&Value::Timestamp(utc))
        );
        assert_eq!(utc.isoformat('T'), "2024-01-01T23:30:17.123456+00:00");
        assert_eq!(
            timestamp(1, 0, 0, 0, 0, Some(-30)).isoformat('T'),
            "2024-01-01T00:00:00-00:30"
        );
    }

    #[test]
    fn float_keys_only_coalesce_with_integers_below_the_bound() {
        assert_eq!(key_id(&Value::Float(42.0)), Some(KeyId::Int(42)));
        assert_eq!(key_id(&Value::Float(-42.0)), Some(KeyId::Int(-42)));
        assert_eq!(
            key_id(&Value::Float(1e38)),
            Some(KeyId::Float(1e38_f64.to_bits()))
        );
        assert_eq!(
            key_id(&Value::Float(-1e38)),
            Some(KeyId::Float((-1e38_f64).to_bits()))
        );
        assert_eq!(
            key_id(&Value::Float(42.5)),
            Some(KeyId::Float(42.5_f64.to_bits()))
        );
    }

    #[test]
    fn mapping_equality_and_mutation_observe_entries() {
        let mut value = Value::Map(Mapping::new());
        let map = value.as_map_mut().unwrap();
        assert!(map.is_empty());
        assert!(!map.contains_key("a"));
        map.insert("a".into(), Value::Int(2));
        map.insert("b".into(), Value::Int(3));
        assert!(!map.is_empty());
        assert!(map.contains_key("a"));
        assert_eq!(map.get_mut("missing"), None);
        *map.get_mut("a").unwrap() = Value::Int(4);
        let same: Mapping = [("a".into(), Value::Int(4)), ("b".into(), Value::Int(3))]
            .into_iter()
            .collect();
        assert_eq!(*map, same);
        assert_ne!(*map, Mapping::new());
        assert_eq!(
            map.clone().into_iter().collect::<Vec<_>>(),
            vec![("a".into(), Value::Int(4)), ("b".into(), Value::Int(3))]
        );
        assert_eq!(value.get("a"), Some(&Value::Int(4)));
        assert_eq!(Value::Null.as_map_mut(), None);
    }

    #[test]
    fn scalar_accessors_preserve_types_and_values() {
        assert!(Value::Null.is_null());
        assert!(!Value::Bool(false).is_null());
        for b in [true, false] {
            assert_eq!(Value::Bool(b).as_bool(), Some(b));
        }
        assert_eq!(Value::Int(1).as_bool(), None);
        for i in [-7, 0, 1, 42] {
            assert_eq!(Value::Int(i).as_int(), Some(i));
        }
        assert_eq!(Value::Bool(true).as_int(), None);
    }

    #[test]
    fn nonfinite_float_representations_and_json_keys_keep_the_sign() {
        for (f, repr, key) in [
            (f64::INFINITY, "inf", "Infinity"),
            (f64::NEG_INFINITY, "-inf", "-Infinity"),
            (f64::NAN, "nan", "NaN"),
        ] {
            assert_eq!(python_float_repr(f), repr);
            assert_eq!(json_key(&Value::Float(f)), key);
        }
    }
}
