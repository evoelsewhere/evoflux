//! The runtime handle and the user-triggered install.
//!
//! The install runs as a background task that outlives the request which
//! started it, so the UI can poll [`Runtime::status`] for byte-level progress.
//! Every archive is checked against the pinned asset (size and SHA-256) before a
//! single member is extracted, extraction refuses anything outside `soffice/` or
//! any special file, and the verified tree replaces the previous version with a
//! rename.

use std::collections::HashSet;
use std::io::{Read, SeekFrom};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex, MutexGuard};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use tokio::io::{AsyncReadExt, AsyncSeekExt, AsyncWriteExt};
use tokio_util::sync::CancellationToken;

use crate::manifest::{self, Asset, RUNTIME_ID, RUNTIME_ROOT};
use crate::Error;

const MAX_ENTRIES: usize = 60_000;
const MAX_EXTRACTED_BYTES: u64 = 4 * 1024 * 1024 * 1024;
const HASH_CHUNK: usize = 1024 * 1024;
const FILE_CHUNK: usize = 64 * 1024;
const INSTALL_RECORD: &str = "install.json";

/// Where an install is.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Phase {
    Downloading,
    Verifying,
    Extracting,
    Failed,
}

/// One install attempt, as the UI sees it.
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct InstallJob {
    pub phase: Phase,
    pub version: String,
    pub bytes_done: u64,
    pub bytes_total: u64,
    /// Unix time in milliseconds.
    pub started_at: u64,
    pub error: Option<String>,
}

/// The active runtime on disk.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Installed {
    pub version: String,
    pub executable: PathBuf,
    pub root: PathBuf,
}

/// What the UI needs to decide whether to offer the download.
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Status {
    pub available: bool,
    pub platform: Option<String>,
    pub version: Option<String>,
    pub download_bytes: Option<u64>,
    pub install_bytes: Option<u64>,
    pub installed_version: Option<String>,
    pub job: Option<InstallJob>,
}

#[derive(Serialize, Deserialize)]
struct InstallRecord {
    id: String,
    version: String,
    platform: String,
    sha256: String,
    executable: String,
    #[serde(rename = "installedAt")]
    installed_at: u64,
}

struct Task {
    handle: tokio::task::JoinHandle<()>,
    cancel: CancellationToken,
}

pub(crate) struct Inner {
    job: Mutex<Option<InstallJob>>,
    task: Mutex<Option<Task>>,
    pub(crate) convert: tokio::sync::Mutex<()>,
}

/// Handle to the runtime of one data directory. Cheap to clone; all clones
/// share the install state.
#[derive(Clone)]
pub struct Runtime {
    home: PathBuf,
    asset: Option<Asset>,
    pub(crate) inner: Arc<Inner>,
}

fn lock<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    mutex
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

impl Runtime {
    /// A runtime stored under `<runtimes_dir>/libreoffice`, using the pinned
    /// asset of this platform (or the test override).
    pub fn new(runtimes_dir: &Path) -> Self {
        Self::with_asset(runtimes_dir, manifest::current_asset())
    }

    /// Like [`Runtime::new`] with an explicit asset (`None`: unsupported platform).
    pub fn with_asset(runtimes_dir: &Path, asset: Option<Asset>) -> Self {
        Self {
            home: runtimes_dir.join(RUNTIME_ID),
            asset,
            inner: Arc::new(Inner {
                job: Mutex::new(None),
                task: Mutex::new(None),
                convert: tokio::sync::Mutex::new(()),
            }),
        }
    }

    /// The runtime's folder (`<runtimes>/libreoffice`).
    pub fn home(&self) -> &Path {
        &self.home
    }

    /// The active runtime, when its executable is present.
    pub fn installed(&self) -> Option<Installed> {
        let text = std::fs::read_to_string(self.home.join(INSTALL_RECORD)).ok()?;
        let record: InstallRecord = serde_json::from_str(&text).ok()?;
        let executable = manifest::safe_executable(&record.executable).ok()?;
        let root = self.home.join(&record.version);
        let path = executable
            .split('/')
            .fold(root.clone(), |dir, part| dir.join(part));
        if !path.is_file() {
            return None;
        }
        Some(Installed {
            version: record.version,
            executable: path,
            root,
        })
    }

    pub fn status(&self) -> Status {
        let installed = self.installed();
        Status {
            available: self.asset.is_some(),
            platform: self.asset.as_ref().map(|a| a.platform.clone()),
            version: self.asset.as_ref().map(|a| a.version.clone()),
            download_bytes: self.asset.as_ref().map(|a| a.size),
            install_bytes: self.asset.as_ref().and_then(|a| a.installed_size),
            installed_version: installed.map(|i| i.version),
            job: lock(&self.inner.job).clone(),
        }
    }

