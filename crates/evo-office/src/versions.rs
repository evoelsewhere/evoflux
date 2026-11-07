//! Document versions: every settled save of an Office file is a version the
//! person can undo, redo or restore (v3 `app/services/document_versions.py`).
//!
//! Every settled save of a `.pptx`/`.docx`/`.xlsx` becomes a version, so a
//! person can step an agent's edits back and forward (undo/redo) or roll a file
//! back to any earlier version from the document viewer. History is per file
//! and independent of the conversation: it never rewinds chat or other files.
//!
//! Storage lives outside the workspace, under the directory given to
//! [`DocumentVersions::new`] (the engine passes `<agent>/document-versions`):
//! `<chat>/<sha256(rel path)[:32]>/manifest.json` plus content-addressed
//! `blobs/<sha256>`, so identical versions share bytes. The history is linear
//! like an editor's: undo/redo move `head`; a new save made while `head` is
//! behind the newest version drops the versions after it.
//!
//! Versions are recorded when the viewer asks for a file's history (catching
//! changes made while nobody watched), at checkpoints the client takes before
//! sending an edit request, and by the engine's watcher on every settled save.
//! A deck or workbook the chat is still building live is skipped until it is
//! finished, and files read mid-write (not a complete ZIP package) are ignored
//! until the next save.
//!
//! Design: `docs/features/office-v3-parity/sdd.md`.

use std::collections::HashMap;
use std::io::Cursor;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex, MutexGuard};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

/// Extensions (lower case, no dot) whose files keep versions.
pub const VERSIONED_EXTENSIONS: [&str; 3] = ["pptx", "docx", "xlsx"];
/// Versions kept per file; older ones are dropped.
pub const MAX_VERSIONS: usize = 50;
/// Larger files are not versioned.
pub const MAX_FILE_BYTES: u64 = 256 * 1024 * 1024;
/// Labels are cut to this many characters.
pub const MAX_LABEL_CHARS: usize = 200;
/// How often a restore retries replacing a file another program holds.
const REPLACE_ATTEMPTS: u32 = 20;
const REPLACE_RETRY_DELAY: Duration = Duration::from_millis(50);

/// What a history operation can fail with. Messages are shown as they are.
#[derive(Debug, thiserror::Error)]
pub enum VersionError {
    /// The operation cannot be carried out (v3 `DocumentVersionError`).
    #[error("{0}")]
    Invalid(String),
    /// Windows: the file stayed locked by another program.
    #[error("The file is open elsewhere; close it and retry.")]
    Locked,
    #[error("{0}")]
    Io(#[from] std::io::Error),
}

impl VersionError {
    fn invalid(message: &str) -> Self {
        Self::Invalid(message.to_string())
    }
}

/// One recorded version of a file.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct DocumentVersion {
    pub id: String,
    pub sha256: String,
    pub size: u64,
    /// Seconds since the Unix epoch.
    pub created_at: f64,
    #[serde(default)]
    pub label: String,
    /// `baseline` (first version), `change`, or `checkpoint`.
    #[serde(default = "default_source")]
    pub source: String,
}

fn default_source() -> String {
    "change".into()
}

/// The history of one file.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct DocumentHistory {
    /// The file, relative to the chat's folder, with `/` separators.
    pub path: String,
    pub versions: Vec<DocumentVersion>,
    pub head: Option<String>,
}

impl DocumentHistory {
    fn empty(path: &str) -> Self {
        Self {
            path: path.to_string(),
            ..Self::default()
        }
    }

    /// Index of the head version (the newest when `head` names none); -1 when
    /// there are no versions.
    pub fn head_index(&self) -> isize {
        self.versions
            .iter()
            .position(|v| Some(&v.id) == self.head.as_ref())
            .map_or(self.versions.len() as isize - 1, |i| i as isize)
    }

    pub fn can_undo(&self) -> bool {
        self.head_index() > 0
    }

    pub fn can_redo(&self) -> bool {
        let index = self.head_index();
        0 <= index && index < self.versions.len() as isize - 1
    }
}

#[derive(Serialize, Deserialize)]
struct Manifest {
    path: String,
    head: Option<String>,
    versions: Vec<DocumentVersion>,
}

/// Whether `rel_path` names a document that keeps versions.
pub fn is_versioned(rel_path: &str) -> bool {
    let name = rel_path.rsplit(['/', '\\']).next().unwrap_or("");
    // `~$deck.pptx` is an Office lock file, not a document.
    let extension = Path::new(name)
        .extension()
        .map(|e| e.to_string_lossy().to_ascii_lowercase())
        .unwrap_or_default();
    VERSIONED_EXTENSIONS.contains(&extension.as_str()) && !name.starts_with("~$")
}

