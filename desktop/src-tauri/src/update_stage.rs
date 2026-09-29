//! A downloaded, verified update waiting for EvoFlux to close.
//!
//! The updater used to download, install and restart in one go, with the
//! installer running the moment the bytes arrived. Two things went wrong with
//! that. The Windows installer ran silently, rewriting ~11,000 files with no
//! window of its own, so for a minute or more the app had simply vanished;
//! anyone who reopened it meanwhile got the old version back, which found the
//! same update and downloaded all of it again. And nothing about the download
//! outlived the process, so any interruption meant starting over.
//!
//! The update is now staged here once it has been downloaded and its signature
//! checked, and installed when the user restarts or quits. A staged file is
//! only reused for the exact release it was verified against: the same version
//! *and* the same signature the release server announces now.

use anyhow::{anyhow, Context, Result};
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};
use tauri::{AppHandle, Manager};

const STAGE_DIR: &str = "updates";
const MANIFEST: &str = "staged.json";

#[derive(Debug, Serialize, Deserialize, PartialEq, Eq)]
struct Manifest {
    version: String,
    /// The release signature the bytes were verified against.
    signature: String,
    file: String,
    /// A truncated write is the one corruption worth checking for cheaply.
    len: u64,
}

pub fn dir(app: &AppHandle) -> Result<PathBuf> {
    Ok(app
        .path()
        .app_local_data_dir()
        .context("resolve app local data directory")?
        .join(STAGE_DIR))
}

/// The staged package for this release, if one was already downloaded.
pub fn find(dir: &Path, version: &str, signature: &str) -> Option<PathBuf> {
    let manifest = read_manifest(dir)?;
    if manifest.version != version || manifest.signature != signature {
        return None;
    }
    let path = dir.join(&manifest.file);
    let len = fs::metadata(&path).ok()?.len();
    (len == manifest.len).then_some(path)
}

/// Keep a verified package for later, replacing whatever was staged before.
pub fn write(dir: &Path, version: &str, signature: &str, bytes: &[u8]) -> Result<PathBuf> {
    clear(dir);
    fs::create_dir_all(dir)
        .with_context(|| format!("create update directory at {}", dir.display()))?;
    let file = package_file_name(version);
    let path = dir.join(&file);
    fs::write(&path, bytes).with_context(|| format!("write update to {}", path.display()))?;
    // The manifest goes last: a package without one is never picked up.
    let manifest = Manifest {
        version: version.to_string(),
        signature: signature.to_string(),
        file,
        len: bytes.len() as u64,
    };
    fs::write(
        dir.join(MANIFEST),
        serde_json::to_vec_pretty(&manifest).context("encode staged update manifest")?,
    )
    .context("write staged update manifest")?;
    Ok(path)
}

pub fn clear(dir: &Path) {
    if let Err(error) = fs::remove_dir_all(dir) {
        if error.kind() != std::io::ErrorKind::NotFound {
            log::warn!(
                "desktop: could not remove staged update at {}: {error}",
                dir.display()
            );
        }
    }
}

/// Drop a package that has already been installed, or that cannot be read.
///
/// Anything else stays: it is either still waiting for a quit, or it is the
/// download a relaunch mid-install would otherwise have to repeat.
pub fn discard_installed(dir: &Path, running_version: &str) {
    if !dir.exists() {
        return;
    }
    match read_manifest(dir) {
        Some(manifest) if manifest.version != running_version => {}
        _ => clear(dir),
    }
}

fn read_manifest(dir: &Path) -> Option<Manifest> {
    let bytes = fs::read(dir.join(MANIFEST)).ok()?;
    serde_json::from_slice(&bytes).ok()
}

fn package_file_name(version: &str) -> String {
    let version: String = version
        .chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() || matches!(c, '.' | '-' | '+') {
                c
            } else {
                '_'
            }
        })
        .collect();
    if cfg!(windows) {
        format!("EvoFlux-{version}-setup.exe")
    } else {
        format!("EvoFlux-{version}.app.tar.gz")
    }
}

