//! Port of app/services/remote_use_service.py::claim.
use crate::db::{rowid, Db, DbError};
use rusqlite::{params, OptionalExtension};
use std::time::{SystemTime, UNIX_EPOCH};

#[derive(Debug)]
pub enum ClaimError {
    Conflict(serde_json::Value),
    Database(DbError),
    InvalidLogin,
}

pub async fn claim(db: &Db, login: &str, device_label: Option<&str>) -> Result<(), ClaimError> {
    let login = python_strip(login).to_owned();
    if login.is_empty() {
        return Err(ClaimError::InvalidLogin);
    }
    let label = device_label
        .map(python_strip)
        .filter(|v| !v.is_empty())
        .map(|v| v.chars().take(128).collect::<String>());
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| ClaimError::InvalidLogin)?;
    let seconds = now.as_secs() as i64;
    let micros = now.subsec_micros();
    let millis = now.as_millis() as u64;
    let id = format!(
        "{:016x}{:016x}",
        (millis << 16) | 0x7000 | (fastrand::u64(..) & 0xfff),
        (fastrand::u64(..) & 0x3fff_ffff_ffff_ffff) | 0x8000_0000_0000_0000
    );
    let timestamp = utc_timestamp(seconds, micros);
    let expires = utc_timestamp(seconds + 1800, micros);
    let result = db.write(move |tx| {
        tx.execute("UPDATE remote_use_sessions SET released_at=?1 WHERE released_at IS NULL AND idle_expires_at <= ?1", [&timestamp])?;
        let holder: Option<(String, Option<String>, String, String, String)> = tx.query_row("SELECT user_login, device_label, claimed_at, last_seen_at, id FROM remote_use_sessions WHERE released_at IS NULL AND idle_expires_at > ?1 ORDER BY claimed_at DESC LIMIT 1", [&timestamp], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?, r.get(4)?))).optional()?;
        if let Some((user, device, claimed, seen, holder_id)) = holder {
            if user == login && device == label {
                tx.execute("UPDATE remote_use_sessions SET last_seen_at=?1, idle_expires_at=?2 WHERE id=?3", params![timestamp, expires, holder_id])?;
                return Ok(None);
            }
            let iso = |v: String| { let v = v.replace(' ', "T"); format!("{}+00:00", v.strip_suffix(".000000").unwrap_or(&v)) };
            let detail = format!("remote session lock is held by {} ({})", user, device.as_deref().filter(|s| !s.is_empty()).unwrap_or("unknown device"));
            return Ok(Some(serde_json::json!({"detail": detail, "current": {"user_login": user, "device_label": device, "claimed_at": iso(claimed), "last_seen_at": iso(seen)}, "live_window_minutes": 30})));
        }
        rowid::insert(tx, "remote_use_sessions", &["id", "user_login", "device_label", "claimed_at", "last_seen_at", "released_at", "idle_expires_at"], &[&id, &login, &label, &timestamp, &timestamp, &None::<String>, &expires])?;
        Ok(None)
    }).await.map_err(ClaimError::Database)?;
    match result {
        Some(body) => Err(ClaimError::Conflict(body)),
        None => Ok(()),
    }
}

// UTC civil date from Unix seconds; all inputs are captured before the write.
fn utc_timestamp(seconds: i64, micros: u32) -> String {
    let days = seconds.div_euclid(86400);
    let day_seconds = seconds.rem_euclid(86400);
    let z = days + 719468;
    let era = z.div_euclid(146097);
    let doe = z - era * 146097;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let mut year = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = mp + if mp < 10 { 3 } else { -9 };
    year += i64::from(month <= 2);
    let hour = day_seconds / 3600;
    let minute = day_seconds % 3600 / 60;
    let second = day_seconds % 60;
    format!("{year:04}-{month:02}-{day:02} {hour:02}:{minute:02}:{second:02}.{micros:06}")
}

fn python_strip(value: &str) -> &str {
    value.trim_matches(|c: char| c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c))
}
