//! Workspaces and the chats inside them, as the desktop sidebar shows them.
//!
//! A chat's `id` is its engine session id: its transcript is the file
//! `transcripts/<id>.db` ([`crate::transcripts`]), written by the chat's engine
//! through `--session-db`. Functions that copy or search transcripts take the
//! transcripts folder; deleting a chat's file is the caller's job, after its
//! engine has stopped (Windows refuses to delete a file in use). Times are
//! Unix milliseconds, the unit the UI works in.

use std::path::Path;

use rusqlite::{params, Connection, OptionalExtension, Row, TransactionBehavior};
use serde::{Deserialize, Serialize};

use crate::{transcripts, DbError};

/// Unix milliseconds.
pub fn now_ms() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis() as i64)
        .unwrap_or(0)
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct Workspace {
    pub id: String,
    pub path: String,
    pub name: String,
    pub collapsed: bool,
    pub position: i64,
    pub created_at: i64,
    pub opened_at: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct Chat {
    pub id: String,
    /// `None`: the chat runs in the home folder ("This computer").
    pub workspace_id: Option<String>,
    pub title: String,
    /// `auto` follows the first prompt; `user` was renamed by hand.
    pub title_source: String,
    pub preview: Option<String>,
    pub provider: Option<String>,
    pub model: Option<String>,
    pub pinned: bool,
    pub unread: bool,
    pub archived_at: Option<i64>,
    pub turn_count: i64,
    pub cost_usd: f64,
    pub tokens: i64,
    pub created_at: i64,
    pub updated_at: i64,
    /// The chat that started this one (nested sessions); `None` at top level.
    pub parent_chat_id: Option<String>,
    /// `user`, or `agent` when another chat's agent started it.
    pub origin: String,
    /// A managed worktree the chat works in instead of its workspace folder.
    pub worktree_path: Option<String>,
}

/// A chat to create.
#[derive(Debug, Clone, Default, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NewChat {
    pub id: String,
    pub workspace_id: Option<String>,
    pub title: String,
    pub provider: Option<String>,
    pub model: Option<String>,
    #[serde(default)]
    pub parent_chat_id: Option<String>,
    /// `user` (default) or `agent`.
    #[serde(default)]
    pub origin: Option<String>,
    #[serde(default)]
    pub worktree_path: Option<String>,
}

/// Fields to change on a chat; `None` leaves a field as it is.
#[derive(Debug, Clone, Default, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ChatPatch {
    /// A title the person chose (marks the title as `user`).
    pub title: Option<String>,
    /// A title derived from the conversation; ignored once the person renamed it.
    pub auto_title: Option<String>,
    pub pinned: Option<bool>,
    pub unread: Option<bool>,
    pub archived: Option<bool>,
    pub provider: Option<String>,
    pub model: Option<String>,
}

/// What one finished turn adds to a chat.
#[derive(Debug, Clone, Default, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TurnRecord {
    /// The start of the agent's reply, for the sidebar.
    pub preview: Option<String>,
    pub cost_usd: f64,
    pub tokens: i64,
    pub provider: Option<String>,
    pub model: Option<String>,
    /// Mark the chat unread (it finished while the person was elsewhere).
    pub unread: bool,
}

const WORKSPACE_COLUMNS: &str = "id, path, name, collapsed, position, created_at, opened_at";
const CHAT_COLUMNS: &str = "id, workspace_id, title, title_source, preview, provider, model, pinned, unread, \
     archived_at, turn_count, cost_usd, tokens, created_at, updated_at, parent_chat_id, origin, worktree_path";

fn workspace_row(row: &Row<'_>) -> rusqlite::Result<Workspace> {
    Ok(Workspace {
        id: row.get(0)?,
        path: row.get(1)?,
        name: row.get(2)?,
        collapsed: row.get(3)?,
        position: row.get(4)?,
        created_at: row.get(5)?,
        opened_at: row.get(6)?,
    })
}

fn chat_row(row: &Row<'_>) -> rusqlite::Result<Chat> {
    Ok(Chat {
        id: row.get(0)?,
        workspace_id: row.get(1)?,
        title: row.get(2)?,
        title_source: row.get(3)?,
        preview: row.get(4)?,
        provider: row.get(5)?,
        model: row.get(6)?,
        pinned: row.get(7)?,
        unread: row.get(8)?,
        archived_at: row.get(9)?,
        turn_count: row.get(10)?,
        cost_usd: row.get(11)?,
        tokens: row.get(12)?,
        created_at: row.get(13)?,
        updated_at: row.get(14)?,
        parent_chat_id: row.get(15)?,
        origin: row.get(16)?,
        worktree_path: row.get(17)?,
    })
}

