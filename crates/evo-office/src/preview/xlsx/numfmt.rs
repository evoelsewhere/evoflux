//! Number formats: openpyxl's built-in table, its date/timedelta detection and
//! serial conversion (`openpyxl.styles.numbers`, `openpyxl.utils.datetime`), and
//! v3's display formatting (`xlsx_formula.format_computed_value`).

use super::value::{
    from_ordinal, ordinal, parse_py_float, py_fixed, py_general, Date, DateTime, Duration, Time,
    Value,
};

/// openpyxl `BUILTIN_FORMATS`.
pub fn builtin_format(id: u32) -> Option<&'static str> {
    Some(match id {
        0 => "General",
        1 => "0",
        2 => "0.00",
        3 => "#,##0",
        4 => "#,##0.00",
        5 => "\"$\"#,##0_);(\"$\"#,##0)",
        6 => "\"$\"#,##0_);[Red](\"$\"#,##0)",
        7 => "\"$\"#,##0.00_);(\"$\"#,##0.00)",
        8 => "\"$\"#,##0.00_);[Red](\"$\"#,##0.00)",
        9 => "0%",
        10 => "0.00%",
        11 => "0.00E+00",
        12 => "# ?/?",
        13 => "# ??/??",
        14 => "mm-dd-yy",
        15 => "d-mmm-yy",
        16 => "d-mmm",
        17 => "mmm-yy",
        18 => "h:mm AM/PM",
        19 => "h:mm:ss AM/PM",
        20 => "h:mm",
        21 => "h:mm:ss",
        22 => "m/d/yy h:mm",
        37 => "#,##0_);(#,##0)",
        38 => "#,##0_);[Red](#,##0)",
        39 => "#,##0.00_);(#,##0.00)",
        40 => "#,##0.00_);[Red](#,##0.00)",
        41 => r#"_(* #,##0_);_(* \(#,##0\);_(* "-"_);_(@_)"#,
        42 => r#"_("$"* #,##0_);_("$"* \(#,##0\);_("$"* "-"_);_(@_)"#,
        43 => r#"_(* #,##0.00_);_(* \(#,##0.00\);_(* "-"??_);_(@_)"#,
        44 => r#"_("$"* #,##0.00_)_("$"* \(#,##0.00\)_("$"* "-"??_)_(@_)"#,
        45 => "mm:ss",
        46 => "[h]:mm:ss",
        47 => "mmss.0",
        48 => "##0.0E+0",
        49 => "@",
        _ => return None,
    })
}

/// Remove quoted literals and bracketed locale/colour groups, keeping `[h]`,
/// `[hh]`, `[m]`, `[mm]`, `[s]`, `[ss]` (openpyxl `STRIP_RE`).
fn strip_literals(fmt: &str) -> String {
    let chars: Vec<char> = fmt.chars().collect();
    let mut out = String::new();
    let mut i = 0;
    while i < chars.len() {
        let c = chars[i];
        if c == '"' {
            if let Some(end) = chars[i + 1..].iter().position(|&x| x == '"') {
                i += end + 2;
                continue;
            }
        } else if c == '[' {
            let rest: String = chars[i + 1..].iter().collect();
            let keep = ["h]", "hh]", "m]", "mm]", "s]", "ss]"]
                .iter()
                .any(|p| rest.starts_with(p));
            if !keep {
                if let Some(end) = chars[i + 1..].iter().position(|&x| x == ']') {
                    i += end + 2;
                    continue;
                }
            }
        }
        out.push(c);
        i += 1;
    }
    out
}

/// openpyxl `is_date_format`.
pub fn is_date_format(fmt: &str) -> bool {
    let first = fmt.split(';').next().unwrap_or_default();
    let stripped: Vec<char> = strip_literals(first).chars().collect();
    stripped.iter().enumerate().any(|(i, c)| {
        "dmhysDMHYS".contains(*c) && (i == 0 || !matches!(stripped[i - 1], '_' | '\\'))
    })
}