/// The version store of one engine (one per process).
pub struct DocumentVersions {
    root: PathBuf,
    locks: Mutex<HashMap<PathBuf, Arc<Mutex<()>>>>,
    /// Labels for the next recorded change of a file, set by a checkpoint taken
    /// right before an edit request: `(chat, path) -> label`.
    pending_labels: Mutex<HashMap<(String, String), String>>,
}

impl DocumentVersions {
    /// A store keeping its histories under `root`.
    pub fn new(root: impl Into<PathBuf>) -> Self {
        Self {
            root: root.into(),
            locks: Mutex::default(),
            pending_labels: Mutex::default(),
        }
    }

    pub fn root(&self) -> &Path {
        &self.root
    }

    /// Where the history of `rel_path` in `chat` lives.
    pub fn history_dir(&self, chat: &str, rel_path: &str) -> PathBuf {
        let key = hex(&Sha256::digest(rel_path.as_bytes()));
        self.root.join(chat_dir_name(chat)).join(&key[..32])
    }

    /// Delete every history of `chat` (when the chat is deleted).
    pub fn delete_chat(&self, chat: &str) -> std::io::Result<()> {
        match std::fs::remove_dir_all(self.root.join(chat_dir_name(chat))) {
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
            other => other,
        }
    }

    fn lock_for(&self, directory: &Path) -> Arc<Mutex<()>> {
        lock(&self.locks)
            .entry(directory.to_path_buf())
            .or_default()
            .clone()
    }

    /// Record the file's current content as a version when it changed.
    ///
    /// `live_session` is the chat whose turn is running, if any: a deck or
    /// workbook it is building live saves once per part and is skipped until
    /// the build is finished.
    pub fn record_version(
        &self,
        chat: &str,
        root: &Path,
        rel_path: &str,
        label: &str,
        source: &str,
        live_session: Option<&str>,
    ) -> Result<DocumentHistory, VersionError> {
        let directory = self.history_dir(chat, rel_path);
        let guard = self.lock_for(&directory);
        let _held = lock(&guard);
        let mut history = load(&directory, rel_path);
        if !is_versioned(rel_path) {
            return Ok(history);
        }
        let path = root.join(rel_path);
        let Some(data) = read_document(&path) else {
            return Ok(history);
        };
        if being_built(&path, &data, live_session) {
            return Ok(history);
        }
        let key = (chat.to_string(), rel_path.to_string());
        let pending = lock(&self.pending_labels).get(&key).cloned();
        let chosen = if label.is_empty() {
            pending.clone().unwrap_or_default()
        } else {
            label.to_string()
        };
        let source = if history.versions.is_empty() {
            "baseline"
        } else {
            source
        };
        if record_locked(&directory, &mut history, &data, &chosen, source)? {
            if pending.is_some() && label.is_empty() {
                lock(&self.pending_labels).remove(&key);
            }
            save(&directory, &history)?;
        }
        Ok(history)
    }

    /// Capture the file before an edit request; its next change gets `label`.
    pub fn checkpoint(
        &self,
        chat: &str,
        root: &Path,
        rel_path: &str,
        label: &str,
        live_session: Option<&str>,
    ) -> Result<DocumentHistory, VersionError> {
        let history = self.record_version(chat, root, rel_path, "", "checkpoint", live_session)?;
        let label = label.trim();
        if !label.is_empty() {
            lock(&self.pending_labels).insert(
                (chat.to_string(), rel_path.to_string()),
                truncate_chars(label, MAX_LABEL_CHARS),
            );
        }
        Ok(history)
    }

    /// The file's history, first recording any change made while unwatched.
    pub fn get_history(
        &self,
        chat: &str,
        root: &Path,
        rel_path: &str,
        live_session: Option<&str>,
    ) -> Result<DocumentHistory, VersionError> {
        self.record_version(chat, root, rel_path, "", "change", live_session)
    }

    /// Write `version_id` back to the folder and make it the head.
    pub fn restore_version(
        &self,
        chat: &str,
        root: &Path,
        rel_path: &str,
        version_id: &str,
    ) -> Result<DocumentHistory, VersionError> {
        let directory = self.history_dir(chat, rel_path);
        let path = root.join(rel_path);
        let guard = self.lock_for(&directory);
        let _held = lock(&guard);
        let mut history = load(&directory, rel_path);
        let target = history
            .versions
            .iter()
            .find(|v| v.id == version_id)
            .cloned()
            .ok_or_else(|| VersionError::invalid("That version no longer exists."))?;
        // Never lose unrecorded work: keep what is on disk as a version first.
        if let Some(current) = read_document(&path) {
            if record_locked(&directory, &mut history, &current, "", "change")? {
                save(&directory, &history)?;
                if !history.versions.contains(&target) {
                    return Err(VersionError::invalid(
                        "The file changed since, so that version was replaced.",
                    ));
                }
            }
        }
        let data = std::fs::read(directory.join("blobs").join(&target.sha256))
            .map_err(|_| VersionError::invalid("That version's content is missing."))?;
        write_atomic(&path, &data)?;
        history.head = Some(target.id);
        save(&directory, &history)?;
        Ok(history)
    }

