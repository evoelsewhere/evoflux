//! Blocking file-system helpers. Everything here runs inside
//! `evoflux_core::blocking::run`, never on the async runtime.

#![allow(clippy::disallowed_methods)]

use std::io::Read;
use std::path::Path;

/// `Path.exists()`: follows symlinks, false on any error.
pub(crate) fn exists(path: &Path) -> bool {
    std::fs::metadata(path).is_ok()
}

/// `Path.is_file()`.
pub(crate) fn is_file(path: &Path) -> bool {
    std::fs::metadata(path).is_ok_and(|m| m.is_file())
}

/// `Path.is_dir()`.
pub(crate) fn is_dir(path: &Path) -> bool {
    std::fs::metadata(path).is_ok_and(|m| m.is_dir())
}

/// Whether `path` itself is a symlink (not followed).
pub(crate) fn is_symlink(path: &Path) -> bool {
    std::fs::symlink_metadata(path).is_ok_and(|m| m.file_type().is_symlink())
}

/// A symlink, or on Windows a junction or other reparse point.
pub(crate) fn is_link(path: &Path) -> bool {
    if is_symlink(path) {
        return true;
    }
    is_reparse_point(path)
}

fn is_reparse_point(path: &Path) -> bool {
    const REPARSE_POINT: u32 = 0x400;
    std::fs::symlink_metadata(path).is_ok_and(|m| attributes(&m) & REPARSE_POINT != 0)
}

/// The Windows file attributes; other platforms have none.
fn attributes(meta: &std::fs::Metadata) -> u32 {
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        meta.file_attributes()
    }
    #[cfg(not(windows))]
    {
        let _ = meta;
        0
    }
}

/// `Path.stat().st_size`.
pub(crate) fn size(path: &Path) -> u64 {
    std::fs::metadata(path).map_or(0, |m| m.len())
}

/// `Path.stat().st_mtime` in nanoseconds; 0 when unreadable.
pub(crate) fn mtime_ns(path: &Path) -> i128 {
    let Ok(modified) = std::fs::metadata(path).and_then(|m| m.modified()) else {
        return 0;
    };
    match modified.duration_since(std::time::UNIX_EPOCH) {
        Ok(after) => i128::try_from(after.as_nanos()).unwrap_or(i128::MAX),
        Err(before) => -i128::try_from(before.duration().as_nanos()).unwrap_or(i128::MAX),
    }
}

/// The first `max` bytes of an opened file.
pub(crate) fn read_capped(file: std::fs::File, max: usize) -> std::io::Result<Vec<u8>> {
    let mut raw = Vec::new();
    file.take(u64::try_from(max).unwrap_or(u64::MAX))
        .read_to_end(&mut raw)?;
    Ok(raw)
}

/// Open `path`, a resolved path under `root`, with every component from `root`
/// down to the file held open first. Each component is opened as itself (a
/// link is not followed) and refused if it is a symlink or junction; the held
/// handles share neither delete nor rename, so no component can be swapped for
/// a link until the file handle is open. `Err` with `PermissionDenied` names
/// the component that is a link.
#[cfg(windows)]
pub(crate) fn open_pinned(root: &Path, path: &Path) -> std::io::Result<std::fs::File> {
    use std::os::windows::fs::OpenOptionsExt;
    const SHARE_READ_WRITE: u32 = 0x1 | 0x2;
    const FILE_READ_ATTRIBUTES: u32 = 0x80;
    const FILE_FLAG_BACKUP_SEMANTICS: u32 = 0x0200_0000;
    const FILE_FLAG_OPEN_REPARSE_POINT: u32 = 0x0020_0000;

    // Hold one component as itself; a symlink or junction is refused. A
    // component that is neither a link nor a folder makes the next open fail.
    let pin = |component: &Path| -> std::io::Result<std::fs::File> {
        let handle = std::fs::OpenOptions::new()
            .access_mode(FILE_READ_ATTRIBUTES)
            .share_mode(SHARE_READ_WRITE)
            .custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT)
            .open(component)?;
        if handle.metadata()?.file_type().is_symlink() {
            return Err(changed_to_link(component));
        }
        Ok(handle)
    };

    let mut current = root.to_path_buf();
    let mut held = vec![pin(&current)?];
    for part in path.components().skip(root.components().count()) {
        current.push(part);
        held.push(pin(&current)?);
    }
    // Every component down to the file itself is now held and is no link, so
    // the normal open below (which reads the data of a cloud placeholder or
    // other non-link reparse point) reaches the file that was checked.
    let file = std::fs::OpenOptions::new()
        .read(true)
        .share_mode(SHARE_READ_WRITE)
        .open(path);
    drop(held);
    file
}