/// openpyxl `is_timedelta_format` (`TIMEDELTA_RE`, case-insensitive search).
pub fn is_timedelta_format(fmt: &str) -> bool {
    use std::sync::OnceLock;
    static RE: OnceLock<regex::Regex> = OnceLock::new();
    let re = RE.get_or_init(|| {
        regex::Regex::new(r"(?i)\[hh?\](:mm(:ss(\.0*)?)?)?|\[mm?\](:ss(\.0*)?)?|\[ss?\](\.0*)?")
            .expect("regex")
    });
    re.is_match(fmt.split(';').next().unwrap_or_default())
}

/// openpyxl `from_excel`. `Err` where Python raises (the cell becomes `#VALUE!`).
pub fn from_excel(value: f64, epoch1904: bool, timedelta: bool) -> Result<Value, ()> {
    if !value.is_finite() {
        return Err(());
    }
    if timedelta {
        let mut micros = timedelta_days_to_micros(value)?;
        let rest = micros.rem_euclid(1_000_000);
        if rest != 0 {
            // timedelta(seconds=total_seconds() // 1, microseconds=round(us, -3))
            let seconds = micros.div_euclid(1_000_000);
            let rounded = round_half_even_int(rest, 1000);
            micros = seconds * 1_000_000 + rounded;
        }
        return Ok(Value::Duration(Duration::from_micros(micros)));
    }
    let day = value.floor();
    let fraction = value - day;
    let millis = (fraction * 86_400.0 * 1000.0).round_ties_even() as i128;
    let diff = Duration::from_micros(millis * 1000);
    if (0.0..1.0).contains(&value) && diff.days == 0 {
        let secs = diff.seconds as u32;
        return Ok(Value::Time(Time {
            hour: secs / 3600,
            minute: secs / 60 % 60,
            second: secs % 60,
            micro: diff.micros as u32,
        }));
    }
    let mut day = day;
    let epoch = if epoch1904 {
        Date {
            year: 1904,
            month: 1,
            day: 1,
        }
    } else {
        Date {
            year: 1899,
            month: 12,
            day: 30,
        }
    };
    if value > 0.0 && value < 60.0 && !epoch1904 {
        day += 1.0;
    }
    if day.abs() > 1e10 {
        return Err(());
    }
    let base = DateTime {
        date: epoch,
        time: Time {
            hour: 0,
            minute: 0,
            second: 0,
            micro: 0,
        },
    };
    let shifted = base
        .add(Duration::from_micros(day as i128 * 86_400_000_000))
        .ok_or(())?;
    shifted.add(diff).map(Value::DateTime).ok_or(())
}

/// `timedelta(days=value)` total microseconds (CPython's accumulation).
fn timedelta_days_to_micros(value: f64) -> Result<i128, ()> {
    if value.abs() > 999_999_999.0 {
        return Err(());
    }
    let int_days = value.trunc();
    let frac_days = value - int_days;
    let mut total = int_days as i128 * 86_400_000_000;
    if frac_days == 0.0 {
        return Ok(total);
    }
    let us = 86_400_000_000.0 * frac_days;
    let int_us = us.trunc();
    let leftover = us - int_us;
    total += int_us as i128;
    let mut whole = leftover.round();
    if (whole - leftover).abs() == 0.5 {
        let odd = total.rem_euclid(2) as f64;
        whole = 2.0 * ((leftover + odd) * 0.5).round() - odd;
    }
    Ok(total + whole as i128)
}

/// Python `round(int, -3)`-style rounding of `value` to a multiple of `unit`.
fn round_half_even_int(value: i128, unit: i128) -> i128 {
    let q = value.div_euclid(unit);
    let r = value.rem_euclid(unit);
    let twice = r * 2;
    let q = if twice > unit || (twice == unit && q % 2 != 0) {
        q + 1
    } else {
        q
    };
    q * unit
}