/// Windows ships the NSIS installer itself; anything else cannot be run.
pub fn check_package(bytes: &[u8]) -> Result<()> {
    if cfg!(windows) && !bytes.starts_with(b"MZ") {
        return Err(anyhow!(
            "The downloaded update is not a Windows installer EvoFlux can run."
        ));
    }
    Ok(())
}

/// Hand the staged installer over and let EvoFlux exit.
///
/// `/P` is passive mode: the installer shows its own progress window and asks
/// nothing. The silent mode used before showed nothing at all while it copied
/// the whole install, which is what "stuck installing" looked like. `/UPDATE`
/// keeps the install in place without an uninstall first, and `/R` starts
/// EvoFlux again when it finishes — only when the user asked to restart. An
/// install that runs because the user quit leaves the app closed.
#[cfg(windows)]
pub fn launch_windows_installer(path: &Path, relaunch: bool) -> Result<()> {
    let mut command = std::process::Command::new(path);
    command.args(installer_args(relaunch));
    command
        .spawn()
        .with_context(|| format!("start the update installer {}", path.display()))?;
    Ok(())
}

#[cfg_attr(not(windows), allow(dead_code))]
fn installer_args(relaunch: bool) -> Vec<&'static str> {
    let mut args = vec!["/P", "/UPDATE"];
    if relaunch {
        args.push("/R");
    }
    args
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_dir(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!(
            "evoflux-update-stage-{name}-{}",
            std::process::id()
        ));
        clear(&dir);
        dir
    }

    #[test]
    fn staged_package_is_found_for_the_same_release() {
        let dir = temp_dir("same");
        let path = write(&dir, "3.0.1", "sig-a", b"MZpackage").expect("stage");
        assert_eq!(find(&dir, "3.0.1", "sig-a"), Some(path));
        clear(&dir);
    }

    #[test]
    fn staged_package_is_ignored_for_another_version_or_signature() {
        let dir = temp_dir("other");
        write(&dir, "3.0.1", "sig-a", b"MZpackage").expect("stage");
        assert_eq!(find(&dir, "3.0.2", "sig-a"), None);
        assert_eq!(find(&dir, "3.0.1", "sig-b"), None);
        clear(&dir);
    }

    #[test]
    fn truncated_package_is_not_reused() {
        let dir = temp_dir("truncated");
        let path = write(&dir, "3.0.1", "sig-a", b"MZpackage").expect("stage");
        fs::write(&path, b"MZ").expect("truncate");
        assert_eq!(find(&dir, "3.0.1", "sig-a"), None);
        clear(&dir);
    }

    #[test]
    fn staging_a_new_release_replaces_the_old_one() {
        let dir = temp_dir("replace");
        let old = write(&dir, "3.0.1", "sig-a", b"MZold").expect("stage old");
        write(&dir, "3.0.2", "sig-b", b"MZnew").expect("stage new");
        assert!(!old.exists());
        assert!(find(&dir, "3.0.2", "sig-b").is_some());
        clear(&dir);
    }

    #[test]
    fn installed_package_is_discarded_and_pending_one_kept() {
        let dir = temp_dir("discard");
        write(&dir, "3.0.1", "sig-a", b"MZpackage").expect("stage");
        discard_installed(&dir, "3.0.0");
        assert!(find(&dir, "3.0.1", "sig-a").is_some());
        discard_installed(&dir, "3.0.1");
        assert!(!dir.exists());
    }

    #[test]
    fn unreadable_stage_is_discarded() {
        let dir = temp_dir("unreadable");
        fs::create_dir_all(&dir).expect("create");
        fs::write(dir.join(MANIFEST), b"not json").expect("write");
        discard_installed(&dir, "3.0.0");
        assert!(!dir.exists());
    }

    #[test]
    fn package_name_keeps_only_safe_characters() {
        let name = package_file_name("3.0.1-beta/../x");
        assert!(!name.contains('/'));
        assert!(name.contains("3.0.1-beta_.._x"));
    }

    #[test]
    fn installer_restarts_the_app_only_when_asked() {
        assert_eq!(installer_args(true), vec!["/P", "/UPDATE", "/R"]);
        assert_eq!(installer_args(false), vec!["/P", "/UPDATE"]);
    }
}
