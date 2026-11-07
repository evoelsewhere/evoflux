//! The preview cache (v3 `service.py` `_cache_path` and
//! `_render_document_preview`, and the cache helpers of `security.py`).
//!
//! A render is stored as `<cache_dir>/<sha256>.html`, keyed by the markup
//! schema, the renderer identity (`native` or `native-live`), the extension,
//! the file name and the bytes. Renders of one key are serialized by 32 striped
//! locks; the HTML is written to a temporary file in the same folder and renamed
//! into place. The folder is pruned after every render: least recently used
//! entries beyond 96 files or 512 MB, and temporary files or page folders older
//! than a day. Pruning only touches names the cache owns and never follows a
//! symbolic link.

use std::fs;
use std::io::{self, Write};
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::path::{Path, PathBuf};
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, SystemTime};

use regex::Regex;
use sha2::{Digest, Sha256};

use super::live::{self, DeckPlan};
use super::{
    extension, security, supports, PreviewError, CACHE_SCHEMA_VERSION, MAX_HTML_BYTES,
    MAX_SOURCE_BYTES,
};

pub const MAX_DOCUMENT_PREVIEW_CACHE_ENTRIES: usize = 96;
pub const MAX_DOCUMENT_PREVIEW_CACHE_BYTES: u64 = 512 * 1024 * 1024;
pub const STALE_DOCUMENT_PREVIEW_TEMP_SECONDS: u64 = 24 * 60 * 60;

const LOCK_STRIPES: usize = 32;
static RENDER_LOCKS: [Mutex<()>; LOCK_STRIPES] = [const { Mutex::new(()) }; LOCK_STRIPES];

/// How much the cache keeps (v3 module constants; tests lower them).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CacheLimits {
    pub max_entries: usize,
    pub max_bytes: u64,
    pub stale_temp: Duration,
}

impl Default for CacheLimits {
    fn default() -> Self {
        Self {
            max_entries: MAX_DOCUMENT_PREVIEW_CACHE_ENTRIES,
            max_bytes: MAX_DOCUMENT_PREVIEW_CACHE_BYTES,
            stale_temp: Duration::from_secs(STALE_DOCUMENT_PREVIEW_TEMP_SECONDS),
        }
    }
}

/// Render `source` natively (cached) for the chat `live_session`.
pub fn render_cached(
    cache_dir: &Path,
    source: &Path,
    live_session: Option<&str>,
) -> Result<PathBuf, PreviewError> {
    render_cached_with(
        cache_dir,
        source,
        live_session,
        &CacheLimits::default(),
        super::render_html,
    )
}