/// openpyxl `from_ISO8601` (cells of type `d`).
pub fn from_iso8601(text: &str) -> Result<Value, ()> {
    use std::sync::OnceLock;
    static ISO: OnceLock<regex::Regex> = OnceLock::new();
    static DURATION: OnceLock<regex::Regex> = OnceLock::new();
    if text.is_empty() {
        return Ok(Value::None);
    }
    let iso = ISO.get_or_init(|| {
        regex::Regex::new(
            r"^(?P<date>(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2}))?T?(?P<time>(?P<hour>\d{2}):(?P<minute>\d{2})(:(?P<second>\d{2})(?P<microsecond>\.\d{1,3})?)?)?Z?",
        )
        .expect("regex")
    });
    if let Some(caps) = iso.captures(text) {
        if caps.get(0).is_some_and(|m| !m.as_str().is_empty())
            && (caps.name("date").is_some() || caps.name("time").is_some())
        {
            let num = |name: &str| {
                caps.name(name)
                    .and_then(|m| m.as_str().parse::<u32>().ok())
                    .unwrap_or(0)
            };
            let micro = caps
                .name("microsecond")
                .and_then(|m| m.as_str().parse::<f64>().ok())
                .map(|f| (f * 1_000_000.0) as u32)
                .unwrap_or(0);
            let time = Time {
                hour: num("hour"),
                minute: num("minute"),
                second: num("second"),
                micro,
            };
            if time.hour > 23 || time.minute > 59 || time.second > 59 {
                return Err(());
            }
            if caps.name("date").is_none() {
                return Ok(Value::Time(time));
            }
            let date = Date {
                year: num("year") as i32,
                month: num("month"),
                day: num("day"),
            };
            if date.year < 1
                || !(1..=12).contains(&date.month)
                || date.day < 1
                || from_ordinal(ordinal(date)) != Some(date)
            {
                return Err(());
            }
            if caps.name("time").is_none() {
                return Ok(Value::Date(date));
            }
            return Ok(Value::DateTime(DateTime { date, time }));
        }
    }
    let duration = DURATION.get_or_init(|| {
        regex::Regex::new(
            r"^PT((?P<hours>\d+)H)?((?P<minutes>\d+)M)?((?P<seconds>\d+(\.\d{1,3})?)S)?",
        )
        .expect("regex")
    });
    if let Some(caps) = duration.captures(text) {
        if caps.name("hours").is_some()
            || caps.name("minutes").is_some()
            || caps.name("seconds").is_some()
        {
            let num = |name: &str| {
                caps.name(name)
                    .and_then(|m| m.as_str().parse::<f64>().ok())
                    .unwrap_or(0.0)
            };
            let micros = ((num("hours") * 3600.0 + num("minutes") * 60.0 + num("seconds"))
                * 1_000_000.0)
                .round_ties_even();
            return Ok(Value::Duration(Duration::from_micros(micros as i128)));
        }
    }
    Err(())
}

/// v3 `format_computed_value`: a computed value as the Office-like grid shows it.
pub fn format_computed_value(value: &Value, number_format: &str) -> String {
    match value {
        Value::None => String::new(),
        Value::Date(d) => d.to_string(),
        Value::DateTime(d) => d.date.to_string(),
        Value::Bool(b) => if *b { "TRUE" } else { "FALSE" }.to_string(),
        Value::Int(_) | Value::Float(_) => {
            let number = value.py_float().unwrap_or(f64::NAN);
            if !number.is_finite() {
                return "#NUM!".to_string();
            }
            if number_format.contains('%') {
                let mut decimals = 0;
                if let Some((_, after)) = number_format.split_once('.') {
                    decimals = after.split('%').next().unwrap_or_default().chars().count();
                }
                return format!("{}%", py_fixed(number * 100.0, decimals, false));
            }
            let currency = ["$", "€", "£", "¥"]
                .into_iter()
                .find(|s| number_format.contains(s));
            let decimals = if number_format.contains(".00") || number_format.contains(".##") {
                2
            } else {
                0
            };
            if let Some(symbol) = currency {
                return format!("{symbol}{}", py_fixed(number, decimals, true));
            }
            if number_format.contains(',') {
                return py_fixed(number, decimals, true);
            }
            if number.fract() == 0.0 {
                return match value {
                    Value::Int(i) => i.to_string(),
                    _ if number == 0.0 => "0".to_string(),
                    _ => format!("{number:.0}"),
                };
            }
            py_general(number, 10)
        }
        other => other.py_str(),
    }
}

