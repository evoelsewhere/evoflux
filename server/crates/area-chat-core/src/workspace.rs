//! Which folders may be a chat session workspace.
//!
//! Rust-only restriction (KNOWN_DIFFERENCES): Python accepts any absolute
//! path, so `workspace=~` lets the model read `~/.ssh/id_rsa` through the file
//! tools. Here the path is resolved first (`~`, `..` and links), then refused
//! when it is a filesystem root, a network (UNC) or device path, a name Windows
//! rewrites (trailing `.` or space, `:`), the home directory or one of its
//! ancestors, a system directory (or a folder above one), another user's
//! profile on Windows, or equal to, inside or above a credential or config
//! folder.

use std::path::{Component, Path, PathBuf};

/// Folders under the home directory that hold credentials or application state.
const HOME_SENSITIVE: [&str; 25] = [
    ".ssh",
    ".aws",
    ".gnupg",
    ".config",
    ".kube",
    ".docker",
    "AppData",
    "Library",
    ".local/share",
    ".azure",
    ".password-store",
    ".netrc",
    ".mozilla",
    ".cargo",
    ".claude",
    ".codex",
    ".gem",
    ".terraform.d",
    "snap",
    ".var/app",
    ".npmrc",
    ".pypirc",
    ".git-credentials",
    ".vscode",
    "NTUSER.DAT",
];

/// Paths compare without regard to case where the filesystem usually does.
const CASE_INSENSITIVE: bool = cfg!(any(windows, target_os = "macos"));

/// System directories on Unix. `/private` holds macOS's `/private/etc` and
/// `/private/var`.
const UNIX_SYSTEM: [&str; 17] = [
    "/etc", "/usr", "/bin", "/sbin", "/var", "/proc", "/sys", "/dev", "/boot", "/root", "/System",
    "/Library", "/private", "/run", "/opt", "/srv", "/snap",
];

/// Windows environment variables that name system directories.
const WINDOWS_SYSTEM_VARS: [&str; 4] =
    ["WINDIR", "ProgramFiles", "ProgramFiles(x86)", "ProgramData"];

/// Folders on the Windows system drive that no workspace may be in or above.
const WINDOWS_DRIVE_SYSTEM: [&str; 2] = ["$Recycle.Bin", "System Volume Information"];

/// The folders a workspace must stay clear of.
pub(crate) struct Protected {
    home: Vec<PathBuf>,
    /// Equal to, inside or above is refused.
    system: Vec<PathBuf>,
    /// Folders holding one profile per user (`C:\Users`): the folder itself,
    /// what is above it and every profile in it but the home folder are refused.
    profiles: Vec<PathBuf>,
    /// Equal to, inside or above is refused.
    sensitive: Vec<PathBuf>,
}

impl Protected {
    /// The protected set for this machine: `home` and `config_dir` come from
    /// `Settings`; system directories come from the OS.
    pub(crate) fn current(home: &Path, config_dir: &Path) -> Self {
        let mut system: Vec<PathBuf> = Vec::new();
        let mut profiles = Vec::new();
        if cfg!(windows) {
            system.extend(
                WINDOWS_SYSTEM_VARS
                    .iter()
                    .filter_map(std::env::var_os)
                    .filter(|value| !value.is_empty())
                    .map(PathBuf::from),
            );
            let drive = std::env::var("SystemDrive").unwrap_or_else(|_| "C:".to_owned());
            let drive = format!("{}\\", drive.trim_end_matches(['\\', '/']));
            system.extend(
                WINDOWS_DRIVE_SYSTEM
                    .iter()
                    .map(|name| Path::new(&drive).join(name)),
            );
            profiles.push(Path::new(&drive).join("Users"));
        } else {
            system.extend(UNIX_SYSTEM.iter().map(PathBuf::from));
        }
        Self::new(home, config_dir, system).with_profiles(profiles)
    }

    /// Also protect these folders of user profiles, as the `Users` folder
    /// above the home folder already is.
    fn with_profiles(mut self, mut roots: Vec<PathBuf>) -> Self {
        roots.append(&mut self.profiles);
        self.profiles = dedup_both(roots);
        self
    }

