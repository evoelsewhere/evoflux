//! Office documents in the engine: the LibreOffice runtime, the preview cache,
//! the shell environment that exposes the runtime to the agent, and the Office
//! skills embedded in the binary.
//!
//! Design: `docs/features/office/sdd.md` (ADR 0008). The management RPCs
//! (`office_status`, `office_install`, …) mirror the language-server ones: the
//! UI starts an install and polls the status.

use std::path::{Path, PathBuf};
use std::sync::OnceLock;
use std::time::SystemTime;

use evo_office::Runtime;
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
    let modified = meta.modified().ok().and_then(|t| t.duration_since(SystemTime::UNIX_EPOCH).ok()).map_or(0, |d| d.as_millis());
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
    let Ok(entries) = std::fs::read_dir(dir) else { return };
    let mut files: Vec<(SystemTime, u64, PathBuf)> = entries
        .flatten()
        .filter_map(|e| {
            let meta = e.metadata().ok()?;
            (meta.is_file() && e.path().extension().is_some_and(|x| x == "pdf"))
                .then(|| (meta.modified().unwrap_or(SystemTime::UNIX_EPOCH), meta.len(), e.path()))
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
    let meta = tokio::fs::metadata(&source).await.map_err(|e| format!("Cannot read {path}: {e}"))?;
    if !meta.is_file() {
        return Err(format!("{path} is not a file"));
    }
    let extension = source.extension().and_then(|e| e.to_str()).unwrap_or("");
    if !evo_office::supports(extension) {
        return Err(format!("Unsupported type: .{extension}"));
    }
    if meta.len() > MAX_DOCUMENT_BYTES {
        return Err(format!("Documents over {} MB are not converted", MAX_DOCUMENT_BYTES / 1024 / 1024));
    }
    let runtime = runtime();
    let installed = runtime.installed().ok_or_else(|| evo_office::Error::NotInstalled.to_string())?;
    let canonical = tokio::fs::canonicalize(&source).await.unwrap_or_else(|_| source.clone());
    let dir = cache_dir();
    let target = dir.join(format!("{}.pdf", cache_key(&canonical, &meta, &installed.version)));
    if tokio::fs::metadata(&target).await.map(|m| m.len() > 0).unwrap_or(false) {
        // Touch it so pruning keeps what is in use.
        let _ = tokio::task::spawn_blocking({
            let target = target.clone();
            move || std::fs::File::options().write(true).open(&target).and_then(|f| f.set_modified(SystemTime::now()))
        })
        .await;
        return Ok(json!({ "pdf": target, "version": installed.version, "cached": true }));
    }
    tokio::fs::create_dir_all(&dir).await.map_err(|e| e.to_string())?;
    let work = tempfile::Builder::new().prefix("convert-").tempdir_in(&dir).map_err(|e| e.to_string())?;
    let pdf = runtime
        .convert_to_pdf(&source, work.path(), evo_office::CONVERSION_TIMEOUT)
        .await
        .map_err(|e| format!("Conversion failed: {e}"))?;
    if tokio::fs::rename(&pdf, &target).await.is_err() {
        tokio::fs::copy(&pdf, &target).await.map_err(|e| e.to_string())?;
    }
    let (prune_dir, keep) = (dir, target.clone());
    let _ = tokio::task::spawn_blocking(move || prune_cache(&prune_dir, &keep, CACHE_LIMIT_BYTES)).await;
    Ok(json!({ "pdf": target, "version": installed.version, "cached": false }))
}

// ── The agent's shell ────────────────────────────────────────────────────────

/// Advertise the installed runtime to agent shell commands: `EVO_SOFFICE` is the
/// executable, and its folder is appended to `PATH`. Evaluated per command, so
/// installing the runtime in the middle of a chat takes effect immediately.
pub fn shell_env() -> ShellEnv {
    match runtime().installed() {
        Some(installed) => ShellEnv {
            vars: vec![("EVO_SOFFICE".into(), installed.executable.to_string_lossy().into_owned())],
            path_append: installed.executable.parent().map(Path::to_path_buf).into_iter().collect(),
        },
        None => ShellEnv::default(),
    }
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
        for skill in ["docx-official", "pptx-official", "xlsx-official"] {
            assert!(target.join(skill).join("SKILL.md").is_file(), "{skill}");
        }
        // A second call reuses the extracted copy.
        let marker = target.join("docx-official").join("SKILL.md");
        let modified = std::fs::metadata(&marker).unwrap().modified().unwrap();
        assert_eq!(extract_bundled_skills(dir.path()).unwrap(), target);
        assert_eq!(std::fs::metadata(&marker).unwrap().modified().unwrap(), modified);
    }

    #[tokio::test]
    async fn the_bundled_skills_load_as_skills() {
        let dir = tempfile::tempdir().unwrap();
        let target = extract_bundled_skills(dir.path()).unwrap();
        let env: std::sync::Arc<dyn evo_tools::ExecutionEnv> =
            std::sync::Arc::new(evo_tools::OsExecutionEnv::with_cwd(dir.path().to_path_buf()));
        let loaded = crate::resource_dirs::load_skills_with_precedence(&env, &[target]).await;
        let mut names: Vec<_> = loaded.skills.iter().map(|s| s.name.clone()).collect();
        names.sort();
        assert_eq!(names, ["docx-official", "pptx-official", "xlsx-official"], "{:?}", loaded.diagnostics);
    }

    #[test]
    fn the_cache_key_changes_with_the_file_and_the_runtime() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("a.docx");
        std::fs::write(&path, b"one").unwrap();
        let first = cache_key(&path, &std::fs::metadata(&path).unwrap(), "1");
        assert_eq!(first, cache_key(&path, &std::fs::metadata(&path).unwrap(), "1"));
        assert_ne!(first, cache_key(&path, &std::fs::metadata(&path).unwrap(), "2"));
        std::fs::write(&path, b"three").unwrap();
        assert_ne!(first, cache_key(&path, &std::fs::metadata(&path).unwrap(), "1"));
    }

    #[test]
    fn pruning_removes_the_oldest_and_keeps_the_new_file() {
        let dir = tempfile::tempdir().unwrap();
        let write = |name: &str, age_s: u64| {
            let path = dir.path().join(name);
            std::fs::write(&path, vec![0u8; 100]).unwrap();
            let when = SystemTime::now() - Duration::from_secs(age_s);
            std::fs::File::options().write(true).open(&path).unwrap().set_modified(when).unwrap();
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
        assert!(convert(text.to_str().unwrap()).await.unwrap_err().contains("Unsupported"));
        assert!(convert(dir.path().join("missing.docx").to_str().unwrap()).await.is_err());
        assert!(convert(dir.path().to_str().unwrap()).await.is_err());
    }

    #[test]
    fn unknown_management_actions_are_rejected() {
        assert!(manage("office_nope").is_err());
    }
}
