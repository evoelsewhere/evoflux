//! Workspace path confinement (`SandboxConfig.validate_path` / `display_path`).
//!
//! The Rust tools get one allowed root, the session workspace. Python also
//! allows extra project roots, read-only roots and internal EvoFlux
//! directories; those are listed in `server/KNOWN_DIFFERENCES.md`.

use std::path::{Component, Path, PathBuf};

use crate::fnmatch::fnmatchcase;

/// `DEFAULT_DENIED_PATTERNS` from `app/agent/sandbox_config.py`.
const DENIED_PATTERNS: [&str; 2] = ["**/.env", "**/.env.*"];

const SYMLINK_LIMIT: usize = 40;

pub(crate) struct Sandbox {
    root: PathBuf,
}

impl Sandbox {
    /// `SandboxConfig(workspace=...)`: the root is resolved once.
    pub(crate) fn new(workspace_root: &Path) -> Self {
        Self {
            root: resolve(workspace_root)
                .unwrap_or_else(|| lexical_normalize(&absolute(workspace_root))),
        }
    }

    pub(crate) fn root(&self) -> &Path {
        &self.root
    }

    fn denied_by(&self, resolved: &Path) -> Option<&'static str> {
        // Case-insensitive on every platform: `.ENV` is `.env` on a
        // case-insensitive file system, and the patterns are lower case.
        let posix = posix_string(resolved).to_lowercase();
        DENIED_PATTERNS
            .into_iter()
            .find(|pattern| fnmatchcase(&posix, pattern))
    }

    fn is_allowed(&self, resolved: &Path) -> bool {
        is_under(resolved, &self.root)
    }

    /// Whether a file found while walking a directory may be read: a symlink
    /// must lead to an allowed, non-denied place. Python reads such files
    /// without checking; the Rust scan does not.
    pub(crate) fn permits_link(&self, path: &Path) -> bool {
        if !crate::fsutil::is_link(path) {
            return true;
        }
        let Some(resolved) = resolve(path) else {
            return false;
        };
        self.is_allowed(&resolved) && self.denied_by(&resolved).is_none()
    }

    /// Resolve `path` and refuse anything outside the workspace or on a deny list.
    pub(crate) fn validate_path(&self, path: &str) -> Result<PathBuf, String> {
        if path.starts_with('~') {
            return Err(format!(
                "Tilde paths are not allowed inside the sandbox: {path}"
            ));
        }

        // Python's `os.lstat` rejects a NUL before anything else is looked at.
        if path.contains('\0') {
            return Err(if cfg!(windows) {
                "lstat: embedded null character in path"
            } else {
                "lstat: embedded null byte"
            }
            .to_owned());
        }

        let given = Path::new(path);
        let candidate = if given.is_absolute() {
            given.to_path_buf()
        } else {
            self.root.join(given)
        };

        // A network path outside the workspace is refused before any file
        // system call: stat or resolve on it would contact the remote host.
        if is_foreign_network_path(&candidate, &self.root) {
            return Err(outside_message(&lexical_normalize(&candidate)));
        }

        // Walk every component looking for symlinks before resolving them.
        let mut check = candidate.clone();
        loop {
            if let Ok(meta) = std::fs::symlink_metadata(&check) {
                if meta.file_type().is_symlink() {
                    if let Ok(link) = std::fs::read_link(&check) {
                        let target = if link.is_absolute() {
                            link
                        } else {
                            check.parent().unwrap_or(&check).join(link)
                        };
                        let Some(target_resolved) = resolve(&target) else {
                            return Err(too_many_links(&candidate));
                        };
                        if let Some(denied) = self.denied_by(&target_resolved) {
                            return Err(format!(
                                "Symlink target is inside a denied root: {} -> {} (denied: {denied})",
                                candidate.display(),
                                target_resolved.display()
                            ));
                        }
                    }
                }
            }
            match check.parent() {
                Some(parent) => check = parent.to_path_buf(),
                None => break,
            }
        }

        let Some(resolved) = resolve(&candidate) else {
            return Err(too_many_links(&candidate));
        };
        if let Some(denied) = self.denied_by(&resolved) {
            return Err(format!(
                "Path '{}' is inside a denied sandbox root: {denied}",
                resolved.display()
            ));
        }
        if !self.is_allowed(&resolved) {
            return Err(outside_message(&resolved));
        }
        Ok(resolved)
    }

    /// Open a resolved path for reading so that the file read is the file that
    /// was judged: a folder swapped for a link between `validate_path` and the
    /// open cannot redirect it. Windows holds every component from the root
    /// down while it opens; Linux checks the opened handle's real path. Other
    /// Unix systems open by path (see `server/KNOWN_DIFFERENCES.md`).
    pub(crate) fn open_confined(&self, resolved: &Path) -> std::io::Result<std::fs::File> {
        if !self.is_allowed(resolved) || self.denied_by(resolved).is_some() {
            return Err(refused(resolved));
        }
        #[cfg(windows)]
        {
            crate::fsutil::open_pinned(&self.root, resolved)
        }
        #[cfg(unix)]
        {
            let file = crate::fsutil::open_read(resolved)?;
            #[cfg(target_os = "linux")]
            {
                let real = crate::fsutil::opened_path(&file)?;
                if !self.is_allowed(&real) || self.denied_by(&real).is_some() {
                    return Err(refused(&real));
                }
            }
            Ok(file)
        }
    }

    /// `display_path`: workspace-relative with `/`, else the absolute path.
    pub(crate) fn display_path(&self, resolved: &Path) -> String {
        if is_under(resolved, &self.root) {
            let rel = relative_to(resolved, &self.root);
            if rel.is_empty() {
                return self.root.display().to_string();
            }
            return rel;
        }
        resolved.display().to_string()
    }
}

