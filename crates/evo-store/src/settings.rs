//! App preferences shared by every window and the engine (key → JSON value).

use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{Map, Value};

use crate::chats::now_ms;
use crate::DbError;

pub fn get(conn: &Connection, key: &str) -> Result<Option<Value>, DbError> {
    let text: Option<String> = conn
        .query_row(
            "SELECT value_json FROM app_settings WHERE key = ?1",
            [key],
            |row| row.get(0),
        )
        .optional()?;
    Ok(text.and_then(|text| serde_json::from_str(&text).ok()))
}

/// Set `key`; a JSON `null` removes it.
pub fn set(conn: &Connection, key: &str, value: &Value) -> Result<(), DbError> {
    if value.is_null() {
        conn.execute("DELETE FROM app_settings WHERE key = ?1", [key])?;
    } else {
        conn.execute(
            "INSERT INTO app_settings (key, value_json, updated_at) VALUES (?1, ?2, ?3)
             ON CONFLICT (key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at",
            params![key, value.to_string(), now_ms()],
        )?;
    }
    Ok(())
}

pub fn all(conn: &Connection) -> Result<Map<String, Value>, DbError> {
    let mut statement = conn.prepare("SELECT key, value_json FROM app_settings ORDER BY key")?;
    let rows = statement.query_map([], |row| {
        Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
    })?;
    let mut out = Map::new();
    for row in rows {
        let (key, text) = row?;
        if let Ok(value) = serde_json::from_str(&text) {
            out.insert(key, value);
        }
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn roundtrip() {
        let dir = tempfile::tempdir().unwrap();
        let conn = crate::open_at(&dir.path().join("evo.db")).unwrap();
        set(&conn, "sidebar.width", &serde_json::json!(280)).unwrap();
        assert_eq!(
            get(&conn, "sidebar.width").unwrap(),
            Some(serde_json::json!(280))
        );
        set(&conn, "sidebar.width", &Value::Null).unwrap();
        assert!(all(&conn).unwrap().is_empty());
    }
}