/// [`render_cached`] with explicit limits and renderer.
pub fn render_cached_with<F>(
    cache_dir: &Path,
    source: &Path,
    live_session: Option<&str>,
    limits: &CacheLimits,
    render: F,
) -> Result<PathBuf, PreviewError>
where
    F: FnOnce(&Path, &[u8], Option<&DeckPlan>) -> Result<String, PreviewError>,
{
    let suffix = extension(source);
    if !supports(source) {
        let shown = if suffix.is_empty() {
            "This file type".to_string()
        } else {
            format!(".{suffix}")
        };
        return Err(PreviewError::unsupported(format!(
            "{shown} is not supported for document preview."
        )));
    }
    let too_large = || {
        PreviewError::unsupported(format!(
            "Document preview is limited to {} MB.",
            MAX_SOURCE_BYTES / (1024 * 1024)
        ))
    };
    if fs::metadata(source)?.len() > MAX_SOURCE_BYTES {
        return Err(too_large());
    }
    let bytes = fs::read(source)?;
    if bytes.len() as u64 > MAX_SOURCE_BYTES {
        return Err(too_large());
    }
    security::preflight(source, &bytes)?;

    let plan = if live::LIVE_EXTENSIONS.contains(&suffix.as_str()) {
        live::read_plan_bytes(&bytes).filter(|plan| plan.live_for(live_session))
    } else {
        None
    };
    let output = cache_path(cache_dir, source, plan.is_some(), &bytes);
    let _guard = lock_for(&output);

    prepare_cache_directory(cache_dir)?;
    if cached_preview_is_valid(&output) {
        mark_cached_preview_used(&output);
        maintain_cache(cache_dir, Some(&output), SystemTime::now(), limits)?;
        if cached_preview_is_valid(&output) {
            return Ok(output);
        }
    }
    match fs::symlink_metadata(&output) {
        Err(e) if e.kind() == io::ErrorKind::NotFound => {}
        Err(e) => return Err(e.into()),
        Ok(metadata) if metadata.is_dir() => {
            return Err(PreviewError::failed(
                "The document preview cache entry is unsafe.",
            ));
        }
        Ok(_) => remove_link_or_file(&output)?,
    }

    maintain_cache(cache_dir, None, SystemTime::now(), limits)?;
    let stem = output
        .file_stem()
        .map(|s| s.to_string_lossy().into_owned())
        .unwrap_or_default();
    let mut temporary = tempfile::Builder::new()
        .prefix(&format!(".{stem}-"))
        .suffix(".tmp")
        .tempfile_in(cache_dir)?;
    let rendered = render_guarded(render, source, &bytes, plan.as_ref())?;
    if rendered.len() > MAX_HTML_BYTES {
        return Err(PreviewError::unsupported(
            "The generated preview is too large for the in-app viewer. \
Download the document to inspect it externally.",
        ));
    }
    temporary.write_all(rendered.as_bytes())?;
    temporary.flush()?;
    temporary
        .persist(&output)
        .map_err(|e| PreviewError::Io(e.error))?;
    maintain_cache(cache_dir, Some(&output), SystemTime::now(), limits)?;
    Ok(output)
}

/// Run a renderer; anything but a preview error becomes "Could not render this
/// document: …" (v3 `_render_source`), a panic included.
fn render_guarded<F>(
    render: F,
    source: &Path,
    bytes: &[u8],
    plan: Option<&DeckPlan>,
) -> Result<String, PreviewError>
where
    F: FnOnce(&Path, &[u8], Option<&DeckPlan>) -> Result<String, PreviewError>,
{
    match catch_unwind(AssertUnwindSafe(|| render(source, bytes, plan))) {
        Ok(Ok(html)) => Ok(html),
        Ok(Err(PreviewError::Io(e))) => Err(PreviewError::failed(format!(
            "Could not render this document: {e}"
        ))),
        Ok(Err(other)) => Err(other),
        Err(panic) => {
            let reason = panic
                .downcast_ref::<&str>()
                .map(|s| s.to_string())
                .or_else(|| panic.downcast_ref::<String>().cloned())
                .unwrap_or_else(|| "the renderer stopped unexpectedly".to_string());
            Err(PreviewError::failed(format!(
                "Could not render this document: {reason}"
            )))
        }
    }
}

/// The renderer that produced an entry, so switching renderers re-renders
/// (v3 `_renderer_identity`; the exact renderer is cached by the engine).
pub fn renderer_identity(live: bool) -> &'static str {
    if live {
        "native-live"
    } else {
        "native"
    }
}

/// `<cache_dir>/<sha256(schema \0 identity \0 .ext \0 name \0 bytes)>.html`.
pub fn cache_path(cache_dir: &Path, source: &Path, live: bool, bytes: &[u8]) -> PathBuf {
    let suffix = extension(source);
    let mut fingerprint = Sha256::new();
    fingerprint.update(CACHE_SCHEMA_VERSION.as_bytes());
    fingerprint.update(b"\0");
    fingerprint.update(renderer_identity(live).as_bytes());
    fingerprint.update(b"\0");
    if !suffix.is_empty() {
        fingerprint.update(format!(".{suffix}").as_bytes());
    }
    fingerprint.update(b"\0");
    if let Some(name) = source.file_name() {
        fingerprint.update(name.as_encoded_bytes());
    }
    fingerprint.update(b"\0");
    fingerprint.update(bytes);
    let digest: String = fingerprint
        .finalize()
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect();
    cache_dir.join(format!("{digest}.html"))
}