fn refused(path: &Path) -> std::io::Error {
    std::io::Error::new(std::io::ErrorKind::PermissionDenied, outside_message(path))
}

fn too_many_links(path: &Path) -> String {
    format!("Too many levels of symbolic links: {}", path.display())
}

fn outside_message(resolved: &Path) -> String {
    format!(
        "Path '{}' is outside the allowed sandbox roots. Add it as an explicit project/read-only root before access.",
        resolved.display()
    )
}

/// `Path.as_posix()`.
fn posix_string(path: &Path) -> String {
    let text = path.display().to_string();
    if cfg!(windows) {
        text.replace('\\', "/")
    } else {
        text
    }
}

/// A network path that does not lead into `root` (judged without the disk).
fn is_foreign_network_path(candidate: &Path, root: &Path) -> bool {
    is_network_path(candidate) && !is_under(&lexical_normalize(candidate), root)
}

fn is_network_path(path: &Path) -> bool {
    use std::path::Prefix;
    matches!(
        path.components().next(),
        Some(Component::Prefix(p)) if matches!(
            p.kind(),
            Prefix::UNC(..) | Prefix::VerbatimUNC(..) | Prefix::DeviceNS(..)
        )
    )
}

fn component_key(component: &Component<'_>) -> String {
    let text = component.as_os_str().to_string_lossy().into_owned();
    if cfg!(windows) {
        text.to_lowercase()
    } else {
        text
    }
}

/// `Path.relative_to` as a containment test (case-insensitive on Windows).
pub(crate) fn is_under(child: &Path, parent: &Path) -> bool {
    let mut child_parts = child.components().map(|c| component_key(&c));
    parent
        .components()
        .map(|c| component_key(&c))
        .all(|p| child_parts.next().is_some_and(|c| c == p))
}

/// `str(child.relative_to(parent))` with `/` separators; empty when equal.
fn relative_to(child: &Path, parent: &Path) -> String {
    let skip = parent.components().count();
    child
        .components()
        .skip(skip)
        .map(|c| c.as_os_str().to_string_lossy().into_owned())
        .collect::<Vec<_>>()
        .join("/")
}

/// `os.path.normpath` on an absolute path: fold `.` and `..` without touching the disk.
pub(crate) fn lexical_normalize(path: &Path) -> PathBuf {
    let mut out = PathBuf::new();
    for component in path.components() {
        match component {
            Component::CurDir => {}
            Component::ParentDir => {
                let can_pop = matches!(out.components().next_back(), Some(Component::Normal(_)));
                if can_pop {
                    out.pop();
                }
            }
            other => out.push(other.as_os_str()),
        }
    }
    out
}