fn trim_path(path: &str) -> &str {
    let trimmed = path.trim_end_matches(['/', '\\']);
    if trimmed.is_empty() || trimmed.ends_with(':') {
        path
    } else {
        trimmed
    }
}

fn folder_name(path: &str) -> String {
    trim_path(path)
        .rsplit(['/', '\\'])
        .find(|part| !part.is_empty())
        .unwrap_or(path)
        .to_string()
}

fn new_id(prefix: &str) -> String {
    use std::sync::atomic::{AtomicU64, Ordering};
    static COUNTER: AtomicU64 = AtomicU64::new(0);
    let n = COUNTER.fetch_add(1, Ordering::Relaxed);
    format!(
        "{prefix}-{:x}{:04x}{:x}",
        now_ms(),
        std::process::id() & 0xffff,
        n
    )
}

pub fn list_workspaces(conn: &Connection) -> Result<Vec<Workspace>, DbError> {
    let mut statement = conn.prepare(&format!(
        "SELECT {WORKSPACE_COLUMNS} FROM workspaces ORDER BY position, name COLLATE NOCASE"
    ))?;
    let rows = statement.query_map([], workspace_row)?;
    Ok(rows.collect::<Result<_, _>>()?)
}

pub fn get_workspace(conn: &Connection, id: &str) -> Result<Option<Workspace>, DbError> {
    Ok(conn
        .query_row(
            &format!("SELECT {WORKSPACE_COLUMNS} FROM workspaces WHERE id = ?1"),
            [id],
            workspace_row,
        )
        .optional()?)
}

/// The workspace for `path`, created on first use; opening it bumps `opened_at`.
pub fn ensure_workspace(conn: &Connection, path: &str) -> Result<Workspace, DbError> {
    let path = trim_path(path);
    let now = now_ms();
    conn.execute(
        "INSERT INTO workspaces (id, path, name, collapsed, position, created_at, opened_at)
         VALUES (?1, ?2, ?3, 0, 0, ?4, ?4)
         ON CONFLICT (path) DO UPDATE SET opened_at = excluded.opened_at",
        params![new_id("ws"), path, folder_name(path), now],
    )?;
    Ok(conn.query_row(
        &format!("SELECT {WORKSPACE_COLUMNS} FROM workspaces WHERE path = ?1"),
        [path],
        workspace_row,
    )?)
}

pub fn set_workspace_collapsed(
    conn: &Connection,
    id: &str,
    collapsed: bool,
) -> Result<(), DbError> {
    conn.execute(
        "UPDATE workspaces SET collapsed = ?2 WHERE id = ?1",
        params![id, collapsed],
    )?;
    Ok(())
}

/// Remove a workspace from the sidebar together with its chats. Returns the
/// removed chat ids: stop their engines, then remove their transcript files.
pub fn remove_workspace(conn: &mut Connection, id: &str) -> Result<Vec<String>, DbError> {
    let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
    let ids: Vec<String> = {
        let mut statement = tx.prepare("SELECT id FROM chats WHERE workspace_id = ?1")?;
        let rows = statement.query_map([id], |row| row.get(0))?;
        rows.collect::<Result<_, _>>()?
    };
    for chat in &ids {
        // A transcript an older build left in this file, if it was not moved.
        tx.execute("DELETE FROM sessions WHERE id = ?1", [chat])?;
    }
    tx.execute("DELETE FROM chats WHERE workspace_id = ?1", [id])?;
    tx.execute("DELETE FROM workspaces WHERE id = ?1", [id])?;
    tx.commit()?;
    Ok(ids)
}

/// Every chat, pinned first then most recently active; `archived` selects
/// the archive instead of the live list.
pub fn list_chats(conn: &Connection, archived: bool) -> Result<Vec<Chat>, DbError> {
    let filter = if archived {
        "archived_at IS NOT NULL ORDER BY archived_at DESC"
    } else {
        "archived_at IS NULL ORDER BY pinned DESC, updated_at DESC"
    };
    let mut statement =
        conn.prepare(&format!("SELECT {CHAT_COLUMNS} FROM chats WHERE {filter}"))?;
    let rows = statement.query_map([], chat_row)?;
    Ok(rows.collect::<Result<_, _>>()?)
}

