//! Test helpers for links, shared by the unit tests.

#![allow(clippy::disallowed_methods, clippy::unwrap_used, clippy::expect_used)]

use std::path::Path;

/// A directory link: a symlink, or on Windows a junction when symlinks need
/// privileges the account lacks. Panics if neither can be made.
pub(crate) fn link_dir(target: &Path, link: &Path) {
    #[cfg(unix)]
    std::os::unix::fs::symlink(target, link).unwrap();
    #[cfg(windows)]
    {
        if std::os::windows::fs::symlink_dir(target, link).is_ok() {
            return;
        }
        // `mklink` rejects forward slashes; rebuild both paths from components.
        let made = std::process::Command::new("cmd")
            .args(["/C", "mklink", "/J"])
            .arg(link.components().collect::<std::path::PathBuf>())
            .arg(target.components().collect::<std::path::PathBuf>())
            .output()
            .unwrap();
        assert!(made.status.success(), "cannot create a directory link here");
    }
}

/// A file symlink. `false` (with a printed notice) where the platform refuses:
/// Windows needs a privilege for file symlinks and has no junction for files.
pub(crate) fn link_file(target: &Path, link: &Path) -> bool {
    #[cfg(unix)]
    let made = std::os::unix::fs::symlink(target, link).is_ok();
    #[cfg(windows)]
    let made = std::os::windows::fs::symlink_file(target, link).is_ok();
    if !made {
        eprintln!(
            "SKIPPED: cannot create a file symlink at {}",
            link.display()
        );
    }
    made
}

/// A temporary workspace holding `files` (relative path, text).
pub(crate) fn workspace(files: &[(&str, &str)]) -> (tempfile::TempDir, crate::sandbox::Sandbox) {
    let dir = tempfile::tempdir().unwrap();
    for (name, text) in files {
        let path = dir.path().join(name);
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(path, text).unwrap();
    }
    let sandbox = crate::sandbox::Sandbox::new(dir.path());
    (dir, sandbox)
}

/// Set a file's modified time to `secs` after the epoch.
pub(crate) fn set_mtime(path: &Path, secs: u64) {
    let file = std::fs::OpenOptions::new().write(true).open(path).unwrap();
    file.set_modified(std::time::UNIX_EPOCH + std::time::Duration::from_secs(secs))
        .unwrap();
}