/// Serialize one cache key without blocking unrelated previews.
fn lock_for(output: &Path) -> std::sync::MutexGuard<'static, ()> {
    let stem = output
        .file_stem()
        .map(|s| s.to_string_lossy().into_owned())
        .unwrap_or_default();
    let index = stem
        .get(..8)
        .and_then(|prefix| usize::from_str_radix(prefix, 16).ok())
        .unwrap_or(0)
        % LOCK_STRIPES;
    RENDER_LOCKS[index]
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}

/// A bounded, regular cache file (never a symlink).
pub fn cached_preview_is_valid(path: &Path) -> bool {
    fs::symlink_metadata(path)
        .is_ok_and(|m| m.file_type().is_file() && m.len() > 0 && m.len() <= MAX_HTML_BYTES as u64)
}

/// Create the cache folder, refusing one that is a link or not a folder.
pub fn prepare_cache_directory(cache_dir: &Path) -> Result<(), PreviewError> {
    if let Some(parent) = cache_dir.parent().filter(|p| !p.as_os_str().is_empty()) {
        fs::create_dir_all(parent)?;
    }
    let unsafe_path = || PreviewError::failed("The document preview cache path is unsafe.");
    match fs::symlink_metadata(cache_dir) {
        Ok(m) if m.file_type().is_symlink() || !m.is_dir() => Err(unsafe_path()),
        Ok(_) => Ok(()),
        Err(e) if e.kind() == io::ErrorKind::NotFound => {
            #[cfg(unix)]
            let builder = {
                let mut builder = fs::DirBuilder::new();
                std::os::unix::fs::DirBuilderExt::mode(&mut builder, 0o700);
                builder
            };
            #[cfg(not(unix))]
            let builder = fs::DirBuilder::new();
            match builder.create(cache_dir) {
                Ok(()) => Ok(()),
                Err(e) if e.kind() == io::ErrorKind::AlreadyExists => {
                    let m = fs::symlink_metadata(cache_dir)?;
                    if m.file_type().is_symlink() || !m.is_dir() {
                        Err(unsafe_path())
                    } else {
                        Ok(())
                    }
                }
                Err(e) => Err(e.into()),
            }
        }
        Err(e) => Err(e.into()),
    }
}

/// Refresh an entry's modification time (its LRU stamp) without following a
/// link swapped in for it. Failures are ignored.
pub fn mark_cached_preview_used(path: &Path) {
    let Ok(before) = fs::symlink_metadata(path) else {
        return;
    };
    if !before.file_type().is_file() {
        return;
    }
    let mut options = fs::OpenOptions::new();
    options.write(true);
    #[cfg(windows)]
    {
        // FILE_FLAG_OPEN_REPARSE_POINT: open a link itself, never its target.
        std::os::windows::fs::OpenOptionsExt::custom_flags(&mut options, 0x0020_0000);
    }
    let Ok(file) = options.open(path) else {
        return;
    };
    let Ok(opened) = file.metadata() else {
        return;
    };
    if !opened.file_type().is_file() {
        return;
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        // The path was replaced between the check and the open.
        if (opened.dev(), opened.ino()) != (before.dev(), before.ino()) {
            return;
        }
    }
    let _ = file.set_modified(SystemTime::now());
}

fn cache_name_patterns() -> &'static [Regex; 3] {
    static PATTERNS: OnceLock<[Regex; 3]> = OnceLock::new();
    PATTERNS.get_or_init(|| {
        [
            Regex::new(r"^[0-9a-f]{64}\.html$").expect("valid regex"),
            Regex::new(r"^(?:\.[0-9a-f]{64}-[^/]+|[0-9a-f]{64})\.tmp$").expect("valid regex"),
            Regex::new(r"^[0-9a-f]{64}-pages$").expect("valid regex"),
        ]
    })
}