    /// Undo (`offset = -1`) or redo (`offset = 1`) one version.
    pub fn step(
        &self,
        chat: &str,
        root: &Path,
        rel_path: &str,
        offset: isize,
        live_session: Option<&str>,
    ) -> Result<DocumentHistory, VersionError> {
        let history = self.get_history(chat, root, rel_path, live_session)?;
        let index = history.head_index() + offset;
        if index < 0 || index >= history.versions.len() as isize {
            return Err(VersionError::invalid(if offset < 0 {
                "Nothing to undo."
            } else {
                "Nothing to redo."
            }));
        }
        let id = history.versions[index as usize].id.clone();
        self.restore_version(chat, root, rel_path, &id)
    }
}

fn lock<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    mutex.lock().unwrap_or_else(|e| e.into_inner())
}

/// A chat id as one safe folder name.
fn chat_dir_name(chat: &str) -> String {
    let name: String = chat
        .chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() || c == '-' || c == '_' {
                c
            } else {
                '_'
            }
        })
        .collect();
    if name.is_empty() {
        "_".into()
    } else {
        name
    }
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

fn truncate_chars(text: &str, max: usize) -> String {
    text.chars().take(max).collect()
}

/// A short random-looking hex id (v3 `uuid4().hex[:n]`).
fn unique_hex(len: usize) -> String {
    static COUNTER: AtomicU64 = AtomicU64::new(0);
    let mut hasher = Sha256::new();
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default();
    hasher.update(now.as_nanos().to_le_bytes());
    hasher.update(COUNTER.fetch_add(1, Ordering::Relaxed).to_le_bytes());
    hasher.update(std::process::id().to_le_bytes());
    hex(&hasher.finalize())[..len].to_string()
}

fn now_seconds() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0)
}

fn load(directory: &Path, rel_path: &str) -> DocumentHistory {
    let text = match std::fs::read_to_string(directory.join("manifest.json")) {
        Ok(text) => text,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            return DocumentHistory::empty(rel_path)
        }
        Err(error) => {
            tracing::warn!(dir = %directory.display(), %error, "document_versions_manifest_unreadable");
            return DocumentHistory::empty(rel_path);
        }
    };
    match serde_json::from_str::<Manifest>(&text) {
        Ok(manifest) => DocumentHistory {
            path: rel_path.to_string(),
            versions: manifest.versions,
            head: manifest.head,
        },
        Err(error) => {
            tracing::warn!(dir = %directory.display(), %error, "document_versions_manifest_unreadable");
            DocumentHistory::empty(rel_path)
        }
    }
}

fn save(directory: &Path, history: &DocumentHistory) -> std::io::Result<()> {
    std::fs::create_dir_all(directory)?;
    let manifest = Manifest {
        path: history.path.clone(),
        head: history.head.clone(),
        versions: history.versions.clone(),
    };
    let mut text = Vec::new();
    let formatter = serde_json::ser::PrettyFormatter::with_indent(b" ");
    let mut serializer = serde_json::Serializer::with_formatter(&mut text, formatter);
    manifest
        .serialize(&mut serializer)
        .map_err(std::io::Error::other)?;
    let temporary = directory.join(format!(".manifest.{}.tmp", unique_hex(32)));
    std::fs::write(&temporary, text)?;
    std::fs::rename(&temporary, directory.join("manifest.json")).inspect_err(|_| {
        let _ = std::fs::remove_file(&temporary);
    })
}

/// Bytes of a complete document, or `None` while it is missing or mid-write.
pub fn read_document(path: &Path) -> Option<Vec<u8>> {
    let meta = std::fs::metadata(path).ok()?;
    if !meta.is_file() || meta.len() > MAX_FILE_BYTES {
        return None;
    }
    let data = std::fs::read(path).ok()?;
    // A file caught mid-save has no central directory yet.
    zip::ZipArchive::new(Cursor::new(data.as_slice())).ok()?;
    Some(data)
}

/// A deck or workbook the running chat is still building saves once per part.
fn being_built(path: &Path, data: &[u8], live_session: Option<&str>) -> bool {
    let extension = crate::preview::extension(path);
    if !crate::preview::live::LIVE_EXTENSIONS.contains(&extension.as_str()) {
        return false;
    }
    crate::preview::live::read_plan_bytes(data).is_some_and(|plan| plan.live_for(live_session))
}

