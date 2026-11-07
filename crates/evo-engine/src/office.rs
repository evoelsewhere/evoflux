//! Office documents in the engine: the LibreOffice runtime, the preview cache,
//! the native preview (`office_preview`), document versions
//! (`document_versions_get/act`), the `office_file_changed` events, the shell
//! environment that exposes the runtime to the agent, and the Office skills
//! embedded in the binary.
//!
//! Design: `docs/features/office/spec.md` (ADR 0008) and
//! `docs/features/office-v3-parity/spec.md`. The management RPCs
//! (`office_status`, `office_install`, …) mirror the language-server ones: the
//! UI starts an install and polls the status.

use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, OnceLock};
use std::time::SystemTime;

use evo_office::preview;
use evo_office::versions::DocumentVersions;
use evo_office::Runtime;
use evo_protocol::office as wire;
use evo_tools::{ShellEnv, ShellEnvProvider};
use include_dir::{include_dir, Dir};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

/// Documents larger than this are not converted.
const MAX_DOCUMENT_BYTES: u64 = 100 * 1024 * 1024;
/// The converted-PDF cache is pruned to this size, oldest first.
const CACHE_LIMIT_BYTES: u64 = 256 * 1024 * 1024;

fn agent_dir() -> PathBuf {
    crate::config::agent_dir().unwrap_or_else(|_| PathBuf::from(".evo"))
}

/// The one runtime handle of this process.
pub fn runtime() -> &'static Runtime {
    static RUNTIME: OnceLock<Runtime> = OnceLock::new();
    RUNTIME.get_or_init(|| Runtime::new(&agent_dir().join("runtimes")))
}

// ── Management RPCs ──────────────────────────────────────────────────────────

/// What Settings → Office shows.
pub fn status() -> Value {
    serde_json::to_value(runtime().status()).unwrap_or(Value::Null)
}

/// Run one management action and answer with the new status.
pub fn manage(action: &str) -> Result<Value, String> {
    let runtime = runtime();
    match action {
        "office_install" => {
            runtime.start_install().map_err(|e| e.to_string())?;
        }
        "office_cancel_install" => runtime.cancel_install().map_err(|e| e.to_string())?,
        "office_dismiss_error" => runtime.dismiss_error(),
        "office_uninstall" => runtime.uninstall().map_err(|e| e.to_string())?,
        "office_status" => {}
        other => return Err(format!("unknown office action `{other}`")),
    }
    Ok(status())
}

// ── Conversion with a cache ──────────────────────────────────────────────────

fn cache_dir() -> PathBuf {
    agent_dir().join("cache").join("office")
}

fn cache_key(path: &Path, meta: &std::fs::Metadata, version: &str) -> String {
    let modified = meta
        .modified()
        .ok()
        .and_then(|t| t.duration_since(SystemTime::UNIX_EPOCH).ok())
        .map_or(0, |d| d.as_millis());
    let mut hasher = Sha256::new();
    hasher.update(path.to_string_lossy().as_bytes());
    hasher.update(b"\0");
    hasher.update(modified.to_string().as_bytes());
    hasher.update(b"\0");
    hasher.update(meta.len().to_string().as_bytes());
    hasher.update(b"\0");
    hasher.update(version.as_bytes());
    format!("{:x}", hasher.finalize())[..32].to_string()
}

/// Delete the oldest cached PDFs until the cache fits `limit`, never `keep`.
fn prune_cache(dir: &Path, keep: &Path, limit: u64) {
    let Ok(entries) = std::fs::read_dir(dir) else {
        return;
    };
    let mut files: Vec<(SystemTime, u64, PathBuf)> = entries
        .flatten()
        .filter_map(|e| {
            let meta = e.metadata().ok()?;
            (meta.is_file() && e.path().extension().is_some_and(|x| x == "pdf")).then(|| {
                (
                    meta.modified().unwrap_or(SystemTime::UNIX_EPOCH),
                    meta.len(),
                    e.path(),
                )
            })
        })
        .collect();
    let mut total: u64 = files.iter().map(|f| f.1).sum();
    files.sort_by_key(|f| f.0);
    for (_, size, path) in files {
        if total <= limit {
            break;
        }
        if path != keep && std::fs::remove_file(&path).is_ok() {
            total = total.saturating_sub(size);
        }
    }
}

