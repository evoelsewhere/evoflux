//! The session mesh hub (`crates/evo-mesh`, `docs/features/session-mesh-protocol/spec.md`).
//!
//! Every engine's stdout passes through [`on_line`]. The hub answers the
//! session tools (`start_session`, `message_session`, `list_sessions`), turns
//! a nested session's finished turn into a note for the chat that started it,
//! stores mail in the app database and writes it to the receiving engine,
//! whichever window shows that chat.
//!
//! The windows still start and hold engines (they set up each engine's other
//! tools). When the hub needs an engine that runs nowhere — a session it just
//! created, a chat with mail waiting — the windows hear `mesh://host`; the main
//! window starts that engine and, once its tools are set up, calls
//! [`mesh_hosted`], and the hub sends what waits for it.

use std::path::PathBuf;

use evo_mesh::hub::{ChildInfo, CreatedSession, Effect, Hub, Mail, MailStore, SessionSpec};
use evo_mesh::wire::MailBody;
use evo_store::chats::{self, ChatPatch, NewChat};
use evo_store::mail::{self, StoredMail};
use serde_json::{json, Value};
use tauri::{AppHandle, Emitter, Manager, State};

use crate::db::Db;

/// [`MailStore`] over the app database.
pub struct DbMailStore {
    app: AppHandle,
}

impl DbMailStore {
    fn db(&self) -> State<'_, Db> {
        self.app.state::<Db>()
    }
}

/// A new chat id, in the UUID v4 shape the UI uses.
fn new_chat_id() -> String {
    use std::hash::{BuildHasher, Hasher};
    let mut bytes = [0u8; 16];
    let nanos = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    for (index, chunk) in bytes.chunks_mut(8).enumerate() {
        // Each RandomState has its own random keys.
        let mut hasher = std::collections::hash_map::RandomState::new().build_hasher();
        hasher.write_u128(nanos);
        hasher.write_usize(index);
        chunk.copy_from_slice(&hasher.finish().to_le_bytes());
    }
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    let hex: String = bytes.iter().map(|b| format!("{b:02x}")).collect();
    format!("{}-{}-{}-{}-{}", &hex[0..8], &hex[8..12], &hex[12..16], &hex[16..20], &hex[20..32])
}

/// The folder a chat works in when it has no workspace: the home folder.
fn home() -> PathBuf {
    std::env::var_os("USERPROFILE")
        .or_else(|| std::env::var_os("HOME"))
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."))
}

impl MailStore for DbMailStore {
    fn parent_of(&self, chat: &str) -> Option<String> {
        self.db().with(|conn| chats::get_chat(conn, chat)).ok().flatten()?.parent_chat_id
    }

    fn title_of(&self, chat: &str) -> Option<String> {
        self.db().with(|conn| chats::get_chat(conn, chat)).ok().flatten().map(|chat| chat.title)
    }

    fn insert(&self, mail: &Mail) -> Result<(), String> {
        let stored = StoredMail {
            id: mail.id.clone(),
            from_chat: mail.from_chat.clone(),
            to_chat: mail.to_chat.clone(),
            body: serde_json::to_string(&mail.body).map_err(|e| e.to_string())?,
            created_at: mail.created_at,
            delivered_at: None,
        };
        self.db().with(|conn| mail::insert_mail(conn, &stored))
    }

    fn pending(&self, chat: &str) -> Vec<Mail> {
        let stored = self.db().with(|conn| mail::pending_mail(conn, chat)).unwrap_or_default();
        stored
            .into_iter()
            .filter_map(|stored| {
                let body: MailBody = serde_json::from_str(&stored.body).ok()?;
                Some(Mail {
                    id: stored.id,
                    from_chat: stored.from_chat,
                    to_chat: stored.to_chat,
                    body,
                    created_at: stored.created_at,
                })
            })
            .collect()
    }

    fn mark_delivered(&self, id: &str) {
        let _ = self.db().with(|conn| mail::mark_mail_delivered(conn, id, chats::now_ms()));
    }

    fn children_of(&self, parent: &str) -> Vec<ChildInfo> {
        let chats = self.db().with(|conn| chats::list_chats(conn, false)).unwrap_or_default();
        chats
            .into_iter()
            .filter(|chat| chat.parent_chat_id.as_deref() == Some(parent))
            .map(|chat| ChildInfo { id: chat.id, title: chat.title, unread: chat.unread, preview: chat.preview })
            .collect()
    }