#[cfg(windows)]
fn changed_to_link(path: &Path) -> std::io::Error {
    std::io::Error::new(
        std::io::ErrorKind::PermissionDenied,
        format!(
            "Path '{}' became a link while it was being opened",
            path.display()
        ),
    )
}

/// Open `path` for reading, following links.
#[cfg(unix)]
pub(crate) fn open_read(path: &Path) -> std::io::Result<std::fs::File> {
    std::fs::File::open(path)
}

/// The real path of an opened file, from `/proc/self/fd`.
#[cfg(target_os = "linux")]
pub(crate) fn opened_path(file: &std::fs::File) -> std::io::Result<std::path::PathBuf> {
    use std::os::unix::io::AsRawFd;
    std::fs::read_link(format!("/proc/self/fd/{}", file.as_raw_fd()))
}

/// Python's `Path.suffix`, lower-cased.
pub(crate) fn suffix_lower(path: &Path) -> String {
    let Some(name) = path.file_name().map(|n| n.to_string_lossy().into_owned()) else {
        return String::new();
    };
    match name.rfind('.') {
        Some(i) if i > 0 && i + 1 < name.len() => name.get(i..).unwrap_or_default().to_lowercase(),
        _ => String::new(),
    }
}

/// Children of `dir` as `(name, path)`; an unreadable directory has none.
pub(crate) fn children(dir: &Path) -> Vec<(String, std::path::PathBuf)> {
    let Ok(entries) = std::fs::read_dir(dir) else {
        return Vec::new();
    };
    entries
        .filter_map(Result::ok)
        .map(|entry| {
            (
                entry.file_name().to_string_lossy().into_owned(),
                entry.path(),
            )
        })
        .collect()
}

#[cfg(test)]
#[allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::indexing_slicing,
    clippy::panic,
    clippy::disallowed_methods
)]
mod tests {
    use super::*;

    #[test]
    fn suffix_follows_pathlib() {
        let s = |p: &str| suffix_lower(Path::new(p));
        assert_eq!(s("a/b.PNG"), ".png");
        assert_eq!(s("archive.tar.gz"), ".gz");
        assert_eq!(s(".png"), "");
        assert_eq!(s("noext"), "");
        assert_eq!(s("trailing."), "");
        assert_eq!(s("a.b/c"), "");
        assert_eq!(s(""), "");
    }

    #[test]
    fn predicates_follow_symlinks_and_swallow_errors() {
        let dir = tempfile::tempdir().unwrap();
        let file = dir.path().join("f.txt");
        std::fs::write(&file, "12345").unwrap();
        assert!(exists(&file) && is_file(&file) && !is_dir(&file));
        assert!(exists(dir.path()) && is_dir(dir.path()) && !is_file(dir.path()));
        let missing = dir.path().join("missing");
        assert!(!exists(&missing) && !is_file(&missing) && !is_dir(&missing));
        assert_eq!(size(&file), 5);
        assert_eq!(size(&missing), 0);
        assert_eq!(mtime_ns(&missing), 0);
        assert!(mtime_ns(&file) > 0);
    }

    #[test]
    fn times_before_the_epoch_are_negative() {
        let dir = tempfile::tempdir().unwrap();
        let file = dir.path().join("old.txt");
        std::fs::write(&file, "x").unwrap();
        let handle = std::fs::OpenOptions::new().write(true).open(&file).unwrap();
        handle
            .set_modified(std::time::UNIX_EPOCH - std::time::Duration::from_secs(100))
            .unwrap();
        assert_eq!(mtime_ns(&file), -100_000_000_000);
        handle
            .set_modified(std::time::UNIX_EPOCH + std::time::Duration::from_secs(7))
            .unwrap();
        assert_eq!(mtime_ns(&file), 7_000_000_000);
    }

    #[test]
    fn plain_files_and_directories_are_not_links() {
        let dir = tempfile::tempdir().unwrap();
        let file = dir.path().join("f.txt");
        std::fs::write(&file, "x").unwrap();
        for path in [file.as_path(), dir.path(), &dir.path().join("missing")] {
            assert!(!is_symlink(path), "{}", path.display());
            assert!(!is_reparse_point(path), "{}", path.display());
            assert!(!is_link(path), "{}", path.display());
        }
    }