/// Convert an Office document to a PDF in the cache and say where it is.
pub async fn convert(path: &str) -> Result<Value, String> {
    let source = PathBuf::from(path);
    let meta = tokio::fs::metadata(&source)
        .await
        .map_err(|e| format!("Cannot read {path}: {e}"))?;
    if !meta.is_file() {
        return Err(format!("{path} is not a file"));
    }
    let extension = source.extension().and_then(|e| e.to_str()).unwrap_or("");
    if !evo_office::supports(extension) {
        return Err(format!("Unsupported type: .{extension}"));
    }
    if meta.len() > MAX_DOCUMENT_BYTES {
        return Err(format!(
            "Documents over {} MB are not converted",
            MAX_DOCUMENT_BYTES / 1024 / 1024
        ));
    }
    let runtime = runtime();
    let installed = runtime
        .installed()
        .ok_or_else(|| evo_office::Error::NotInstalled.to_string())?;
    let canonical = tokio::fs::canonicalize(&source)
        .await
        .unwrap_or_else(|_| source.clone());
    let dir = cache_dir();
    let target = dir.join(format!(
        "{}.pdf",
        cache_key(&canonical, &meta, &installed.version)
    ));
    if tokio::fs::metadata(&target)
        .await
        .map(|m| m.len() > 0)
        .unwrap_or(false)
    {
        // Touch it so pruning keeps what is in use.
        let _ = tokio::task::spawn_blocking({
            let target = target.clone();
            move || {
                std::fs::File::options()
                    .write(true)
                    .open(&target)
                    .and_then(|f| f.set_modified(SystemTime::now()))
            }
        })
        .await;
        return Ok(json!({ "pdf": target, "version": installed.version, "cached": true }));
    }
    tokio::fs::create_dir_all(&dir)
        .await
        .map_err(|e| e.to_string())?;
    let work = tempfile::Builder::new()
        .prefix("convert-")
        .tempdir_in(&dir)
        .map_err(|e| e.to_string())?;
    let pdf = runtime
        .convert_to_pdf(&source, work.path(), evo_office::CONVERSION_TIMEOUT)
        .await
        .map_err(|e| format!("Conversion failed: {e}"))?;
    if tokio::fs::rename(&pdf, &target).await.is_err() {
        tokio::fs::copy(&pdf, &target)
            .await
            .map_err(|e| e.to_string())?;
    }
    let (prune_dir, keep) = (dir, target.clone());
    let _ = tokio::task::spawn_blocking(move || prune_cache(&prune_dir, &keep, CACHE_LIMIT_BYTES))
        .await;
    Ok(json!({ "pdf": target, "version": installed.version, "cached": false }))
}

// ── Native preview, versions and file events (v3 parity) ─────────────────────
//
// Design: `docs/features/office-v3-parity/spec.md`. Wire types:
// `evo_protocol::office`.

/// Where native (HTML) renders are cached.
pub fn preview_cache_dir() -> PathBuf {
    cache_dir().join("previews")
}

/// Types the LibreOffice runtime renders (v3 `_OFFICE_RUNTIME_SUFFIXES`).
const RUNTIME_EXTENSIONS: [&str; 3] = ["docx", "xlsx", "pptx"];
/// Longest checkpoint label a request may carry (v3 request schema).
const MAX_REQUEST_LABEL_CHARS: usize = 2000;
const MAX_VERSION_ID_CHARS: usize = 64;

/// The chat this engine serves, as the Office requests see it.
#[derive(Clone)]
pub struct OfficeChat {
    /// The chat's working folder.
    pub cwd: PathBuf,
    /// The chat (session) id; `EVO_SESSION_ID` in its shells.
    pub session_id: String,
    /// Whether the chat's turn is running.
    pub run_active: Arc<AtomicBool>,
}

impl OfficeChat {
    /// The chat id while its turn runs: files it builds live render live and
    /// are not versioned until finished.
    pub fn live_session(&self) -> Option<&str> {
        (self.run_active.load(Ordering::Acquire) && !self.session_id.is_empty())
            .then_some(self.session_id.as_str())
    }
}

/// The version store of this process.
pub fn versions() -> &'static DocumentVersions {
    static VERSIONS: OnceLock<DocumentVersions> = OnceLock::new();
    VERSIONS.get_or_init(|| DocumentVersions::new(agent_dir().join("document-versions")))
}

/// Delete a chat's document versions (call when the chat is deleted).
pub fn delete_chat_versions(chat: &str) -> std::io::Result<()> {
    versions().delete_chat(chat)
}

/// v3's message for a type the native renderer does not open.
pub fn unsupported_message(path: &Path) -> Option<String> {
    if preview::supports(path) {
        return None;
    }
    let extension = path
        .extension()
        .map(|e| format!(".{}", e.to_string_lossy().to_lowercase()))
        .unwrap_or_default();
    let subject = if extension.is_empty() {
        "This file type".to_string()
    } else {
        extension
    };
    Some(format!("{subject} is not supported for document preview."))
}