    fn set_job(&self, job: Option<InstallJob>) {
        *lock(&self.inner.job) = job;
    }

    fn update(&self, change: impl FnOnce(&mut InstallJob)) {
        if let Some(job) = lock(&self.inner.job).as_mut() {
            change(job);
        }
    }

    fn partial_path(&self, asset: &Asset) -> PathBuf {
        self.home.join(format!(".download-{}.part", asset.sha256))
    }

    /// Begin downloading and installing; returns immediately. Starting while an
    /// install runs returns the running job.
    pub fn start_install(&self) -> Result<InstallJob, Error> {
        let asset = self.asset.clone().ok_or_else(|| {
            Error::Install("No verified LibreOffice runtime is published for this platform.".into())
        })?;
        let mut task = lock(&self.inner.task);
        if task.as_ref().is_some_and(|t| !t.handle.is_finished()) {
            if let Some(job) = lock(&self.inner.job).clone() {
                return Ok(job);
            }
        }
        remove_stale(&self.home, Some(&self.partial_path(&asset)));
        let job = InstallJob {
            phase: Phase::Downloading,
            version: asset.version.clone(),
            bytes_done: 0,
            bytes_total: asset.size,
            started_at: now_ms(),
            error: None,
        };
        self.set_job(Some(job.clone()));
        let cancel = CancellationToken::new();
        let this = self.clone();
        let token = cancel.clone();
        let handle = tokio::spawn(async move {
            let outcome = tokio::select! {
                _ = token.cancelled() => None,
                result = this.install(&asset) => Some(result),
            };
            match outcome {
                None => {
                    // The user stopped the download: keep nothing of it.
                    let _ = std::fs::remove_file(this.partial_path(&asset));
                    this.set_job(None);
                    tracing::info!(version = %asset.version, "office runtime install cancelled");
                }
                Some(Ok(())) => {
                    this.set_job(None);
                    tracing::info!(version = %asset.version, "office runtime installed");
                }
                Some(Err(error)) => {
                    tracing::warn!(%error, "office runtime install failed");
                    this.update(|job| {
                        job.phase = Phase::Failed;
                        job.error = Some(error.to_string());
                    });
                }
            }
        });
        *task = Some(Task { handle, cancel });
        Ok(job)
    }

    /// Stop an install that is still downloading or verifying. Extraction runs
    /// in worker threads that cannot be interrupted safely, so a cancel that
    /// arrives then is refused.
    pub fn cancel_install(&self) -> Result<(), Error> {
        let job = lock(&self.inner.job);
        let task = lock(&self.inner.task);
        let Some(task) = task.as_ref().filter(|t| !t.handle.is_finished()) else {
            return Ok(());
        };
        match job.as_ref().map(|j| j.phase) {
            Some(Phase::Downloading | Phase::Verifying) => {
                task.cancel.cancel();
                Ok(())
            }
            _ => Err(Error::Install(
                "The renderer is already being installed.".into(),
            )),
        }
    }

    /// Forget a failed install so the UI returns to its idle state.
    pub fn dismiss_error(&self) {
        let mut job = lock(&self.inner.job);
        if job.as_ref().is_some_and(|j| j.phase == Phase::Failed) {
            *job = None;
        }
    }

    /// Remove the runtime and its profile.
    pub fn uninstall(&self) -> Result<(), Error> {
        if lock(&self.inner.task)
            .as_ref()
            .is_some_and(|t| !t.handle.is_finished())
        {
            return Err(Error::Install(
                "The runtime is still being installed.".into(),
            ));
        }
        match std::fs::remove_dir_all(&self.home) {
            Ok(()) => Ok(()),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(()),
            Err(e) => Err(Error::Install(format!("Could not remove the runtime: {e}"))),
        }
    }

    async fn install(&self, asset: &Asset) -> Result<(), Error> {
        tokio::fs::create_dir_all(&self.home).await?;
        let archive = self.partial_path(asset);
        // Any failure keeps the partial file so Retry resumes from it.
        let digest = self.download(asset, &archive).await?;
        self.update(|job| job.phase = Phase::Verifying);
        if digest != asset.sha256 {
            let _ = tokio::fs::remove_file(&archive).await;
            return Err(Error::Install(
                "Runtime archive checksum does not match".into(),
            ));
        }
        self.update(|job| job.phase = Phase::Extracting);
        let staging = tempfile::Builder::new()
            .prefix(".staging-")
            .tempdir_in(&self.home)?;
        let tree = staging.path().join("tree");
        std::fs::create_dir(&tree)?;
        let (source, target) = (archive.clone(), tree.clone());
        tokio::task::spawn_blocking(move || extract(&source, &target))
            .await
            .map_err(join_error)??;
        let (home, asset, tree) = (self.home.clone(), asset.clone(), tree);
        tokio::task::spawn_blocking(move || activate(&home, &asset, &tree))
            .await
            .map_err(join_error)??;
        let _ = tokio::fs::remove_file(&archive).await;
        Ok(())
    }

