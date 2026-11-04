//! Which folders may be a chat session workspace.
//!
//! Rust-only restriction (KNOWN_DIFFERENCES): Python accepts any absolute
//! path, so `workspace=~` lets the model read `~/.ssh/id_rsa` through the file
//! tools. Here the path is resolved first (`~`, `..` and links) and accepted
//! only when it is equal to or inside an allowed root: the default workspace
//! folder (`EVOFLUX_WORKSPACE_DIR`) or a folder of `EVOFLUX_WORKSPACE_ROOTS`.
//! A root the denylist refuses (a drive root, the home folder, a system or
//! credentials folder) is ignored with a warning. Inside a root the denylist
//! stays as a second layer: a network (UNC), device or non-disk verbatim path, a
//! name Windows rewrites (trailing `.` or space, `:`), the home directory or one
//! of its ancestors, a system directory (or a folder above one), another user's
//! profile on Windows, or a credential or config folder, in or above.

use std::path::{Component, Path, PathBuf};

use evoflux_core::config::Settings;

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

/// The one `HOME_SENSITIVE` folder the default workspace folder may live in.
const LOCAL_SHARE: &str = ".local/share";

/// The default workspace folder, under the home folder: the only place in
/// `LOCAL_SHARE` that is exempt from the credential folders.
const DEFAULT_WORKSPACE: &str = ".local/share/evoflux-workspace";

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
    /// The config dir: equal to, inside or above is refused.
    config: Vec<PathBuf>,
    /// Credential folders under the home folder: equal to, inside or above is refused.
    home_sensitive: Vec<PathBuf>,
    /// `~/.local/share`: a credential folder like the others, except for the
    /// default workspace folder.
    local_share: Vec<PathBuf>,
    /// `~/.local/share/evoflux-workspace`: the one place `local_share` is not
    /// applied to, for the default workspace folder.
    default_workspace: Vec<PathBuf>,
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
        let mut home_sensitive = Vec::new();
        let mut local_share = Vec::new();
        let mut default_workspace = Vec::new();
        if !home.as_os_str().is_empty() {
            for name in HOME_SENSITIVE {
                if name == LOCAL_SHARE {
                    local_share.push(home.join(name));
                } else {
                    home_sensitive.push(home.join(name));
                }
            }
            let default = strip_verbatim(home.join(DEFAULT_WORKSPACE));
            if resolve(&default.to_string_lossy(), home)
                .is_some_and(|real| parts(&default) == parts(&real))
            {
                default_workspace.push(default);
            }
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
            config: both(vec![config_dir.to_path_buf()]),
            home_sensitive: both(home_sensitive),
            local_share: both(local_share),
            // Unlike protected folders, an exemption must never gain a link's target.
            default_workspace,
        }
    }

    /// Why `path` (already resolved) cannot be a workspace, if it cannot.
    pub(crate) fn refusal(&self, path: &Path) -> Option<&'static str> {
        self.refusal_with(path, true)
    }

    /// [`Self::refusal`] for the default workspace folder (`default`) or what is
    /// inside it: `~/.local/share/evoflux-workspace` is exempt from the
    /// `~/.local/share` rule and from nothing else, so `~/.local/share/keyrings`
    /// and every other credential folder stay refused.
    fn refusal_with(&self, path: &Path, default: bool) -> Option<&'static str> {
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
        let exempt = default && self.default_workspace.iter().any(|dir| within(dir, &path));
        let share: &[PathBuf] = if exempt { &[] } else { &self.local_share };
        let credentials = self.config.iter().chain(&self.home_sensitive).chain(share);
        if credentials
            .into_iter()
            .any(|dir| within(dir, &path) || within(&path, dir))
        {
            return Some("a credentials or configuration folder");
        }
        None
    }
}

/// The reason for a workspace that is in no allowed root.
const OUTSIDE_ROOTS: &str = "outside the allowed workspace folders";

/// What every refusal tells the user to do about it.
pub const ALLOW_HINT: &str = "To allow a folder, add it to EVOFLUX_WORKSPACE_ROOTS (a list of folders, separated by ';' on Windows and ':' elsewhere).";

