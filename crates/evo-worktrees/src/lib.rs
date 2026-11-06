//! Managed Git worktrees: isolated working copies for delegated agents and
//! nested sessions.
//!
//! A worktree of the project's repository, on a branch of its own cut from the
//! current `HEAD`. Where new ones go is a [`Location`] (Settings → Sandbox):
//!
//! * inside the repository: `<repo>/.evo/worktrees/<name>`, with
//!   `/.evo/worktrees/` added to the repository-local `.git/info/exclude`
//!   (never `.gitignore`);
//! * the user data directory: `~/.evo/agent/worktrees/<repo>-<hash>/<name>`.
//!
//! Worktrees in either place are listed and removable whichever is selected.
//! Branches are named `evo/worktree-<name>`; removing a worktree deletes its
//! branch too.
//!
//! What a worktree changed ([`Worktrees::changes`]) is measured from where it
//! was cut, commits and new files included; [`Worktrees::apply`] brings those
//! changes into the repository's working folder (uncommitted) and removes the
//! worktree. Used by the engine (child agents) and by the desktop shell
//! (review, apply, discard, worktree sessions); it only shells out to `git`.

use std::path::{Path, PathBuf};
use std::process::Command;

use serde::{Deserialize, Serialize};

/// Where new managed worktrees go. Existing ones are found in either place.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub enum Location {
    /// `<repository>/.evo/worktrees`, kept out of Git by `.git/info/exclude`.
    Repository,
    /// The user data directory (`~/.evo/agent/worktrees`). The default: the
    /// engine's working data stays out of the user's project.
    #[default]
    UserData,
}

use Location as WorktreeLocation;

/// Branches of managed worktrees.
pub const BRANCH_PREFIX: &str = "evo/worktree-";
/// Inside the repository, relative to its root.
const REPO_DIR: &str = ".evo/worktrees";
/// The line that keeps them out of `git status`.
const EXCLUDE_LINE: &str = "/.evo/worktrees/";

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct Worktree {
    pub path: PathBuf,
    pub branch: String,
    /// `repository` or `userData`.
    pub location: &'static str,
    /// Uncommitted changes, or commits beyond where it started.
    pub changed: bool,
}

/// A worktree just made for a child, and the folder the child works in (the
/// same subfolder of the worktree as the parent's is of the repository).
#[derive(Debug, Clone)]
pub struct Created {
    pub worktree: Worktree,
    pub base: String,
    pub cwd: PathBuf,
}

pub struct Worktrees {
    /// `~/.evo/agent/worktrees` (tests use a temporary folder).
    data_root: PathBuf,
}

fn git(dir: &Path, args: &[&str]) -> Result<String, String> {
    let mut command = Command::new("git");
    command.arg("-C").arg(dir).args(args);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        // The engine has no console; git must not open one.
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        command.creation_flags(CREATE_NO_WINDOW);
    }
    let output = command.output().map_err(|e| format!("could not run git: {e}"))?;
    if output.status.success() {
        Ok(String::from_utf8_lossy(&output.stdout).trim_end().to_string())
    } else {
        let stderr = String::from_utf8_lossy(&output.stderr);
        Err(format!("git {} failed: {}", args.join(" "), stderr.trim()))
    }
}

/// Paths as one comparable string: forward slashes, no trailing slash, and
/// case-folded where the file system ignores case.
fn key(path: &Path) -> String {
    let text = path.to_string_lossy().replace('\\', "/");
    let text = text.trim_end_matches('/').to_string();
    if cfg!(any(windows, target_os = "macos")) {
        text.to_lowercase()
    } else {
        text
    }
}

fn is_under(path: &Path, dir: &Path) -> bool {
    let (path, dir) = (key(path), key(dir));
    path.len() > dir.len() && path.starts_with(&dir) && path.as_bytes()[dir.len()] == b'/'
}

/// FNV-1a: a stable name for a repository's folder in the data directory.
fn fnv(text: &str) -> u32 {
    text.bytes().fold(0x811c_9dc5u32, |hash, byte| (hash ^ byte as u32).wrapping_mul(0x0100_0193))
}