    pub(crate) fn new(home: &Path, config_dir: &Path, system: Vec<PathBuf>) -> Self {
        let mut sensitive = vec![config_dir.to_path_buf()];
        if !home.as_os_str().is_empty() {
            sensitive.extend(HOME_SENSITIVE.iter().map(|name| home.join(name)));
        }
        let both = dedup_both;
        let home_paths = if home.as_os_str().is_empty() {
            Vec::new()
        } else {
            both(vec![home.to_path_buf()])
        };
        // The folder above a home folder named `Users` holds the other profiles.
        let profiles = home
            .parent()
            .filter(|parent| {
                parent
                    .file_name()
                    .is_some_and(|name| name.to_string_lossy().eq_ignore_ascii_case("users"))
            })
            .map(|parent| vec![parent.to_path_buf()])
            .unwrap_or_default();
        Self {
            home: home_paths,
            profiles: both(profiles),
            system: both(system),
            sensitive: both(sensitive),
        }
    }

    /// Why `path` (already resolved) cannot be a workspace, if it cannot.
    pub(crate) fn refusal(&self, path: &Path) -> Option<&'static str> {
        let path = strip_verbatim(path.to_path_buf());
        if is_network_or_device(&path) {
            return Some("a network share or device path");
        }
        if cfg!(windows) && has_rewritten_name(&path) {
            return Some("a name Windows would rewrite (a trailing dot or space, or a ':')");
        }
        if is_root(&path) {
            return Some("a filesystem root");
        }
        if self.home.iter().any(|home| within(&path, home)) {
            return Some("the home folder or a folder above it");
        }
        if self
            .system
            .iter()
            .any(|dir| within(dir, &path) || within(&path, dir))
        {
            return Some("a system folder");
        }
        if self.profiles.iter().any(|root| {
            within(&path, root)
                || (within(root, &path) && !self.home.iter().any(|home| within(home, &path)))
        }) {
            return Some("the profiles folder or another user's profile");
        }
        if self
            .sensitive
            .iter()
            .any(|dir| within(dir, &path) || within(&path, dir))
        {
            return Some("a credentials or configuration folder");
        }
        None
    }
}

/// A protected folder reached through a link is protected under both names.
fn dedup_both(paths: Vec<PathBuf>) -> Vec<PathBuf> {
    paths
        .into_iter()
        .flat_map(|p| {
            let real = std::fs::canonicalize(&p).ok();
            [Some(p), real]
        })
        .flatten()
        .map(strip_verbatim)
        .collect()
}

/// `path` with `~` expanded, folded and link-resolved without requiring it to
/// exist: the deepest existing part is canonicalized, the rest is appended.
/// `None` when the path is not absolute.
pub(crate) fn resolve(raw: &str, home: &Path) -> Option<PathBuf> {
    let expanded = match raw.strip_prefix('~') {
        Some(rest) if rest.is_empty() || rest.starts_with(['/', '\\']) => {
            home.join(rest.trim_start_matches(['/', '\\']))
        }
        _ => PathBuf::from(raw),
    };
    if !expanded.is_absolute() {
        return None;
    }
    let mut resolved = PathBuf::new();
    for component in expanded.components() {
        match component {
            Component::Prefix(_) | Component::RootDir => resolved.push(component),
            Component::CurDir => {}
            Component::ParentDir => {
                resolved.pop();
            }
            Component::Normal(name) => {
                resolved.push(name);
                if let Ok(real) = std::fs::canonicalize(&resolved) {
                    resolved = real;
                }
            }
        }
    }
    Some(strip_verbatim(resolved))
}

/// Drop the `\\?\` prefix `canonicalize` adds on Windows.
pub(crate) fn strip_verbatim(path: PathBuf) -> PathBuf {
    let text = path.to_string_lossy();
    if let Some(rest) = text.strip_prefix(r"\\?\UNC\") {
        return PathBuf::from(format!(r"\\{rest}"));
    }
    match text.strip_prefix(r"\\?\") {
        Some(rest) => PathBuf::from(rest),
        None => path,
    }
}

/// Anything but a plain drive or Unix root: `\\server\share`, `\\localhost\C$`, `\\.\COM1`.
/// A chat workspace has no use for one, and a loopback admin share names the
/// same folder as a local path the protected list cannot match.
fn is_network_or_device(path: &Path) -> bool {
    use std::path::Prefix;
    matches!(
        path.components().next(),
        Some(Component::Prefix(prefix)) if !matches!(prefix.kind(), Prefix::Disk(_))
    )
}

/// A folder name Windows normalizes to another one: `.ssh.` and `.ssh ` open
/// `.ssh`, and `x::$INDEX_ALLOCATION` opens the folder `x`.
fn has_rewritten_name(path: &Path) -> bool {
    path.components().any(|component| match component {
        Component::Normal(name) => {
            let name = name.to_string_lossy();
            name.ends_with(['.', ' ']) || name.contains(':')
        }
        _ => false,
    })
}

