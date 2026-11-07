//! Cell values with the semantics v3 relied on: v3 read workbooks with openpyxl
//! and formatted the resulting Python objects, so the display strings follow
//! Python's `str()`, `repr()` and format-spec rules. This module reproduces the
//! parts the renderer, the formula evaluator and the conditional formatting
//! observe.

use std::fmt::Write as _;

/// A Python value as openpyxl (or the v3 evaluator) produced it.
#[derive(Debug, Clone, PartialEq, Default)]
pub enum Value {
    #[default]
    None,
    Bool(bool),
    Int(i128),
    Float(f64),
    Str(String),
    Date(Date),
    DateTime(DateTime),
    Time(Time),
    Duration(Duration),
    /// A range reference (`A1:B2`) evaluated to its cell values.
    List(Vec<Value>),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Date {
    pub year: i32,
    pub month: u32,
    pub day: u32,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Time {
    pub hour: u32,
    pub minute: u32,
    pub second: u32,
    pub micro: u32,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DateTime {
    pub date: Date,
    pub time: Time,
}

/// `datetime.timedelta`: normalised like Python (`0 <= seconds < 86400`,
/// `0 <= micros < 1_000_000`, days carries the sign).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Duration {
    pub days: i64,
    pub seconds: i64,
    pub micros: i64,
}

impl Duration {
    pub fn from_micros(total: i128) -> Self {
        let day = 86_400_000_000i128;
        let days = total.div_euclid(day);
        let rest = total.rem_euclid(day);
        Self {
            days: days as i64,
            seconds: (rest / 1_000_000) as i64,
            micros: (rest % 1_000_000) as i64,
        }
    }

    pub fn total_micros(&self) -> i128 {
        (self.days as i128 * 86_400 + self.seconds as i128) * 1_000_000 + self.micros as i128
    }
}

/// Days since 0001-01-01 (day 1 = 0001-01-01), Python's `date.toordinal()`.
pub fn ordinal(date: Date) -> i64 {
    let y = date.year as i64 - 1;
    let mut days = y * 365 + y / 4 - y / 100 + y / 400;
    const BEFORE: [i64; 13] = [0, 0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334];
    days += BEFORE[date.month as usize];
    if date.month > 2 && is_leap(date.year) {
        days += 1;
    }
    days + date.day as i64
}

pub fn is_leap(year: i32) -> bool {
    year % 4 == 0 && (year % 100 != 0 || year % 400 == 0)
}

fn days_in_month(year: i32, month: u32) -> u32 {
    match month {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        4 | 6 | 9 | 11 => 30,
        _ if is_leap(year) => 29,
        _ => 28,
    }
}

/// The date for a Python ordinal; `None` outside years 1–9999 (OverflowError).
pub fn from_ordinal(ordinal: i64) -> Option<Date> {
    if !(1..=3_652_059).contains(&ordinal) {
        return None;
    }
    // Walk 400/100/4/1-year cycles like CPython's `_ord2ymd`.
    let mut n = ordinal - 1;
    let n400 = n / 146_097;
    n %= 146_097;
    let n100 = n / 36_524;
    n %= 36_524;
    let n4 = n / 1_461;
    n %= 1_461;
    let n1 = n / 365;
    n %= 365;
    let mut year = (n400 * 400 + n100 * 100 + n4 * 4 + n1 + 1) as i32;
    if n1 == 4 || n100 == 4 {
        return Some(Date {
            year: year - 1,
            month: 12,
            day: 31,
        });
    }
    let _ = &mut year;
    let mut month = 1;
    let mut left = n as u32;
    loop {
        let len = days_in_month(year, month);
        if left < len {
            break;
        }
        left -= len;
        month += 1;
    }
    Some(Date {
        year,
        month,
        day: left + 1,
    })
}

impl DateTime {
    /// `self + duration`, `None` on overflow (Python raises OverflowError).
    pub fn add(&self, duration: Duration) -> Option<DateTime> {
        let base = (ordinal(self.date) as i128 * 86_400_000_000)
            + ((self.time.hour as i128 * 3600
                + self.time.minute as i128 * 60
                + self.time.second as i128)
                * 1_000_000)
            + self.time.micro as i128;
        let total = base + duration.total_micros();
        let day = 86_400_000_000i128;
        let ord = total.div_euclid(day);
        let rest = total.rem_euclid(day);
        let date = from_ordinal(i64::try_from(ord).ok()?)?;
        let secs = (rest / 1_000_000) as u32;
        Some(DateTime {
            date,
            time: Time {
                hour: secs / 3600,
                minute: secs / 60 % 60,
                second: secs % 60,
                micro: (rest % 1_000_000) as u32,
            },
        })
    }
}

impl std::fmt::Display for Date {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{:04}-{:02}-{:02}", self.year, self.month, self.day)
    }
}

impl std::fmt::Display for Time {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{:02}:{:02}:{:02}", self.hour, self.minute, self.second)?;
        if self.micro != 0 {
            write!(f, ".{:06}", self.micro)?;
        }
        Ok(())
    }
}

