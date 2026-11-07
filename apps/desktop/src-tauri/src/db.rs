//! The app database on this machine (`~/.evo/agent/evo.db`, via `evo-store`),
//! the run log written into it, and the chats' transcript files.
//!
//! The shell owns the sidebar's data (workspaces, chats, their totals and
//! search text), shared settings and the log. Each chat's transcript is a file
//! of its own (`~/.evo/agent/transcripts/<chat id>.db`), written only by the
//! engine running that chat (`--session-db`, ADR 0007); the shell reads those
//! files to search and fork chats and removes them with their chat, after
//! stopping the chat's engine. Everything here is a thin command layer over
//! `evo_store`, so the schema, its migrations and the file rules live in one
//! place.

use std::path::PathBuf;
use std::sync::mpsc::{self, RecvTimeoutError, Sender};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use evo_store::chats::{self, Chat, ChatPatch, NewChat, TurnRecord, Workspace};
use evo_store::logs::{self, LogEntry, LogQuery, LogStats, NewLog};
use evo_store::rusqlite::Connection;
use evo_store::transcripts;
use evo_store::usage::{self, UsageEvent, UsageQuery, UsageSummary};
use serde::Serialize;
use serde_json::{json, Map, Value};
use tauri::{AppHandle, Manager, State};
use tauri_plugin_opener::OpenerExt;

use crate::engine::EngineState;

pub struct Db {
    pub path: PathBuf,
    /// `~/.evo/agent/transcripts`: one transcript file per chat.
    pub transcripts: PathBuf,
    conn: Mutex<Connection>,
    logger: Sender<NewLog>,
}

impl Db {
    /// Open (creating and migrating) the database, put the transcript files
    /// in order, and start the log writer. Runs before any engine starts.
    pub fn open() -> Result<Self, String> {
        let path = evo_store::db_path().map_err(|e| e.to_string())?;
        let transcripts = transcripts::dir().map_err(|e| e.to_string())?;
        let mut conn = evo_store::open_at(&path).map_err(|e| e.to_string())?;
        let notes = tidy_transcripts(&mut conn, &transcripts);
        let logger = spawn_log_writer(path.clone())?;
        let db = Self {
            path,
            transcripts,
            conn: Mutex::new(conn),
            logger,
        };
        for note in notes {
            db.log(note);
        }
        Ok(db)
    }

    pub(crate) fn with<T>(&self, f: impl FnOnce(&mut Connection) -> Result<T, evo_store::DbError>) -> Result<T, String> {
        let mut conn = self.conn.lock().map_err(|_| "database lock poisoned".to_string())?;
        f(&mut conn).map_err(|e| e.to_string())
    }

    /// Chat `id`'s transcript file.
    pub fn transcript(&self, id: &str) -> Result<PathBuf, String> {
        transcripts::path_in(&self.transcripts, id).map_err(|e| e.to_string())
    }

    /// The transcript file to start chat `id`'s engine on. When `evo.db` still
    /// holds the chat's transcript from an older build (moving it at startup
    /// failed), it is moved now; if that fails too the engine must not start,
    /// or it would begin an empty transcript beside the real one.
    pub fn transcript_for_engine(&self, id: &str) -> Result<PathBuf, String> {
        let path = self.transcript(id)?;
        if self.with(|conn| transcripts::has_legacy(conn, id))? {
            let moved = self.with(|conn| transcripts::adopt_legacy(conn, &self.transcripts));
            if let Err(error) = &moved {
                self.log(NewLog::new("error", "db", format!("could not move the transcript out of evo.db: {error}")).chat(Some(id)));
            }
            if self.with(|conn| transcripts::has_legacy(conn, id))? {
                return Err(format!(
                    "this chat's transcript is still in {} and could not be moved to {}",
                    self.path.display(),
                    path.display()
                ));
            }
        }
        Ok(path)
    }

    /// Queue one log entry; written within half a second, off this thread.
    pub fn log(&self, entry: NewLog) {
        if cfg!(debug_assertions) {
            eprintln!("[{}] {} {}", entry.level, entry.source, entry.message);
        }
        let _ = self.logger.send(entry);
    }