fn resolve_in(cwd: &Path, path: &str) -> PathBuf {
    let candidate = Path::new(path);
    if candidate.is_absolute() {
        candidate.to_path_buf()
    } else {
        cwd.join(candidate)
    }
}

/// The live-build plan in `path`, reading only its custom properties.
fn live_plan(path: &Path) -> Option<preview::DeckPlan> {
    const CUSTOM_PART: &str = "docProps/custom.xml";
    const MAX_PLAN_BYTES: u64 = 64 * 1024;
    let file = std::fs::File::open(path).ok()?;
    let mut archive = zip::ZipArchive::new(std::io::BufReader::new(file)).ok()?;
    let entry = archive.by_name(CUSTOM_PART).ok()?;
    if entry.size() > MAX_PLAN_BYTES {
        return None;
    }
    let mut data = Vec::new();
    std::io::Read::read_to_end(&mut std::io::Read::take(entry, MAX_PLAN_BYTES), &mut data).ok()?;
    preview::live::read_plan(&preview::Package::from_parts([(
        CUSTOM_PART.to_string(),
        data,
    )]))
}

/// Answer `office_preview`, `document_versions_get` or `document_versions_act`.
pub async fn rpc(kind: &str, msg: &Value, chat: &OfficeChat) -> Result<Value, String> {
    match kind {
        wire::OFFICE_PREVIEW => office_preview(msg, chat).await,
        wire::DOCUMENT_VERSIONS_GET | wire::DOCUMENT_VERSIONS_ACT => {
            let (kind, msg, chat) = (kind.to_string(), msg.clone(), chat.clone());
            tokio::task::spawn_blocking(move || document_versions(versions(), &kind, &msg, &chat))
                .await
                .map_err(|e| e.to_string())?
        }
        other => Err(format!("unknown office request `{other}`")),
    }
}

/// `office_preview {path, mode}` (v3 `_render_source` / `_renderer_identity`).
async fn office_preview(msg: &Value, chat: &OfficeChat) -> Result<Value, String> {
    let request: wire::OfficePreviewRequest = serde_json::from_value(msg.clone())
        .map_err(|e| format!("invalid office_preview request: {e}"))?;
    if request.path.trim().is_empty() {
        return Err("`path` is required".into());
    }
    let source = resolve_in(&chat.cwd, &request.path);
    let meta = tokio::fs::metadata(&source)
        .await
        .map_err(|_| format!("Document not found: {}", request.path))?;
    if !meta.is_file() {
        return Err(format!("Path is not a file: {}", request.path));
    }
    if let Some(message) = unsupported_message(&source) {
        return Err(message);
    }
    let extension = preview::extension(&source);
    let live_session = chat.live_session().map(str::to_owned);
    // A deck under construction is re-rendered on every save; the exact
    // renderer (seconds per conversion) takes over once it is finished.
    let live = match live_session.clone() {
        Some(session) if preview::live::LIVE_EXTENSIONS.contains(&extension.as_str()) => {
            let path = source.clone();
            tokio::task::spawn_blocking(move || {
                live_plan(&path).is_some_and(|plan| plan.live_for(Some(&session)))
            })
            .await
            .unwrap_or(false)
        }
        _ => false,
    };
    let mut fallback = false;
    if RUNTIME_EXTENSIONS.contains(&extension.as_str()) && !live {
        let exact = match request.mode {
            wire::OfficePreviewMode::Exact => true,
            wire::OfficePreviewMode::Auto => extension != "xlsx" && runtime().installed().is_some(),
            wire::OfficePreviewMode::Native => false,
        };
        if exact {
            match convert(&source.to_string_lossy()).await {
                Ok(done) => {
                    let preview = wire::OfficePreview::Pdf {
                        path: done["pdf"].as_str().unwrap_or_default().to_string(),
                        renderer: format!(
                            "libreoffice-{}",
                            done["version"].as_str().unwrap_or_default()
                        ),
                    };
                    return serde_json::to_value(preview).map_err(|e| e.to_string());
                }
                Err(error) if request.mode == wire::OfficePreviewMode::Exact => return Err(error),
                Err(error) => {
                    tracing::warn!(file = %source.display(), %error, "document_preview_exact_failed");
                    fallback = true;
                }
            }
        }
    }
    let rendered = {
        let (cache, path, session) = (preview_cache_dir(), source.clone(), live_session.clone());
        tokio::task::spawn_blocking(move || {
            preview::render_document_preview(&cache, &path, session.as_deref())
        })
        .await
        .map_err(|e| e.to_string())?
        .map_err(|e| e.to_string())?
    };
    let rendered = std::path::absolute(&rendered).unwrap_or(rendered);
    let preview = wire::OfficePreview::Html {
        path: rendered.to_string_lossy().into_owned(),
        renderer: if live { "native-live" } else { "native" }.to_string(),
        live,
        fallback: fallback.then_some(true),
    };
    serde_json::to_value(preview).map_err(|e| e.to_string())
}