pub fn get_chat(conn: &Connection, id: &str) -> Result<Option<Chat>, DbError> {
    Ok(conn
        .query_row(
            &format!("SELECT {CHAT_COLUMNS} FROM chats WHERE id = ?1"),
            [id],
            chat_row,
        )
        .optional()?)
}

/// Create a chat (or return the existing one with that id).
pub fn create_chat(conn: &Connection, chat: &NewChat) -> Result<Chat, DbError> {
    let now = now_ms();
    conn.execute(
        "INSERT INTO chats (id, workspace_id, title, title_source, provider, model, created_at, updated_at, parent_chat_id, origin, worktree_path)
         VALUES (?1, ?2, ?3, 'auto', ?4, ?5, ?6, ?6, ?7, ?8, ?9)
         ON CONFLICT (id) DO NOTHING",
        params![
            chat.id,
            chat.workspace_id,
            chat.title,
            chat.provider,
            chat.model,
            now,
            chat.parent_chat_id,
            chat.origin.as_deref().unwrap_or("user"),
            chat.worktree_path
        ],
    )?;
    get_chat(conn, &chat.id)?.ok_or_else(|| DbError::Sqlite(rusqlite::Error::QueryReturnedNoRows))
}

pub fn update_chat(
    conn: &Connection,
    id: &str,
    patch: &ChatPatch,
) -> Result<Option<Chat>, DbError> {
    if let Some(title) = &patch.title {
        conn.execute(
            "UPDATE chats SET title = ?2, title_source = 'user' WHERE id = ?1",
            params![id, title],
        )?;
    }
    if let Some(title) = &patch.auto_title {
        conn.execute(
            "UPDATE chats SET title = ?2 WHERE id = ?1 AND title_source = 'auto'",
            params![id, title],
        )?;
    }
    if let Some(pinned) = patch.pinned {
        conn.execute(
            "UPDATE chats SET pinned = ?2 WHERE id = ?1",
            params![id, pinned],
        )?;
    }
    if let Some(unread) = patch.unread {
        conn.execute(
            "UPDATE chats SET unread = ?2 WHERE id = ?1",
            params![id, unread],
        )?;
    }
    if let Some(archived) = patch.archived {
        let at = archived.then(now_ms);
        conn.execute(
            "UPDATE chats SET archived_at = ?2, pinned = CASE WHEN ?2 IS NULL THEN pinned ELSE 0 END WHERE id = ?1",
            params![id, at],
        )?;
    }
    if patch.provider.is_some() || patch.model.is_some() {
        conn.execute(
            "UPDATE chats SET provider = COALESCE(?2, provider), model = COALESCE(?3, model) WHERE id = ?1",
            params![id, patch.provider, patch.model],
        )?;
    }
    get_chat(conn, id)
}

/// Add one finished turn to a chat's totals and bump its activity time.
pub fn record_turn(
    conn: &Connection,
    id: &str,
    turn: &TurnRecord,
) -> Result<Option<Chat>, DbError> {
    let preview = turn.preview.as_deref().map(|text| {
        let line = text.split_whitespace().collect::<Vec<_>>().join(" ");
        line.chars().take(200).collect::<String>()
    });
    conn.execute(
        "UPDATE chats SET
             turn_count = turn_count + 1,
             cost_usd = cost_usd + ?2,
             tokens = tokens + ?3,
             preview = COALESCE(?4, preview),
             provider = COALESCE(?5, provider),
             model = COALESCE(?6, model),
             unread = CASE WHEN ?7 THEN 1 ELSE unread END,
             updated_at = ?8
         WHERE id = ?1",
        params![
            id,
            turn.cost_usd,
            turn.tokens,
            preview.filter(|text| !text.is_empty()),
            turn.provider,
            turn.model,
            turn.unread,
            now_ms()
        ],
    )?;
    get_chat(conn, id)
}