/// Whether an error means another program holds the file (Python's
/// `PermissionError`, which includes Windows sharing violations).
fn is_locked(error: &std::io::Error) -> bool {
    if error.kind() == std::io::ErrorKind::PermissionDenied {
        return true;
    }
    // ERROR_ACCESS_DENIED, ERROR_SHARING_VIOLATION, ERROR_LOCK_VIOLATION.
    cfg!(windows) && matches!(error.raw_os_error(), Some(5 | 32 | 33))
}

fn write_atomic(path: &Path, data: &[u8]) -> Result<(), VersionError> {
    let name = path
        .file_name()
        .map(|n| n.to_string_lossy().into_owned())
        .unwrap_or_default();
    let temporary = path.with_file_name(format!(".{name}.{}.restore", unique_hex(8)));
    if let Err(error) = std::fs::write(&temporary, data) {
        let _ = std::fs::remove_file(&temporary);
        return Err(if is_locked(&error) {
            VersionError::Locked
        } else {
            error.into()
        });
    }
    for attempt in 0..REPLACE_ATTEMPTS {
        match std::fs::rename(&temporary, path) {
            Ok(()) => return Ok(()),
            // Windows: a viewer or antivirus may hold the file briefly.
            Err(error) if is_locked(&error) => {
                if attempt == REPLACE_ATTEMPTS - 1 {
                    let _ = std::fs::remove_file(&temporary);
                    return Err(VersionError::Locked);
                }
                std::thread::sleep(REPLACE_RETRY_DELAY);
            }
            Err(error) => {
                let _ = std::fs::remove_file(&temporary);
                return Err(error.into());
            }
        }
    }
    Ok(())
}

/// Append `data` as the new head unless it already is. The caller holds the
/// file's lock.
fn record_locked(
    directory: &Path,
    history: &mut DocumentHistory,
    data: &[u8],
    label: &str,
    source: &str,
) -> std::io::Result<bool> {
    let digest = hex(&Sha256::digest(data));
    let index = history.head_index();
    if index >= 0 && history.versions[index as usize].sha256 == digest {
        return Ok(false);
    }
    // A new save after undo replaces the redo branch, like an editor.
    let keep = (index + 1) as usize;
    let mut removed = history.versions.split_off(keep.min(history.versions.len()));
    let version = DocumentVersion {
        id: unique_hex(12),
        sha256: digest.clone(),
        size: data.len() as u64,
        created_at: now_seconds(),
        label: truncate_chars(label, MAX_LABEL_CHARS),
        source: source.to_string(),
    };
    let blobs = directory.join("blobs");
    std::fs::create_dir_all(&blobs)?;
    let blob = blobs.join(&digest);
    if !blob.exists() {
        let temporary = blobs.join(format!(".{digest}.{}.tmp", unique_hex(8)));
        std::fs::write(&temporary, data)?;
        std::fs::rename(&temporary, &blob).inspect_err(|_| {
            let _ = std::fs::remove_file(&temporary);
        })?;
    }
    history.head = Some(version.id.clone());
    history.versions.push(version);
    if history.versions.len() > MAX_VERSIONS {
        let excess = history.versions.len() - MAX_VERSIONS;
        removed.extend(history.versions.drain(..excess));
    }
    for old in removed {
        if !history.versions.iter().any(|v| v.sha256 == old.sha256) {
            let _ = std::fs::remove_file(blobs.join(&old.sha256));
        }
    }
    Ok(true)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn versioned_names() {
        assert!(is_versioned("deck.pptx"));
        assert!(is_versioned("a/b/Book.XLSX"));
        assert!(is_versioned("a\\memo.docx"));
        assert!(!is_versioned("~$deck.pptx"));
        assert!(!is_versioned("dir/~$deck.pptx"));
        assert!(!is_versioned("notes.pdf"));
        assert!(!is_versioned("pptx"));
    }

    #[test]
    fn head_index_follows_python() {
        let version = |id: &str| DocumentVersion {
            id: id.into(),
            sha256: id.into(),
            size: 1,
            created_at: 0.0,
            label: String::new(),
            source: "change".into(),
        };
        let mut history = DocumentHistory::empty("a.pptx");
        assert_eq!(history.head_index(), -1);
        assert!(!history.can_undo() && !history.can_redo());
        history.versions = vec![version("a"), version("b"), version("c")];
        assert_eq!(history.head_index(), 2);
        history.head = Some("b".into());
        assert!(history.can_undo() && history.can_redo());
        history.head = Some("gone".into());
        assert_eq!(history.head_index(), 2);
    }

    #[test]
    fn chat_ids_stay_one_folder() {
        assert_eq!(chat_dir_name("../x"), "___x");
        assert_eq!(chat_dir_name("0190-ab_C"), "0190-ab_C");
        assert_eq!(chat_dir_name(""), "_");
    }
}
