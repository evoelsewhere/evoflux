//! The app database on this machine (`~/.evo/agent/evo.db`, via `evo-store`)
//! and the run log written into it.
//!
//! The shell owns the sidebar's data (workspaces, chats, their totals), shared
//! settings and the log; the engines it starts write each chat's transcript
//! into the same file (`--session-db`). Everything here is a thin command layer
//! over `evo_store`, so the schema and its migrations live in one place.

use std::path::PathBuf;
use std::sync::mpsc::{self, RecvTimeoutError, Sender};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use evo_store::chats::{self, Chat, ChatPatch, NewChat, TurnRecord, Workspace};
use evo_store::logs::{self, LogEntry, LogQuery, LogStats, NewLog};
use evo_store::rusqlite::Connection;
use serde::Serialize;
use serde_json::{Map, Value};
use tauri::{AppHandle, State};
use tauri_plugin_opener::OpenerExt;

pub struct Db {
    pub path: PathBuf,
    conn: Mutex<Connection>,
    logger: Sender<NewLog>,
}

impl Db {
    /// Open (creating and migrating) the database and start the log writer.
    pub fn open() -> Result<Self, String> {
        let path = evo_store::db_path().map_err(|e| e.to_string())?;
        let conn = evo_store::open_at(&path).map_err(|e| e.to_string())?;
        // Transcripts of chats that were never sent (a new chat's engine
        // creates its session up front) and of chats removed while their
        // engine still ran. No engine runs yet, so nothing is in use.
        let _ = conn.execute("DELETE FROM sessions WHERE id NOT IN (SELECT id FROM chats)", []);
        let logger = spawn_log_writer(path.clone())?;
        Ok(Self {
            path,
            conn: Mutex::new(conn),
            logger,
        })
    }

    pub(crate) fn with<T>(&self, f: impl FnOnce(&mut Connection) -> Result<T, evo_store::DbError>) -> Result<T, String> {
        let mut conn = self.conn.lock().map_err(|_| "database lock poisoned".to_string())?;
        f(&mut conn).map_err(|e| e.to_string())
    }

    /// Queue one log entry; written within half a second, off this thread.
    pub fn log(&self, entry: NewLog) {
        if cfg!(debug_assertions) {
            eprintln!("[{}] {} {}", entry.level, entry.source, entry.message);
        }
        let _ = self.logger.send(entry);
    }
}