/// A copy of chat `source` under `id`: the same folder, model and whole
/// transcript (a new file in `transcripts_dir` whose session is a child of the
/// source's), titled `title`. The copy starts with no spend of its own. The
/// source may be running: its transcript is copied as far as it was written.
/// `None` when `source` does not exist.
pub fn fork_chat(
    conn: &mut Connection,
    transcripts_dir: &Path,
    source: &str,
    id: &str,
    title: &str,
) -> Result<Option<Chat>, DbError> {
    if get_chat(conn, source)?.is_none() {
        return Ok(None);
    }
    let now = now_ms();
    // The file first: a chat row never points at a half-made copy.
    let copied = transcripts::fork(transcripts_dir, source, id, now)?;
    let inserted = (|| -> Result<usize, DbError> {
        let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let inserted = tx.execute(
            "INSERT INTO chats (id, workspace_id, title, title_source, preview, provider, model, turn_count, created_at, updated_at)
             SELECT ?2, workspace_id, ?3, 'user', preview, provider, model, turn_count, ?4, ?4
             FROM chats WHERE id = ?1",
            params![source, id, title, now],
        )?;
        tx.commit()?;
        Ok(inserted)
    })();
    match inserted {
        Ok(1) => get_chat(conn, id),
        other => {
            if copied {
                let _ = transcripts::remove(&transcripts::path_in(transcripts_dir, id)?);
            }
            other.map(|_| None)
        }
    }
}

/// The worktree a chat works in, or (`None`) its workspace folder again.
pub fn set_worktree(
    conn: &Connection,
    id: &str,
    worktree_path: Option<&str>,
) -> Result<Option<Chat>, DbError> {
    conn.execute(
        "UPDATE chats SET worktree_path = ?2 WHERE id = ?1",
        params![id, worktree_path],
    )?;
    get_chat(conn, id)
}

/// Link a chat to the chat that started it, or (`None`) detach it.
pub fn set_parent(
    conn: &Connection,
    id: &str,
    parent_chat_id: Option<&str>,
) -> Result<Option<Chat>, DbError> {
    if parent_chat_id == Some(id) {
        return get_chat(conn, id);
    }
    conn.execute(
        "UPDATE chats SET parent_chat_id = ?2 WHERE id = ?1",
        params![id, parent_chat_id],
    )?;
    get_chat(conn, id)
}

/// Move a chat to another workspace (`None`: "This computer").
pub fn move_chat(
    conn: &Connection,
    id: &str,
    workspace_id: Option<&str>,
) -> Result<Option<Chat>, DbError> {
    conn.execute(
        "UPDATE chats SET workspace_id = ?2 WHERE id = ?1",
        params![id, workspace_id],
    )?;
    get_chat(conn, id)
}

/// Delete a chat (its search text goes with it). Its transcript file is the
/// caller's to remove once the chat's engine has stopped.
pub fn delete_chat(conn: &mut Connection, id: &str) -> Result<(), DbError> {
    let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
    // A transcript an older build left in this file, if it was not moved.
    tx.execute("DELETE FROM sessions WHERE id = ?1", [id])?;
    tx.execute("DELETE FROM chats WHERE id = ?1", [id])?;
    tx.commit()?;
    Ok(())
}

/// Bring the search text of every chat up to date with its transcript file:
/// re-read the transcripts whose file changed since they were last read
/// (their [`transcripts::stamp`]), drop the text of chats whose file is gone.
/// Returns how many chats changed. Only changed files are read, so a search
/// after a few turns reads a few files.
pub fn refresh_search(conn: &mut Connection, transcripts_dir: &Path) -> Result<usize, DbError> {
    let known: Vec<(String, Option<String>)> = {
        let mut statement = conn.prepare(
            "SELECT c.id, s.stamp FROM chats c LEFT JOIN chat_search s ON s.chat_id = c.id",
        )?;
        let rows = statement.query_map([], |row| Ok((row.get(0)?, row.get(1)?)))?;
        rows.collect::<Result<_, _>>()?
    };
    let mut changed: Vec<(String, Option<(String, String)>)> = Vec::new();
    for (id, recorded) in known {
        let Ok(path) = transcripts::path_in(transcripts_dir, &id) else {
            continue;
        };
        match transcripts::stamp(&path) {
            None if recorded.is_some() => changed.push((id, None)),
            None => {}
            Some(stamp) if recorded.as_deref() != Some(stamp.as_str()) => {
                // Stamp first, then read: a write in between leaves an older
                // stamp, so the next refresh reads the file again.
                let body = transcripts::read_state(&path, &id)
                    .ok()
                    .flatten()
                    .map(|state| transcripts::searchable_text(&state))
                    .unwrap_or_default();
                changed.push((id, Some((stamp, body))));
            }
            Some(_) => {}
        }
    }
    if changed.is_empty() {
        return Ok(0);
    }
    let tx = conn.transaction_with_behavior(TransactionBehavior::Immediate)?;
    for (id, text) in &changed {
        match text {
            Some((stamp, body)) => tx.execute(
                "INSERT INTO chat_search (chat_id, stamp, body) VALUES (?1, ?2, ?3)
                 ON CONFLICT (chat_id) DO UPDATE SET stamp = excluded.stamp, body = excluded.body",
                params![id, stamp, body],
            )?,
            None => tx.execute("DELETE FROM chat_search WHERE chat_id = ?1", [id])?,
        };
    }
    tx.commit()?;
    Ok(changed.len())
}