/// Strip the `\\?\` prefix `canonicalize` adds on Windows.
fn strip_verbatim(path: PathBuf) -> PathBuf {
    let text = path.display().to_string();
    if let Some(rest) = text.strip_prefix("\\\\?\\UNC\\") {
        return PathBuf::from(format!("\\\\{rest}"));
    }
    match text.strip_prefix("\\\\?\\") {
        Some(rest) if rest.chars().nth(1) == Some(':') => PathBuf::from(rest),
        _ => path,
    }
}

fn absolute(path: &Path) -> PathBuf {
    if path.has_root() && (!cfg!(windows) || path.is_absolute()) {
        return path.to_path_buf();
    }
    std::path::absolute(path).unwrap_or_else(|_| path.to_path_buf())
}

/// `Path.resolve()` (non-strict): follow symlinks, tolerate missing tails.
/// `None` when a link chain passes `SYMLINK_LIMIT`: the path is refused rather
/// than judged by an unresolved link.
///
/// Windows folds `..` lexically first, as `ntpath.realpath` does; elsewhere
/// each component is resolved in turn so `link/..` leaves the link target.
pub(crate) fn resolve(path: &Path) -> Option<PathBuf> {
    let start = absolute(path);
    if cfg!(windows) {
        // A path given with the `\\?\` prefix keeps it, as `ntpath.realpath` does.
        let keep_verbatim = start.display().to_string().starts_with("\\\\?\\");
        Some(resolve_prefix(&lexical_normalize(&start), keep_verbatim))
    } else {
        resolve_sequential(&start, 0)
    }
}

/// Canonicalize the longest existing prefix and re-attach the missing tail.
fn resolve_prefix(path: &Path, keep_verbatim: bool) -> PathBuf {
    let mut tail: Vec<std::ffi::OsString> = Vec::new();
    let mut head = path.to_path_buf();
    loop {
        if let Ok(real) = std::fs::canonicalize(&head) {
            let mut out = if keep_verbatim {
                real
            } else {
                strip_verbatim(real)
            };
            for part in tail.iter().rev() {
                out.push(part);
            }
            return out;
        }
        match (head.file_name().map(ToOwned::to_owned), head.parent()) {
            (Some(name), Some(parent)) => {
                tail.push(name);
                head = parent.to_path_buf();
            }
            _ => {
                let mut out = head;
                for part in tail.iter().rev() {
                    out.push(part);
                }
                return out;
            }
        }
    }
}