/// A path with no folder name: `/`, `C:\`, `\\server\share\`.
fn is_root(path: &Path) -> bool {
    !path
        .components()
        .any(|component| matches!(component, Component::Normal(_)))
}

/// `inner` is `outer` or inside it, by whole components; case-insensitive on
/// Windows and macOS.
fn within(outer: &Path, inner: &Path) -> bool {
    let outer = parts(outer);
    let inner = parts(inner);
    inner.starts_with(&outer)
}

fn parts(path: &Path) -> Vec<String> {
    path.components()
        .map(|component| fold(&component.as_os_str().to_string_lossy(), CASE_INSENSITIVE))
        .collect()
}

fn fold(text: &str, insensitive: bool) -> String {
    if insensitive {
        text.to_lowercase()
    } else {
        text.to_owned()
    }
}

#[cfg(test)]
#[allow(clippy::unwrap_used)]
mod tests {
    use super::*;

    fn protected() -> (tempfile::TempDir, PathBuf, Protected) {
        let dir = tempfile::tempdir().unwrap();
        let root = std::fs::canonicalize(dir.path()).unwrap();
        let home = strip_verbatim(root.join("home"));
        let system = strip_verbatim(root.join("sys"));
        let config = strip_verbatim(root.join("elsewhere").join("evoflux-config"));
        for path in [&home, &system, &config] {
            std::fs::create_dir_all(path).unwrap();
        }
        let guard = Protected::new(&home, &config, vec![system.join("etc")]);
        (dir, strip_verbatim(root), guard)
    }