/// One allowed root, resolved at startup.
struct Root {
    path: PathBuf,
    /// The default workspace folder (`EVOFLUX_WORKSPACE_DIR`): exempt from the
    /// `~/.local/share` rule only, and only at its real default location.
    default: bool,
}

/// The folders a chat workspace may be in, with the denylist as a second layer.
pub struct Allowed {
    roots: Vec<Root>,
    protected: Protected,
}

impl Allowed {
    /// The allowed roots of these settings: `workspace_dir` plus
    /// `workspace_roots`, each resolved (`~`, `..`, links) once, here. A root
    /// that is not absolute or that the denylist refuses is ignored with a warning.
    pub fn current(settings: &Settings) -> Self {
        let protected = Protected::current(&settings.home_dir, &settings.config_dir);
        let candidates = std::iter::once((settings.workspace_dir.as_path(), true)).chain(
            settings
                .workspace_roots
                .iter()
                .map(|root| (root.as_path(), false)),
        );
        let mut roots: Vec<Root> = Vec::new();
        for (raw, default) in candidates {
            let Some(path) = resolve(&raw.to_string_lossy(), &settings.home_dir) else {
                tracing::warn!(root = %raw.display(), "workspace_root_ignored_not_absolute");
                continue;
            };
            if let Some(why) = protected.refusal_with(&path, default) {
                tracing::warn!(root = %path.display(), why, "workspace_root_ignored_refused");
                continue;
            }
            if !roots.iter().any(|known| known.path == path) {
                roots.push(Root { path, default });
            }
        }
        Self { roots, protected }
    }

    /// Why `path` (already resolved) cannot be a workspace, if it cannot: it
    /// must be a local disk path, equal to or inside a root, and clear of the
    /// denylist. The answer completes "it is ...".
    pub fn refusal(&self, path: &Path) -> Option<&'static str> {
        let path = strip_verbatim(path.to_path_buf());
        if is_network_or_device(&path) {
            return Some("a network share or device path");
        }
        if !path.is_absolute() {
            return Some("not an absolute local path");
        }
        let mut matched = false;
        for root in self.roots.iter().filter(|root| within(&root.path, &path)) {
            matched = true;
            if let Some(why) = self
                .protected
                .refusal_with(&path, root.default)
                .or_else(|| credential_inside(&root.path, &path))
            {
                // Every matching root must be clear; an inner root cannot undo
                // a credential-folder refusal relative to an outer root.
                return Some(why);
            }
        }
        if matched {
            return None;
        }
        // Outside every root, a denylist reason is the more useful one to give.
        self.protected.refusal(&path).or(Some(OUTSIDE_ROOTS))
    }
}