    fn create_session(&self, parent: &str, spec: &SessionSpec) -> Result<CreatedSession, String> {
        let db = self.db();
        let parent_row = db
            .with(|conn| chats::get_chat(conn, parent))?
            .ok_or_else(|| format!("no chat {parent}"))?;
        let title: String = spec.title.split_whitespace().collect::<Vec<_>>().join(" ").chars().take(80).collect();
        let id = new_chat_id();
        // Its own worktree of the parent's repository (fails outside a repository).
        let worktree = if spec.worktree {
            let base = match parent_row.workspace_id.as_deref() {
                Some(workspace) => db
                    .with(|conn| chats::get_workspace(conn, workspace))?
                    .map(|w| PathBuf::from(w.path))
                    .unwrap_or_else(home),
                None => home(),
            };
            Some(crate::worktrees::create_blocking(&db, &base)?)
        } else {
            None
        };
        let worktree_path = worktree.as_ref().map(|(path, _)| path.display().to_string());
        let chat = if spec.fork {
            db.with(|conn| {
                // The parent's engine is running: its transcript is copied
                // as far as it has been written.
                chats::fork_chat(conn, &db.transcripts, parent, &id, &title)?;
                chats::set_parent(conn, &id, Some(parent))?;
                chats::update_chat(conn, &id, &ChatPatch { title: Some(title.clone()), ..Default::default() })?;
                chats::set_worktree(conn, &id, worktree_path.as_deref())
            })?
            .ok_or("the fork was not created")?
        } else {
            db.with(|conn| {
                chats::create_chat(
                    conn,
                    &NewChat {
                        id: id.clone(),
                        workspace_id: parent_row.workspace_id.clone(),
                        title: title.clone(),
                        parent_chat_id: Some(parent.to_string()),
                        origin: Some("agent".into()),
                        worktree_path: worktree_path.clone(),
                        ..Default::default()
                    },
                )
            })?
        };
        db.log(evo_store::logs::NewLog::new("info", "mesh", format!("started nested session {id}")).chat(Some(parent)));
        // The windows' sidebars add it (session-store.ts listens).
        let _ = self.app.emit("chat://updated", json!({ "from": "shell", "chat": chat }));
        Ok(CreatedSession {
            id,
            title: chat.title,
            cwd: worktree.map(|(_, cwd)| cwd.display().to_string()),
        })
    }
}

/// The hub, managed as Tauri state.
pub struct MeshHub(pub Hub<DbMailStore>);

impl MeshHub {
    pub fn new(app: AppHandle) -> Self {
        MeshHub(Hub::new(DbMailStore { app }))
    }
}

/// One stdout line of `chat`'s engine: let the hub react, then carry out
/// what it asks (writes to engines, events to the windows).
pub async fn on_line(app: &AppHandle, chat: &str, line: &Value) {
    let effects = if line.get("type").and_then(Value::as_str) == Some("external_tool_request") {
        // A session tool may create a chat and a worktree: off the reader.
        let (app2, chat2, line2) = (app.clone(), chat.to_string(), line.clone());
        tauri::async_runtime::spawn_blocking(move || app2.state::<MeshHub>().0.on_line(&chat2, &line2))
            .await
            .unwrap_or_default()
    } else {
        app.state::<MeshHub>().0.on_line(chat, line)
    };
    apply(app, effects).await;
}

/// `chat`'s engine exited or was stopped.
pub async fn on_exit(app: &AppHandle, chat: &str) {
    let effects = app.state::<MeshHub>().0.on_exit(chat);
    apply(app, effects).await;
}

async fn apply(app: &AppHandle, effects: Vec<Effect>) {
    for effect in effects {
        match effect {
            Effect::Send { chat, line } => {
                let engines = app.state::<crate::engine::EngineState>();
                if let Err(error) = engines.write(&chat, &line).await {
                    // It stays pending: the next `ready` of that engine sends it.
                    app.state::<Db>().log(
                        evo_store::logs::NewLog::new("warn", "mesh", format!("mail not sent: {error}"))
                            .chat(Some(&chat)),
                    );
                    app.state::<MeshHub>().0.on_start(&chat);
                }
            }
            Effect::Host { chat, cwd, restore } => {
                let _ = app.emit("mesh://host", json!({ "chat": chat, "cwd": cwd, "restore": restore }));
            }
            Effect::Prompted { chat, text } => {
                let _ = app.emit("mesh://prompted", json!({ "chat": chat, "text": text }));
            }
        }
    }
}

/// Undelivered mail per chat, for the UI.
#[tauri::command]
pub fn mesh_pending(db: State<'_, Db>, chat: String) -> Result<usize, String> {
    db.with(|conn| mail::pending_mail(conn, &chat)).map(|mail| mail.len())
}

/// The chats with undelivered mail. At startup no engine runs, so nothing
/// asks for them to be hosted; the main window starts their engines.
#[tauri::command]
pub fn mesh_pending_chats(db: State<'_, Db>) -> Result<Vec<String>, String> {
    db.with(|conn| mail::chats_with_pending_mail(conn))
}

/// A window set up `chat`'s engine (its tools): send what waits for it.
#[tauri::command]
pub async fn mesh_hosted(app: AppHandle, chat: String) -> Result<(), String> {
    let effects = app.state::<MeshHub>().0.on_hosted(&chat);
    apply(&app, effects).await;
    Ok(())
}

/// Settings the hub follows (Settings → Sandbox: start sessions without asking).
#[tauri::command]
pub fn mesh_configure(hub: State<'_, MeshHub>, auto_start_sessions: bool) {
    hub.0.set_auto_start(auto_start_sessions);
}

/// The session tools' definitions, for a top-level chat's external tools.
#[tauri::command]
pub fn mesh_session_tools() -> Value {
    evo_mesh::hub::session_tools()
}

/// Start a nested session of `parent` (a proposal card's Start): returns its id.
#[tauri::command]
pub async fn mesh_start_session(app: AppHandle, parent: String, spec: SessionSpec) -> Result<String, String> {
    let app2 = app.clone();
    let (created, effects) =
        tauri::async_runtime::spawn_blocking(move || app2.state::<MeshHub>().0.start_session(&parent, &spec))
            .await
            .map_err(|e| e.to_string())??;
    apply(&app, effects).await;
    Ok(created.id)
}