    #[test]
    fn roots_are_refused() {
        let (_dir, root, guard) = protected();
        let top = root.ancestors().last().unwrap().to_path_buf();
        assert_eq!(guard.refusal(&top), Some("a filesystem root"));
        if cfg!(windows) {
            assert!(guard.refusal(Path::new(r"\\server\share\")).is_some());
            assert!(guard.refusal(Path::new(r"\\?\UNC\server\share")).is_some());
            assert!(guard.refusal(Path::new(r"\\?\C:\")).is_some());
        }
    }

    #[test]
    fn home_and_its_ancestors_are_refused() {
        let (_dir, root, guard) = protected();
        let home = root.join("home");
        assert_eq!(
            guard.refusal(&home),
            Some("the home folder or a folder above it")
        );
        assert!(guard.refusal(&root).is_some());
        assert!(guard.refusal(root.parent().unwrap()).is_some());
        assert!(guard.refusal(&home.join("projects").join("x")).is_none());
    }

    #[test]
    fn system_folders_are_refused_with_everything_inside() {
        let (_dir, root, guard) = protected();
        let etc = root.join("sys").join("etc");
        assert_eq!(guard.refusal(&etc), Some("a system folder"));
        assert_eq!(guard.refusal(&etc.join("nginx")), Some("a system folder"));
        assert!(guard.refusal(&root.join("sys").join("other")).is_none());
        // A folder above a system folder would contain it.
        assert_eq!(guard.refusal(&root.join("sys")), Some("a system folder"));
    }

    #[test]
    fn the_second_batch_of_credential_folders_is_protected() {
        let (_dir, root, guard) = protected();
        let home = root.join("home");
        for rel in [
            ".mozilla",
            ".cargo",
            ".claude",
            ".codex",
            ".gem",
            ".terraform.d",
            "snap",
            ".var/app",
            ".var/app/org.x.App/data",
            ".npmrc",
            ".pypirc",
            ".git-credentials",
            ".vscode",
            ".config",
            "NTUSER.DAT",
            "AppData",
        ] {
            assert!(guard.refusal(&home.join(rel)).is_some(), "{rel}");
        }
        assert!(guard.refusal(&home.join(".var")).is_some());
        assert!(guard.refusal(&home.join(".var").join("other")).is_none());
        assert!(guard.refusal(&home.join("snapshots")).is_none());
    }

    #[test]
    fn other_users_profiles_and_the_profiles_folder_are_refused() {
        let dir = tempfile::tempdir().unwrap();
        let root = strip_verbatim(std::fs::canonicalize(dir.path()).unwrap());
        let users = root.join("Users");
        let home = users.join("me");
        let config = root.join("cfg");
        for path in [&home, &users.join("other"), &config] {
            std::fs::create_dir_all(path).unwrap();
        }
        let guard = Protected::new(&home, &config, Vec::new());
        let profiles = Some("the profiles folder or another user's profile");
        assert!(guard.refusal(&users).is_some());
        assert_eq!(guard.refusal(&users.join("other")), profiles);
        assert_eq!(guard.refusal(&users.join("other").join("x")), profiles);
        assert_eq!(guard.refusal(&users.join("Public")), profiles);
        assert!(guard.refusal(&home.join("projects").join("x")).is_none());
        // A home folder that is not under a `Users` folder protects no siblings.
        let flat = Protected::new(&root.join("me"), &config, Vec::new());
        assert!(flat.refusal(&root.join("other")).is_none());
    }

    #[test]
    fn windows_current_protects_users_recycle_bin_and_volume_information() {
        if !cfg!(windows) {
            return;
        }
        let guard = Protected::current(Path::new(r"D:\Home\me"), Path::new(r"D:\Cfg"));
        for path in [
            r"C:\Users",
            r"C:\Users\other",
            r"C:\Users\other\code",
            r"C:\$Recycle.Bin",
            r"C:\$Recycle.Bin\S-1",
            r"C:\System Volume Information",
        ] {
            assert!(guard.refusal(Path::new(path)).is_some(), "{path}");
        }
        assert!(guard.refusal(Path::new(r"D:\work\repo")).is_none());
        let own = Protected::current(Path::new(r"C:\Users\me"), Path::new(r"D:\Cfg"));
        assert!(own.refusal(Path::new(r"C:\Users\me\code\x")).is_none());
        assert!(own.refusal(Path::new(r"C:\Users\you\code")).is_some());
    }

    #[test]
    fn credential_and_config_folders_are_refused_above_equal_and_inside() {
        let (_dir, root, guard) = protected();
        let home = root.join("home");
        let config = root.join("elsewhere").join("evoflux-config");
        for name in HOME_SENSITIVE {
            let dir = home.join(name);
            assert!(guard.refusal(&dir).is_some(), "{name}");
            assert!(guard.refusal(&dir.join("sub").join("deep")).is_some());
        }
        assert_eq!(
            guard.refusal(&config),
            Some("a credentials or configuration folder")
        );
        assert!(guard.refusal(&config.join("sub")).is_some());
        // Above the config dir but not above the home dir.
        assert_eq!(
            guard.refusal(&root.join("elsewhere")),
            Some("a credentials or configuration folder")
        );
        assert!(guard.refusal(&root.join("elsewhere2")).is_none());
        assert!(guard.refusal(&home.join(".sshx")).is_none());
        assert!(guard.refusal(&home.join(".configs").join("x")).is_none());
    }

    #[test]
    fn network_and_device_paths_are_refused_whatever_they_point_at() {
        if !cfg!(windows) {
            return;
        }
        let guard = Protected::new(
            Path::new(r"C:\Users\Someone"),
            Path::new(r"C:\Cfg"),
            Vec::new(),
        );
        for path in [
            r"\\localhost\C$\Users\Someone",
            r"\\127.0.0.1\C$\Users\Someone\.ssh",
            r"\\?\UNC\localhost\C$\Users\Someone",
            r"\\server\share\project",
            r"\\.\COM1",
        ] {
            assert_eq!(
                guard.refusal(Path::new(path)),
                Some("a network share or device path"),
                "{path}"
            );
        }
        assert!(guard.refusal(Path::new(r"D:\work")).is_none());
    }

    #[test]
    fn windows_names_that_are_rewritten_are_refused() {
        if !cfg!(windows) {
            return;
        }
        let guard = Protected::new(
            Path::new(r"C:\Users\Someone"),
            Path::new(r"C:\Cfg"),
            Vec::new(),
        );
        for path in [
            r"D:\work\x.",
            r"D:\work\x ",
            r"D:\work\x.\y",
            r"D:\work\x:y",
            r"D:\work\x::$INDEX_ALLOCATION",
        ] {
            assert!(
                guard.refusal(Path::new(path)).unwrap().contains("rewrite"),
                "{path}"
            );
        }
        assert!(guard.refusal(Path::new(r"D:\work\x.y\z")).is_none());
    }

    #[test]
    fn the_added_credential_folders_are_protected() {
        let (_dir, root, guard) = protected();
        let home = root.join("home");
        for rel in [
            "Library",
            ".local/share",
            ".local/share/keyrings",
            ".azure",
            ".password-store",
            ".netrc",
        ] {
            assert!(guard.refusal(&home.join(rel)).is_some(), "{rel}");
        }
        assert!(guard.refusal(&home.join(".local").join("bin")).is_none());
    }

    #[test]
    fn case_is_folded_only_where_the_filesystem_is_insensitive() {
        assert_eq!(fold("Library", true), "library");
        assert_eq!(fold("Library", false), "Library");
        assert_eq!(CASE_INSENSITIVE, cfg!(any(windows, target_os = "macos")));
    }

    #[test]
    fn normal_project_folders_are_accepted() {
        let (_dir, root, guard) = protected();
        assert!(guard
            .refusal(&root.join("home").join("projects").join("x"))
            .is_none());
        assert!(guard.refusal(&root.join("work").join("repo")).is_none());
    }

    #[test]
    fn current_protects_the_real_system_folders() {
        let home = PathBuf::from(if cfg!(windows) {
            r"C:\Users\someone"
        } else {
            "/home/someone"
        });
        let config = home.join("cfg");
        let guard = Protected::current(&home, &config);
        if cfg!(windows) {
            for var in WINDOWS_SYSTEM_VARS {
                if let Some(dir) = std::env::var_os(var) {
                    assert_eq!(
                        guard.refusal(&PathBuf::from(&dir).join("x")),
                        Some("a system folder"),
                        "{var}"
                    );
                }
            }
        } else {
            for dir in UNIX_SYSTEM {
                let path = Path::new(dir).join("x");
                assert!(guard.refusal(&path).is_some(), "{dir}");
                assert!(guard.refusal(Path::new(dir)).is_some(), "{dir}");
            }
        }
        assert!(guard.refusal(&home.join("projects").join("x")).is_none());
    }

    #[test]
    fn windows_comparison_ignores_case_and_verbatim_prefix() {
        if !cfg!(windows) {
            return;
        }
        let guard = Protected::new(
            Path::new(r"C:\Users\Someone"),
            Path::new(r"C:\Cfg\EvoFlux"),
            vec![PathBuf::from(r"C:\Windows")],
        );
        assert!(guard.refusal(Path::new(r"c:\WINDOWS\system32")).is_some());
        assert!(guard.refusal(Path::new(r"\\?\C:\Windows")).is_some());
        assert!(guard.refusal(Path::new(r"c:\users\SOMEONE")).is_some());
        assert!(guard
            .refusal(Path::new(r"C:\Users\someone\appdata\local"))
            .is_some());
        assert!(guard.refusal(Path::new(r"c:\cfg\evoflux\x")).is_some());
        assert!(guard.refusal(Path::new(r"D:\work\repo")).is_none());
        assert!(guard
            .refusal(Path::new(r"C:\Users\Someone\projects\x"))
            .is_none());
    }

    #[test]
    fn resolve_expands_home_folds_dots_and_needs_no_existing_folder() {
        let (_dir, root, _guard) = protected();
        let home = root.join("home");
        assert_eq!(resolve("~", &home).unwrap(), home);
        assert_eq!(resolve("~/a/../b", &home).unwrap(), home.join("b"));
        let raw = home
            .join("new")
            .join("..")
            .join("..")
            .join("home")
            .join("x");
        assert_eq!(
            resolve(&raw.to_string_lossy(), &home).unwrap(),
            home.join("x")
        );
        assert!(resolve("relative/dir", &home).is_none());
        assert!(resolve("~other", &home).is_none());
    }

    #[test]
    #[allow(clippy::disallowed_methods)] // a test, nothing async runs here
    fn resolve_follows_links_before_the_check() {
        let (_dir, root, guard) = protected();
        let home = root.join("home");
        let target = home.join(".ssh");
        std::fs::create_dir_all(&target).unwrap();
        let link = root.join("innocent");
        let linked = if cfg!(windows) {
            std::process::Command::new("cmd")
                .args(["/C", "mklink", "/J"])
                .arg(&link)
                .arg(&target)
                .output()
                .map(|o| o.status.success())
                .unwrap_or(false)
        } else {
            #[cfg(unix)]
            {
                std::os::unix::fs::symlink(&target, &link).is_ok()
            }
            #[cfg(not(unix))]
            {
                false
            }
        };
        if !linked {
            return;
        }
        let through = link.join("keys");
        let resolved = resolve(&through.to_string_lossy(), &home).unwrap();
        assert_eq!(resolved, target.join("keys"));
        assert!(guard.refusal(&resolved).is_some());
        // `..` after a link pops the link's target, not the link's parent.
        let up = format!("{}/../x", link.to_string_lossy());
        assert_eq!(resolve(&up, &home).unwrap(), home.join("x"));
    }
}