impl std::fmt::Display for DateTime {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{} {}", self.date, self.time)
    }
}

impl std::fmt::Display for Duration {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        if self.days != 0 {
            let plural = if self.days.abs() != 1 { "s" } else { "" };
            write!(f, "{} day{plural}, ", self.days)?;
        }
        let (hh, rest) = (self.seconds / 3600, self.seconds % 3600);
        write!(f, "{}:{:02}:{:02}", hh, rest / 60, rest % 60)?;
        if self.micros != 0 {
            write!(f, ".{:06}", self.micros)?;
        }
        Ok(())
    }
}

impl Value {
    pub fn is_none(&self) -> bool {
        matches!(self, Value::None)
    }

    /// Python truthiness (`bool(value)`).
    pub fn truthy(&self) -> bool {
        match self {
            Value::None => false,
            Value::Bool(b) => *b,
            Value::Int(i) => *i != 0,
            Value::Float(f) => *f != 0.0,
            Value::Str(s) => !s.is_empty(),
            Value::Date(_) | Value::DateTime(_) | Value::Time(_) => true,
            Value::Duration(d) => d.total_micros() != 0,
            Value::List(items) => !items.is_empty(),
        }
    }

    /// `value in (None, "")`.
    pub fn is_blank(&self) -> bool {
        match self {
            Value::None => true,
            Value::Str(s) => s.is_empty(),
            _ => false,
        }
    }

    /// Python `str(value)`.
    pub fn py_str(&self) -> String {
        match self {
            Value::None => "None".to_string(),
            Value::Bool(true) => "True".to_string(),
            Value::Bool(false) => "False".to_string(),
            Value::Int(i) => i.to_string(),
            Value::Float(f) => py_repr_float(*f),
            Value::Str(s) => s.clone(),
            Value::Date(d) => d.to_string(),
            Value::DateTime(d) => d.to_string(),
            Value::Time(t) => t.to_string(),
            Value::Duration(d) => d.to_string(),
            Value::List(items) => {
                let inner: Vec<String> = items.iter().map(Value::py_repr).collect();
                format!("[{}]", inner.join(", "))
            }
        }
    }

    /// Python `repr(value)` (used inside list reprs only).
    fn py_repr(&self) -> String {
        match self {
            Value::Str(s) => {
                if s.contains('\'') && !s.contains('"') {
                    format!("\"{s}\"")
                } else {
                    format!("'{}'", s.replace('\\', "\\\\").replace('\'', "\\'"))
                }
            }
            Value::Date(d) => format!("datetime.date({}, {}, {})", d.year, d.month, d.day),
            other => other.py_str(),
        }
    }

    /// Python `float(value)`; `None` where Python raises.
    pub fn py_float(&self) -> Option<f64> {
        match self {
            Value::Bool(b) => Some(if *b { 1.0 } else { 0.0 }),
            Value::Int(i) => Some(*i as f64),
            Value::Float(f) => Some(*f),
            Value::Str(s) => parse_py_float(s),
            _ => None,
        }
    }
}

/// Python `float(text)`.
pub fn parse_py_float(text: &str) -> Option<f64> {
    let trimmed = text.trim();
    if trimmed.is_empty() {
        return None;
    }
    let lower = trimmed.to_ascii_lowercase();
    let unsigned = lower.trim_start_matches(['+', '-']);
    if unsigned.len() + 1 < lower.len() {
        return None;
    }
    let negative = lower.starts_with('-');
    match unsigned {
        "inf" | "infinity" => {
            return Some(if negative {
                f64::NEG_INFINITY
            } else {
                f64::INFINITY
            })
        }
        "nan" => return Some(f64::NAN),
        _ => {}
    }
    let mut cleaned = String::with_capacity(trimmed.len());
    let chars: Vec<char> = trimmed.chars().collect();
    for (i, &c) in chars.iter().enumerate() {
        if c == '_' {
            let before = i > 0 && chars[i - 1].is_ascii_digit();
            let after = chars.get(i + 1).is_some_and(|n| n.is_ascii_digit());
            if !(before && after) {
                return None;
            }
            continue;
        }
        if !(c.is_ascii_digit() || matches!(c, '+' | '-' | '.' | 'e' | 'E')) {
            return None;
        }
        cleaned.push(c);
    }
    cleaned.parse::<f64>().ok()
}