/// Unique per process and moment: time, process id and a counter.
fn new_name() -> String {
    use std::sync::atomic::{AtomicU32, Ordering};
    static NEXT: AtomicU32 = AtomicU32::new(0);
    let millis = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or(0);
    let salt = fnv(&format!("{}-{}", std::process::id(), NEXT.fetch_add(1, Ordering::Relaxed))) & 0xffff;
    format!("{millis:x}{salt:04x}")
}

impl Worktrees {
    /// `data_root` holds the user-data-directory worktrees (`<agent dir>/worktrees`).
    pub fn with_data_root(data_root: PathBuf) -> Self {
        Self { data_root }
    }

    /// The repository's main working folder, also when `cwd` is inside one of
    /// its worktrees, so a worktree is never nested in another.
    fn main_root(cwd: &Path) -> Result<PathBuf, String> {
        let top = PathBuf::from(
            git(cwd, &["rev-parse", "--show-toplevel"]).map_err(|_| "this folder is not in a Git repository".to_string())?,
        );
        let common = PathBuf::from(git(cwd, &["rev-parse", "--path-format=absolute", "--git-common-dir"])?);
        // `<main>/.git` for ordinary repositories; a bare common dir has no main folder.
        match (common.file_name().and_then(|n| n.to_str()), common.parent()) {
            (Some(".git"), Some(main)) => Ok(main.to_path_buf()),
            _ => Ok(top),
        }
    }

    fn user_data_dir(&self, main: &Path) -> PathBuf {
        let name = main.file_name().map(|n| n.to_string_lossy().to_string()).unwrap_or_else(|| "repo".into());
        self.data_root.join(format!("{name}-{:08x}", fnv(&key(main))))
    }

    fn dir(&self, main: &Path, location: WorktreeLocation) -> PathBuf {
        match location {
            WorktreeLocation::Repository => main.join(REPO_DIR),
            WorktreeLocation::UserData => self.user_data_dir(main),
        }
    }

    /// Keep `<repo>/.evo/worktrees` out of `git status` without touching
    /// `.gitignore`.
    fn exclude(main: &Path) -> Result<(), String> {
        let common = PathBuf::from(git(main, &["rev-parse", "--path-format=absolute", "--git-common-dir"])?);
        let file = common.join("info").join("exclude");
        let current = std::fs::read_to_string(&file).unwrap_or_default();
        if current.lines().any(|line| line.trim() == EXCLUDE_LINE) {
            return Ok(());
        }
        std::fs::create_dir_all(file.parent().expect("exclude has a folder")).map_err(|e| e.to_string())?;
        let separator = if current.is_empty() || current.ends_with('\n') { "" } else { "\n" };
        std::fs::write(&file, format!("{current}{separator}# evo managed worktrees\n{EXCLUDE_LINE}\n"))
            .map_err(|e| format!("could not update {}: {e}", file.display()))
    }

    /// A new worktree of `cwd`'s repository, on a new branch at `HEAD`.
    pub fn create(&self, cwd: &Path, location: WorktreeLocation) -> Result<Created, String> {
        let main = Self::main_root(cwd)?;
        // Where `cwd` sits in its working tree (`src/`), to start the child there too.
        let prefix = git(cwd, &["rev-parse", "--show-prefix"])?;
        let base = git(cwd, &["rev-parse", "HEAD"]).map_err(|_| "the repository has no commits yet".to_string())?;
        if location == WorktreeLocation::Repository {
            Self::exclude(&main)?;
        }
        let name = new_name();
        let dir = self.dir(&main, location);
        std::fs::create_dir_all(&dir).map_err(|e| format!("could not create {}: {e}", dir.display()))?;
        let path = dir.join(&name);
        let branch = format!("{BRANCH_PREFIX}{name}");
        git(&main, &["worktree", "add", "-b", &branch, &path.to_string_lossy(), &base])?;
        let child_cwd = path.join(prefix.trim_end_matches('/'));
        let cwd = if child_cwd.is_dir() { child_cwd } else { path.clone() };
        Ok(Created {
            worktree: Worktree {
                path,
                branch,
                location: location_name(location),
                changed: false,
            },
            base,
            cwd,
        })
    }

    /// Whether `path` has uncommitted changes or commits beyond `base`.
    pub fn changed(path: &Path, base: Option<&str>) -> bool {
        let dirty = git(path, &["status", "--porcelain"]).map(|out| !out.trim().is_empty()).unwrap_or(true);
        let moved = match base {
            Some(base) => git(path, &["rev-parse", "HEAD"]).map(|head| head != base).unwrap_or(true),
            None => false,
        };
        dirty || moved
    }