/// Prune generated previews: stale temporary files and page folders, then the
/// least recently used entries beyond the limits (`preserve` is kept).
pub fn maintain_cache(
    cache_dir: &Path,
    preserve: Option<&Path>,
    now: SystemTime,
    limits: &CacheLimits,
) -> Result<(), PreviewError> {
    prepare_cache_directory(cache_dir)?;
    let [entry_file, temp_file, page_folder] = cache_name_patterns();
    let entries = match fs::read_dir(cache_dir) {
        Ok(entries) => entries,
        Err(e) if e.kind() == io::ErrorKind::NotFound => return Ok(()),
        Err(e) => return Err(e.into()),
    };
    let mut candidates: Vec<(SystemTime, String, u64, PathBuf)> = Vec::new();
    for entry in entries.flatten() {
        let Some(name) = entry.file_name().to_str().map(str::to_string) else {
            continue;
        };
        let path = entry.path();
        let Ok(metadata) = fs::symlink_metadata(&path) else {
            continue;
        };
        if entry_file.is_match(&name) {
            if metadata.file_type().is_symlink() {
                let _ = remove_link_or_file(&path);
            } else if metadata.file_type().is_file() {
                let modified = metadata.modified().unwrap_or(SystemTime::UNIX_EPOCH);
                candidates.push((modified, name, metadata.len(), path));
            }
            continue;
        }
        if !(temp_file.is_match(&name) || page_folder.is_match(&name)) {
            continue;
        }
        let modified = metadata.modified().unwrap_or(SystemTime::UNIX_EPOCH);
        let age = now.duration_since(modified).unwrap_or(Duration::ZERO);
        if age < limits.stale_temp {
            continue;
        }
        remove_owned_path(&path);
    }

    candidates.sort_by(|a, b| (a.0, &a.1).cmp(&(b.0, &b.1)));
    let mut entry_count = candidates.len();
    let mut total_bytes: u64 = candidates.iter().map(|c| c.2).sum();
    for (_, _, size, path) in &candidates {
        if entry_count <= limits.max_entries && total_bytes <= limits.max_bytes {
            break;
        }
        if preserve.is_some_and(|p| p == path) {
            continue;
        }
        if fs::remove_file(path).is_ok() {
            entry_count -= 1;
            total_bytes -= size;
        }
    }
    Ok(())
}

/// Remove a link (never its target) or a regular file.
fn remove_link_or_file(path: &Path) -> io::Result<()> {
    match fs::remove_file(path) {
        Ok(()) => Ok(()),
        Err(e) if e.kind() == io::ErrorKind::NotFound => Ok(()),
        // A directory link on Windows is removed as a directory.
        Err(e) => fs::remove_dir(path).map_err(|_| e),
    }
}

