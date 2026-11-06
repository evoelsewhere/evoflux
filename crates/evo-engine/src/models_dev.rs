//! The engine's copy of the models.dev database.
//!
//! [`current`] is what provider declarations read: the document last stored
//! in the application database (`models_dev_cache`), else the snapshot
//! bundled in evo-runtime. [`refresh`] revalidates it against
//! https://models.dev/api.json with an ETag and stores what changed; the RPC
//! host runs it in the background at startup and swaps provider runtimes
//! when it brings new data.

use std::sync::{Arc, RwLock};
use std::time::Duration;

use evo_runtime::models_dev::{ModelsDev, MODELS_DEV_URL};

/// Revalidate at most this often.
pub const REFRESH_INTERVAL_SECS: i64 = 6 * 60 * 60;
const FETCH_TIMEOUT: Duration = Duration::from_secs(20);

fn now() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}

fn slot() -> &'static RwLock<Option<Arc<ModelsDev>>> {
    static SLOT: RwLock<Option<Arc<ModelsDev>>> = RwLock::new(None);
    &SLOT
}

/// Where the data in use came from, for the settings page.
#[derive(Clone, Debug, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Status {
    pub source: &'static str,
    pub fetched_at: Option<i64>,
    pub checked_at: Option<i64>,
    pub model_count: usize,
}

fn load_cached() -> Option<(ModelsDev, i64, i64)> {
    let db = crate::app_db::open().ok()?;
    let (body, fetched_at, checked_at): (String, i64, i64) = db
        .query_row(
            "SELECT body, fetched_at, checked_at FROM models_dev_cache WHERE singleton = 1",
            [],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
        )
        .ok()?;
    ModelsDev::parse(&body)
        .ok()
        .map(|parsed| (parsed, fetched_at, checked_at))
}

/// The database in use (cached download, else the bundled snapshot).
pub fn current() -> Arc<ModelsDev> {
    if let Some(db) = slot().read().unwrap_or_else(|e| e.into_inner()).clone() {
        return db;
    }
    let db = load_cached()
        .map(|(db, _, _)| Arc::new(db))
        .unwrap_or_else(ModelsDev::bundled);
    *slot().write().unwrap_or_else(|e| e.into_inner()) = Some(db.clone());
    db
}

pub fn status() -> Status {
    let model_count = current().model_count();
    let row = crate::app_db::open().ok().and_then(|db| {
        db.query_row(
            "SELECT fetched_at, checked_at FROM models_dev_cache WHERE singleton = 1",
            [],
            |row| Ok((row.get::<_, i64>(0)?, row.get::<_, i64>(1)?)),
        )
        .ok()
    });
    Status {
        source: if row.is_some() { "models.dev" } else { "bundled" },
        fetched_at: row.map(|(fetched, _)| fetched),
        checked_at: row.map(|(_, checked)| checked),
        model_count,
    }
}

fn due() -> bool {
    crate::app_db::open()
        .ok()
        .and_then(|db| {
            db.query_row(
                "SELECT checked_at FROM models_dev_cache WHERE singleton = 1",
                [],
                |row| row.get::<_, i64>(0),
            )
            .ok()
        })
        .map_or(true, |checked| now() - checked >= REFRESH_INTERVAL_SECS)
}

/// Revalidate the cached document. Returns `Ok(true)` when new data was
/// stored and is now [`current`]; `Ok(false)` when it was unchanged or not
/// due (unless `force`).
pub async fn refresh(force: bool) -> Result<bool, String> {
    if !force && !due() {
        return Ok(false);
    }
    let etag: Option<String> = crate::app_db::open()
        .ok()
        .and_then(|db| {
            db.query_row(
                "SELECT etag FROM models_dev_cache WHERE singleton = 1",
                [],
                |row| row.get(0),
            )
            .ok()
        })
        .flatten();
    let client = reqwest::Client::builder()
        .timeout(FETCH_TIMEOUT)
        .build()
        .map_err(|_| "could not create an HTTP client".to_string())?;
    let mut request = client
        .get(MODELS_DEV_URL)
        .header("user-agent", evo_ai::http::user_agent());
    if let Some(etag) = &etag {
        request = request.header("if-none-match", etag);
    }
    let response = request
        .send()
        .await
        .map_err(|error| format!("could not reach models.dev: {error}"))?;
    let at = now();
    if response.status() == reqwest::StatusCode::NOT_MODIFIED {
        if let Ok(db) = crate::app_db::open() {
            let _ = db.execute(
                "UPDATE models_dev_cache SET checked_at = ?1 WHERE singleton = 1",
                [at],
            );
        }
        return Ok(false);
    }
    if !response.status().is_success() {
        return Err(format!("models.dev answered {}", response.status()));
    }
    let new_etag = response
        .headers()
        .get("etag")
        .and_then(|value| value.to_str().ok())
        .map(str::to_string);
    let body = response
        .text()
        .await
        .map_err(|error| format!("models.dev download failed: {error}"))?;
    let parsed = ModelsDev::parse(&body)?;
    let count = parsed.model_count() as i64;
    let db = crate::app_db::open().map_err(|error| error.to_string())?;
    db.execute(
        "INSERT INTO models_dev_cache (singleton, body, etag, fetched_at, checked_at, model_count)
         VALUES (1, ?1, ?2, ?3, ?3, ?4)
         ON CONFLICT (singleton) DO UPDATE SET body = excluded.body, etag = excluded.etag,
           fetched_at = excluded.fetched_at, checked_at = excluded.checked_at,
           model_count = excluded.model_count",
        rusqlite::params![body, new_etag, at, count],
    )
    .map_err(|error| error.to_string())?;
    *slot().write().unwrap_or_else(|e| e.into_inner()) = Some(Arc::new(parsed));
    Ok(true)
}