    /// Managed worktrees of `cwd`'s repository, in either location.
    pub fn list(&self, cwd: &Path) -> Result<Vec<Worktree>, String> {
        let main = Self::main_root(cwd)?;
        let places = [
            (self.dir(&main, WorktreeLocation::Repository), WorktreeLocation::Repository),
            (self.dir(&main, WorktreeLocation::UserData), WorktreeLocation::UserData),
        ];
        let porcelain = git(&main, &["worktree", "list", "--porcelain"])?;
        let mut found = Vec::new();
        for block in porcelain.split("\n\n") {
            let mut path = None;
            let mut branch = String::new();
            for line in block.lines() {
                if let Some(p) = line.strip_prefix("worktree ") {
                    path = Some(PathBuf::from(p));
                } else if let Some(b) = line.strip_prefix("branch refs/heads/") {
                    branch = b.to_string();
                }
            }
            let Some(path) = path else { continue };
            if let Some((_, location)) = places.iter().find(|(dir, _)| is_under(&path, dir)) {
                // Commits on the branch beyond where `main` is now count as changes.
                let ahead = git(&main, &["rev-list", "--count", &format!("HEAD..{branch}")])
                    .map(|n| n.trim() != "0")
                    .unwrap_or(false);
                found.push(Worktree {
                    changed: ahead || Self::changed(&path, None),
                    path,
                    branch,
                    location: location_name(*location),
                });
            }
        }
        Ok(found)
    }

    /// A managed worktree of `cwd`'s repository at `path`, or an error.
    fn managed(&self, cwd: &Path, path: &Path) -> Result<Worktree, String> {
        self.list(cwd)?
            .into_iter()
            .find(|w| key(&w.path) == key(path))
            .ok_or_else(|| format!("{} is not a managed worktree of this repository", path.display()))
    }

    /// Everything the worktree at `path` changed since it was cut from the
    /// repository: its commits, uncommitted edits and new files, as one patch.
    pub fn changes(&self, cwd: &Path, path: &Path) -> Result<Changes, String> {
        let main = Self::main_root(cwd)?;
        self.managed(cwd, path)?;
        let head = git(&main, &["rev-parse", "HEAD"])?;
        let base = git(path, &["merge-base", "HEAD", &head])?;
        // Stage everything in the worktree's own index so new files count; the
        // repository's index is untouched.
        git(path, &["add", "-A"])?;
        let patch = git_raw(path, &["diff", "--cached", "--binary", "--no-color", "--no-ext-diff", &base])?;
        let mut files = Vec::new();
        let numstat = git(path, &["diff", "--cached", "--numstat", "--no-renames", &base])?;
        let statuses = git(path, &["diff", "--cached", "--name-status", "--no-renames", &base])?;
        for (line, status) in numstat.lines().zip(statuses.lines()) {
            let mut parts = line.splitn(3, '\t');
            let added = parts.next().and_then(|n| n.parse().ok());
            let removed = parts.next().and_then(|n| n.parse().ok());
            let file = parts.next().unwrap_or_default().to_string();
            let status = match status.chars().next() {
                Some('A') => "added",
                Some('D') => "deleted",
                _ => "modified",
            };
            files.push(FileChange { path: file, status, added, removed });
        }
        Ok(Changes {
            added: files.iter().filter_map(|f| f.added).sum(),
            removed: files.iter().filter_map(|f| f.removed).sum(),
            base,
            files,
            patch,
        })
    }

    /// Bring the worktree's changes into the repository's working folder
    /// (uncommitted, nothing staged), then remove the worktree and its branch.
    /// Nothing is changed when the patch does not apply cleanly.
    pub fn apply(&self, cwd: &Path, path: &Path) -> Result<Changes, String> {
        let main = Self::main_root(cwd)?;
        let changes = self.changes(cwd, path)?;
        if !changes.patch.trim().is_empty() {
            let file = std::env::temp_dir().join(format!("evo-worktree-{}.patch", new_name()));
            std::fs::write(&file, &changes.patch).map_err(|e| format!("could not write the patch: {e}"))?;
            let file_arg = file.to_string_lossy().to_string();
            let checked = git(&main, &["apply", "--check", "--whitespace=nowarn", &file_arg]);
            let applied = checked.and_then(|_| git(&main, &["apply", "--whitespace=nowarn", &file_arg]));
            let _ = std::fs::remove_file(&file);
            applied.map_err(|e| {
                format!("the changes do not apply cleanly to your working folder (it changed in the same places): {e}")
            })?;
        }
        self.remove(cwd, path)?;
        Ok(changes)
    }