/// A credential folder name anywhere below `root` (`<root>/sub/.ssh`,
/// `<root>/backup/Users/old/.aws`), whatever the root is. A name of two parts
/// (`.local/share`) matches two consecutive folders.
fn credential_inside(root: &Path, path: &Path) -> Option<&'static str> {
    let relative = parts(path).split_off(parts(root).len());
    HOME_SENSITIVE
        .iter()
        .any(|name| {
            let name: Vec<String> = name
                .split('/')
                .map(|part| fold(part, CASE_INSENSITIVE))
                .collect();
            relative.windows(name.len()).any(|window| window == name)
        })
        .then_some("a credentials or configuration folder")
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
pub fn resolve(raw: &str, home: &Path) -> Option<PathBuf> {
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

/// Drop the `\\?\` prefix `canonicalize` adds on Windows from a disk path
/// (`\\?\C:\x` is `C:\x`) and from a share (`\\?\UNC\s\x` is `\\s\x`). Other
/// verbatim paths (`\\?\Volume{GUID}\`, `\\?\GLOBALROOT\...`) keep their prefix,
/// so they are still seen as device paths.
pub fn strip_verbatim(path: PathBuf) -> PathBuf {
    use std::path::Prefix;
    let text = path.to_string_lossy();
    let rest = match path.components().next() {
        Some(Component::Prefix(prefix)) => match prefix.kind() {
            Prefix::VerbatimUNC(..) => text
                .strip_prefix(r"\\?\UNC\")
                .map(|rest| format!(r"\\{rest}")),
            Prefix::VerbatimDisk(_) => text.strip_prefix(r"\\?\").map(str::to_owned),
            _ => None,
        },
        _ => None,
    };
    rest.map_or(path, PathBuf::from)
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

    /// The allowlist of settings with this home folder and `roots` as
    /// `EVOFLUX_WORKSPACE_ROOTS`; the config folder sits next to the home folder.
    fn allowed(home: &Path, roots: &[PathBuf]) -> Allowed {
        let config = home.with_file_name("evoflux-config");
        let vars = std::collections::HashMap::from([
            (
                "EVOFLUX_CONFIG_DIR".to_owned(),
                config.to_string_lossy().into_owned(),
            ),
            (
                "EVOFLUX_WORKSPACE_ROOTS".to_owned(),
                std::env::join_paths(roots)
                    .unwrap()
                    .to_string_lossy()
                    .into_owned(),
            ),
        ]);
        let settings = Settings::from_vars(&vars, Some(home), &config).unwrap();
        Allowed::current(&settings)
    }

    fn link(link: &Path, target: &Path) -> bool {
        if cfg!(windows) {
            #[allow(clippy::disallowed_methods)] // a test, nothing async runs here
            return std::process::Command::new("cmd")
                .args(["/C", "mklink", "/J"])
                .arg(link)
                .arg(target)
                .output()
                .map(|o| o.status.success())
                .unwrap_or(false);
        }
        #[cfg(unix)]
        {
            std::os::unix::fs::symlink(target, link).is_ok()
        }
        #[cfg(not(unix))]
        {
            false
        }
    }

    #[test]
    fn a_root_and_what_is_inside_it_are_accepted_a_sibling_is_refused() {
        let (_dir, root, _guard) = protected();
        let home = root.join("home");
        let projects = home.join("projects");
        let allowed = allowed(&home, std::slice::from_ref(&projects));
        assert_eq!(allowed.refusal(&projects), None);
        assert_eq!(allowed.refusal(&projects.join("a").join("b")), None);
        let outside = Some("outside the allowed workspace folders");
        assert_eq!(allowed.refusal(&home.join("projects2")), outside);
        assert_eq!(allowed.refusal(&home.join("other")), outside);
        assert_eq!(allowed.refusal(&home.join("x").join("projects")), outside);
    }

    #[test]
    fn another_user_next_to_the_home_folder_is_refused() {
        // The Linux /home/<other> gap: a folder next to the home folder.
        let (_dir, root, _guard) = protected();
        let home = root.join("home").join("me");
        let other = root.join("home").join("other");
        let projects = home.join("projects");
        std::fs::create_dir_all(&projects).unwrap();
        std::fs::create_dir_all(&other).unwrap();
        let allowed = allowed(&home, std::slice::from_ref(&projects));
        assert!(allowed.refusal(&other).is_some());
        assert!(allowed.refusal(&other.join("work")).is_some());
        assert!(allowed.refusal(&projects.join("x")).is_none());
        if cfg!(unix) {
            assert!(allowed.refusal(Path::new("/home/other/work")).is_some());
            assert!(allowed.refusal(Path::new("/home/other")).is_some());
        }
    }

    #[test]
    fn a_link_inside_a_root_pointing_outside_is_refused() {
        let (_dir, root, _guard) = protected();
        let home = root.join("home");
        let projects = home.join("projects");
        let outside = home.join("outside");
        std::fs::create_dir_all(&projects).unwrap();
        std::fs::create_dir_all(&outside).unwrap();
        if !link(&projects.join("door"), &outside) {
            return;
        }
        let allowed = allowed(&home, std::slice::from_ref(&projects));
        let through = projects.join("door").join("x");
        let resolved = resolve(&through.to_string_lossy(), &home).unwrap();
        assert_eq!(resolved, outside.join("x"));
        assert!(allowed.refusal(&resolved).is_some());
        assert!(allowed.refusal(&projects.join("real")).is_none());
    }

    #[test]
    fn a_credential_folder_inside_a_root_is_still_refused() {
        let (_dir, root, _guard) = protected();
        let home = root.join("home");
        let projects = home.join("projects");
        let allowed = allowed(&home, &[projects.clone(), home.join("data")]);
        for dir in [
            projects.join(".ssh"),
            projects.join(".ssh").join("keys"),
            projects.join(".local").join("share").join("x"),
            home.join("data").join(".aws"),
        ] {
            assert_eq!(
                allowed.refusal(&dir),
                Some("a credentials or configuration folder"),
                "{}",
                dir.display()
            );
        }
        assert!(allowed.refusal(&home.join("data").join("a")).is_none());
        assert!(allowed.refusal(&projects.join(".sshx")).is_none());
        assert!(allowed
            .refusal(&projects.join(".local").join("bin"))
            .is_none());
    }

    #[test]
    fn a_credential_folder_deeper_below_a_root_is_refused() {
        let (_dir, root, _guard) = protected();
        let home = root.join("home");
        let data = home.join("data");
        let allowed = allowed(&home, std::slice::from_ref(&data));
        let refused = Some("a credentials or configuration folder");
        for dir in [
            data.join("sub").join(".ssh"),
            data.join("sub").join(".ssh").join("keys"),
            data.join("backup").join("Users").join("old").join(".aws"),
            data.join("a").join("b").join(".gnupg").join("x"),
            data.join("a").join(".local").join("share").join("x"),
            data.join("a").join(".vscode"),
        ] {
            assert_eq!(allowed.refusal(&dir), refused, "{}", dir.display());
        }
        // Whole names only, and a folder that merely holds them is fine.
        for dir in [
            data.join("sub").join(".sshx"),
            data.join("sub").join("ssh"),
            data.join("sub").join(".local").join("bin"),
            data.join("sub").join("share"),
        ] {
            assert_eq!(allowed.refusal(&dir), None, "{}", dir.display());
        }
        if CASE_INSENSITIVE {
            assert_eq!(allowed.refusal(&data.join("sub").join(".SSH")), refused);
            assert_eq!(
                allowed.refusal(&data.join("sub").join(".Aws").join("x")),
                refused
            );
        }
    }

    #[test]
    fn overlapping_roots_cannot_override_a_credential_folder_refusal() {
        let (_dir, root, _guard) = protected();
        let home = root.join("home");
        let projects = home.join("projects");
        let credentials = projects.join("sub").join(".ssh");
        for roots in [
            [projects.clone(), credentials.clone()],
            [credentials.clone(), projects.clone()],
        ] {
            let allowed = allowed(&home, &roots);
            assert_eq!(
                allowed.refusal(&credentials.join("new")),
                Some("a credentials or configuration folder")
            );
            assert_eq!(allowed.refusal(&projects.join("sub").join("plain")), None);
        }
    }

    #[test]
    fn a_root_the_denylist_refuses_is_ignored() {
        let (_dir, root, _guard) = protected();
        let home = root.join("home");
        let top = root.ancestors().last().unwrap().to_path_buf();
        let bad_roots = [
            top,
            home.clone(),
            root.clone(),
            home.join(".ssh"),
            home.join(".ssh").join("inner"),
            root.join("evoflux-config"),
            PathBuf::from("relative/root"),
        ];
        let allowed = allowed(&home, &bad_roots);
        for path in [
            home.join("projects"),
            home.join(".ssh").join("inner").join("x"),
            root.join("evoflux-config").join("x"),
            root.join("elsewhere"),
        ] {
            assert!(allowed.refusal(&path).is_some(), "{}", path.display());
        }
        // Only the default workspace folder is left.
        assert_eq!(allowed.roots.len(), 1);
    }

    #[test]
    fn the_default_workspace_folder_is_allowed_inside_a_credentials_parent() {
        let (_dir, root, _guard) = protected();
        let home = root.join("home");
        let allowed = allowed(&home, &[]);
        let share = home.join(".local").join("share");
        let default = share.join("evoflux-workspace");
        assert_eq!(allowed.refusal(&default), None);
        assert_eq!(allowed.refusal(&default.join("06ae6ab0")), None);
        // Its surroundings stay refused, and so does a credentials folder in it.
        assert!(allowed.refusal(&share).is_some());
        assert!(allowed.refusal(&share.join("keyrings")).is_some());
        assert!(allowed.refusal(&default.join(".ssh")).is_some());
        assert!(allowed
            .refusal(&default.join("a").join("b").join(".aws"))
            .is_some());
    }

    /// The allowlist with `dir` as `EVOFLUX_WORKSPACE_DIR` and no other root.
    fn allowed_default(home: &Path, dir: &Path) -> Allowed {
        let config = home.with_file_name("evoflux-config");
        let vars = std::collections::HashMap::from([
            (
                "EVOFLUX_CONFIG_DIR".to_owned(),
                config.to_string_lossy().into_owned(),
            ),
            (
                "EVOFLUX_WORKSPACE_DIR".to_owned(),
                dir.to_string_lossy().into_owned(),
            ),
        ]);
        let settings = Settings::from_vars(&vars, Some(home), &config).unwrap();
        Allowed::current(&settings)
    }

    #[test]
    fn an_existing_default_workspace_is_still_allowed() {
        let (_dir, root, _guard) = protected();
        let home = root.join("home");
        let default = home.join(DEFAULT_WORKSPACE);
        std::fs::create_dir_all(&default).unwrap();
        for allowed in [allowed(&home, &[]), allowed_default(&home, &default)] {
            assert_eq!(allowed.refusal(&default), None);
            assert_eq!(allowed.refusal(&default.join("sid")), None);
        }
    }

    #[cfg(any(windows, unix))]
    fn assert_linked_default_is_refused() {
        let (_dir, root, _guard) = protected();
        let home = root.join("home");
        let share = home.join(".local").join("share");
        let keyrings = share.join("keyrings");
        let default = share.join("evoflux-workspace");
        std::fs::create_dir_all(&keyrings).unwrap();
        // Do not silently skip: Windows must exercise a real junction, Unix a symlink.
        #[cfg(windows)]
        {
            #[allow(clippy::disallowed_methods)] // synchronous junction fixture
            let output = std::process::Command::new("cmd")
                .args(["/C", "mklink", "/J"])
                .arg(&default)
                .arg(&keyrings)
                .output()
                .unwrap();
            assert!(
                output.status.success(),
                "junction fixture: {} {}",
                String::from_utf8_lossy(&output.stdout),
                String::from_utf8_lossy(&output.stderr)
            );
        }
        #[cfg(unix)]
        std::os::unix::fs::symlink(&keyrings, &default).unwrap();
        let requested = default.join("sid");
        let resolved = resolve(&requested.to_string_lossy(), &home).unwrap();
        assert_eq!(resolved, keyrings.join("sid"));
        for allowed in [
            allowed(&home, &[]),
            allowed_default(&home, &default),
            allowed_default(&home, &keyrings),
        ] {
            assert_eq!(
                allowed.refusal(&resolved),
                Some("a credentials or configuration folder")
            );
            assert!(allowed.roots.is_empty());
        }
    }

    #[cfg(windows)]
    #[test]
    fn a_default_workspace_junction_to_keyrings_is_refused() {
        assert_linked_default_is_refused();
    }

    #[cfg(unix)]
    #[test]
    fn a_default_workspace_symlink_to_keyrings_is_refused() {
        assert_linked_default_is_refused();
    }

    #[test]
    fn a_default_workspace_dir_is_not_exempt_from_the_other_credential_folders() {
        let (_dir, root, _guard) = protected();
        let home = root.join("home");
        let share = home.join(".local").join("share");
        for dir in [
            home.join(".ssh"),
            home.join(".aws").join("x"),
            home.join(".gnupg"),
            home.join(".config").join("evoflux"),
            home.join(".claude"),
            share.clone(),
            share.join("keyrings"),
            share.join("keyrings").join("x"),
            home.join(".local"),
            home.clone(),
            root.join("evoflux-config").join("ws"),
        ] {
            let allowed = allowed_default(&home, &dir);
            assert!(allowed.roots.is_empty(), "{}", dir.display());
            assert!(
                allowed.refusal(&dir.join("sid")).is_some(),
                "{}",
                dir.display()
            );
        }
        // The real default is still the one allowed place under `~/.local/share`.
        let allowed = allowed_default(&home, &share.join("evoflux-workspace"));
        assert_eq!(allowed.roots.len(), 1);
        assert_eq!(
            allowed.refusal(&share.join("evoflux-workspace").join("s")),
            None
        );
        assert!(allowed.refusal(&share.join("keyrings")).is_some());
    }

    #[test]
    fn non_disk_verbatim_and_unrooted_paths_are_refused() {
        let (_dir, root, _guard) = protected();
        let home = root.join("home");
        let allowed = allowed(&home, &[home.join("projects")]);
        let guid = r"\\?\Volume{12345678-1234-1234-1234-123456789abc}\projects";
        for path in [
            guid,
            r"\\?\Volume{12345678-1234-1234-1234-123456789abc}\",
            r"\\?\GLOBALROOT\Device\HarddiskVolume1\projects",
            r"\\.\PhysicalDrive0",
            "projects/x",
            "",
        ] {
            assert!(allowed.refusal(Path::new(path)).is_some(), "{path}");
        }
        if cfg!(windows) {
            assert_eq!(
                allowed.refusal(Path::new(guid)),
                Some("a network share or device path")
            );
            // The prefix is kept, so the path is still a device path.
            assert_eq!(resolve(guid, &home), Some(PathBuf::from(guid)));
        }
    }

    #[test]
    fn a_root_given_with_other_case_matches_on_windows() {
        if !cfg!(windows) {
            return;
        }
        let (_dir, root, _guard) = protected();
        let home = root.join("home");
        let projects = home.join("projects");
        std::fs::create_dir_all(&projects).unwrap();
        let shouted = PathBuf::from(projects.to_string_lossy().to_uppercase());
        let allowed = allowed(&home, &[shouted]);
        assert_eq!(allowed.refusal(&projects.join("x")), None);
        assert_eq!(allowed.refusal(&projects), None);
        let lowered = PathBuf::from(projects.join("x").to_string_lossy().to_lowercase());
        assert_eq!(allowed.refusal(&lowered), None);
        assert!(allowed.refusal(&home.join("projects2")).is_some());
    }

    #[test]
    fn roots_are_canonicalised_once_and_repeats_are_dropped() {
        let (_dir, root, _guard) = protected();
        let home = root.join("home");
        let projects = home.join("projects");
        std::fs::create_dir_all(&projects).unwrap();
        let dotted = projects.join("a").join("..");
        let allowed = allowed(&home, &[projects.clone(), dotted, projects.clone()]);
        assert_eq!(allowed.roots.len(), 2);
        assert!(allowed.roots.iter().any(|r| r.path == projects));
    }

    #[test]
    fn verbatim_prefixes_are_stripped_from_disk_and_share_paths_only() {
        if !cfg!(windows) {
            return;
        }
        let strip = |text: &str| strip_verbatim(PathBuf::from(text));
        assert_eq!(strip(r"\\?\C:\work\x"), PathBuf::from(r"C:\work\x"));
        assert_eq!(
            strip(r"\\?\UNC\server\share\x"),
            PathBuf::from(r"\\server\share\x")
        );
        for kept in [
            r"\\?\Volume{12345678-1234-1234-1234-123456789abc}\x",
            r"\\?\GLOBALROOT\Device\x",
            r"C:\work\x",
        ] {
            assert_eq!(strip(kept), PathBuf::from(kept));
        }
    }
}