/// Chats whose title, preview or transcript mentions `query` (case-insensitive),
/// live and archived, most recent first. Refreshes the search text of changed
/// transcripts first ([`refresh_search`]).
pub fn search_chats(
    conn: &mut Connection,
    transcripts_dir: &Path,
    query: &str,
    limit: u32,
) -> Result<Vec<Chat>, DbError> {
    refresh_search(conn, transcripts_dir)?;
    let escaped = query
        .replace('\\', "\\\\")
        .replace('%', "\\%")
        .replace('_', "\\_");
    let pattern = format!("%{escaped}%");
    let columns = CHAT_COLUMNS
        .split(", ")
        .map(|column| format!("c.{}", column.trim()))
        .collect::<Vec<_>>()
        .join(", ");
    let mut statement = conn.prepare(&format!(
        "SELECT {columns} FROM chats c LEFT JOIN chat_search s ON s.chat_id = c.id
         WHERE c.title LIKE ?1 ESCAPE '\\' OR c.preview LIKE ?1 ESCAPE '\\' OR s.body LIKE ?1 ESCAPE '\\'
         ORDER BY c.updated_at DESC LIMIT ?2"
    ))?;
    let rows = statement.query_map(params![pattern, limit], chat_row)?;
    Ok(rows.collect::<Result<_, _>>()?)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn db() -> (tempfile::TempDir, Connection) {
        let dir = tempfile::tempdir().unwrap();
        let conn = crate::open_at(&dir.path().join("evo.db")).unwrap();
        (dir, conn)
    }

    #[test]
    fn nested_sessions_link_to_their_parent() {
        let (_dir, mut conn) = db();
        let parent = create_chat(
            &conn,
            &NewChat {
                id: "p".into(),
                title: "Parent".into(),
                ..Default::default()
            },
        )
        .unwrap();
        assert_eq!(
            (parent.parent_chat_id.as_deref(), parent.origin.as_str()),
            (None, "user")
        );
        let child = create_chat(
            &conn,
            &NewChat {
                id: "c".into(),
                title: "Child".into(),
                parent_chat_id: Some("p".into()),
                origin: Some("agent".into()),
                ..Default::default()
            },
        )
        .unwrap();
        assert_eq!(
            (child.parent_chat_id.as_deref(), child.origin.as_str()),
            (Some("p"), "agent")
        );
        assert_eq!(list_chats(&conn, false).unwrap().len(), 2);
        // Deleting the parent keeps the child, at the top level.
        delete_chat(&mut conn, "p").unwrap();
        let orphan = get_chat(&conn, "c").unwrap().unwrap();
        assert_eq!(orphan.parent_chat_id, None);
        // Linking and detaching; a chat is never its own parent.
        create_chat(
            &conn,
            &NewChat {
                id: "q".into(),
                title: "Q".into(),
                ..Default::default()
            },
        )
        .unwrap();
        assert_eq!(
            set_parent(&conn, "c", Some("q"))
                .unwrap()
                .unwrap()
                .parent_chat_id
                .as_deref(),
            Some("q")
        );
        assert_eq!(
            set_parent(&conn, "c", Some("c"))
                .unwrap()
                .unwrap()
                .parent_chat_id
                .as_deref(),
            Some("q")
        );
        assert_eq!(
            set_parent(&conn, "c", None)
                .unwrap()
                .unwrap()
                .parent_chat_id,
            None
        );
        // A chat's worktree folder.
        assert_eq!(
            set_worktree(&conn, "c", Some("/w/1"))
                .unwrap()
                .unwrap()
                .worktree_path
                .as_deref(),
            Some("/w/1")
        );
        assert_eq!(
            set_worktree(&conn, "c", None)
                .unwrap()
                .unwrap()
                .worktree_path,
            None
        );
    }

    #[test]
    fn workspaces_are_unique_by_path() {
        let (_dir, conn) = db();
        let a = ensure_workspace(&conn, "C:\\code\\app\\").unwrap();
        let b = ensure_workspace(&conn, "c:\\code\\APP").unwrap();
        assert_eq!(a.id, b.id);
        assert_eq!(a.name, "app");
        assert_eq!(list_workspaces(&conn).unwrap().len(), 1);
    }

    #[test]
    fn chat_lifecycle() {
        let (_dir, mut conn) = db();
        let ws = ensure_workspace(&conn, "/tmp/proj").unwrap();
        let chat = create_chat(
            &conn,
            &NewChat {
                id: "c1".into(),
                workspace_id: Some(ws.id.clone()),
                title: "Fix the build".into(),
                ..Default::default()
            },
        )
        .unwrap();
        assert_eq!(chat.title_source, "auto");

        let renamed = update_chat(
            &conn,
            "c1",
            &ChatPatch {
                title: Some("Build".into()),
                ..Default::default()
            },
        )
        .unwrap()
        .unwrap();
        assert_eq!(renamed.title_source, "user");
        let kept = update_chat(
            &conn,
            "c1",
            &ChatPatch {
                auto_title: Some("x".into()),
                ..Default::default()
            },
        )
        .unwrap()
        .unwrap();
        assert_eq!(kept.title, "Build");

        let after = record_turn(
            &conn,
            "c1",
            &TurnRecord {
                preview: Some("Done.\n\nAll  green".into()),
                cost_usd: 0.5,
                tokens: 10,
                unread: true,
                ..Default::default()
            },
        )
        .unwrap()
        .unwrap();
        assert_eq!(
            (after.turn_count, after.tokens, after.unread),
            (1, 10, true)
        );
        assert_eq!(after.preview.as_deref(), Some("Done. All green"));

        update_chat(
            &conn,
            "c1",
            &ChatPatch {
                pinned: Some(true),
                ..Default::default()
            },
        )
        .unwrap();
        update_chat(
            &conn,
            "c1",
            &ChatPatch {
                archived: Some(true),
                ..Default::default()
            },
        )
        .unwrap();
        assert!(list_chats(&conn, false).unwrap().is_empty());
        let archived = list_chats(&conn, true).unwrap();
        assert!(!archived[0].pinned, "archiving unpins");

        let files = _dir.path().join(transcripts::DIR_NAME);
        let c1 = write_transcript(&files, "c1", r#"{"records":[{"text":"needle"}]}"#);
        assert_eq!(
            search_chats(&mut conn, &files, "NEEDLE", 10).unwrap().len(),
            1
        );
        assert_eq!(
            search_chats(&mut conn, &files, "100%", 10).unwrap().len(),
            0
        );

        let fork = fork_chat(&mut conn, &files, "c1", "c2", "Build (fork)")
            .unwrap()
            .unwrap();
        assert_eq!(
            (fork.title.as_str(), fork.turn_count, fork.tokens),
            ("Build (fork)", 1, 0)
        );
        assert_eq!(fork.workspace_id.as_deref(), Some(ws.id.as_str()));
        let copy = transcripts::path_in(&files, "c2").unwrap();
        let (parent, state): (Option<String>, String) = Connection::open(&copy)
            .unwrap()
            .query_row(
                "SELECT parent_session_id, state_json FROM sessions WHERE id = 'c2'",
                [],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .unwrap();
        assert_eq!(
            (parent.as_deref(), state.contains("needle")),
            (Some("c1"), true)
        );
        assert!(fork_chat(&mut conn, &files, "missing", "c3", "x")
            .unwrap()
            .is_none());
        assert!(!transcripts::path_in(&files, "c3").unwrap().exists());
        // A fork onto an existing chat id fails and leaves no stray file.
        create_chat(
            &conn,
            &NewChat {
                id: "taken".into(),
                title: "T".into(),
                ..Default::default()
            },
        )
        .unwrap();
        assert!(fork_chat(&mut conn, &files, "c1", "taken", "x").is_err());
        assert!(!transcripts::path_in(&files, "taken").unwrap().exists());
        delete_chat(&mut conn, "taken").unwrap();
        // A chat with no transcript yet forks into a chat with none.
        create_chat(
            &conn,
            &NewChat {
                id: "empty".into(),
                title: "E".into(),
                ..Default::default()
            },
        )
        .unwrap();
        assert!(fork_chat(&mut conn, &files, "empty", "empty2", "x")
            .unwrap()
            .is_some());
        assert!(!transcripts::path_in(&files, "empty2").unwrap().exists());
        delete_chat(&mut conn, "empty").unwrap();
        delete_chat(&mut conn, "empty2").unwrap();

        let moved = move_chat(&conn, "c2", None).unwrap().unwrap();
        assert_eq!(moved.workspace_id, None);
        delete_chat(&mut conn, "c2").unwrap();
        let indexed: i64 = conn
            .query_row("SELECT COUNT(*) FROM chat_search", [], |r| r.get(0))
            .unwrap();
        assert_eq!(indexed, 1, "a deleted chat's search text goes with it");

        let removed = remove_workspace(&mut conn, &ws.id).unwrap();
        assert_eq!(removed, vec!["c1".to_string()]);
        assert!(
            c1.exists(),
            "files are removed by the caller, after the engine stops"
        );
        let left: i64 = conn
            .query_row("SELECT COUNT(*) FROM chat_search", [], |r| r.get(0))
            .unwrap();
        assert_eq!(left, 0);
    }

    fn write_transcript(dir: &Path, id: &str, state: &str) -> std::path::PathBuf {
        let path = transcripts::path_in(dir, id).unwrap();
        transcripts::prepare(&path).unwrap();
        let conn = Connection::open(&path).unwrap();
        conn.execute_batch(transcripts::SESSION_SCHEMA).unwrap();
        conn.execute(
            "INSERT INTO sessions (id, created_at, parent_session_id, state_json) VALUES (?1, 0, NULL, ?2)
             ON CONFLICT (id) DO UPDATE SET state_json = excluded.state_json",
            params![id, state],
        )
        .unwrap();
        path
    }

    #[test]
    fn search_follows_transcript_changes() {
        let (dir, mut conn) = db();
        let files = dir.path().join(transcripts::DIR_NAME);
        for id in ["a", "b"] {
            create_chat(
                &conn,
                &NewChat {
                    id: id.into(),
                    title: format!("Chat {id}"),
                    ..Default::default()
                },
            )
            .unwrap();
        }
        // No transcripts yet: titles still match, nothing is indexed.
        assert_eq!(
            search_chats(&mut conn, &files, "chat a", 10).unwrap().len(),
            1
        );
        assert_eq!(refresh_search(&mut conn, &files).unwrap(), 0);

        write_transcript(&files, "a", r#"{"records":[{"text":"alpha"}]}"#);
        write_transcript(&files, "b", r#"{"records":[{"text":"beta"}]}"#);
        assert_eq!(refresh_search(&mut conn, &files).unwrap(), 2);
        // Unchanged files are not read again.
        assert_eq!(refresh_search(&mut conn, &files).unwrap(), 0);
        let ids = |found: Vec<Chat>| found.into_iter().map(|chat| chat.id).collect::<Vec<_>>();
        assert_eq!(
            ids(search_chats(&mut conn, &files, "ALPHA", 10).unwrap()),
            vec!["a"]
        );

        // A new turn in `b` is found by the next search.
        std::thread::sleep(std::time::Duration::from_millis(20));
        write_transcript(
            &files,
            "b",
            r#"{"records":[{"text":"beta"},{"text":"gamma ray"}]}"#,
        );
        assert_eq!(
            ids(search_chats(&mut conn, &files, "gamma", 10).unwrap()),
            vec!["b"]
        );
        // Identifiers and type tags are not searchable text.
        assert!(search_chats(&mut conn, &files, "records", 10)
            .unwrap()
            .is_empty());

        // A transcript removed from disk drops out of the search.
        transcripts::remove(&transcripts::path_in(&files, "a").unwrap()).unwrap();
        assert!(search_chats(&mut conn, &files, "alpha", 10)
            .unwrap()
            .is_empty());
        let indexed: i64 = conn
            .query_row("SELECT COUNT(*) FROM chat_search", [], |r| r.get(0))
            .unwrap();
        assert_eq!(indexed, 1);
    }
}