    /// Remove a managed worktree and its branch. Refuses anything else.
    pub fn remove(&self, cwd: &Path, path: &Path) -> Result<(), String> {
        let main = Self::main_root(cwd)?;
        let worktree = self.managed(cwd, path)?;
        git(&main, &["worktree", "remove", "--force", &worktree.path.to_string_lossy()])?;
        if worktree.branch.starts_with(BRANCH_PREFIX) {
            git(&main, &["branch", "-D", &worktree.branch])?;
        }
        let _ = git(&main, &["worktree", "prune"]);
        Ok(())
    }
}

/// Git's empty tree: the base of a repository with no commit yet.
const EMPTY_TREE: &str = "4b825dc642cb6eb9a060e54bf8d69288fbee4904";
/// New files are only measured up to this size and this many.
const UNTRACKED_MAX_BYTES: u64 = 2 * 1024 * 1024;
const UNTRACKED_MAX_FILES: usize = 500;

/// Where a working folder's repository stands: its branch, how far it is from
/// its upstream, and what is changed against `HEAD` (staged, unstaged and new
/// files together). Read-only: nothing is staged or written.
#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct RepoStatus {
    /// The repository's top folder; `files` paths are relative to it.
    pub root: PathBuf,
    /// `None` on a detached `HEAD`.
    pub branch: Option<String>,
    /// Short commit id; `None` before the first commit.
    pub head: Option<String>,
    pub upstream: Option<String>,
    pub ahead: u32,
    pub behind: u32,
    pub files: Vec<FileChange>,
    pub added: usize,
    pub removed: usize,
}

/// Lines of a new file, `None` when it looks binary or is too big to read.
fn count_lines(path: &Path) -> Option<usize> {
    let meta = std::fs::metadata(path).ok()?;
    if !meta.is_file() || meta.len() > UNTRACKED_MAX_BYTES {
        return None;
    }
    let bytes = std::fs::read(path).ok()?;
    if bytes[..bytes.len().min(8000)].contains(&0) {
        return None;
    }
    let newlines = bytes.iter().filter(|&&b| b == b'\n').count();
    Some(if bytes.last().is_some_and(|&b| b != b'\n') { newlines + 1 } else { newlines })
}