/// Python `repr(float)`.
pub fn py_repr_float(x: f64) -> String {
    if x.is_nan() {
        return "nan".to_string();
    }
    if x.is_infinite() {
        return if x > 0.0 { "inf" } else { "-inf" }.to_string();
    }
    if x == 0.0 {
        return if x.is_sign_negative() { "-0.0" } else { "0.0" }.to_string();
    }
    let (negative, digits, exp) = shortest_digits(x);
    let decpt = exp + 1;
    let mut out = String::new();
    if negative {
        out.push('-');
    }
    if decpt > -4 && decpt <= 16 {
        place_fixed(&mut out, &digits, decpt, true);
    } else {
        place_exponent(&mut out, &digits, exp);
    }
    out
}

/// Sign, significant digits and decimal exponent of the shortest repr.
fn shortest_digits(x: f64) -> (bool, String, i32) {
    split_exponent(&format!("{x:e}"))
}

fn split_exponent(text: &str) -> (bool, String, i32) {
    let (mantissa, exp) = text.split_once('e').unwrap_or((text, "0"));
    let negative = mantissa.starts_with('-');
    let digits: String = mantissa.chars().filter(char::is_ascii_digit).collect();
    (negative, digits, exp.parse().unwrap_or(0))
}

fn place_fixed(out: &mut String, digits: &str, decpt: i32, add_dot_zero: bool) {
    if decpt <= 0 {
        out.push_str("0.");
        for _ in 0..(-decpt) {
            out.push('0');
        }
        out.push_str(digits);
    } else if decpt as usize >= digits.len() {
        out.push_str(digits);
        for _ in 0..(decpt as usize - digits.len()) {
            out.push('0');
        }
        if add_dot_zero {
            out.push_str(".0");
        }
    } else {
        out.push_str(&digits[..decpt as usize]);
        out.push('.');
        out.push_str(&digits[decpt as usize..]);
    }
}

fn place_exponent(out: &mut String, digits: &str, exp: i32) {
    out.push_str(&digits[..1]);
    if digits.len() > 1 {
        out.push('.');
        out.push_str(&digits[1..]);
    }
    let _ = write!(out, "e{}{:02}", if exp < 0 { '-' } else { '+' }, exp.abs());
}

/// Python `format(x, ".{precision}g")` for finite `x`.
pub fn py_general(x: f64, precision: usize) -> String {
    if x == 0.0 {
        return if x.is_sign_negative() { "-0" } else { "0" }.to_string();
    }
    let precision = precision.max(1);
    let (negative, digits, exp) = split_exponent(&format!("{:.*e}", precision - 1, x));
    let digits = digits.trim_end_matches('0');
    let digits = if digits.is_empty() { "0" } else { digits };
    let mut out = String::new();
    if negative {
        out.push('-');
    }
    if exp >= -4 && (exp as i64) < precision as i64 {
        place_fixed(&mut out, digits, exp + 1, false);
    } else {
        place_exponent(&mut out, digits, exp);
    }
    out
}

/// Python `format(x, f"{grouping}.{decimals}f")`; `grouping` adds `,`.
pub fn py_fixed(x: f64, decimals: usize, grouping: bool) -> String {
    let text = format!("{x:.decimals$}");
    if !grouping || !x.is_finite() {
        return text;
    }
    let (sign, body) = match text.strip_prefix('-') {
        Some(rest) => ("-", rest),
        None => ("", text.as_str()),
    };
    let (int_part, frac) = match body.split_once('.') {
        Some((i, f)) => (i, Some(f)),
        None => (body, None),
    };
    let mut grouped = String::new();
    for (i, c) in int_part.chars().enumerate() {
        if i > 0 && (int_part.len() - i) % 3 == 0 {
            grouped.push(',');
        }
        grouped.push(c);
    }
    match frac {
        Some(f) => format!("{sign}{grouped}.{f}"),
        None => format!("{sign}{grouped}"),
    }
}