/// The canonical chat folder and `path`'s place in it (v3 route `_document`).
fn versioned_document(cwd: &Path, path: &str) -> Result<(PathBuf, String), String> {
    if path.trim().is_empty() {
        return Err("Empty path.".into());
    }
    let candidate = Path::new(path);
    if !candidate.is_absolute()
        && candidate
            .components()
            .any(|c| matches!(c, std::path::Component::ParentDir))
    {
        return Err("Path must not traverse upward.".into());
    }
    let root = std::fs::canonicalize(cwd)
        .map_err(|_| "The chat's folder is not available.".to_string())?;
    let candidate = resolve_in(cwd, path);
    let name = candidate
        .file_name()
        .map(|n| n.to_string_lossy().into_owned())
        .unwrap_or_default();
    if !evo_office::versions::is_versioned(&name) {
        return Err("Only Word, Excel and PowerPoint files keep versions.".into());
    }
    let resolved =
        std::fs::canonicalize(&candidate).map_err(|_| "Document not found.".to_string())?;
    if !resolved.is_file() {
        return Err("Document not found.".into());
    }
    let rel = resolved
        .strip_prefix(&root)
        .map_err(|_| "Path escapes workspace root.".to_string())?;
    let rel = rel
        .components()
        .map(|c| c.as_os_str().to_string_lossy())
        .collect::<Vec<_>>()
        .join("/");
    if rel.is_empty() {
        return Err("Path must name an entry.".into());
    }
    Ok((root, rel))
}

fn history_value(history: &evo_office::versions::DocumentHistory) -> Result<Value, String> {
    let wire = wire::DocumentHistory {
        path: history.path.clone(),
        head: history.head.clone(),
        can_undo: history.can_undo(),
        can_redo: history.can_redo(),
        versions: history
            .versions
            .iter()
            .map(|v| wire::DocumentVersionInfo {
                id: v.id.clone(),
                size: v.size,
                created_at: v.created_at,
                label: v.label.clone(),
                source: v.source.clone(),
            })
            .collect(),
    };
    serde_json::to_value(wire).map_err(|e| e.to_string())
}

/// `document_versions_get` / `document_versions_act` (blocking).
fn document_versions(
    store: &DocumentVersions,
    kind: &str,
    msg: &Value,
    chat: &OfficeChat,
) -> Result<Value, String> {
    let live = chat.live_session();
    let session = chat.session_id.as_str();
    if kind == wire::DOCUMENT_VERSIONS_GET {
        let request: wire::DocumentVersionsGet = serde_json::from_value(msg.clone())
            .map_err(|e| format!("invalid {kind} request: {e}"))?;
        let (root, rel) = versioned_document(&chat.cwd, &request.path)?;
        let history = store
            .get_history(session, &root, &rel, live)
            .map_err(|e| e.to_string())?;
        return history_value(&history);
    }
    let request: wire::DocumentVersionsAct =
        serde_json::from_value(msg.clone()).map_err(|e| format!("invalid {kind} request: {e}"))?;
    let label = request.label.unwrap_or_default();
    if label.chars().count() > MAX_REQUEST_LABEL_CHARS {
        return Err(format!(
            "`label` is longer than {MAX_REQUEST_LABEL_CHARS} characters."
        ));
    }
    let (root, rel) = versioned_document(&chat.cwd, &request.path)?;
    let history = match request.action {
        wire::DocumentVersionAction::Checkpoint => {
            store.checkpoint(session, &root, &rel, &label, live)
        }
        wire::DocumentVersionAction::Restore => {
            let id = request
                .version_id
                .filter(|id| !id.is_empty())
                .ok_or("versionId is required.")?;
            if id.chars().count() > MAX_VERSION_ID_CHARS {
                return Err("versionId is too long.".into());
            }
            store.restore_version(session, &root, &rel, &id)
        }
        wire::DocumentVersionAction::Undo => store.step(session, &root, &rel, -1, live),
        wire::DocumentVersionAction::Redo => store.step(session, &root, &rel, 1, live),
    }
    .map_err(|e| e.to_string())?;
    history_value(&history)
}