    /// Stream the archive to `dest` and return its SHA-256.
    ///
    /// A previous attempt's bytes are kept and the transfer resumes with an HTTP
    /// range request. The final SHA-256 still covers every byte, resumed or not.
    async fn download(&self, asset: &Asset, dest: &Path) -> Result<String, Error> {
        let (existing, size) = (dest.to_path_buf(), asset.size);
        let (mut digest, mut received) =
            tokio::task::spawn_blocking(move || hash_existing(&existing, size))
                .await
                .map_err(join_error)??;
        let mut file = tokio::fs::OpenOptions::new()
            .create(true)
            .write(true)
            .read(true)
            .truncate(false)
            .open(dest)
            .await?;
        if file.metadata().await?.len() != received {
            file.set_len(received).await?;
        }
        file.seek(SeekFrom::Start(received)).await?;
        self.update(|job| job.bytes_done = received);

        let url = url::Url::parse(&asset.url).map_err(|e| Error::Install(e.to_string()))?;
        if received < asset.size && url.scheme() == "file" {
            let path = url
                .to_file_path()
                .map_err(|_| Error::Install("Invalid file URL".into()))?;
            let mut reader = tokio::fs::File::open(path).await?;
            reader.seek(SeekFrom::Start(received)).await?;
            let mut buffer = vec![0u8; FILE_CHUNK];
            loop {
                let n = reader.read(&mut buffer).await?;
                if n == 0 {
                    break;
                }
                self.accept(asset, &buffer[..n], &mut digest, &mut received, &mut file)
                    .await?;
            }
        } else if received < asset.size {
            let client = reqwest::Client::builder()
                .user_agent("evo")
                .connect_timeout(Duration::from_secs(30))
                .read_timeout(Duration::from_secs(120))
                .build()
                .map_err(|e| Error::Install(e.to_string()))?;
            let mut request = client.get(asset.url.as_str());
            if received > 0 {
                request = request.header(reqwest::header::RANGE, format!("bytes={received}-"));
            }
            let mut response = request
                .send()
                .await
                .map_err(|e| Error::Install(format!("Download failed: {e}")))?;
            let status = response.status().as_u16();
            if status == 200 && received > 0 {
                // The server ignored the range: start over.
                digest = Sha256::new();
                received = 0;
                file.set_len(0).await?;
                file.seek(SeekFrom::Start(0)).await?;
                self.update(|job| job.bytes_done = 0);
            } else if status != 200 && status != 206 {
                if status == 416 {
                    // The partial is unusable; the next attempt starts clean.
                    file.set_len(0).await?;
                }
                return Err(Error::Install(format!(
                    "Download failed with HTTP {status}"
                )));
            }
            // No fixed chunk size: on a slow link waiting to fill a megabyte
            // would freeze the progress bar.
            while let Some(chunk) = response
                .chunk()
                .await
                .map_err(|e| Error::Install(format!("Download failed: {e}")))?
            {
                self.accept(asset, &chunk, &mut digest, &mut received, &mut file)
                    .await?;
            }
        }
        file.flush().await?;
        if received != asset.size {
            return Err(Error::Install(format!(
                "Runtime archive is {received} bytes, expected {}",
                asset.size
            )));
        }
        Ok(format!("{:x}", digest.finalize()))
    }

    async fn accept(
        &self,
        asset: &Asset,
        chunk: &[u8],
        digest: &mut Sha256,
        received: &mut u64,
        file: &mut tokio::fs::File,
    ) -> Result<(), Error> {
        *received += chunk.len() as u64;
        if *received > asset.size {
            return Err(Error::Install(
                "Runtime archive is larger than pinned".into(),
            ));
        }
        digest.update(chunk);
        file.write_all(chunk).await?;
        let done = *received;
        self.update(|job| job.bytes_done = done);
        Ok(())
    }
}

fn join_error(error: tokio::task::JoinError) -> Error {
    Error::Install(format!("Install worker failed: {error}"))
}