/// Writes queued log entries in batches on its own connection and prunes the
/// log at startup and hourly, so logging never blocks a command or the UI.
fn spawn_log_writer(path: PathBuf) -> Result<Sender<NewLog>, String> {
    let (tx, rx) = mpsc::channel::<NewLog>();
    let mut conn = evo_store::open_at(&path).map_err(|e| e.to_string())?;
    std::thread::Builder::new()
        .name("evo-log-writer".into())
        .spawn(move || {
            let prune = |conn: &Connection| {
                let _ = logs::prune(conn, logs::DEFAULT_MAX_AGE_MS, logs::DEFAULT_MAX_ROWS);
            };
            prune(&conn);
            let mut pruned_at = Instant::now();
            let mut batch = Vec::new();
            loop {
                match rx.recv_timeout(Duration::from_millis(500)) {
                    Ok(entry) => {
                        batch.push(entry);
                        // Drain what is already queued so a burst is one transaction.
                        while let Ok(entry) = rx.try_recv() {
                            batch.push(entry);
                            if batch.len() >= 500 {
                                break;
                            }
                        }
                    }
                    Err(RecvTimeoutError::Timeout) => {}
                    Err(RecvTimeoutError::Disconnected) => {
                        let _ = logs::append(&mut conn, &batch);
                        break;
                    }
                }
                if !batch.is_empty() {
                    if let Err(error) = logs::append(&mut conn, &batch) {
                        eprintln!("evo: could not write the log: {error}");
                    }
                    batch.clear();
                }
                if pruned_at.elapsed() > Duration::from_secs(3600) {
                    prune(&conn);
                    pruned_at = Instant::now();
                }
            }
        })
        .map_err(|e| e.to_string())?;
    Ok(tx)
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DbInfo {
    path: String,
    dir: String,
    size_bytes: u64,
    schema_version: i64,
    logs: LogStats,
}

#[tauri::command]
pub fn db_info(db: State<'_, Db>) -> Result<DbInfo, String> {
    let size = |suffix: &str| {
        std::fs::metadata(format!("{}{suffix}", db.path.display()))
            .map(|m| m.len())
            .unwrap_or(0)
    };
    let (schema_version, stats) = db.with(|conn| {
        let version: i64 = conn.query_row("PRAGMA user_version", [], |row| row.get(0))?;
        Ok((version, logs::stats(conn)?))
    })?;
    Ok(DbInfo {
        path: db.path.display().to_string(),
        dir: db
            .path
            .parent()
            .map(|dir| dir.display().to_string())
            .unwrap_or_default(),
        size_bytes: size("") + size("-wal"),
        schema_version,
        logs: stats,
    })
}

/// Open the folder that holds the database, auth and logs in the file manager.
#[tauri::command]
pub fn db_reveal(app: AppHandle, db: State<'_, Db>) -> Result<(), String> {
    app.opener()
        .reveal_item_in_dir(&db.path)
        .map_err(|e| e.to_string())
}

// ── Workspaces and chats ────────────────────────────────────────────────────

#[tauri::command]
pub fn workspaces_list(db: State<'_, Db>) -> Result<Vec<Workspace>, String> {
    db.with(|conn| chats::list_workspaces(conn))
}

#[tauri::command]
pub fn workspace_ensure(db: State<'_, Db>, path: String) -> Result<Workspace, String> {
    db.with(|conn| chats::ensure_workspace(conn, &path))
}

#[tauri::command]
pub fn workspace_set_collapsed(db: State<'_, Db>, id: String, collapsed: bool) -> Result<(), String> {
    db.with(|conn| chats::set_workspace_collapsed(conn, &id, collapsed))
}

/// Remove a workspace with its chats; returns the removed chat ids.
#[tauri::command]
pub fn workspace_remove(db: State<'_, Db>, id: String) -> Result<Vec<String>, String> {
    let removed = db.with(|conn| chats::remove_workspace(conn, &id))?;
    db.log(NewLog::new("info", "shell", format!("removed workspace {id} with {} chats", removed.len())));
    Ok(removed)
}

#[tauri::command]
pub fn chats_list(db: State<'_, Db>, archived: bool) -> Result<Vec<Chat>, String> {
    db.with(|conn| chats::list_chats(conn, archived))
}

#[tauri::command]
pub fn chats_search(db: State<'_, Db>, query: String) -> Result<Vec<Chat>, String> {
    db.with(|conn| chats::search_chats(conn, &query, 50))
}

#[tauri::command]
pub fn chat_create(db: State<'_, Db>, chat: NewChat) -> Result<Chat, String> {
    db.with(|conn| chats::create_chat(conn, &chat))
}

#[tauri::command]
pub fn chat_update(db: State<'_, Db>, id: String, patch: ChatPatch) -> Result<Option<Chat>, String> {
    db.with(|conn| chats::update_chat(conn, &id, &patch))
}

/// Copy chat `source` (folder, model, whole transcript) as a new chat `id`.
#[tauri::command]
pub fn chat_fork(db: State<'_, Db>, source: String, id: String, title: String) -> Result<Option<Chat>, String> {
    let chat = db.with(|conn| chats::fork_chat(conn, &source, &id, &title))?;
    db.log(NewLog::new("info", "shell", format!("forked chat {source}")).chat(Some(&id)));
    Ok(chat)
}

/// The worktree a chat works in, or (`None`) its workspace folder again.
#[tauri::command]
pub fn chat_set_worktree(db: State<'_, Db>, id: String, worktree_path: Option<String>) -> Result<Option<Chat>, String> {
    db.with(|conn| chats::set_worktree(conn, &id, worktree_path.as_deref()))
}

/// Link a chat under another (nested sessions), or detach it with `None`.
#[tauri::command]
pub fn chat_set_parent(db: State<'_, Db>, id: String, parent_chat_id: Option<String>) -> Result<Option<Chat>, String> {
    db.with(|conn| chats::set_parent(conn, &id, parent_chat_id.as_deref()))
}

/// Move a chat to another workspace (`None`: "This computer").
#[tauri::command]
pub fn chat_move(db: State<'_, Db>, id: String, workspace_id: Option<String>) -> Result<Option<Chat>, String> {
    db.with(|conn| chats::move_chat(conn, &id, workspace_id.as_deref()))
}

#[tauri::command]
pub fn chat_record_turn(db: State<'_, Db>, id: String, turn: TurnRecord) -> Result<Option<Chat>, String> {
    db.with(|conn| chats::record_turn(conn, &id, &turn))
}

/// Delete a chat and its transcript. Stop its engine first.
#[tauri::command]
pub fn chat_delete(db: State<'_, Db>, id: String) -> Result<(), String> {
    db.with(|conn| chats::delete_chat(conn, &id))?;
    db.log(NewLog::new("info", "shell", "deleted chat").chat(Some(&id)));
    Ok(())
}

// ── Settings ────────────────────────────────────────────────────────────────

#[tauri::command]
pub fn settings_all(db: State<'_, Db>) -> Result<Map<String, Value>, String> {
    db.with(|conn| evo_store::settings::all(conn))
}

#[tauri::command]
pub fn settings_set(db: State<'_, Db>, key: String, value: Value) -> Result<(), String> {
    db.with(|conn| evo_store::settings::set(conn, &key, &value))
}

// ── Logs ────────────────────────────────────────────────────────────────────

#[tauri::command]
pub fn logs_append(db: State<'_, Db>, entries: Vec<NewLog>) {
    for entry in entries {
        db.log(entry);
    }
}

#[tauri::command]
pub fn logs_query(db: State<'_, Db>, query: LogQuery) -> Result<Vec<LogEntry>, String> {
    db.with(|conn| logs::query(conn, &query))
}

#[tauri::command]
pub fn logs_clear(db: State<'_, Db>) -> Result<usize, String> {
    db.with(|conn| logs::clear(conn))
}

/// Write the matching entries to `<agent dir>/logs/evo-<time>.log` and show
/// the file in the file manager. Returns its path.
#[tauri::command]
pub fn logs_export(app: AppHandle, db: State<'_, Db>, query: LogQuery) -> Result<String, String> {
    let text = db.with(|conn| logs::export_text(conn, &query))?;
    let dir = db
        .path
        .parent()
        .map(|dir| dir.join("logs"))
        .ok_or("no log folder")?;
    std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    let file = dir.join(format!("evo-{}.log", chats::now_ms()));
    std::fs::write(&file, text).map_err(|e| e.to_string())?;
    let _ = app.opener().reveal_item_in_dir(&file);
    Ok(file.display().to_string())
}