/// Number conversion for raw `<v>` text (openpyxl `_cast_number`).
pub fn cast_number(text: &str) -> Option<Value> {
    if text.contains(['.', 'E', 'e']) {
        parse_py_float(text).map(Value::Float)
    } else {
        let trimmed = text.trim();
        match trimmed.replace('_', "").parse::<i128>() {
            Ok(i) => Some(Value::Int(i)),
            Err(_) => parse_py_float(text).map(Value::Float),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn detects_dates_like_openpyxl() {
        assert!(is_date_format("mm-dd-yy"));
        assert!(is_date_format("yyyy-mm-dd h:mm"));
        assert!(!is_date_format("General"));
        assert!(!is_date_format("0.00%"));
        assert!(!is_date_format("\"$\"#,##0.00"));
        assert!(!is_date_format("[Red]0.00"));
        assert!(is_date_format("[h]:mm:ss"));
        assert!(!is_date_format("#,##0_);[Red](#,##0)"));
        assert!(!is_date_format(r"0\d"));
        assert!(is_timedelta_format("[h]:mm:ss"));
        assert!(!is_timedelta_format("h:mm:ss"));
    }

    #[test]
    fn converts_serials_like_openpyxl() {
        assert_eq!(
            from_excel(45000.0, false, false).unwrap().py_str(),
            "2023-03-15 00:00:00"
        );
        assert_eq!(
            from_excel(0.5625, false, false).unwrap().py_str(),
            "13:30:00"
        );
        assert_eq!(from_excel(0.0, false, false).unwrap().py_str(), "00:00:00");
        assert_eq!(
            from_excel(59.0, false, false).unwrap().py_str(),
            "1900-02-28 00:00:00"
        );
        assert_eq!(
            from_excel(61.0, false, false).unwrap().py_str(),
            "1900-03-01 00:00:00"
        );
        assert_eq!(
            from_excel(1.0416666666666667, false, true)
                .unwrap()
                .py_str(),
            "1 day, 1:00:00"
        );
        assert!(from_excel(1e12, false, false).is_err());
        assert_eq!(
            from_iso8601("2024-03-05T10:00:00").unwrap().py_str(),
            "2024-03-05 10:00:00"
        );
        assert_eq!(from_iso8601("2024-03-05").unwrap().py_str(), "2024-03-05");
    }

    #[test]
    fn formats_like_v3() {
        assert_eq!(format_computed_value(&Value::Float(0.125), "0.0%"), "12.5%");
        assert_eq!(
            format_computed_value(&Value::Float(1234.5), "\"$\"#,##0.00"),
            "$1,234.50"
        );
        assert_eq!(
            format_computed_value(&Value::Float(1234567.891), "#,##0"),
            "1,234,568"
        );
        assert_eq!(
            format_computed_value(&Value::Float(1e20), "General"),
            "100000000000000000000"
        );
        assert_eq!(format_computed_value(&Value::Float(0.1 + 0.2), ""), "0.3");
        assert_eq!(
            format_computed_value(&Value::Float(f64::INFINITY), ""),
            "#NUM!"
        );
        assert_eq!(format_computed_value(&Value::Int(-42), ""), "-42");
        assert_eq!(format_computed_value(&Value::Bool(true), ""), "TRUE");
        assert_eq!(format_computed_value(&Value::Float(-0.0), ""), "0");
    }
}
