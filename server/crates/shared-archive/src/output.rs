//! Port of app/plugin_platform/installer.py::_safe_archive_name and safe writes.
use crate::{ArchiveError, Extracted, Limits};
use cap_fs_ext::DirExt;
use cap_std::fs::{Dir, OpenOptions};
use std::collections::HashSet;
use std::io::{Read, Write};
use std::path::Path;

fn components(name: &str, directory: bool) -> Result<Vec<&str>, ArchiveError> {
    let name = if directory {
        name.strip_suffix('/').unwrap_or(name)
    } else {
        name
    };
    if name.len() > 4096 || name.contains('\\') {
        return Err(ArchiveError::Path);
    }
    let parts: Vec<_> = name.split('/').collect();
    for part in &parts {
        if part.is_empty()
            || *part == "."
            || *part == ".."
            || part.ends_with(['.', ' '])
            || part
                .chars()
                .any(|c| c.is_control() || "<>:\"|?*".contains(c))
        {
            return Err(ArchiveError::Path);
        }
        let stem = part.split('.').next().unwrap_or("").to_ascii_uppercase();
        if matches!(
            stem.as_str(),
            "CON" | "PRN" | "AUX" | "NUL" | "CONIN$" | "CONOUT$"
        ) || ["COM", "LPT"].iter().any(|prefix| {
            stem.strip_prefix(prefix).is_some_and(|tail| {
                matches!(
                    tail,
                    "1" | "2" | "3" | "4" | "5" | "6" | "7" | "8" | "9" | "¹" | "²" | "³"
                )
            })
        }) {
            return Err(ArchiveError::Path);
        }
        if short_name_alias(part) {
            return Err(ArchiveError::Path);
        }
    }
    Ok(parts)
}

/// Whether `part` has the form of a Windows 8.3 short name: a base name (up to
/// the first `.`) ending in `~` and ASCII digits, as in `LONGDI~1` or
/// `FILENA~12.TXT`. On a volume with 8.3 names such a component can open an
/// existing directory under a different long name, which bypasses the
/// duplicate screening (SR-014), so it is refused on every platform. Other
/// names with `~` (`a~b`, `~tmp`, `a~`, `a~1b`, `x.y~1`) are kept.
fn short_name_alias(part: &str) -> bool {
    let base = part.split('.').next().unwrap_or(part);
    base.rsplit_once('~')
        .is_some_and(|(_, tail)| !tail.is_empty() && tail.bytes().all(|b| b.is_ascii_digit()))
}

fn create_directory(parent: &Dir, name: impl AsRef<Path>) -> Result<Dir, ArchiveError> {
    match parent.create_dir(&name) {
        Ok(()) => (),
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => (),
        Err(error) => return Err(error.into()),
    }
    // No check-then-open: links, junctions and replacements are refused during open.
    Ok(parent.open_dir_nofollow(name)?)
}

pub(crate) struct Output {
    root: Dir,
    seen: HashSet<String>,
    limits: Limits,
    stats: Extracted,
}
impl Output {
    pub(crate) fn new(dest: &Path, limits: Limits) -> Result<Self, ArchiveError> {
        let name = dest.file_name().ok_or(ArchiveError::Path)?;
        let parent = dest
            .parent()
            .filter(|p| !p.as_os_str().is_empty())
            .unwrap_or(Path::new("."));
        // The caller grants the parent; archive names never participate in this open.
        let parent = Dir::open_ambient_dir(parent, cap_std::ambient_authority())?;
        let root = create_directory(&parent, name)?;
        Ok(Self {
            root,
            seen: HashSet::new(),
            limits,
            stats: Extracted::default(),
        })
    }

    pub(crate) fn entry(
        &mut self,
        name: &str,
        directory: bool,
        size: u64,
        mode: u32,
        src: &mut impl Read,
    ) -> Result<(), ArchiveError> {
        if self.stats.entries >= self.limits.max_entries {
            return Err(ArchiveError::Entries);
        }
        let parts = components(name, directory)?;
        if !self
            .seen
            .insert(caseless::default_case_fold_str(&parts.join("/")))
        {
            return Err(ArchiveError::Duplicate);
        }
        if size > self.limits.max_total_bytes.saturating_sub(self.stats.bytes)
            || (directory && size != 0)
        {
            return Err(ArchiveError::Size);
        }
        self.stats.entries += 1;
        let mut parent = self.root.try_clone()?;
        let mut remaining = parts.iter().peekable();
        while let Some(part) = remaining.next() {
            if directory || remaining.peek().is_some() {
                parent = create_directory(&parent, part)?;
                continue;
            }
            let mut file =
                parent.open_with(part, OpenOptions::new().write(true).create_new(true))?;
            let mut actual = 0u64;
            let mut buffer = [0; 64 * 1024];
            loop {
                let read = src.read(&mut buffer)?;
                if read == 0 {
                    break;
                }
                actual = actual.checked_add(read as u64).ok_or(ArchiveError::Size)?;
                if actual > size {
                    return Err(ArchiveError::Size);
                }
                let chunk = buffer.get(..read).ok_or(ArchiveError::Size)?;
                file.write_all(chunk)?;
            }
            if actual != size {
                return Err(ArchiveError::Size);
            }
            self.stats.bytes += actual;
            portable_permissions(&file, mode)?;
        }
        Ok(())
    }
    pub(crate) fn finish(self) -> Extracted {
        self.stats
    }
}

#[cfg(unix)]
fn portable_permissions(file: &cap_std::fs::File, mode: u32) -> Result<(), ArchiveError> {
    use std::os::unix::fs::PermissionsExt;
    let permissions =
        std::fs::Permissions::from_mode(if mode & 0o111 != 0 { 0o755 } else { 0o644 });
    file.set_permissions(cap_std::fs::Permissions::from_std(permissions))?;
    Ok(())
}
#[cfg(not(unix))]
fn portable_permissions(_: &cap_std::fs::File, _: u32) -> Result<(), ArchiveError> {
    Ok(())
}