/// The status of the repository `dir` is in; `None` outside a repository.
pub fn repo_status(dir: &Path) -> Result<Option<RepoStatus>, String> {
    let Ok(root) = git(dir, &["rev-parse", "--show-toplevel"]) else {
        return Ok(None);
    };
    let root = PathBuf::from(root);
    let status = git(
        &root,
        &["-c", "core.quotePath=false", "status", "--porcelain=v2", "--branch", "--untracked-files=all"],
    )?;

    let (mut branch, mut head, mut upstream, mut ahead, mut behind) = (None, None, None, 0, 0);
    // Path → `added`, `modified` or `deleted`, in git's order.
    let mut changed: Vec<(String, &'static str)> = Vec::new();
    let kind = |xy: &str| {
        if xy.contains('D') {
            "deleted"
        } else if xy.contains('A') {
            "added"
        } else {
            "modified"
        }
    };
    for line in status.lines() {
        if let Some(header) = line.strip_prefix("# ") {
            let (key, value) = header.split_once(' ').unwrap_or((header, ""));
            match key {
                "branch.oid" if value != "(initial)" => head = Some(value.chars().take(7).collect()),
                "branch.head" if value != "(detached)" => branch = Some(value.to_string()),
                "branch.upstream" => upstream = Some(value.to_string()),
                "branch.ab" => {
                    for part in value.split(' ') {
                        if let Some(n) = part.strip_prefix('+') {
                            ahead = n.parse().unwrap_or(0);
                        } else if let Some(n) = part.strip_prefix('-') {
                            behind = n.parse().unwrap_or(0);
                        }
                    }
                }
                _ => {}
            }
            continue;
        }
        let mut fields = line.splitn(2, ' ');
        let (tag, rest) = (fields.next().unwrap_or_default(), fields.next().unwrap_or_default());
        // Ordinary (1), renamed (2) and unmerged (u) entries end with the path.
        let skip = match tag {
            "1" => 7,
            "2" => 8,
            "u" => 9,
            "?" => {
                changed.push((rest.to_string(), "added"));
                continue;
            }
            _ => continue,
        };
        let xy = rest.split(' ').next().unwrap_or_default();
        let path = rest.splitn(skip + 1, ' ').nth(skip).unwrap_or_default();
        // A rename's path is `new\told`.
        let path = path.split('\t').next().unwrap_or_default().to_string();
        changed.push((path, kind(xy)));
    }

    // Line counts of tracked changes against HEAD, without touching the index.
    let base = if head.is_some() { "HEAD" } else { EMPTY_TREE };
    let numstat =
        git(&root, &["-c", "core.quotePath=false", "diff", base, "--numstat", "--no-renames"]).unwrap_or_default();
    let mut counts = std::collections::HashMap::new();
    for line in numstat.lines() {
        let mut parts = line.splitn(3, '\t');
        let added = parts.next().and_then(|n| n.parse::<usize>().ok());
        let removed = parts.next().and_then(|n| n.parse::<usize>().ok());
        if let Some(path) = parts.next() {
            counts.insert(path.to_string(), (added, removed));
        }
    }

    let mut measured = 0;
    let files: Vec<FileChange> = changed
        .into_iter()
        .map(|(path, status)| {
            let (added, removed) = match counts.get(&path) {
                Some(&count) => count,
                // Untracked: every line is new.
                None if status == "added" && measured < UNTRACKED_MAX_FILES => {
                    measured += 1;
                    (count_lines(&root.join(&path)), Some(0))
                }
                None => (None, None),
            };
            FileChange { path, status, added, removed }
        })
        .collect();

    Ok(Some(RepoStatus {
        added: files.iter().filter_map(|f| f.added).sum(),
        removed: files.iter().filter_map(|f| f.removed).sum(),
        root,
        branch,
        head,
        upstream,
        ahead,
        behind,
        files,
    }))
}

/// One file a worktree changed.
#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct FileChange {
    pub path: String,
    /// `added`, `modified` or `deleted`.
    pub status: &'static str,
    /// Lines; `None` for binary files.
    pub added: Option<usize>,
    pub removed: Option<usize>,
}

/// What a worktree changed since it was cut.
#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct Changes {
    /// The commit it was cut from.
    pub base: String,
    pub files: Vec<FileChange>,
    pub added: usize,
    pub removed: usize,
    /// A `git apply` patch (binary-safe).
    pub patch: String,
}

/// `git` output as is (a patch must keep its trailing newline).
fn git_raw(dir: &Path, args: &[&str]) -> Result<String, String> {
    let mut command = Command::new("git");
    command.arg("-C").arg(dir).args(args);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        command.creation_flags(CREATE_NO_WINDOW);
    }
    let output = command.output().map_err(|e| format!("could not run git: {e}"))?;
    if output.status.success() {
        Ok(String::from_utf8_lossy(&output.stdout).to_string())
    } else {
        Err(format!("git {} failed: {}", args.join(" "), String::from_utf8_lossy(&output.stderr).trim()))
    }
}