    #[test]
    fn a_directory_link_is_a_link_and_reads_through_to_its_target() {
        let dir = tempfile::tempdir().unwrap();
        std::fs::create_dir(dir.path().join("real")).unwrap();
        let link = dir.path().join("alias");
        crate::testutil::link_dir(&dir.path().join("real"), &link);
        assert!(is_link(&link));
        assert!(is_dir(&link), "predicates follow the link");
        assert!(!is_link(&dir.path().join("real")));
        // A symlink is both; a Windows junction is only a reparse point.
        assert!(is_symlink(&link) || is_reparse_point(&link));
        if !cfg!(windows) {
            assert!(is_symlink(&link) && !is_reparse_point(&link));
        }
    }

    #[cfg(windows)]
    #[test]
    fn a_junction_is_a_reparse_point() {
        let dir = tempfile::tempdir().unwrap();
        std::fs::create_dir(dir.path().join("real")).unwrap();
        let link = dir.path().join("junction");
        let made = std::process::Command::new("cmd")
            .args(["/C", "mklink", "/J"])
            .arg(&link)
            .arg(dir.path().join("real"))
            .output()
            .unwrap();
        assert!(made.status.success());
        assert!(is_reparse_point(&link) && is_link(&link));
        assert!(!is_reparse_point(&dir.path().join("real")));
    }

    #[test]
    fn read_capped_stops_at_the_cap() {
        let dir = tempfile::tempdir().unwrap();
        let file = dir.path().join("f.txt");
        std::fs::write(&file, "abcdef").unwrap();
        let open = || std::fs::File::open(&file).unwrap();
        assert_eq!(read_capped(open(), 4).unwrap(), b"abcd");
        assert_eq!(read_capped(open(), 100).unwrap(), b"abcdef");
        assert_eq!(read_capped(open(), 0).unwrap(), b"");
    }

    #[cfg(windows)]
    #[test]
    fn open_pinned_refuses_a_component_that_is_a_link() {
        let dir = tempfile::tempdir().unwrap();
        let root = std::fs::canonicalize(dir.path()).unwrap();
        let root = std::path::PathBuf::from(root.display().to_string().trim_start_matches(r"\\?\"));
        std::fs::create_dir_all(root.join("d")).unwrap();
        std::fs::write(root.join("d/f.txt"), "inside").unwrap();
        let file = open_pinned(&root, &root.join("d").join("f.txt")).unwrap();
        assert_eq!(read_capped(file, 100).unwrap(), b"inside");

        std::fs::create_dir(root.join("real")).unwrap();
        std::fs::write(root.join("real/f.txt"), "behind").unwrap();
        crate::testutil::link_dir(&root.join("real"), &root.join("alias"));
        let err = open_pinned(&root, &root.join("alias").join("f.txt")).unwrap_err();
        assert_eq!(err.kind(), std::io::ErrorKind::PermissionDenied);
        assert!(err.to_string().contains("alias"), "{err}");
        assert!(open_pinned(&root, &root.join("d").join("none")).is_err());
    }

    #[cfg(windows)]
    #[test]
    fn open_pinned_reads_a_file_another_program_is_writing() {
        let dir = tempfile::tempdir().unwrap();
        let root = std::fs::canonicalize(dir.path()).unwrap();
        let root = std::path::PathBuf::from(root.display().to_string().trim_start_matches(r"\\?\"));
        std::fs::create_dir(root.join("d")).unwrap();
        let path = root.join("d").join("log.txt");
        std::fs::write(&path, "line").unwrap();
        let _writer = std::fs::OpenOptions::new()
            .append(true)
            .open(&path)
            .unwrap();
        // A folder another program lists (a file watcher, Explorer).
        let _lister = {
            use std::os::windows::fs::OpenOptionsExt;
            std::fs::OpenOptions::new()
                .read(true)
                .custom_flags(0x0200_0000)
                .open(root.join("d"))
                .unwrap()
        };
        let file = open_pinned(&root, &path).unwrap();
        assert_eq!(read_capped(file, 100).unwrap(), b"line");
    }

    #[test]
    fn children_lists_names_and_tolerates_missing_dirs() {
        let dir = tempfile::tempdir().unwrap();
        std::fs::write(dir.path().join("b"), "").unwrap();
        std::fs::create_dir(dir.path().join("a")).unwrap();
        let mut names: Vec<String> = children(dir.path()).into_iter().map(|c| c.0).collect();
        names.sort();
        assert_eq!(names, vec!["a", "b"]);
        assert!(children(&dir.path().join("none")).is_empty());
    }
}