/// Whether a changed path is one the viewer and the versions care about.
pub fn is_office_change(rel: &str) -> bool {
    evo_office::versions::is_versioned(rel) && !crate::fs_watch::has_hidden_segment(rel)
}

/// Folders too broad to poll: a filesystem root or the home folder (a chat
/// started without a project folder).
fn too_broad_to_watch(cwd: &Path) -> bool {
    cwd.parent().is_none() || dirs::home_dir().is_some_and(|home| home == cwd)
}

/// Watch the chat's folder for Office files: tell the client
/// (`office_file_changed`) and record each settled save as a version.
pub(crate) fn watch_office_files(
    chat: OfficeChat,
    out: crate::rpc::writer::RpcWriter,
) -> Option<crate::fs_watch::WatchHandle> {
    if !chat.cwd.is_dir() || too_broad_to_watch(&chat.cwd) {
        return None;
    }
    let root = chat.cwd.clone();
    let options = crate::fs_watch::TreeWatchOptions::default();
    Some(crate::fs_watch::watch_tree(
        root,
        is_office_change,
        options,
        move |changes| {
            let (chat, out) = (chat.clone(), out.clone());
            async move {
                let event = wire::OfficeFileChanged {
                    changes: changes
                        .iter()
                        .map(|change| wire::OfficeFileChange {
                            kind: match change.kind {
                                crate::fs_watch::TreeChangeKind::Added => {
                                    wire::OfficeChangeKind::Added
                                }
                                crate::fs_watch::TreeChangeKind::Modified => {
                                    wire::OfficeChangeKind::Modified
                                }
                                crate::fs_watch::TreeChangeKind::Deleted => {
                                    wire::OfficeChangeKind::Deleted
                                }
                            },
                            path: change.path.clone(),
                        })
                        .collect(),
                };
                if let Ok(value) = serde_json::to_value(&event) {
                    crate::rpc::writer::write_line(&out, &value).await;
                }
                let saved: Vec<String> = changes
                    .into_iter()
                    .filter(|c| c.kind != crate::fs_watch::TreeChangeKind::Deleted)
                    .map(|c| c.path)
                    .collect();
                if !saved.is_empty() {
                    let _ = tokio::task::spawn_blocking(move || record_saves(&chat, &saved)).await;
                }
            }
        },
    ))
}

/// Record settled saves as versions.
fn record_saves(chat: &OfficeChat, paths: &[String]) {
    for rel in paths {
        if let Err(error) = versions().record_version(
            &chat.session_id,
            &chat.cwd,
            rel,
            "",
            "change",
            chat.live_session(),
        ) {
            tracing::warn!(path = %rel, %error, "document_version_record_failed");
        }
    }
}

// ── The agent's shell ────────────────────────────────────────────────────────

/// The chat this engine serves (one engine per chat), for agent shells.
static CHAT_ID: OnceLock<String> = OnceLock::new();

/// Record the chat id this engine serves; agent shells get it as `EVO_CHAT_ID`.
pub fn set_chat_id(id: &str) {
    if !id.is_empty() {
        let _ = CHAT_ID.set(id.to_string());
    }
}

/// Advertise the installed runtime to agent shell commands: `EVO_SOFFICE` is the
/// executable, and its folder is appended to `PATH`. `EVO_CHAT_ID` names the
/// chat, so the live-build scripts (`deck_live.py`, `workbook_live.py`) stamp the
/// build plan with the chat that builds the file (v3 `EVOFLUX_SESSION`;
/// `EVO_SESSION_ID` is host plumbing and is kept out of shells). Evaluated per
/// command, so installing the runtime in the middle of a chat takes effect
/// immediately.
pub fn shell_env() -> ShellEnv {
    let mut env = match runtime().installed() {
        Some(installed) => ShellEnv {
            vars: vec![(
                "EVO_SOFFICE".into(),
                installed.executable.to_string_lossy().into_owned(),
            )],
            path_append: installed
                .executable
                .parent()
                .map(Path::to_path_buf)
                .into_iter()
                .collect(),
        },
        None => ShellEnv::default(),
    };
    if let Some(id) = CHAT_ID.get() {
        env.vars.push(("EVO_CHAT_ID".into(), id.clone()));
    }
    env
}

/// [`shell_env`] as a provider for `OsExecutionEnv::with_shell_env_provider`.
pub fn shell_env_provider() -> ShellEnvProvider {
    std::sync::Arc::new(shell_env)
}

// ── Embedded skills ──────────────────────────────────────────────────────────