fn hash_existing(path: &Path, limit: u64) -> Result<(Sha256, u64), Error> {
    let mut digest = Sha256::new();
    let mut received = 0u64;
    let Ok(mut file) = std::fs::File::open(path) else {
        return Ok((digest, 0));
    };
    let mut buffer = vec![0u8; HASH_CHUNK];
    while received < limit {
        let want = ((limit - received) as usize).min(buffer.len());
        let n = file.read(&mut buffer[..want])?;
        if n == 0 {
            break;
        }
        digest.update(&buffer[..n]);
        received += n as u64;
    }
    Ok((digest, received))
}

/// Resolve a link target against the link's own folder; `None` when it leaves
/// `soffice/` or is absolute.
fn resolve_link(parent: &[&str], target: &str) -> Option<Vec<String>> {
    if target.starts_with('/') || target.contains(':') {
        return None;
    }
    let mut stack: Vec<String> = parent.iter().map(|s| s.to_string()).collect();
    for part in target.split('/') {
        match part {
            "" | "." => {}
            ".." => {
                stack.pop()?;
            }
            other => stack.push(other.to_string()),
        }
    }
    (stack.first().map(String::as_str) == Some(RUNTIME_ROOT)).then_some(stack)
}

fn check_member<R: Read>(
    entry: &tar::Entry<'_, R>,
    count: &mut usize,
    total: &mut u64,
    seen: &mut HashSet<String>,
) -> Result<(), Error> {
    let bad = |message: String| Error::Install(message);
    *count += 1;
    if *count > MAX_ENTRIES {
        return Err(bad("Runtime archive has too many entries".into()));
    }
    let raw = entry
        .path()
        .map_err(|e| bad(format!("Runtime archive has an unreadable path: {e}")))?;
    let name = raw.to_string_lossy().replace('\\', "/");
    let parts: Vec<&str> = name.trim_end_matches('/').split('/').collect();
    if name.starts_with('/')
        || parts.first() != Some(&RUNTIME_ROOT)
        || parts
            .iter()
            .any(|p| p.is_empty() || *p == "." || *p == "..")
        || parts[0].contains(':')
    {
        return Err(bad(format!(
            "Runtime archive entry escapes {RUNTIME_ROOT}/: {name}"
        )));
    }
    let kind = entry.header().entry_type();
    if kind.is_symlink() || kind.is_hard_link() {
        let target = entry
            .link_name()
            .map_err(|e| bad(format!("Runtime archive has an unreadable link: {e}")))?
            .map(|t| t.to_string_lossy().replace('\\', "/"))
            .unwrap_or_default();
        // A hard link names a path from the archive root; a symlink one relative to its folder.
        let base: &[&str] = if kind.is_hard_link() {
            &[]
        } else {
            &parts[..parts.len() - 1]
        };
        if resolve_link(base, &target).is_none() {
            return Err(bad(format!("Runtime archive link escapes: {name}")));
        }
    } else if !(kind.is_file() || kind.is_dir()) {
        return Err(bad(format!("Runtime archive has a special file: {name}")));
    }
    if !kind.is_dir() && !seen.insert(parts.join("/").to_lowercase()) {
        return Err(bad(format!("Runtime archive has a duplicate path: {name}")));
    }
    *total += entry.header().size().unwrap_or(0);
    if *total > MAX_EXTRACTED_BYTES {
        return Err(bad("Runtime archive expands beyond the size limit".into()));
    }
    Ok(())
}

/// Validate every member as it is read and unpack it under `dest`. A bad member
/// aborts the install; what was written so far lives in a staging folder that is
/// deleted.
fn extract(archive: &Path, dest: &Path) -> Result<(), Error> {
    let file = std::io::BufReader::new(std::fs::File::open(archive)?);
    let mut tar = tar::Archive::new(flate2::read::GzDecoder::new(file));
    tar.set_unpack_xattrs(false);
    let (mut count, mut total) = (0usize, 0u64);
    let mut seen = HashSet::new();
    for entry in tar.entries()? {
        let mut entry = entry?;
        if entry.header().entry_type().is_pax_global_extensions() {
            continue;
        }
        check_member(&entry, &mut count, &mut total, &mut seen)?;
        if !entry.unpack_in(dest)? {
            return Err(Error::Install("Runtime archive entry was refused".into()));
        }
    }
    if count == 0 {
        return Err(Error::Install("Runtime archive is empty".into()));
    }
    Ok(())
}