    /// Remove chat `id`'s transcript file. Stop its engine first: a file still
    /// in use stays, and the startup sweep removes it next time.
    pub fn remove_transcript(&self, id: &str) {
        let removed = self
            .transcript(id)
            .and_then(|path| transcripts::remove(&path).map_err(|e| e.to_string()));
        if let Err(error) = removed {
            self.log(
                NewLog::new("warn", "db", format!("transcript not removed yet (removed at next start): {error}"))
                    .chat(Some(id)),
            );
        }
    }
}

/// Before any engine runs: move the transcripts older builds kept in `evo.db`
/// into their own files, then remove the files of chats that no longer exist
/// (drafts that never got a prompt, chats deleted while their file was in
/// use) and partial files a crash left. Returns what to log; a failure here
/// is logged, never fatal (a chat whose transcript could not be moved is
/// refused an engine, see [`Db::transcript_for_engine`]).
fn tidy_transcripts(conn: &mut Connection, dir: &std::path::Path) -> Vec<NewLog> {
    let mut notes = Vec::new();
    match transcripts::adopt_legacy(conn, dir) {
        Ok(adopted) => {
            let moved = adopted.moved.len() + adopted.already.len() + adopted.conflicts.len();
            if moved > 0 {
                notes.push(
                    NewLog::new("info", "db", format!("moved {moved} chat transcripts out of evo.db into {}", dir.display()))
                        .data(json!({ "moved": adopted.moved, "already": adopted.already, "dropped": adopted.dropped })),
                );
                // Give the space back once; later writes would reuse it anyway.
                if let Err(error) = conn.execute_batch("VACUUM") {
                    notes.push(NewLog::new("warn", "db", format!("could not compact evo.db: {error}")));
                }
            }
            for id in &adopted.conflicts {
                notes.push(
                    NewLog::new(
                        "warn",
                        "db",
                        "a transcript file disagreed with evo.db; evo.db's transcript was kept and the file set aside as <id>.db.conflict-<time>",
                    )
                    .chat(Some(id)),
                );
            }
        }
        Err(error) => notes.push(NewLog::new(
            "error",
            "db",
            format!("could not move chat transcripts out of evo.db: {error}"),
        )),
    }
    match transcripts::sweep(conn, dir) {
        Ok(swept) => {
            if !swept.orphans.is_empty() {
                notes.push(
                    NewLog::new("info", "db", format!("removed {} transcripts without a chat", swept.orphans.len()))
                        .data(json!({ "chats": swept.orphans })),
                );
            }
            if !swept.failed.is_empty() {
                notes.push(
                    NewLog::new("warn", "db", format!("{} transcripts without a chat are still in use", swept.failed.len()))
                        .data(json!({ "chats": swept.failed })),
                );
            }
        }
        Err(error) => notes.push(NewLog::new("warn", "db", format!("could not tidy the transcripts: {error}"))),
    }
    notes
}

/// Run `f` on a blocking thread: commands that read or copy transcript files
/// must not hold up the thread that serves the window.
async fn blocking<T: Send + 'static>(
    app: AppHandle,
    f: impl FnOnce(&Db) -> Result<T, String> + Send + 'static,
) -> Result<T, String> {
    tauri::async_runtime::spawn_blocking(move || f(&app.state::<Db>()))
        .await
        .map_err(|e| e.to_string())?
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
    /// The folder of the chats' transcript files, their total size and count.
    transcripts_dir: String,
    transcripts_bytes: u64,
    transcripts_count: usize,
}

#[tauri::command]
pub fn db_info(db: State<'_, Db>) -> Result<DbInfo, String> {
    let (transcripts_bytes, transcripts_count) = transcripts::usage(&db.transcripts);
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
        transcripts_dir: db.transcripts.display().to_string(),
        transcripts_bytes,
        transcripts_count,
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
    check_workspace_folder(&path)?;
    db.with(|conn| chats::ensure_workspace(conn, &path))
}

/// A workspace is an existing folder named by an absolute path. This keeps out
/// a mangled path (say `C:Users…` with its backslashes eaten by a string
/// escape), which would otherwise be stored and shown whole as the name.
fn check_workspace_folder(path: &str) -> Result<(), String> {
    let folder = std::path::Path::new(path);
    if path.chars().any(char::is_control) || !folder.is_absolute() {
        return Err(format!("not an absolute folder path: {path:?}"));
    }
    if !folder.is_dir() {
        return Err(format!("no such folder: {path}"));
    }
    Ok(())
}

#[tauri::command]
pub fn workspace_set_collapsed(db: State<'_, Db>, id: String, collapsed: bool) -> Result<(), String> {
    db.with(|conn| chats::set_workspace_collapsed(conn, &id, collapsed))
}