/// Python `round(x, ndigits)` for floats (correctly rounded, half to even).
pub fn py_round(x: f64, ndigits: i64) -> f64 {
    if !x.is_finite() || x == 0.0 {
        return x;
    }
    if ndigits > 323 {
        return x;
    }
    if ndigits < -308 {
        return 0.0 * x;
    }
    if ndigits >= 0 {
        let text = format!("{:.*}", ndigits as usize, x);
        return text.parse().unwrap_or(x);
    }
    // Negative digits: round the exact integer part at 10^-ndigits.
    let places = (-ndigits) as usize;
    let negative = x < 0.0;
    let ax = x.abs();
    let int_text = format!("{:.0}", ax.trunc());
    let frac = ax - ax.trunc();
    if int_text.len() < places {
        // |x| < 10^places: 0, or 10^places when above the half.
        let half = format!("5{}", "0".repeat(places - 1));
        let padded = format!("{int_text:0>places$}");
        let above = padded > half || (padded == half && frac > 0.0);
        let value = if above {
            10f64.powi(places as i32)
        } else {
            0.0
        };
        return if negative { -value } else { value };
    }
    let split = int_text.len() - places;
    let (head, tail) = int_text.split_at(split);
    let half = format!("5{}", "0".repeat(places - 1));
    let head_odd = head
        .chars()
        .last()
        .is_some_and(|c| (c as u8 - b'0') % 2 == 1);
    let round_up = tail > half.as_str() || (tail == half && (frac > 0.0 || head_odd));
    let mut digits: Vec<u8> = head.bytes().map(|b| b - b'0').collect();
    if round_up {
        let mut i = digits.len();
        loop {
            if i == 0 {
                digits.insert(0, 1);
                break;
            }
            i -= 1;
            if digits[i] == 9 {
                digits[i] = 0;
            } else {
                digits[i] += 1;
                break;
            }
        }
    }
    let mut text: String = digits.iter().map(|d| (d + b'0') as char).collect();
    text.push_str(&"0".repeat(places));
    let value: f64 = text.parse().unwrap_or(0.0);
    if negative {
        -value
    } else {
        value
    }
}

/// Python `str.casefold()` (lower-casing plus the common full foldings).
pub fn casefold(text: &str) -> String {
    let lower = text.to_lowercase();
    if lower.chars().any(|c| matches!(c, 'ß' | 'ſ' | 'ς')) {
        lower.replace('ß', "ss").replace('ſ', "s").replace('ς', "σ")
    } else {
        lower
    }
}

/// Python `str.strip()` (Unicode whitespace).
pub fn py_strip(text: &str) -> &str {
    text.trim_matches(|c: char| c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c))
}

/// A Python number in the renderer's geometry (ints stay ints, as in v3:
/// `max(height, 25) + 1` is an int when the row is short).
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum Num {
    Int(i64),
    Float(f64),
}

impl Num {
    pub fn f(self) -> f64 {
        match self {
            Num::Int(i) => i as f64,
            Num::Float(f) => f,
        }
    }

    /// `self + other`.
    pub fn add(self, other: Num) -> Num {
        match (self, other) {
            (Num::Int(a), Num::Int(b)) => Num::Int(a + b),
            (a, b) => Num::Float(a.f() + b.f()),
        }
    }

    /// Python `max(self, other)` (the first unless the second is larger).
    pub fn max(self, other: Num) -> Num {
        if other.f() > self.f() {
            other
        } else {
            self
        }
    }

    /// Python `min(self, other)`.
    pub fn min(self, other: Num) -> Num {
        if other.f() < self.f() {
            other
        } else {
            self
        }
    }
}

/// CPython's `sum()` (3.12+) fed one item at a time: exact ints until the
/// first float, then Neumaier-compensated floats (ints added plainly).
#[derive(Debug, Clone, Copy, Default)]
pub struct PySum {
    int_total: i64,
    float_phase: bool,
    total: f64,
    compensation: f64,
}

impl PySum {
    pub fn push(&mut self, item: Num) {
        match (self.float_phase, item) {
            (false, Num::Int(i)) => self.int_total += i,
            (false, Num::Float(x)) => {
                self.float_phase = true;
                self.total = self.int_total as f64 + x;
            }
            (true, Num::Int(i)) => self.total += i as f64,
            (true, Num::Float(x)) => {
                let t = self.total + x;
                if self.total.abs() >= x.abs() {
                    self.compensation += (self.total - t) + x;
                } else {
                    self.compensation += (x - t) + self.total;
                }
                self.total = t;
            }
        }
    }

    pub fn value(&self) -> Num {
        if !self.float_phase {
            return Num::Int(self.int_total);
        }
        let mut total = self.total;
        if self.compensation != 0.0 && self.compensation.is_finite() {
            total += self.compensation;
        }
        Num::Float(total)
    }

    pub fn of(items: impl IntoIterator<Item = Num>) -> Num {
        let mut sum = PySum::default();
        for item in items {
            sum.push(item);
        }
        sum.value()
    }