/// Rename a freshly extracted tree, riding out transient Windows locks.
///
/// Antivirus and the search indexer open newly written executables for a few
/// seconds; renaming their parent directory meanwhile fails with a permission
/// error even though nothing is wrong.
fn replace_with_retry(source: &Path, target: &Path) -> std::io::Result<()> {
    let mut delay = Duration::from_millis(250);
    for attempt in 0..40 {
        match std::fs::rename(source, target) {
            Ok(()) => return Ok(()),
            Err(e)
                if cfg!(windows)
                    && e.kind() == std::io::ErrorKind::PermissionDenied
                    && attempt < 39 =>
            {
                std::thread::sleep(delay);
                delay = (delay * 3 / 2).min(Duration::from_secs(2));
            }
            Err(e) => return Err(e),
        }
    }
    unreachable!("the last attempt returns")
}

fn activate(home: &Path, asset: &Asset, extracted: &Path) -> Result<(), Error> {
    let executable = asset
        .executable
        .split('/')
        .fold(extracted.to_path_buf(), |dir, part| dir.join(part));
    if !executable.is_file() {
        return Err(Error::Install(format!(
            "Runtime is missing {}",
            asset.executable
        )));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if let Ok(meta) = std::fs::metadata(&executable) {
            let mut permissions = meta.permissions();
            permissions.set_mode(permissions.mode() | 0o111);
            let _ = std::fs::set_permissions(&executable, permissions);
        }
    }
    if cfg!(target_os = "macos") {
        // A bundle copied in by other means may be quarantined; Gatekeeper
        // would then block the trimmed app on first launch.
        let _ = std::process::Command::new("xattr")
            .args(["-dr", "com.apple.quarantine"])
            .arg(extracted)
            .output();
    }
    let target = home.join(&asset.version);
    if target.exists() {
        let _ = std::fs::remove_dir_all(&target);
    }
    replace_with_retry(extracted, &target)?;
    let record = InstallRecord {
        id: RUNTIME_ID.into(),
        version: asset.version.clone(),
        platform: asset.platform.clone(),
        sha256: asset.sha256.clone(),
        executable: asset.executable.clone(),
        installed_at: now_ms() / 1000,
    };
    let temporary = home.join(format!(".{INSTALL_RECORD}.tmp"));
    std::fs::write(
        &temporary,
        serde_json::to_vec_pretty(&record).map_err(|e| Error::Install(e.to_string()))?,
    )?;
    std::fs::rename(&temporary, home.join(INSTALL_RECORD))?;
    if let Ok(entries) = std::fs::read_dir(home) {
        for entry in entries.flatten() {
            let name = entry.file_name().to_string_lossy().to_string();
            if entry.path().is_dir()
                && name != asset.version
                && name != "profile"
                && !name.starts_with('.')
            {
                let _ = std::fs::remove_dir_all(entry.path());
            }
        }
    }
    Ok(())
}

/// Delete leftovers of installs the app quit in the middle of.
///
/// Activation only prunes version folders, so an interrupted extraction would
/// otherwise keep up to a gigabyte on disk forever. Partial downloads are kept
/// only for the asset about to be installed (`keep`); those of other versions
/// are removed.
fn remove_stale(home: &Path, keep: Option<&Path>) {
    let Ok(entries) = std::fs::read_dir(home) else {
        return;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        let name = entry.file_name().to_string_lossy().to_string();
        if name.starts_with(".staging-") {
            let _ = std::fs::remove_dir_all(&path);
        } else if name.starts_with(".download-")
            && name.ends_with(".part")
            && keep != Some(path.as_path())
        {
            let _ = std::fs::remove_file(&path);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn links_must_stay_inside_the_runtime() {
        assert!(resolve_link(&["soffice", "program"], "libfoo.so.1").is_some());
        assert!(resolve_link(&["soffice", "program"], "../share/x").is_some());
        assert!(resolve_link(&["soffice", "program"], "../../etc").is_none());
        assert!(resolve_link(&["soffice"], "..").is_none());
        assert!(resolve_link(&["soffice"], "/etc/passwd").is_none());
        assert!(resolve_link(&["soffice"], "C:/x").is_none());
        assert!(resolve_link(&[], "soffice/program/x").is_some());
        assert!(resolve_link(&[], "other/x").is_none());
    }

    #[test]
    fn a_file_is_hashed_up_to_the_limit() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("p");
        std::fs::write(&path, b"hello world").unwrap();
        let (digest, n) = hash_existing(&path, 5).unwrap();
        assert_eq!(n, 5);
        assert_eq!(
            format!("{:x}", digest.finalize()),
            format!("{:x}", Sha256::digest(b"hello"))
        );
        assert_eq!(hash_existing(&dir.path().join("missing"), 5).unwrap().1, 0);
    }
}
