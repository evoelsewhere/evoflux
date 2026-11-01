//! UTC calendar helpers for the `datetime` arithmetic in
//! app/services/observability_service.py (no time-zone data, no `chrono`).

use std::time::{SystemTime, UNIX_EPOCH};

pub const MICROS_PER_SECOND: i64 = 1_000_000;
pub const MICROS_PER_HOUR: i64 = 3_600 * MICROS_PER_SECOND;
pub const MICROS_PER_DAY: i64 = 24 * MICROS_PER_HOUR;

/// `datetime.now(timezone.utc)` as microseconds since the epoch.
pub fn now_micros() -> i64 {
    match SystemTime::now().duration_since(UNIX_EPOCH) {
        Ok(elapsed) => i64::try_from(elapsed.as_micros()).unwrap_or(i64::MAX),
        Err(_) => 0,
    }
}

/// `(year, month, day)` of a day count since 1970-01-01 (proleptic Gregorian).
fn civil_from_days(days: i64) -> (i64, i64, i64) {
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1_460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = yoe + era * 400 + i64::from(month <= 2);
    (year, month, day)
}

struct Parts {
    year: i64,
    month: i64,
    day: i64,
    hour: i64,
    minute: i64,
    second: i64,
    micro: i64,
}

fn parts(micros: i64) -> Parts {
    let days = micros.div_euclid(MICROS_PER_DAY);
    let in_day = micros.rem_euclid(MICROS_PER_DAY);
    let (year, month, day) = civil_from_days(days);
    Parts {
        year,
        month,
        day,
        hour: in_day / MICROS_PER_HOUR,
        minute: in_day % MICROS_PER_HOUR / (60 * MICROS_PER_SECOND),
        second: in_day % (60 * MICROS_PER_SECOND) / MICROS_PER_SECOND,
        micro: in_day % MICROS_PER_SECOND,
    }
}

/// `datetime.isoformat()` of a UTC instant: fraction only when non-zero, `+00:00` suffix.
pub fn isoformat(micros: i64) -> String {
    let p = parts(micros);
    let mut text = format!(
        "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}",
        p.year, p.month, p.day, p.hour, p.minute, p.second
    );
    if p.micro != 0 {
        text.push_str(&format!(".{:06}", p.micro));
    }
    text.push_str("+00:00");
    text
}

/// `strftime("%Y-%m-%d-%H")`, the key compared with a partition file's stem.
pub fn partition_key(micros: i64) -> String {
    let p = parts(micros);
    format!("{:04}-{:02}-{:02}-{:02}", p.year, p.month, p.day, p.hour)
}

/// `strftime("%Y-%m-%d")`.
pub fn day_key(micros: i64) -> String {
    let p = parts(micros);
    format!("{:04}-{:02}-{:02}", p.year, p.month, p.day)
}

/// `strftime("%Y-%m-%dT%H:00:00Z")` (hour buckets) or `%Y-%m-%dT00:00:00Z` (day buckets).
pub fn bucket_key(micros: i64, hourly: bool) -> String {
    let p = parts(micros);
    if hourly {
        format!(
            "{:04}-{:02}-{:02}T{:02}:00:00Z",
            p.year, p.month, p.day, p.hour
        )
    } else {
        format!("{:04}-{:02}-{:02}T00:00:00Z", p.year, p.month, p.day)
    }
}

/// Start of the hour or day containing `micros`.
pub fn floor_bucket(micros: i64, hourly: bool) -> i64 {
    let unit = if hourly {
        MICROS_PER_HOUR
    } else {
        MICROS_PER_DAY
    };
    micros.div_euclid(unit) * unit
}

#[cfg(test)]
mod tests {
    use super::*;

    // 2026-10-30T12:34:56.789012Z
    const SAMPLE: i64 = 1_793_363_696_789_012;

    #[test]
    fn formats_like_python_strftime() {
        assert_eq!(partition_key(SAMPLE), "2026-10-30-12");
        assert_eq!(day_key(SAMPLE), "2026-10-30");
        assert_eq!(bucket_key(SAMPLE, true), "2026-10-30T12:00:00Z");
        assert_eq!(bucket_key(SAMPLE, false), "2026-10-30T00:00:00Z");
    }

    #[test]
    fn isoformat_keeps_the_fraction_only_when_present() {
        assert_eq!(isoformat(SAMPLE), "2026-10-30T12:34:56.789012+00:00");
        assert_eq!(isoformat(SAMPLE - 789_012), "2026-10-30T12:34:56+00:00");
        assert_eq!(isoformat(0), "1970-01-01T00:00:00+00:00");
    }

    #[test]
    fn handles_leap_days_and_year_ends() {
        // 2024-02-29T23:59:59Z and 2024-12-31T00:00:00Z
        assert_eq!(day_key(1_709_251_199 * MICROS_PER_SECOND), "2024-02-29");
        assert_eq!(day_key(1_735_603_200 * MICROS_PER_SECOND), "2024-12-31");
        assert_eq!(day_key(1_709_251_200 * MICROS_PER_SECOND), "2024-03-01");
    }

    #[test]
    fn civil_dates_match_python_across_centuries() {
        for (year, month, day, days) in [
            (1970, 1, 1, 0),
            (1969, 12, 31, -1),
            (1900, 2, 28, -25509),
            (1900, 3, 1, -25508),
            (2000, 2, 29, 11016),
            (2000, 3, 1, 11017),
            (2100, 2, 28, 47540),
            (2100, 3, 1, 47541),
            (2400, 2, 29, 157113),
            (2400, 3, 1, 157114),
            (2026, 10, 30, 20756),
            (2023, 12, 31, 19722),
            (2024, 1, 1, 19723),
            (1999, 12, 31, 10956),
        ] {
            assert_eq!(civil_from_days(days), (year, month, day), "{days}");
        }
    }

    #[test]
    fn floors_to_the_hour_and_the_day() {
        assert_eq!(
            bucket_key(floor_bucket(SAMPLE, true), true),
            "2026-10-30T12:00:00Z"
        );
        assert_eq!(floor_bucket(SAMPLE, true) % MICROS_PER_HOUR, 0);
        assert_eq!(floor_bucket(SAMPLE, false) % MICROS_PER_DAY, 0);
        assert_eq!(floor_bucket(-1, true), -MICROS_PER_HOUR);
    }

    #[test]
    fn now_is_after_2026() {
        assert!(now_micros() > SAMPLE - 1_000 * MICROS_PER_DAY);
    }
}