static BUNDLED_SKILLS: Dir<'static> = include_dir!("$CARGO_MANIFEST_DIR/bundled-skills");

fn skills_fingerprint(dir: &Dir<'_>, hasher: &mut Sha256) {
    let mut entries: Vec<_> = dir.entries().iter().collect();
    entries.sort_by_key(|e| e.path().to_path_buf());
    for entry in entries {
        hasher.update(entry.path().to_string_lossy().as_bytes());
        match entry {
            include_dir::DirEntry::Dir(sub) => skills_fingerprint(sub, hasher),
            include_dir::DirEntry::File(file) => hasher.update(file.contents()),
        }
    }
}

/// Write the embedded skills under `base/bundled-skills/<fingerprint>/` (once per
/// content) and return that folder. Older copies are removed.
pub fn extract_bundled_skills(base: &Path) -> std::io::Result<PathBuf> {
    let mut hasher = Sha256::new();
    skills_fingerprint(&BUNDLED_SKILLS, &mut hasher);
    let id = format!("{:x}", hasher.finalize())[..16].to_string();
    let root = base.join("bundled-skills");
    let target = root.join(&id);
    if !target.join(".complete").is_file() {
        std::fs::create_dir_all(&root)?;
        let staging = root.join(format!(".staging-{id}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&staging);
        BUNDLED_SKILLS.extract(&staging)?;
        std::fs::write(staging.join(".complete"), b"")?;
        let _ = std::fs::remove_dir_all(&target);
        if let Err(error) = std::fs::rename(&staging, &target) {
            // Another engine process finished first: use its copy.
            let _ = std::fs::remove_dir_all(&staging);
            if !target.join(".complete").is_file() {
                return Err(error);
            }
        }
    }
    if let Ok(entries) = std::fs::read_dir(&root) {
        for entry in entries.flatten() {
            let name = entry.file_name().to_string_lossy().to_string();
            if name != id && !name.starts_with(".staging-") {
                let _ = std::fs::remove_dir_all(entry.path());
            }
        }
    }
    Ok(target)
}

/// The folder holding the embedded skills, extracted on first use.
pub fn bundled_skill_dirs() -> Vec<PathBuf> {
    // Unit tests build their own skill sets. The extraction is cached per
    // process in whichever agent dir the first caller had, so it would leak the
    // bundled skills into later tests depending on their order. The tests of
    // the bundled skills call `extract_bundled_skills` directly.
    if cfg!(test) {
        return Vec::new();
    }
    static DIR: OnceLock<Option<PathBuf>> = OnceLock::new();
    DIR.get_or_init(|| match extract_bundled_skills(&agent_dir()) {
        Ok(dir) => Some(dir),
        Err(error) => {
            tracing::warn!(%error, "could not extract the bundled skills");
            None
        }
    })
    .clone()
    .into_iter()
    .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

    #[test]
    fn the_embedded_skills_extract_once_and_replace_older_copies() {
        let dir = tempfile::tempdir().unwrap();
        let stale = dir.path().join("bundled-skills").join("0000000000000000");
        std::fs::create_dir_all(&stale).unwrap();
        let target = extract_bundled_skills(dir.path()).unwrap();
        assert!(!stale.exists());
        for skill in [
            "docx-official",
            "office-annotation-edit",
            "pptx-official",
            "xlsx-official",
        ] {
            assert!(target.join(skill).join("SKILL.md").is_file(), "{skill}");
        }
        // A second call reuses the extracted copy.
        let marker = target.join("docx-official").join("SKILL.md");
        let modified = std::fs::metadata(&marker).unwrap().modified().unwrap();
        assert_eq!(extract_bundled_skills(dir.path()).unwrap(), target);
        assert_eq!(
            std::fs::metadata(&marker).unwrap().modified().unwrap(),
            modified
        );
    }

    #[tokio::test]
    async fn the_bundled_skills_load_as_skills() {
        let dir = tempfile::tempdir().unwrap();
        let target = extract_bundled_skills(dir.path()).unwrap();
        let env: std::sync::Arc<dyn evo_tools::ExecutionEnv> = std::sync::Arc::new(
            evo_tools::OsExecutionEnv::with_cwd(dir.path().to_path_buf()),
        );
        let loaded = crate::resource_dirs::load_skills_with_precedence(&env, &[target]).await;
        let mut names: Vec<_> = loaded.skills.iter().map(|s| s.name.clone()).collect();
        names.sort();
        assert_eq!(
            names,
            [
                "docx-official",
                "office-annotation-edit",
                "pptx-official",
                "xlsx-official"
            ],
            "{:?}",
            loaded.diagnostics
        );
    }

    fn chat_in(cwd: &Path, running: bool) -> OfficeChat {
        OfficeChat {
            cwd: cwd.to_path_buf(),
            session_id: "chat-1".into(),
            run_active: Arc::new(AtomicBool::new(running)),
        }
    }

    fn zip_with(parts: &[(&str, &str)]) -> Vec<u8> {
        use std::io::Write;
        let mut bytes = Vec::new();
        {
            let mut zip = zip::ZipWriter::new(std::io::Cursor::new(&mut bytes));
            for (name, content) in parts {
                zip.start_file(*name, zip::write::SimpleFileOptions::default())
                    .unwrap();
                zip.write_all(content.as_bytes()).unwrap();
            }
            zip.finish().unwrap();
        }
        bytes
    }

    #[test]
    fn the_live_session_is_the_chat_only_while_its_turn_runs() {
        let chat = chat_in(Path::new("."), false);
        assert_eq!(chat.live_session(), None);
        chat.run_active.store(true, Ordering::Release);
        assert_eq!(chat.live_session(), Some("chat-1"));
    }

    #[test]
    fn the_live_plan_is_read_from_the_custom_properties() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("deck.pptx");
        let custom = r#"<?xml version="1.0"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"><property fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}" pid="2" name="evo.deck"><vt:lpwstr>{&quot;total&quot;:2,&quot;state&quot;:&quot;building&quot;,&quot;session&quot;:&quot;chat-1&quot;}</vt:lpwstr></property></Properties>"#;
        std::fs::write(&path, zip_with(&[("docProps/custom.xml", custom)])).unwrap();
        let plan = live_plan(&path).unwrap();
        assert!(plan.live_for(Some("chat-1")) && !plan.live_for(Some("chat-2")));
        std::fs::write(&path, zip_with(&[("ppt/presentation.xml", "<p/>")])).unwrap();
        assert!(live_plan(&path).is_none());
    }

    #[tokio::test]
    async fn office_preview_refuses_what_it_cannot_show() {
        let dir = tempfile::tempdir().unwrap();
        let chat = chat_in(dir.path(), false);
        std::fs::write(dir.path().join("notes.txt"), "x").unwrap();
        std::fs::create_dir_all(dir.path().join("folder")).unwrap();
        let ask =
            |path: &str, mode: &str| json!({"type": "office_preview", "path": path, "mode": mode});
        assert_eq!(
            rpc("office_preview", &ask("", "auto"), &chat)
                .await
                .unwrap_err(),
            "`path` is required"
        );
        assert_eq!(
            rpc("office_preview", &ask("notes.txt", "native"), &chat)
                .await
                .unwrap_err(),
            ".txt is not supported for document preview."
        );
        assert_eq!(
            rpc("office_preview", &ask("missing.pptx", "auto"), &chat)
                .await
                .unwrap_err(),
            "Document not found: missing.pptx"
        );
        assert_eq!(
            rpc("office_preview", &ask("folder", "auto"), &chat)
                .await
                .unwrap_err(),
            "Path is not a file: folder"
        );
        assert!(rpc("office_preview", &ask("notes.txt", "pixels"), &chat)
            .await
            .unwrap_err()
            .starts_with("invalid office_preview request"));
        assert!(rpc("office_nope", &json!({}), &chat).await.is_err());
    }

    #[test]
    fn document_versions_answer_with_the_history() {
        let dir = tempfile::tempdir().unwrap();
        let cwd = dir.path().join("ws");
        std::fs::create_dir_all(cwd.join("sub")).unwrap();
        let store = DocumentVersions::new(dir.path().join("document-versions"));
        let chat = chat_in(&cwd, false);
        let deck = cwd.join("sub").join("deck.pptx");
        std::fs::write(&deck, zip_with(&[("ppt/slides/slide1.xml", "one")])).unwrap();

        let get = json!({"type": "document_versions_get", "path": "sub/deck.pptx"});
        let history = document_versions(&store, "document_versions_get", &get, &chat).unwrap();
        assert_eq!(history["path"], "sub/deck.pptx");
        assert_eq!(history["canUndo"], false);
        assert_eq!(history["canRedo"], false);
        let first = &history["versions"][0];
        assert_eq!(first["source"], "baseline");
        assert_eq!(first["label"], "");
        assert!(first["createdAt"].as_f64().unwrap() > 1.0e9);
        assert_eq!(history["head"], first["id"]);
        assert_eq!(
            history
                .as_object()
                .unwrap()
                .keys()
                .cloned()
                .collect::<Vec<_>>(),
            ["path", "head", "canUndo", "canRedo", "versions"]
        );

        let act = |body: Value| document_versions(&store, "document_versions_act", &body, &chat);
        act(json!({"type": "document_versions_act", "path": deck.to_str().unwrap(), "action": "checkpoint", "label": "Make it blue"}))
            .unwrap();
        std::fs::write(&deck, zip_with(&[("ppt/slides/slide1.xml", "two")])).unwrap();
        let history = act(json!({"path": "sub/deck.pptx", "action": "undo"})).unwrap();
        assert_eq!(history["versions"][1]["label"], "Make it blue");
        assert_eq!(history["canRedo"], true);
        let history = act(json!({"path": "sub/deck.pptx", "action": "redo"})).unwrap();
        assert_eq!(history["canRedo"], false);
        assert_eq!(
            act(json!({"path": "sub/deck.pptx", "action": "redo"})).unwrap_err(),
            "Nothing to redo."
        );
        assert_eq!(
            act(json!({"path": "sub/deck.pptx", "action": "restore"})).unwrap_err(),
            "versionId is required."
        );
        assert_eq!(
            act(json!({"path": "sub/deck.pptx", "action": "restore", "versionId": "nope"}))
                .unwrap_err(),
            "That version no longer exists."
        );

        std::fs::write(cwd.join("notes.txt"), "x").unwrap();
        let get_path = |path: &str| {
            document_versions(
                &store,
                "document_versions_get",
                &json!({"path": path}),
                &chat,
            )
            .unwrap_err()
        };
        assert_eq!(
            get_path("notes.txt"),
            "Only Word, Excel and PowerPoint files keep versions."
        );
        assert_eq!(get_path("missing.docx"), "Document not found.");
        assert_eq!(get_path("../x.docx"), "Path must not traverse upward.");
        let outside = dir.path().join("outside.xlsx");
        std::fs::write(&outside, zip_with(&[("a", "b")])).unwrap();
        assert_eq!(
            get_path(outside.to_str().unwrap()),
            "Path escapes workspace root."
        );
    }

    #[test]
    fn office_changes_skip_hidden_paths_and_lock_files() {
        assert!(is_office_change("deck.pptx") && is_office_change("a/b/Book.xlsx"));
        assert!(!is_office_change(".cache/deck.pptx"));
        assert!(!is_office_change("~$deck.pptx"));
        assert!(!is_office_change("notes.pdf"));
    }

    #[test]
    fn the_cache_key_changes_with_the_file_and_the_runtime() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("a.docx");
        std::fs::write(&path, b"one").unwrap();
        let first = cache_key(&path, &std::fs::metadata(&path).unwrap(), "1");
        assert_eq!(
            first,
            cache_key(&path, &std::fs::metadata(&path).unwrap(), "1")
        );
        assert_ne!(
            first,
            cache_key(&path, &std::fs::metadata(&path).unwrap(), "2")
        );
        std::fs::write(&path, b"three").unwrap();
        assert_ne!(
            first,
            cache_key(&path, &std::fs::metadata(&path).unwrap(), "1")
        );
    }

    #[test]
    fn pruning_removes_the_oldest_and_keeps_the_new_file() {
        let dir = tempfile::tempdir().unwrap();
        let write = |name: &str, age_s: u64| {
            let path = dir.path().join(name);
            std::fs::write(&path, vec![0u8; 100]).unwrap();
            let when = SystemTime::now() - Duration::from_secs(age_s);
            std::fs::File::options()
                .write(true)
                .open(&path)
                .unwrap()
                .set_modified(when)
                .unwrap();
            path
        };
        let old = write("old.pdf", 300);
        let mid = write("mid.pdf", 200);
        let new = write("new.pdf", 0);
        prune_cache(dir.path(), &new, 150);
        assert!(!old.exists() && !mid.exists() && new.exists());
    }

    #[tokio::test]
    async fn conversion_refuses_what_it_cannot_do() {
        let dir = tempfile::tempdir().unwrap();
        let text = dir.path().join("a.txt");
        std::fs::write(&text, b"x").unwrap();
        assert!(convert(text.to_str().unwrap())
            .await
            .unwrap_err()
            .contains("Unsupported"));
        assert!(convert(dir.path().join("missing.docx").to_str().unwrap())
            .await
            .is_err());
        assert!(convert(dir.path().to_str().unwrap()).await.is_err());
    }

    #[test]
    fn unknown_management_actions_are_rejected() {
        assert!(manage("office_nope").is_err());
    }
}
