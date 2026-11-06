//! Managed Git worktrees from the app: review what an agent or a nested
//! session changed in its worktree, apply it to the workspace, or discard it;
//! and create worktrees for nested sessions (`evo-worktrees`, the same manager
//! the engine uses). User-data-directory worktrees live next to the app
//! database, in `<agent dir>/worktrees`.

use std::path::PathBuf;

use evo_worktrees::{Changes, Location, Worktree, Worktrees};
use serde::Serialize;
use serde_json::Value;
use tauri::State;

use crate::db::Db;

/// Patches longer than this are cut for display (applying uses the whole one).
const MAX_PATCH: usize = 1024 * 1024;

fn manager(db: &Db) -> Worktrees {
    let root = db.path.parent().map(|dir| dir.join("worktrees")).unwrap_or_else(|| PathBuf::from("worktrees"));
    Worktrees::with_data_root(root)
}

/// Settings → Sandbox → Managed worktrees.
fn location(db: &Db) -> Location {
    db.with(|conn| evo_store::settings::all(conn))
        .ok()
        .and_then(|settings| settings.get(crate::engine::SANDBOX_KEY).cloned())
        .and_then(|sandbox| sandbox.get("worktreeLocation").cloned())
        .and_then(|value| serde_json::from_value::<Location>(value).ok())
        .unwrap_or_default()
}

async fn blocking<T: Send + 'static>(work: impl FnOnce() -> Result<T, String> + Send + 'static) -> Result<T, String> {
    tauri::async_runtime::spawn_blocking(work).await.map_err(|e| e.to_string())?
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Created {
    path: PathBuf,
    branch: String,
    cwd: PathBuf,
    base: String,
}

/// A new worktree of `cwd`'s repository (blocking): its folder, and the
/// folder in it that matches `cwd` (for a nested session started by the hub).
pub(crate) fn create_blocking(db: &Db, cwd: &std::path::Path) -> Result<(PathBuf, PathBuf), String> {
    let created = manager(db).create(cwd, location(db))?;
    Ok((created.worktree.path, created.cwd))
}

/// A new worktree of `cwd`'s repository, where the sandbox setting says.
#[tauri::command]
pub async fn worktree_create(db: State<'_, Db>, cwd: String) -> Result<Created, String> {
    let (worktrees, location) = (manager(&db), location(&db));
    blocking(move || {
        let created = worktrees.create(&PathBuf::from(cwd), location)?;
        Ok(Created { path: created.worktree.path, branch: created.worktree.branch, cwd: created.cwd, base: created.base })
    })
    .await
}

/// The managed worktrees of `cwd`'s repository (empty outside a repository).
#[tauri::command]
pub async fn worktree_list(db: State<'_, Db>, cwd: String) -> Result<Vec<Worktree>, String> {
    let worktrees = manager(&db);
    blocking(move || Ok(worktrees.list(&PathBuf::from(cwd)).unwrap_or_default())).await
}

/// What the worktree at `path` changed, for review (`patch` cut when huge).
#[tauri::command]
pub async fn worktree_changes(db: State<'_, Db>, cwd: String, path: String) -> Result<Value, String> {
    let worktrees = manager(&db);
    blocking(move || {
        let mut changes = worktrees.changes(&PathBuf::from(cwd), &PathBuf::from(path))?;
        let truncated = changes.patch.len() > MAX_PATCH;
        if truncated {
            let mut cut = MAX_PATCH;
            while !changes.patch.is_char_boundary(cut) {
                cut -= 1;
            }
            changes.patch.truncate(cut);
        }
        let mut value = serde_json::to_value(changes).map_err(|e| e.to_string())?;
        value["truncated"] = Value::Bool(truncated);
        Ok(value)
    })
    .await
}

fn summary(changes: Changes) -> Value {
    serde_json::json!({ "files": changes.files.len(), "added": changes.added, "removed": changes.removed })
}

/// Apply the worktree's changes to the workspace (uncommitted) and remove it.
#[tauri::command]
pub async fn worktree_apply(db: State<'_, Db>, cwd: String, path: String) -> Result<Value, String> {
    let worktrees = manager(&db);
    blocking(move || worktrees.apply(&PathBuf::from(cwd), &PathBuf::from(path)).map(summary)).await
}

/// Where the repository `cwd` is in stands (branch, upstream, changes against
/// `HEAD`), for the chat summary; `null` outside a repository.
#[tauri::command]
pub async fn git_status(cwd: String) -> Result<Option<evo_worktrees::RepoStatus>, String> {
    blocking(move || evo_worktrees::repo_status(&PathBuf::from(cwd))).await
}

/// Paths git ignores in `cwd`'s repository (absolute, forward slashes, folders
/// end with `/`), for dimming them in Files; `null` outside a repository.
#[tauri::command]
pub async fn git_ignored(cwd: String) -> Result<Option<Vec<String>>, String> {
    blocking(move || evo_worktrees::ignored_paths(&PathBuf::from(cwd))).await
}

/// `path` as committed at `HEAD`, for the editor's changed-line markers;
/// `null` when it is untracked, binary, large or outside the repository.
#[tauri::command]
pub async fn git_file_base(cwd: String, path: String) -> Result<Option<String>, String> {
    blocking(move || evo_worktrees::file_at_head(&PathBuf::from(cwd), &PathBuf::from(path))).await
}

/// Throw the worktree and its branch away.
#[tauri::command]
pub async fn worktree_discard(db: State<'_, Db>, cwd: String, path: String) -> Result<(), String> {
    let worktrees = manager(&db);
    blocking(move || worktrees.remove(&PathBuf::from(cwd), &PathBuf::from(path))).await
}