/// Remove a workspace with its chats, their engines and transcripts; returns
/// the removed chat ids.
#[tauri::command]
pub async fn workspace_remove(
    db: State<'_, Db>,
    engines: State<'_, EngineState>,
    id: String,
) -> Result<Vec<String>, String> {
    let removed = db.with(|conn| chats::remove_workspace(conn, &id))?;
    for chat in &removed {
        // The engine holds its transcript open; Windows will not delete it.
        engines.stop(chat).await;
        db.remove_transcript(chat);
    }
    db.log(NewLog::new("info", "shell", format!("removed workspace {id} with {} chats", removed.len())));
    Ok(removed)
}

#[tauri::command]
pub fn chats_list(db: State<'_, Db>, archived: bool) -> Result<Vec<Chat>, String> {
    db.with(|conn| chats::list_chats(conn, archived))
}

/// Chats whose title, preview or transcript mentions `query`. Transcripts
/// written since the last search are read first, off the window's thread.
#[tauri::command]
pub async fn chats_search(app: AppHandle, query: String) -> Result<Vec<Chat>, String> {
    blocking(app, move |db| db.with(|conn| chats::search_chats(conn, &db.transcripts, &query, 50))).await
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
pub async fn chat_fork(app: AppHandle, source: String, id: String, title: String) -> Result<Option<Chat>, String> {
    blocking(app, move |db| {
        let chat = db.with(|conn| chats::fork_chat(conn, &db.transcripts, &source, &id, &title))?;
        db.log(NewLog::new("info", "shell", format!("forked chat {source}")).chat(Some(&id)));
        Ok(chat)
    })
    .await
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

/// Delete a chat, stop its engine and remove its transcript file.
#[tauri::command]
pub async fn chat_delete(db: State<'_, Db>, engines: State<'_, EngineState>, id: String) -> Result<(), String> {
    db.with(|conn| chats::delete_chat(conn, &id))?;
    // The engine holds its transcript open; Windows will not delete it.
    engines.stop(&id).await;
    db.remove_transcript(&id);
    // The chat's Office document versions (docs/features/office-v3-parity/spec.md):
    // kept by its engine under `<agent>/document-versions/<chat>`.
    if !id.is_empty() && id.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_') {
        let versions = crate::mcp::agent_dir().join("document-versions").join(&id);
        if versions.is_dir() {
            if let Err(error) = std::fs::remove_dir_all(&versions) {
                db.log(NewLog::new("warn", "shell", format!("could not remove document versions: {error}")).chat(Some(&id)));
            }
        }
    }
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

/// Usage and cost totals, the per-day series and breakdowns for the Usage
/// page (`docs/features/usage-and-cost/spec.md`). Off the window's thread: a
/// long history takes a moment to sum.
#[tauri::command]
pub async fn usage_summary(app: AppHandle, query: UsageQuery) -> Result<UsageSummary, String> {
    blocking(app, move |db| db.with(|conn| usage::summary(conn, &query))).await
}

/// The newest recorded responses matching `query`, paging back from `before_id`.
#[tauri::command]
pub async fn usage_events(
    app: AppHandle,
    query: UsageQuery,
    before_id: Option<i64>,
    limit: Option<u32>,
) -> Result<Vec<UsageEvent>, String> {
    blocking(app, move |db| db.with(|conn| usage::events(conn, &query, before_id, limit.unwrap_or(200)))).await
}

/// Forget the usage history. Chats keep their own totals.
#[tauri::command]
pub fn usage_clear(db: State<'_, Db>) -> Result<usize, String> {
    db.with(|conn| usage::clear(conn))
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

#[cfg(test)]
mod tests {
    use super::check_workspace_folder;

    #[test]
    fn workspace_folder_must_be_an_existing_absolute_dir() {
        let dir = std::env::temp_dir();
        assert!(check_workspace_folder(dir.to_str().unwrap()).is_ok());
        // Backslashes eaten by a JS string escape: drive-relative, with `\1` as U+0001.
        assert!(check_workspace_folder("C:UsersHungKV4AppDataLocalTempclaude\u{1}cd6de").is_err());
        assert!(check_workspace_folder("relative/folder").is_err());
        assert!(check_workspace_folder(dir.join("evo-no-such-folder-9f3a").to_str().unwrap()).is_err());
    }
}