    /// `[sum(items[:k]) for k in 0..=len]`.
    pub fn prefixes(items: &[Num]) -> Vec<Num> {
        let mut sum = PySum::default();
        let mut out = Vec::with_capacity(items.len() + 1);
        out.push(sum.value());
        for item in items {
            sum.push(*item);
            out.push(sum.value());
        }
        out
    }
}

/// Python `sum()` of floats (3.12+: Neumaier compensated, starting from int 0).
pub fn py_sum(numbers: &[f64]) -> Value {
    let Some((&first, rest)) = numbers.split_first() else {
        return Value::Int(0);
    };
    let mut total = 0.0 + first;
    let mut compensation = 0.0;
    for &x in rest {
        let t = total + x;
        if total.abs() >= x.abs() {
            compensation += (total - t) + x;
        } else {
            compensation += (x - t) + total;
        }
        total = t;
    }
    if compensation != 0.0 && compensation.is_finite() {
        total += compensation;
    }
    Value::Float(total)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn float_repr_matches_python() {
        assert_eq!(py_repr_float(1.0), "1.0");
        assert_eq!(py_repr_float(0.1 + 0.2), "0.30000000000000004");
        assert_eq!(py_repr_float(1e16), "1e+16");
        assert_eq!(py_repr_float(1234567890123456.0), "1234567890123456.0");
        assert_eq!(py_repr_float(0.0001), "0.0001");
        assert_eq!(py_repr_float(0.00001), "1e-05");
        assert_eq!(py_repr_float(-1.5e-7), "-1.5e-07");
        assert_eq!(py_repr_float(1.5e300), "1.5e+300");
    }

    #[test]
    fn general_and_fixed_match_python() {
        assert_eq!(py_general(0.1 + 0.2, 10), "0.3");
        assert_eq!(py_general(1.23456789012345e-7, 10), "1.23456789e-07");
        assert_eq!(py_general(1e20, 10), "1e+20");
        assert_eq!(py_general(10.0 / 3.0, 10), "3.333333333");
        assert_eq!(py_general(1234567890.5, 10), "1234567890");
        assert_eq!(py_general(12345678901.5, 10), "1.23456789e+10");
        assert_eq!(py_fixed(1234567.891, 2, true), "1,234,567.89");
        assert_eq!(py_fixed(-1234.5, 0, true), "-1,234");
        assert_eq!(py_fixed(999.999, 2, true), "1,000.00");
    }

    #[test]
    fn rounding_matches_python() {
        assert_eq!(py_round(2.5, 0), 2.0);
        assert_eq!(py_round(-2.5, 0), -2.0);
        assert_eq!(py_round(2.675, 2), 2.67);
        assert_eq!(py_round(1234.5, -2), 1200.0);
        assert_eq!(py_round(1250.0, -2), 1200.0);
        assert_eq!(py_round(1350.0, -2), 1400.0);
        assert_eq!(py_round(1250.1, -2), 1300.0);
        assert_eq!(py_round(49.0, -2), 0.0);
        assert_eq!(py_round(51.0, -2), 100.0);
        assert_eq!(py_round(9999.0, -2), 10000.0);
    }

    #[test]
    fn dates_round_trip() {
        let date = Date {
            year: 2024,
            month: 1,
            day: 15,
        };
        assert_eq!(from_ordinal(ordinal(date)), Some(date));
        let epoch = Date {
            year: 1899,
            month: 12,
            day: 30,
        };
        assert_eq!(
            from_ordinal(ordinal(epoch) + 45000),
            Some(Date {
                year: 2023,
                month: 3,
                day: 15
            })
        );
        assert_eq!(
            from_ordinal(ordinal(Date {
                year: 2000,
                month: 12,
                day: 31
            }))
            .unwrap()
            .day,
            31
        );
        assert_eq!(
            Duration::from_micros(95_400_000_000).to_string(),
            "1 day, 2:30:00"
        );
        assert_eq!(
            Duration::from_micros(-3_600_000_000).to_string(),
            "-1 day, 23:00:00"
        );
    }

    #[test]
    fn sums_like_python() {
        assert_eq!(py_sum(&[]), Value::Int(0));
        assert_eq!(py_sum(&[0.1, 0.2, 0.3]), Value::Float(0.6));
        assert_eq!(parse_py_float(" 1_000 "), Some(1000.0));
        assert_eq!(parse_py_float("1,000"), None);
        assert_eq!(parse_py_float("12"), Some(12.0));
    }
}