fn location_name(location: WorktreeLocation) -> &'static str {
    match location {
        WorktreeLocation::Repository => "repository",
        WorktreeLocation::UserData => "userData",
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A repository with one commit, in a temporary folder; `None` without git.
    fn repo() -> Option<(tempfile::TempDir, PathBuf)> {
        let dir = tempfile::tempdir().unwrap();
        let root = dir.path().join("project");
        std::fs::create_dir_all(root.join("src")).unwrap();
        if git(&root, &["init", "-q"]).is_err() {
            eprintln!("skipping: git is not available");
            return None;
        }
        std::fs::write(root.join("src/main.rs"), "fn main() {}\n").unwrap();
        for args in [
            &["config", "user.email", "evo@example.invalid"][..],
            &["config", "user.name", "evo"],
            &["add", "."],
            &["commit", "-q", "-m", "init"],
        ] {
            git(&root, args).unwrap();
        }
        Some((dir, root))
    }

    #[test]
    fn repo_status_counts_tracked_and_new_files() {
        let Some((dir, root)) = repo() else { return };
        assert_eq!(repo_status(dir.path()).unwrap(), None, "outside a repository");

        let clean = repo_status(&root.join("src")).unwrap().unwrap();
        assert!(clean.files.is_empty());
        assert!(clean.branch.is_some() && clean.head.is_some());

        std::fs::write(root.join("src/main.rs"), "fn main() {\n    run();\n}\n").unwrap();
        std::fs::write(root.join("src/new file.rs"), "a\nb\nc").unwrap();
        let status = repo_status(&root).unwrap().unwrap();
        let file = |p: &str| status.files.iter().find(|f| f.path == p).unwrap().clone();
        assert_eq!(file("src/main.rs").status, "modified");
        assert_eq!((file("src/main.rs").added, file("src/main.rs").removed), (Some(3), Some(1)));
        assert_eq!(file("src/new file.rs").status, "added");
        assert_eq!(file("src/new file.rs").added, Some(3));
        assert_eq!((status.added, status.removed), (6, 1));
    }

    #[test]
    fn inside_the_repository_and_excluded_from_git() {
        let Some((dir, root)) = repo() else { return };
        let worktrees = Worktrees::with_data_root(dir.path().join("data"));
        let created = worktrees.create(&root.join("src"), WorktreeLocation::Repository).unwrap();
        assert!(is_under(&created.worktree.path, &root.join(".evo/worktrees")));
        assert!(created.worktree.branch.starts_with(BRANCH_PREFIX));
        // The child works in the same subfolder as the parent.
        assert!(created.cwd.ends_with("src") && created.cwd.join("main.rs").is_file());
        // `.gitignore` untouched, the folder excluded locally, the main tree clean.
        assert!(!root.join(".gitignore").exists());
        let exclude = std::fs::read_to_string(root.join(".git/info/exclude")).unwrap();
        assert!(exclude.contains(EXCLUDE_LINE));
        assert_eq!(git(&root, &["status", "--porcelain"]).unwrap(), "");
        // A second worktree adds no second exclude line.
        worktrees.create(&root, WorktreeLocation::Repository).unwrap();
        let exclude = std::fs::read_to_string(root.join(".git/info/exclude")).unwrap();
        assert_eq!(exclude.matches(EXCLUDE_LINE).count(), 1);
    }

    #[test]
    fn both_locations_are_listed_and_removable() {
        let Some((dir, root)) = repo() else { return };
        let worktrees = Worktrees::with_data_root(dir.path().join("data"));
        let inside = worktrees.create(&root, WorktreeLocation::Repository).unwrap();
        let outside = worktrees.create(&root, WorktreeLocation::UserData).unwrap();
        assert!(is_under(&outside.worktree.path, &dir.path().join("data")));

        let listed = worktrees.list(&root).unwrap();
        assert_eq!(listed.len(), 2, "{listed:?}");
        assert!(listed.iter().all(|w| !w.changed));

        // A change in one shows up, from the worktree and from the list.
        std::fs::write(outside.worktree.path.join("new.txt"), "x").unwrap();
        assert!(Worktrees::changed(&outside.worktree.path, Some(&outside.base)));
        assert!(!Worktrees::changed(&inside.worktree.path, Some(&inside.base)));
        let changed: Vec<_> = worktrees.list(&root).unwrap().into_iter().filter(|w| w.changed).collect();
        assert_eq!(changed.len(), 1);
        assert_eq!(key(&changed[0].path), key(&outside.worktree.path));

        // Listed from inside a worktree too, and removed with their branches.
        assert_eq!(worktrees.list(&inside.worktree.path).unwrap().len(), 2);
        worktrees.remove(&root, &inside.worktree.path).unwrap();
        worktrees.remove(&root, &outside.worktree.path).unwrap();
        assert!(worktrees.list(&root).unwrap().is_empty());
        assert!(!inside.worktree.path.exists() && !outside.worktree.path.exists());
        let branches = git(&root, &["branch", "--list", &format!("{BRANCH_PREFIX}*")]).unwrap();
        assert!(branches.trim().is_empty(), "branches left: {branches}");
    }

    #[test]
    fn only_managed_worktrees_are_removed() {
        let Some((dir, root)) = repo() else { return };
        let worktrees = Worktrees::with_data_root(dir.path().join("data"));
        let elsewhere = dir.path().join("mine");
        git(&root, &["worktree", "add", "-q", "-b", "mine", &elsewhere.to_string_lossy()]).unwrap();
        assert!(worktrees.list(&root).unwrap().is_empty());
        assert!(worktrees.remove(&root, &elsewhere).is_err());
        assert!(elsewhere.exists());
    }

    #[test]
    fn changes_are_measured_from_the_fork_and_applied_to_the_working_folder() {
        let Some((dir, root)) = repo() else { return };
        let worktrees = Worktrees::with_data_root(dir.path().join("data"));
        let created = worktrees.create(&root, WorktreeLocation::UserData).unwrap();
        let wt = &created.worktree.path;
        // An edit, a new file, a deleted file, and a commit in between.
        std::fs::write(wt.join("src/main.rs"), "fn main() { println!(\"hi\"); }\n").unwrap();
        git(wt, &["commit", "-qam", "say hi"]).unwrap();
        std::fs::write(wt.join("NOTES.md"), "new\nfile\n").unwrap();
        std::fs::create_dir_all(wt.join("docs")).unwrap();
        std::fs::write(wt.join("docs/a.md"), "a\n").unwrap();

        let changes = worktrees.changes(&root, wt).unwrap();
        assert_eq!(changes.base, created.base);
        let mut paths: Vec<_> = changes.files.iter().map(|f| (f.path.as_str(), f.status)).collect();
        paths.sort();
        assert_eq!(paths, [("NOTES.md", "added"), ("docs/a.md", "added"), ("src/main.rs", "modified")]);
        assert_eq!((changes.added, changes.removed), (4, 1));
        assert!(changes.patch.contains("+fn main() { println!(\"hi\"); }"));
        // The repository is untouched until applied.
        assert_eq!(git(&root, &["status", "--porcelain"]).unwrap(), "");

        worktrees.apply(&root, wt).unwrap();
        // Line endings follow the repository's own settings (core.autocrlf).
        let read = |p: &str| std::fs::read_to_string(root.join(p)).unwrap().replace("\r\n", "\n");
        assert_eq!(read("NOTES.md"), "new\nfile\n");
        assert!(std::fs::read_to_string(root.join("src/main.rs")).unwrap().contains("hi"));
        // Uncommitted, unstaged, history unchanged; the worktree and branch are gone.
        let status = git(&root, &["status", "--porcelain"]).unwrap();
        assert!(status.contains(" M src/main.rs") && status.contains("?? NOTES.md"), "{status}");
        assert_eq!(git(&root, &["rev-parse", "HEAD"]).unwrap(), created.base);
        assert!(!wt.exists());
        assert!(worktrees.list(&root).unwrap().is_empty());
    }

    #[test]
    fn a_conflicting_apply_changes_nothing() {
        let Some((dir, root)) = repo() else { return };
        let worktrees = Worktrees::with_data_root(dir.path().join("data"));
        let created = worktrees.create(&root, WorktreeLocation::Repository).unwrap();
        std::fs::write(created.worktree.path.join("src/main.rs"), "fn main() { worktree(); }\n").unwrap();
        // The working folder changed the same line meanwhile.
        std::fs::write(root.join("src/main.rs"), "fn main() { mine(); }\n").unwrap();
        let error = worktrees.apply(&root, &created.worktree.path).unwrap_err();
        assert!(error.contains("do not apply cleanly"), "{error}");
        assert_eq!(
            std::fs::read_to_string(root.join("src/main.rs")).unwrap().replace("\r\n", "\n"),
            "fn main() { mine(); }\n"
        );
        assert!(created.worktree.path.exists(), "the worktree is kept to try again");
    }

    #[test]
    fn outside_a_repository_is_an_error() {
        let dir = tempfile::tempdir().unwrap();
        let worktrees = Worktrees::with_data_root(dir.path().join("data"));
        if git(dir.path(), &["--version"]).is_err() {
            return;
        }
        let error = worktrees.create(dir.path(), WorktreeLocation::Repository).unwrap_err();
        assert!(error.contains("not in a Git repository"), "{error}");
    }
}