fn resolve_sequential(path: &Path, depth: usize) -> Option<PathBuf> {
    let mut out = PathBuf::new();
    for component in path.components() {
        match component {
            Component::CurDir => {}
            Component::ParentDir => {
                out.pop();
            }
            Component::Normal(name) => {
                out.push(name);
                let is_link =
                    std::fs::symlink_metadata(&out).is_ok_and(|m| m.file_type().is_symlink());
                if is_link {
                    if depth >= SYMLINK_LIMIT {
                        return None;
                    }
                    let link = std::fs::read_link(&out).ok()?;
                    let base = out.parent().map(Path::to_path_buf).unwrap_or_default();
                    let target = if link.is_absolute() {
                        link
                    } else {
                        base.join(link)
                    };
                    out = resolve_sequential(&target, depth + 1)?;
                }
            }
            other => out.push(other.as_os_str()),
        }
    }
    Some(out)
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

    fn sandbox() -> (tempfile::TempDir, Sandbox) {
        let dir = tempfile::tempdir().unwrap();
        let ws = dir.path().join("ws");
        std::fs::create_dir_all(ws.join("sub")).unwrap();
        std::fs::write(ws.join("a.txt"), "a").unwrap();
        std::fs::write(dir.path().join("secret.txt"), "s").unwrap();
        let sandbox = Sandbox::new(&ws);
        (dir, sandbox)
    }

    fn outside_error(sandbox: &Sandbox, path: &str) -> String {
        match sandbox.validate_path(path) {
            Err(message) => message,
            Ok(resolved) => panic!("{path} resolved to {}", resolved.display()),
        }
    }

    #[test]
    fn relative_and_absolute_paths_inside_the_workspace_resolve() {
        let (_dir, sandbox) = sandbox();
        let root = sandbox.root().to_path_buf();
        assert_eq!(sandbox.validate_path("a.txt").unwrap(), root.join("a.txt"));
        assert_eq!(sandbox.validate_path(".").unwrap(), root);
        assert_eq!(
            sandbox.validate_path("sub/../a.txt").unwrap(),
            root.join("a.txt")
        );
        assert_eq!(
            sandbox
                .validate_path(&root.join("sub").display().to_string())
                .unwrap(),
            root.join("sub")
        );
        assert_eq!(
            sandbox.validate_path("missing/deeper.txt").unwrap(),
            root.join("missing").join("deeper.txt")
        );
    }

    #[test]
    fn dotdot_out_of_the_workspace_is_refused() {
        let (_dir, sandbox) = sandbox();
        let message = outside_error(&sandbox, "../secret.txt");
        assert!(message.starts_with("Path '"), "{message}");
        assert!(message.contains("secret.txt"));
        assert!(message.ends_with(
            "' is outside the allowed sandbox roots. Add it as an explicit project/read-only root before access."
        ));
        assert!(sandbox.validate_path("sub/../../secret.txt").is_err());
        assert!(sandbox.validate_path("..").is_err());
        assert!(
            sandbox.validate_path("../ws/a.txt").is_ok(),
            "re-enters the workspace"
        );
    }

    #[test]
    fn absolute_paths_outside_the_workspace_are_refused() {
        let (dir, sandbox) = sandbox();
        let outside = dir.path().join("secret.txt");
        let message = outside_error(&sandbox, &outside.display().to_string());
        assert!(
            message.contains("is outside the allowed sandbox roots."),
            "{message}"
        );
        let elsewhere = if cfg!(windows) {
            "C:\\Windows\\win.ini"
        } else {
            "/etc/passwd"
        };
        assert!(sandbox.validate_path(elsewhere).is_err());
    }

    #[test]
    fn a_nul_in_the_path_is_refused_with_the_lstat_wording() {
        let (_dir, sandbox) = sandbox();
        let want = if cfg!(windows) {
            "lstat: embedded null character in path"
        } else {
            "lstat: embedded null byte"
        };
        for path in ["a\0b", "\0", "sub/\0"] {
            assert_eq!(outside_error(&sandbox, path), want);
        }
    }

    #[test]
    fn tilde_paths_are_refused_verbatim() {
        let (_dir, sandbox) = sandbox();
        assert_eq!(
            outside_error(&sandbox, "~/x"),
            "Tilde paths are not allowed inside the sandbox: ~/x"
        );
        assert_eq!(
            outside_error(&sandbox, "~"),
            "Tilde paths are not allowed inside the sandbox: ~"
        );
        assert!(sandbox.validate_path("a~").is_ok());
    }

    #[test]
    fn denied_patterns_apply_inside_the_workspace() {
        let (_dir, sandbox) = sandbox();
        let message = outside_error(&sandbox, ".env");
        assert!(
            message.ends_with("' is inside a denied sandbox root: **/.env"),
            "{message}"
        );
        let message = outside_error(&sandbox, "sub/.env.local");
        assert!(
            message.ends_with("' is inside a denied sandbox root: **/.env.*"),
            "{message}"
        );
        assert!(sandbox.validate_path("sub/env").is_ok());
        assert!(sandbox.validate_path("sub/.envrc").is_ok());
    }

    #[test]
    fn link_out_of_the_workspace_is_refused() {
        let (dir, sandbox) = sandbox();
        crate::testutil::link_dir(dir.path(), &sandbox.root().join("escape"));
        let message = outside_error(&sandbox, "escape/secret.txt");
        assert!(
            message.contains("is outside the allowed sandbox roots."),
            "{message}"
        );
        assert!(message.contains("secret.txt"));
        assert!(sandbox.validate_path("escape").is_err());
        assert!(
            sandbox.validate_path("escape/ws/a.txt").is_ok(),
            "ends back inside"
        );
    }

    #[test]
    fn link_inside_the_workspace_is_followed() {
        let (_dir, sandbox) = sandbox();
        crate::testutil::link_dir(&sandbox.root().join("sub"), &sandbox.root().join("alias"));
        let root = sandbox.root().to_path_buf();
        assert_eq!(sandbox.validate_path("alias").unwrap(), root.join("sub"));
    }

    #[test]
    fn symlink_to_a_denied_file_is_refused_with_the_symlink_message() {
        let (_dir, sandbox) = sandbox();
        std::fs::write(sandbox.root().join(".env"), "KEY=1").unwrap();
        if !crate::testutil::link_file(
            &sandbox.root().join(".env"),
            &sandbox.root().join("innocent.txt"),
        ) {
            return;
        }
        let message = outside_error(&sandbox, "innocent.txt");
        assert!(
            message.starts_with("Symlink target is inside a denied root: "),
            "{message}"
        );
        assert!(message.contains(" -> "));
        assert!(message.ends_with("(denied: **/.env)"), "{message}");
    }

    #[test]
    fn denied_names_match_in_any_case() {
        let (_dir, sandbox) = sandbox();
        for name in [".ENV", ".Env", "sub/.ENV.local", "sub/.Env.Production"] {
            let message = outside_error(&sandbox, name);
            assert!(
                message.contains("is inside a denied sandbox root: **/.env"),
                "{name}: {message}"
            );
        }
        assert!(sandbox.validate_path("sub/ENV").is_ok());
        assert!(sandbox.validate_path("sub/.ENVRC").is_ok());
    }

    #[cfg(unix)]
    #[test]
    fn a_link_chain_past_the_limit_is_refused_not_half_resolved() {
        let (dir, sandbox) = sandbox();
        let root = sandbox.root().to_path_buf();
        // l0 -> l1 -> ... -> l(LIMIT) -> outside: one link more than is followed.
        let name = |i: usize| root.join(format!("l{i}"));
        for i in 0..=SYMLINK_LIMIT {
            let target = if i == SYMLINK_LIMIT {
                dir.path().to_path_buf()
            } else {
                name(i + 1)
            };
            crate::testutil::link_dir(&target, &name(i));
        }
        let message = outside_error(&sandbox, "l0/secret.txt");
        assert!(
            message.starts_with("Too many levels of symbolic links: "),
            "{message}"
        );
        assert!(outside_error(&sandbox, "l0").starts_with("Too many levels"));
        assert!(!sandbox.permits_link(&name(0)), "ls and grep skip it");
    }

    #[test]
    fn the_link_limit_message_names_the_path() {
        assert_eq!(
            too_many_links(Path::new("/ws/l0")),
            format!(
                "Too many levels of symbolic links: {}",
                Path::new("/ws/l0").display()
            )
        );
    }

    /// `ws/d/secret.txt` exists as a real folder, and `outside/secret.txt` sits
    /// next to the workspace.
    fn swap_fixture() -> (tempfile::TempDir, Sandbox, PathBuf, PathBuf) {
        let (dir, sandbox) = sandbox();
        let root = sandbox.root().to_path_buf();
        std::fs::create_dir(root.join("d")).unwrap();
        std::fs::write(root.join("d").join("secret.txt"), "inside").unwrap();
        let outside = resolve(dir.path()).unwrap().join("outside");
        std::fs::create_dir(&outside).unwrap();
        std::fs::write(outside.join("secret.txt"), "OUTSIDE").unwrap();
        (dir, sandbox, root, outside)
    }

    fn read_confined(sandbox: &Sandbox, resolved: &Path) -> std::io::Result<Vec<u8>> {
        sandbox
            .open_confined(resolved)
            .and_then(|file| crate::fsutil::read_capped(file, 100))
    }

    #[test]
    fn open_confined_reads_a_validated_file() {
        let (_dir, sandbox, root, _outside) = swap_fixture();
        let resolved = sandbox.validate_path("d/secret.txt").unwrap();
        assert_eq!(read_confined(&sandbox, &resolved).unwrap(), b"inside");
        crate::testutil::link_dir(&root.join("d"), &root.join("alias"));
        let through_inside_link = resolve(&root.join("alias").join("secret.txt")).unwrap();
        assert_eq!(
            read_confined(&sandbox, &through_inside_link).unwrap(),
            b"inside"
        );
    }

    #[test]
    fn open_confined_refuses_paths_outside_or_denied() {
        let (_dir, sandbox, root, outside) = swap_fixture();
        std::fs::write(root.join(".env"), "KEY=1").unwrap();
        for path in [outside.join("secret.txt"), root.join(".env")] {
            let err = read_confined(&sandbox, &path).unwrap_err();
            assert_eq!(err.kind(), std::io::ErrorKind::PermissionDenied, "{err}");
        }
    }

    /// The race in one step: the folder is swapped for a link to outside
    /// after `validate_path` judged it and before the file is opened.
    #[cfg(any(windows, target_os = "linux"))]
    #[test]
    fn a_folder_swapped_for_a_link_after_validation_is_refused() {
        let (_dir, sandbox, root, outside) = swap_fixture();
        let resolved = sandbox.validate_path("d/secret.txt").unwrap();
        std::fs::rename(root.join("d"), root.join("d-real")).unwrap();
        crate::testutil::link_dir(&outside, &root.join("d"));
        let err = read_confined(&sandbox, &resolved).unwrap_err();
        assert_eq!(err.kind(), std::io::ErrorKind::PermissionDenied, "{err}");
    }

    /// A thread keeps swapping `d` between the real folder and a link to
    /// outside while `read` runs: the outside content is never returned.
    #[cfg(any(windows, target_os = "linux"))]
    #[test]
    fn read_never_returns_outside_content_while_a_folder_is_swapped() {
        use std::sync::atomic::{AtomicBool, Ordering};
        let (_dir, sandbox, root, outside) = swap_fixture();
        let stop = std::sync::Arc::new(AtomicBool::new(false));
        let swapper = {
            let stop = std::sync::Arc::clone(&stop);
            let (real, parked, link) = (root.join("d"), root.join("d-real"), root.join("d"));
            std::thread::spawn(move || {
                while !stop.load(Ordering::Relaxed) {
                    if std::fs::rename(&real, &parked).is_err() {
                        continue;
                    }
                    crate::testutil::link_dir(&outside, &link);
                    // A junction is a folder to remove_dir; a symlink is a file elsewhere.
                    let _ = std::fs::remove_dir(&link).or_else(|_| std::fs::remove_file(&link));
                    while std::fs::rename(&parked, &real).is_err() {
                        if stop.load(Ordering::Relaxed) {
                            return;
                        }
                    }
                }
            })
        };
        let mut inside_reads = 0;
        for _ in 0..300 {
            if let Ok(text) = crate::read::run(&sandbox, "d/secret.txt", 1, None) {
                assert!(!text.contains("OUTSIDE"), "outside file read: {text}");
                inside_reads += 1;
            }
        }
        stop.store(true, Ordering::Relaxed);
        swapper.join().unwrap();
        eprintln!("inside reads: {inside_reads} of 300");
    }

    #[test]
    fn permits_link_judges_only_links() {
        let (dir, sandbox) = sandbox();
        let root = sandbox.root().to_path_buf();
        assert!(sandbox.permits_link(&root.join("a.txt")), "a plain file");
        crate::testutil::link_dir(dir.path(), &root.join("escape"));
        crate::testutil::link_dir(&root.join("sub"), &root.join("alias"));
        assert!(!sandbox.permits_link(&root.join("escape")));
        assert!(sandbox.permits_link(&root.join("alias")));
    }

    #[cfg(windows)]
    #[test]
    fn windows_drive_letters_and_unc_paths_are_refused() {
        let (_dir, sandbox) = sandbox();
        for path in [
            "C:\\Windows\\win.ini",
            "c:/windows/win.ini",
            "Z:\\nope\\file.txt",
            "\\\\evil-host\\share\\file.txt",
            "//evil-host/share/file.txt",
            "\\\\?\\C:\\Windows\\win.ini",
            "\\\\.\\C:\\Windows\\win.ini",
            "\\Windows\\win.ini",
            "C:win.ini",
        ] {
            let message = outside_error(&sandbox, path);
            assert!(
                message.contains("is outside the allowed sandbox roots."),
                "{path}: {message}"
            );
        }
    }

    #[cfg(windows)]
    #[test]
    fn only_network_paths_outside_the_root_are_foreign() {
        let root = Path::new("\\\\host\\share\\ws");
        let foreign = |p: &str| is_foreign_network_path(Path::new(p), root);
        assert!(foreign("\\\\host\\share\\other\\a.txt"));
        assert!(foreign("\\\\host\\share\\ws\\..\\other"));
        assert!(foreign("\\\\.\\C:\\ws\\a.txt"));
        assert!(!foreign("\\\\host\\share\\ws\\a.txt"));
        assert!(!foreign("\\\\host\\share\\ws\\sub\\..\\a.txt"));
        // A local path is never a network path, inside the root or not.
        assert!(!foreign("C:\\elsewhere\\a.txt"));
        assert!(!is_foreign_network_path(
            Path::new("C:\\ws\\a.txt"),
            Path::new("C:\\ws")
        ));
    }

    #[cfg(windows)]
    #[test]
    fn unc_refusal_names_the_normalised_path_without_touching_the_network() {
        let (_dir, sandbox) = sandbox();
        let message = outside_error(&sandbox, "\\\\evil-host\\share\\a\\..\\file.txt");
        assert_eq!(
            message,
            "Path '\\\\evil-host\\share\\file.txt' is outside the allowed sandbox roots. Add it as an explicit project/read-only root before access."
        );
    }

    #[cfg(windows)]
    #[test]
    fn strip_verbatim_only_unwraps_drive_and_unc_paths() {
        let strip = |p: &str| strip_verbatim(PathBuf::from(p)).display().to_string();
        assert_eq!(strip("\\\\?\\C:\\ws\\a"), "C:\\ws\\a");
        assert_eq!(strip("\\\\?\\UNC\\host\\share\\a"), "\\\\host\\share\\a");
        assert_eq!(
            strip("\\\\?\\Volume{1234}\\ws"),
            "\\\\?\\Volume{1234}\\ws",
            "a volume path has no drive letter to fall back to"
        );
        assert_eq!(strip("C:\\ws"), "C:\\ws");
    }

    #[cfg(windows)]
    #[test]
    fn windows_paths_compare_case_insensitively() {
        let (_dir, sandbox) = sandbox();
        let upper = sandbox
            .root()
            .join("A.TXT")
            .display()
            .to_string()
            .to_uppercase();
        assert!(sandbox.validate_path(&upper).is_ok());
    }

    #[test]
    fn absolute_keeps_rooted_paths_and_anchors_the_rest() {
        let (_dir, sandbox) = sandbox();
        let root = sandbox.root().to_path_buf();
        // A fully absolute path is returned as given, `..` and all.
        let dotted = root.join("sub").join("..").join("a.txt");
        assert_eq!(absolute(&dotted), dotted);
        let relative = absolute(Path::new("some/where"));
        assert!(relative.is_absolute(), "{}", relative.display());
        assert!(relative.ends_with("some/where"));
        #[cfg(windows)]
        {
            // Rooted but driveless: Windows adds the current drive.
            let rooted = absolute(Path::new("\\Windows\\win.ini"));
            assert!(rooted.is_absolute(), "{}", rooted.display());
            assert!(rooted.ends_with("Windows\\win.ini"));
        }
    }

    #[test]
    fn resolve_follows_a_link_through_a_missing_tail() {
        let (_dir, sandbox) = sandbox();
        let root = sandbox.root().to_path_buf();
        crate::testutil::link_dir(&root.join("sub"), &root.join("alias"));
        let tail = Path::new("nothing").join("x.txt");
        assert_eq!(
            resolve(&root.join("alias").join(&tail)).unwrap(),
            root.join("sub").join(&tail)
        );
    }

    #[test]
    fn a_missing_tail_behind_an_outside_link_is_refused() {
        let (dir, sandbox) = sandbox();
        crate::testutil::link_dir(dir.path(), &sandbox.root().join("escape"));
        let message = outside_error(&sandbox, "escape/missing.txt");
        assert!(
            message.contains("is outside the allowed sandbox roots."),
            "{message}"
        );
    }

    #[test]
    fn sequential_resolution_folds_dots_and_follows_links() {
        let (dir, sandbox) = sandbox();
        let root = sandbox.root().to_path_buf();
        assert_eq!(
            resolve_sequential(&root.join("sub").join("..").join("a.txt"), 0).unwrap(),
            root.join("a.txt")
        );
        assert_eq!(
            resolve_sequential(&root.join(".").join("sub"), 0).unwrap(),
            root.join("sub")
        );
        crate::testutil::link_dir(&root.join("sub"), &root.join("alias"));
        let tail = Path::new("x").join("y");
        assert_eq!(
            resolve_sequential(&root.join("alias").join(&tail), 0).unwrap(),
            root.join("sub").join(&tail)
        );
        // `link/..` leaves the link target, not the link's own folder.
        crate::testutil::link_dir(&dir.path().join("out-of-ws"), &root.join("up"));
        assert_eq!(
            resolve_sequential(&root.join("up").join("..").join("n"), 0).unwrap(),
            dir.path().join("n")
        );
    }

    #[test]
    fn sequential_resolution_stops_at_the_link_limit() {
        let (dir, _sandbox) = sandbox();
        let links = dir.path().join("chain");
        std::fs::create_dir_all(&links).unwrap();
        let real = dir.path().join("real");
        std::fs::create_dir_all(&real).unwrap();
        let name = |i: usize| links.join(format!("l{i}"));
        // l0 -> l1 -> ... -> l(n-1) -> real: n links in a row.
        let build = |n: usize| {
            for i in 0..n {
                let target = if i + 1 == n {
                    real.clone()
                } else {
                    name(i + 1)
                };
                crate::testutil::link_dir(&target, &name(i));
            }
        };
        build(SYMLINK_LIMIT);
        assert_eq!(resolve_sequential(&name(0), 0), Some(real.clone()));
        // One more link than the limit: the path is refused, never half-resolved.
        std::fs::remove_dir(name(SYMLINK_LIMIT - 1)).unwrap();
        crate::testutil::link_dir(&name(SYMLINK_LIMIT), &name(SYMLINK_LIMIT - 1));
        crate::testutil::link_dir(&real, &name(SYMLINK_LIMIT));
        assert_eq!(resolve_sequential(&name(0), 0), None);
    }

    #[test]
    fn a_link_loop_ends_instead_of_recursing_forever() {
        let (_dir, sandbox) = sandbox();
        let root = sandbox.root().to_path_buf();
        // `one` -> `two`, then `two` is replaced by a link back to `one`.
        std::fs::create_dir(root.join("two")).unwrap();
        crate::testutil::link_dir(&root.join("two"), &root.join("one"));
        std::fs::remove_dir(root.join("two")).unwrap();
        crate::testutil::link_dir(&root.join("one"), &root.join("two"));
        assert_eq!(resolve_sequential(&root.join("one"), 0), None);
    }

    #[test]
    fn display_path_is_workspace_relative_with_slashes() {
        let (_dir, sandbox) = sandbox();
        let root = sandbox.root().to_path_buf();
        assert_eq!(
            sandbox.display_path(&root.join("sub").join("x.rs")),
            "sub/x.rs"
        );
        assert_eq!(sandbox.display_path(&root), root.display().to_string());
        let outside = root.parent().unwrap().join("secret.txt");
        assert_eq!(
            sandbox.display_path(&outside),
            outside.display().to_string()
        );
    }

    #[test]
    fn is_under_requires_whole_components() {
        assert!(is_under(Path::new("/a/b/c"), Path::new("/a/b")));
        assert!(is_under(Path::new("/a/b"), Path::new("/a/b")));
        assert!(!is_under(Path::new("/a/bc"), Path::new("/a/b")));
        assert!(!is_under(Path::new("/a"), Path::new("/a/b")));
    }

    #[test]
    fn lexical_normalize_folds_dots_but_never_pops_the_root() {
        let base = if cfg!(windows) { "C:\\" } else { "/" };
        let p = |s: &str| lexical_normalize(&Path::new(base).join(s));
        assert_eq!(p("a/./b/../c"), Path::new(base).join("a").join("c"));
        assert_eq!(p("../../x"), Path::new(base).join("x"));
    }
}