/// Remove a path the cache owns: a link or file is unlinked, a real folder is
/// removed with its content (links inside are not followed).
fn remove_owned_path(path: &Path) {
    let Ok(metadata) = fs::symlink_metadata(path) else {
        return;
    };
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        let _ = remove_link_or_file(path);
    } else {
        let _ = fs::remove_dir_all(path);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn source(dir: &Path, name: &str, content: &[u8]) -> PathBuf {
        let path = dir.join(name);
        fs::write(&path, content).unwrap();
        path
    }

    fn limits(max_entries: usize, max_bytes: u64) -> CacheLimits {
        CacheLimits {
            max_entries,
            max_bytes,
            ..CacheLimits::default()
        }
    }

    fn set_mtime(path: &Path, secs: u64) {
        let file = fs::OpenOptions::new().write(true).open(path).unwrap();
        file.set_modified(SystemTime::UNIX_EPOCH + Duration::from_secs(secs))
            .unwrap();
    }

    #[test]
    fn cache_evicts_oldest_entry() {
        let tmp = tempfile::tempdir().unwrap();
        let cache = tmp.path().join("cache").join("previews");
        let limits = limits(2, 1024 * 1024);
        let render = |s: &Path, _: &[u8], _: Option<&DeckPlan>| {
            Ok(format!(
                "<!doctype html><title>{}</title>",
                s.file_name().unwrap().to_string_lossy()
            ))
        };
        let sources: Vec<PathBuf> = (0..3)
            .map(|i| {
                source(
                    tmp.path(),
                    &format!("source-{i}.pdf"),
                    format!("%PDF-{i}").as_bytes(),
                )
            })
            .collect();
        let first = render_cached_with(&cache, &sources[0], None, &limits, render).unwrap();
        let second = render_cached_with(&cache, &sources[1], None, &limits, render).unwrap();
        set_mtime(&first, 1);
        set_mtime(&second, 2);
        let third = render_cached_with(&cache, &sources[2], None, &limits, render).unwrap();
        assert!(!first.exists());
        assert!(second.is_file());
        assert!(third.is_file());
    }

    #[test]
    fn cache_enforces_total_byte_limit() {
        let tmp = tempfile::tempdir().unwrap();
        let cache = tmp.path().join("previews");
        let limits = limits(10, 12);
        let render = |_: &Path, _: &[u8], _: Option<&DeckPlan>| Ok("x".repeat(8));
        let first_source = source(tmp.path(), "first.pdf", b"%PDF-first");
        let second_source = source(tmp.path(), "second.pdf", b"%PDF-second");
        let first = render_cached_with(&cache, &first_source, None, &limits, render).unwrap();
        set_mtime(&first, 1);
        let second = render_cached_with(&cache, &second_source, None, &limits, render).unwrap();
        assert!(!first.exists());
        assert!(second.is_file());
    }

    #[test]
    fn cache_hit_reuses_the_render_and_refreshes_its_stamp() {
        let tmp = tempfile::tempdir().unwrap();
        let cache = tmp.path().join("previews");
        let pdf = source(tmp.path(), "a.pdf", b"%PDF-1");
        let first = render_cached_with(&cache, &pdf, None, &CacheLimits::default(), |_, _, _| {
            Ok("one".into())
        })
        .unwrap();
        set_mtime(&first, 5);
        let again = render_cached_with(&cache, &pdf, None, &CacheLimits::default(), |_, _, _| {
            panic!("must not render twice")
        })
        .unwrap();
        assert_eq!(first, again);
        assert_eq!(fs::read_to_string(&again).unwrap(), "one");
        let stamp = fs::metadata(&again).unwrap().modified().unwrap();
        assert!(stamp > SystemTime::UNIX_EPOCH + Duration::from_secs(5));
    }

    #[test]
    fn cleanup_removes_only_stale_owned_transients() {
        let tmp = tempfile::tempdir().unwrap();
        let cache = tmp.path().join("cache").join("previews");
        fs::create_dir_all(&cache).unwrap();
        let stale_pages = cache.join(format!("{}-pages", "a".repeat(64)));
        fs::create_dir(&stale_pages).unwrap();
        fs::write(stale_pages.join("page.png"), b"generated").unwrap();
        let stale_temp = cache.join(format!(".{}-abc.tmp", "b".repeat(64)));
        fs::write(&stale_temp, b"partial").unwrap();
        let fresh_temp = cache.join(format!("{}.tmp", "c".repeat(64)));
        fs::write(&fresh_temp, b"partial").unwrap();
        let unrelated = cache.join("keep-me");
        fs::create_dir(&unrelated).unwrap();
        set_mtime(&stale_temp, 1);
        let now = SystemTime::now();
        // A folder's mtime cannot be set portably: age everything instead.
        let later = now + Duration::from_secs(STALE_DOCUMENT_PREVIEW_TEMP_SECONDS + 60);
        set_mtime(
            &fresh_temp,
            later
                .duration_since(SystemTime::UNIX_EPOCH)
                .unwrap()
                .as_secs()
                - 10,
        );
        maintain_cache(&cache, None, later, &CacheLimits::default()).unwrap();
        assert!(!stale_pages.exists());
        assert!(!stale_temp.exists());
        assert!(fresh_temp.exists());
        assert!(unrelated.is_dir());
    }

    #[test]
    fn a_failed_render_leaves_no_temporary_file() {
        let tmp = tempfile::tempdir().unwrap();
        let cache = tmp.path().join("previews");
        let pdf = source(tmp.path(), "a.pdf", b"%PDF-1");
        let error = render_cached_with(&cache, &pdf, None, &CacheLimits::default(), |_, _, _| {
            Err(PreviewError::Io(io::Error::other("disk on fire")))
        })
        .unwrap_err();
        assert_eq!(
            error.to_string(),
            "Could not render this document: disk on fire"
        );
        let panicked =
            render_cached_with(&cache, &pdf, None, &CacheLimits::default(), |_, _, _| {
                panic!("index out of range")
            })
            .unwrap_err();
        assert_eq!(
            panicked.to_string(),
            "Could not render this document: index out of range"
        );
        assert_eq!(fs::read_dir(&cache).unwrap().count(), 0);
    }

    #[test]
    fn oversized_output_is_refused() {
        let tmp = tempfile::tempdir().unwrap();
        let cache = tmp.path().join("previews");
        let pdf = source(tmp.path(), "a.pdf", b"%PDF-1");
        let error = render_cached_with(&cache, &pdf, None, &CacheLimits::default(), |_, _, _| {
            Ok("x".repeat(MAX_HTML_BYTES + 1))
        })
        .unwrap_err();
        assert!(matches!(error, PreviewError::Unsupported(_)));
        assert!(error
            .to_string()
            .starts_with("The generated preview is too large"));
    }

    #[test]
    fn cache_key_depends_on_identity_name_and_bytes() {
        let dir = Path::new("c");
        let a = cache_path(dir, Path::new("x/a.pptx"), false, b"1");
        assert_ne!(a, cache_path(dir, Path::new("x/a.pptx"), true, b"1"));
        assert_ne!(a, cache_path(dir, Path::new("x/b.pptx"), false, b"1"));
        assert_ne!(a, cache_path(dir, Path::new("x/a.pptx"), false, b"2"));
        assert_eq!(
            a.file_name(),
            cache_path(dir, Path::new("y/a.pptx"), false, b"1").file_name()
        );
        let name = a.file_name().unwrap().to_string_lossy().into_owned();
        assert!(cache_name_patterns()[0].is_match(&name));
    }

    #[cfg(unix)]
    #[test]
    fn cache_replaces_a_symlink_without_touching_its_target() {
        let tmp = tempfile::tempdir().unwrap();
        let cache = tmp.path().join("previews");
        fs::create_dir_all(&cache).unwrap();
        let pdf = source(tmp.path(), "source.pdf", b"%PDF-1");
        let output = cache_path(&cache, &pdf, false, b"%PDF-1");
        let victim = source(tmp.path(), "victim.txt", b"unchanged");
        std::os::unix::fs::symlink(&victim, &output).unwrap();
        let rendered =
            render_cached_with(&cache, &pdf, None, &CacheLimits::default(), |_, _, _| {
                Ok("safe preview".into())
            })
            .unwrap();
        assert_eq!(fs::read_to_string(&rendered).unwrap(), "safe preview");
        assert!(!fs::symlink_metadata(&rendered)
            .unwrap()
            .file_type()
            .is_symlink());
        assert_eq!(fs::read_to_string(&victim).unwrap(), "unchanged");
    }

    #[cfg(unix)]
    #[test]
    fn a_symlinked_cache_directory_is_refused() {
        let tmp = tempfile::tempdir().unwrap();
        let elsewhere = tmp.path().join("elsewhere");
        fs::create_dir(&elsewhere).unwrap();
        let cache = tmp.path().join("previews");
        std::os::unix::fs::symlink(&elsewhere, &cache).unwrap();
        let pdf = source(tmp.path(), "source.pdf", b"%PDF-1");
        let error = render_cached_with(&cache, &pdf, None, &CacheLimits::default(), |_, _, _| {
            Ok("x".into())
        })
        .unwrap_err();
        assert_eq!(
            error.to_string(),
            "The document preview cache path is unsafe."
        );
    }
}
