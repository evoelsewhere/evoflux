//! Mirrors `packages/agent/src/harness/env/nodejs.ts` — `NodeExecutionEnv` →
//! `OsExecutionEnv`. Real-filesystem + real-process backend via `tokio::fs` +
//! `tokio::process`.
//!
//! Path resolution (\[`resolvePath`\]): tilde (`~`/`~/`, `~\` on Windows),
//! `file://` URL (parse failure silently keeps the literal string), absolute
//! → `canonicalize`-style normalize, relative → `cwd.join`. No env-var or
//! `~user` expansion. No symlink resolution (that's `canonical_path`).
//!
//! Shell detection (\[`getShellConfig`\]): explicit override → Windows
//! git-bash probe (`ProgramFiles\Git\bin\bash.exe`, `ProgramFiles(x86)\…`) →
//! `where bash.exe` → POSIX `/bin/bash` → `which bash` → `/bin/sh` fallback
//! (POSIX only). **No cmd.exe fallback** on Windows — failure is
//! `ExecutionError::ShellUnavailable`. Legacy WSL bash (`System32\bash.exe`)
//! uses `bash -s` stdin transport to avoid argv parse bugs.
//!
//! Kill tree: Windows terminates the shell's job object, falling back to
//! `taskkill /F /T /PID`; POSIX `kill -PG` (process group, since the child is
//! spawned as its own group leader) with fallback to `kill -PID`. Best-effort,
//! errors swallowed.
//!
//! `exec` abort+timeout bracketing (plan §5.4): the spawn is `tokio::select!`-ed
//! against the cancellation token and `tokio::time::timeout`. Resolution
//! priority: callbackError → timeout → aborted → exit-code-from-success.
//! `cleanup()` kills tracked child pids best-effort.

use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::sync::Arc;

use async_trait::async_trait;
use tokio::sync::Mutex;
use tokio_util::sync::CancellationToken;

use crate::env::{
    check_cancel_exec, check_cancel_file, ExecutionEnv, FileContent, FileInfo, FileKind,
    FileSystem, Shell, ShellExecOptions, ShellOutput,
};
use crate::error::{
    io_to_file_error, ExecutionError, ExecutionErrorCode, FileError, FileErrorCode,
};
use crate::file_mutation_queue::{MutatingEnv, MutationQueueRegistry};

/// Max timeout in ms (Int32 max). Mirrors `MAX_TIMEOUT_MS`.
const MAX_TIMEOUT_MS: u64 = 2_147_483_647;
/// Max timeout in seconds. Mirrors `MAX_TIMEOUT_SECONDS`.
const MAX_TIMEOUT_SECONDS: f64 = 2_147_483.647;
/// Grace period after child exit for trailing stdio. Mirrors
/// `EXIT_STDIO_GRACE_MS`.
const EXIT_STDIO_GRACE_MS: u64 = 100;

/// How the command is fed to the shell. Mirrors `commandTransport`.
#[derive(Clone, Copy)]
enum CommandTransport {
    /// Append the command as the last argv element (`bash -c <cmd>`).
    Argv,
    /// Pipe the command to the shell's stdin (`bash -s`).
    Stdin,
}

/// Resolved shell config. Mirrors `ShellConfig`.
struct ShellConfig {
    shell: PathBuf,
    args: Vec<String>,
    transport: CommandTransport,
}

mod append;
mod read;

/// Environment variables the **host** sets for its own runtime plumbing, which
/// must not be handed to a shell it spawns.
///
/// A spawned shell is a child process, so anything inherited reaches whatever
/// that shell runs — including another `evo`. `EVO_SESSION_ID` names the session
/// *this process* serves, which is meaningless (and actively misleading) in a
/// descendant: the child would either report the parent's session or, seeing the
/// variable already present, refuse to publish its own. Both are wrong answers,
/// and neither is visible from the child.
///
/// This is only the host's own half. An *extension* can publish variables with
/// the same hazard, and it declares them itself; [`is_host_private_env`] is the
/// function that answers the full question. Use it rather than reading this
/// slice, or an extension's channel will be missed — which is precisely the bug
/// that let `LANGFUSE_EVO_PARENT_*` through.
pub const HOST_PRIVATE_ENV: &[&str] = &[evo_plugin_sdk::SESSION_ID_ENV];

/// Whether `name` must not be inherited by a spawned shell.
///
/// Two sources, because the variables come from two places:
///
/// - [`HOST_PRIVATE_ENV`] — the host's own plumbing.
/// - [`evo_plugin_sdk::SUBAGENT_PARENT_ENV`] — the family an *extension*
///   declares for subagent nesting. An inherited copy makes a plain `evo` started
///   from inside `bash` adopt its ancestor's trace, hang its root off the
///   ancestor's root span, and call itself `Subagent Turn` instead of opening its
///   own trace. A launcher that sets these on the child *it* starts is the
///   supported nesting path, so this is about not *inheriting* them, not about
///   forbidding the names.
///
/// The extension family is consulted **as the SDK's slice**, never as names
/// restated here. Restating them is what the previous version did, and it is
/// how the channel re-leaked when the plugin renamed them: the list went on
/// matching a name nobody set. Going through the constant means a rename is a
/// compile error, and a newly added family member is excluded automatically.
pub fn is_host_private_env(name: &str) -> bool {
    HOST_PRIVATE_ENV.contains(&name) || evo_plugin_sdk::SUBAGENT_PARENT_ENV.contains(&name)
}

/// Extra environment a host supplies for shell commands, evaluated at every
/// command so something installed while a chat is open is visible to it.
#[derive(Debug, Clone, Default)]
pub struct ShellEnv {
    /// Variables to set (they win over the inherited environment).
    pub vars: Vec<(String, String)>,
    /// Folders appended to the inherited `PATH` (never put in front of it, so a
    /// tool the user already has is not shadowed). Ignored when the host
    /// environment is not inherited.
    pub path_append: Vec<PathBuf>,
}

/// Supplies a [`ShellEnv`] per command.
pub type ShellEnvProvider = Arc<dyn Fn() -> ShellEnv + Send + Sync>;

/// Real-OS `ExecutionEnv`. Clone shares the tracked-pid set + registry.
pub struct OsExecutionEnv {
    cwd: PathBuf,
    shell_path: Option<PathBuf>,
    shell_env: Option<HashMap<String, String>>,
    shell_env_provider: Option<ShellEnvProvider>,
    active_pids: Arc<Mutex<HashSet<u32>>>,
    registry: Arc<MutationQueueRegistry>,
}

impl OsExecutionEnv {
    pub fn new() -> Self {
        Self {
            cwd: std::env::current_dir().unwrap_or_else(|_| PathBuf::from("/")),
            shell_path: None,
            shell_env: None,
            shell_env_provider: None,
            active_pids: Arc::new(Mutex::new(HashSet::new())),
            registry: Arc::new(MutationQueueRegistry::new()),
        }
    }

    pub fn with_cwd(cwd: PathBuf) -> Self {
        Self {
            cwd,
            shell_path: None,
            shell_env: None,
            shell_env_provider: None,
            active_pids: Arc::new(Mutex::new(HashSet::new())),
            registry: Arc::new(MutationQueueRegistry::new()),
        }
    }

    pub fn with_shell_path(mut self, shell_path: PathBuf) -> Self {
        self.shell_path = Some(shell_path);
        self
    }

    pub fn with_shell_env(mut self, env: HashMap<String, String>) -> Self {
        self.shell_env = Some(env);
        self
    }

    /// Ask `provider` for extra environment each time a shell command starts.
    pub fn with_shell_env_provider(mut self, provider: ShellEnvProvider) -> Self {
        self.shell_env_provider = Some(provider);
        self
    }

    /// Resolve a path (tilde, file://, absolute/relative) against `cwd`. Pure.
    fn resolve_path(cwd: &Path, path: &str) -> PathBuf {
        let mut p = path.to_string();
        // Tilde expansion (literal only).
        if p == "~" {
            p = home_dir_string();
        } else if let Some(rest) = p.strip_prefix("~/") {
            p = format!("{}/{}", home_dir_string(), rest);
        } else if cfg!(windows) {
            if let Some(rest) = p.strip_prefix("~\\") {
                p = format!("{}\\{}", home_dir_string(), rest);
            }
        }
        // file:// URL → path. Parse failure silently keeps the literal.
        if p.starts_with("file://") {
            if let Some(local) = file_url_to_path(&p) {
                p = local;
            }
        }
        let pb = PathBuf::from(&p);
        if pb.is_absolute() {
            normalize_absolute(&pb)
        } else {
            normalize_absolute(&cwd.join(pb))
        }
    }

    /// Detect + return the shell config, or `ShellUnavailable`. Mirrors
    /// `getShellConfig`.
    async fn get_shell_config(&self) -> Result<ShellConfig, ExecutionError> {
        // Explicit override. Shell discovery happens on the hot path immediately
        // before spawning a command. Keep this probe synchronous: putting a
        // `tokio::fs` metadata future here can queue work on Tokio's blocking
        // pool and leave a tool run waiting before it has even created a child.
        if let Some(sp) = &self.shell_path {
            if sp.is_file() {
                return Ok(bash_shell_config(sp.clone()));
            }
            return Err(ExecutionError::new(
                ExecutionErrorCode::ShellUnavailable,
                format!("Custom shell path not found: {}", sp.display()),
            ));
        }
        // Windows probe.
        #[cfg(windows)]
        {
            if let Some(cfg) = windows_probe_bash().await {
                return Ok(cfg);
            }
            Err(ExecutionError::new(
                ExecutionErrorCode::ShellUnavailable,
                "bash not found. Install Git for Windows / MSYS2 / Cygwin, or set shellPath.",
            ))
        }
        // POSIX.
        #[cfg(not(windows))]
        {
            if std::path::Path::new("/bin/bash").is_file() {
                return Ok(ShellConfig {
                    shell: PathBuf::from("/bin/bash"),
                    args: vec!["-c".to_string()],
                    transport: CommandTransport::Argv,
                });
            }
            // `which bash` fallback.
            if let Some(found) =
                run_command("which", &["bash"], std::time::Duration::from_millis(5000)).await
            {
                let trimmed = found.trim();
                if !trimmed.is_empty() && std::path::Path::new(trimmed).is_file() {
                    return Ok(ShellConfig {
                        shell: PathBuf::from(trimmed),
                        args: vec!["-c".to_string()],
                        transport: CommandTransport::Argv,
                    });
                }
            }
            // sh fallback.
            return Ok(ShellConfig {
                shell: PathBuf::from("sh"),
                args: vec!["-c".to_string()],
                transport: CommandTransport::Argv,
            });
        }
    }
}

impl Default for OsExecutionEnv {
    fn default() -> Self {
        Self::new()
    }
}

/// `current` PATH with `extra` appended, skipping folders already on it.
fn path_with(current: Option<std::ffi::OsString>, extra: &[PathBuf]) -> Option<std::ffi::OsString> {
    let mut entries: Vec<PathBuf> = current
        .as_deref()
        .map(|p| std::env::split_paths(p).collect())
        .unwrap_or_default();
    let same = |a: &Path, b: &Path| {
        if cfg!(windows) {
            a.to_string_lossy()
                .eq_ignore_ascii_case(&b.to_string_lossy())
        } else {
            a == b
        }
    };
    for dir in extra {
        if !entries.iter().any(|e| same(e, dir)) {
            entries.push(dir.clone());
        }
    }
    std::env::join_paths(entries).ok()
}

fn apply_shell_env(cmd: &mut tokio::process::Command, extra: ShellEnv, inherited: bool) {
    for (k, v) in &extra.vars {
        cmd.env(k, v);
    }
    if inherited && !extra.path_append.is_empty() {
        if let Some(path) = path_with(std::env::var_os("PATH"), &extra.path_append) {
            cmd.env("PATH", path);
        }
    }
}

#[cfg(test)]
mod shell_env_provider_tests {
    use super::*;

    #[test]
    fn path_is_appended_not_prepended_and_never_duplicated() {
        let (a, b) = (
            PathBuf::from(if cfg!(windows) { r"C:" } else { "/a" }),
            PathBuf::from(if cfg!(windows) { r"C:" } else { "/b" }),
        );
        let current = std::env::join_paths([&a]).unwrap();
        let joined = path_with(Some(current.clone()), &[b.clone()]).unwrap();
        let parts: Vec<PathBuf> = std::env::split_paths(&joined).collect();
        assert_eq!(parts, vec![a.clone(), b.clone()]);
        let again = path_with(Some(joined), &[b.clone()]).unwrap();
        assert_eq!(std::env::split_paths(&again).count(), 2);
        assert_eq!(
            std::env::split_paths(&path_with(None, &[b.clone()]).unwrap()).collect::<Vec<_>>(),
            vec![b]
        );
    }
}

fn home_dir_string() -> String {
    dirs::home_dir()
        .map(|p| p.to_string_lossy().into_owned())
        .unwrap_or_default()
}

fn normalize_absolute(p: &Path) -> PathBuf {
    // std::path doesn't expose ".."/"." collapse without canonicalize (which
    // hits the FS). Rebuild component-by-component.
    let mut out = PathBuf::new();
    for comp in p.components() {
        match comp {
            std::path::Component::ParentDir => {
                out.pop();
            }
            std::path::Component::CurDir => {}
            other => out.push(other),
        }
    }
    out
}

fn file_url_to_path(url: &str) -> Option<String> {
    // Minimal file:// → path conversion. Handles `file:///abs/path` and
    // Windows `file:///C:/...`. Parse failure → None (caller keeps literal).
    let rest = url.strip_prefix("file://")?;
    if let Some(drive_rest) = rest.strip_prefix('/') {
        // `/C:/...` (Windows drive) or `/abs/path`.
        if drive_rest.len() >= 2 && drive_rest.as_bytes()[1] == b':' {
            return Some(drive_rest.to_string());
        }
        return Some(format!("/{}", drive_rest));
    }
    Some(rest.to_string())
}

fn bash_shell_config(shell: PathBuf) -> ShellConfig {
    if is_legacy_wsl_bash_path(&shell) {
        ShellConfig {
            shell,
            args: vec!["-s".to_string()],
            transport: CommandTransport::Stdin,
        }
    } else {
        ShellConfig {
            shell,
            args: vec!["-c".to_string()],
            transport: CommandTransport::Argv,
        }
    }
}

fn is_legacy_wsl_bash_path(p: &Path) -> bool {
    let s = p.to_string_lossy().replace('/', "\\").to_lowercase();
    let re = regex::Regex::new(r"^[a-z]:\\windows\\(?:system32|sysnative)\\bash\.exe$").unwrap();
    re.is_match(&s)
}

#[cfg(windows)]
async fn windows_probe_bash() -> Option<ShellConfig> {
    let pf = std::env::var("ProgramFiles").ok();
    let pf86 = std::env::var("ProgramFiles(x86)").ok();
    let mut candidates: Vec<PathBuf> = Vec::new();
    if let Some(p) = pf {
        candidates.push(PathBuf::from(p).join("Git").join("bin").join("bash.exe"));
    }
    if let Some(p) = pf86 {
        candidates.push(PathBuf::from(p).join("Git").join("bin").join("bash.exe"));
    }
    for c in &candidates {
        if tokio::fs::metadata(c).await.is_ok() {
            return Some(bash_shell_config(c.clone()));
        }
    }
    // `where bash.exe`.
    if let Some(found) = run_command(
        "where",
        &["bash.exe"],
        std::time::Duration::from_millis(5000),
    )
    .await
    {
        let first = found.lines().next().unwrap_or("").trim().to_string();
        if !first.is_empty() && tokio::fs::metadata(&first).await.is_ok() {
            return Some(bash_shell_config(PathBuf::from(first)));
        }
    }
    None
}

/// Run a quick command, capture stdout, with a timeout. Mirrors `runCommand`
/// (used only by shell detection). Returns `None` on spawn failure / timeout /
/// empty stdout.
async fn run_command(cmd: &str, args: &[&str], timeout: std::time::Duration) -> Option<String> {
    let mut command = tokio::process::Command::new(cmd);
    command.args(args);
    command.stdout(std::process::Stdio::piped());
    command.stderr(std::process::Stdio::null());
    command.stdin(std::process::Stdio::null());
    #[cfg(windows)]
    {
        // Hide the console window for the probe.
        use windows_sys::Win32::System::Threading::CREATE_NO_WINDOW;
        command.creation_flags(CREATE_NO_WINDOW);
    }
    let child = command.spawn().ok()?;
    let out = match tokio::time::timeout(timeout, child.wait_with_output()).await {
        Ok(Ok(o)) => o,
        _ => return None,
    };
    if !out.status.success() {
        return None;
    }
    // `where` prints paths in the console code page (e.g. a Chinese user name).
    let s = crate::output_decode::decode_output(&out.stdout);
    if s.trim().is_empty() {
        None
    } else {
        Some(s)
    }
}

/// One job object per running shell, by root pid. `taskkill /T` walks parent
/// pids, and an MSYS shell's children are not on that chain: `sleep` under Git
/// Bash outlives it. Job membership is inherited by every descendant.
///
/// Kill-on-close is armed only when killing, so whatever a command leaves
/// running on purpose keeps running after it ends normally.
#[cfg(windows)]
mod shell_jobs {
    use std::collections::HashMap;
    use std::sync::{LazyLock, Mutex};

    use win32job::{ExtendedLimitInfo, Job};

    static JOBS: LazyLock<Mutex<HashMap<u32, Job>>> = LazyLock::new(Default::default);

    /// Put a shell spawned with `CREATE_SUSPENDED` in its own job, then let it
    /// run: no descendant can start outside the job. A shell that gets no job
    /// still runs, and cancelling it falls back to `taskkill`.
    pub fn start(pid: u32, process: std::os::windows::io::RawHandle) -> Result<(), String> {
        if let Ok(job) = Job::create() {
            if job.assign_process(process as isize).is_ok() {
                JOBS.lock().unwrap().insert(pid, job);
            }
        }
        evo_plugin_sdk::process::resume_child(pid)
    }

    /// End every process in `pid`'s job: arm kill-on-close, then drop the only
    /// handle. False when `pid` has no job or arming failed.
    pub fn terminate(pid: u32) -> bool {
        let Some(job) = JOBS.lock().unwrap().remove(&pid) else {
            return false;
        };
        let mut info = ExtendedLimitInfo::new();
        info.limit_kill_on_job_close();
        job.set_extended_limit_info(&info).is_ok()
    }

    pub fn forget(pid: u32) {
        JOBS.lock().unwrap().remove(&pid);
    }
}

/// Kill a process tree. Windows: the shell's job object, else
/// `taskkill /F /T /PID`. POSIX: `kill -PG` with fallback to `kill -PID`.
/// Best-effort, errors swallowed.
async fn kill_process_tree(pid: u32) {
    #[cfg(windows)]
    {
        if shell_jobs::terminate(pid) {
            return;
        }
        use windows_sys::Win32::System::Threading::CREATE_NO_WINDOW;
        let mut cmd = tokio::process::Command::new("taskkill");
        cmd.args(["/F", "/T", "/PID", &pid.to_string()]);
        cmd.creation_flags(CREATE_NO_WINDOW);
        cmd.stdin(std::process::Stdio::null());
        cmd.stdout(std::process::Stdio::null());
        cmd.stderr(std::process::Stdio::null());
        // Wait for taskkill itself to finish. Spawning it fire-and-forget lets
        // the shell's `child.wait()` race the tree termination, and a listener
        // can keep its inherited stdout/stderr handles open long enough to
        // deadlock the capture join after Ctrl+C.
        let _ = cmd.status().await;
    }
    #[cfg(unix)]
    {
        use nix::sys::signal::{kill, Signal};
        use nix::unistd::Pid;
        // Process group: negative pid.
        let pg = Pid::from_raw(-(pid as i32));
        if kill(pg, Signal::SIGKILL).is_err() {
            let _ = kill(Pid::from_raw(pid as i32), Signal::SIGKILL);
        }
    }
    #[cfg(not(any(windows, unix)))]
    {
        let _ = pid;
    }
}

#[async_trait]
impl FileSystem for OsExecutionEnv {
    async fn open_append_file(
        &self,
        path: &str,
    ) -> Result<Option<Box<dyn crate::env::AppendFile>>, FileError> {
        let path = Self::resolve_path(&self.cwd, path);
        Ok(Some(Box::new(append::OsAppendFile::open(path).await?)))
    }

    async fn open_read_file(
        &self,
        path: &str,
    ) -> Result<Option<Arc<dyn crate::env::ReadFile>>, FileError> {
        let path = Self::resolve_path(&self.cwd, path);
        Ok(Some(Arc::new(read::OsReadFile::open(path).await?)))
    }

    async fn truncate_file(
        &self,
        path: &str,
        len: u64,
        cancel: Option<&CancellationToken>,
    ) -> Result<(), FileError> {
        check_cancel_file(cancel, Some(path))?;
        let abs = Self::resolve_path(&self.cwd, path);
        let error_path = abs.to_string_lossy().into_owned();
        tokio::task::spawn_blocking(move || {
            let file = std::fs::OpenOptions::new().write(true).open(&abs)?;
            if len > file.metadata()?.len() {
                return Err(std::io::Error::new(
                    std::io::ErrorKind::InvalidInput,
                    "truncation cannot grow a file",
                ));
            }
            file.set_len(len)
        })
        .await
        .map_err(|error| {
            FileError::new(
                FileErrorCode::Unknown,
                format!("file truncation task failed: {error}"),
            )
        })?
        .map_err(|error| io_to_file_error(error, Some(&error_path)))
    }

    fn cwd(&self) -> &Path {
        &self.cwd
    }

    async fn absolute_path(
        &self,
        path: &str,
        cancel: Option<&CancellationToken>,
    ) -> Result<PathBuf, FileError> {
        check_cancel_file(cancel, Some(path))?;
        Ok(Self::resolve_path(&self.cwd, path))
    }

    async fn join_path(
        &self,
        parts: &[&str],
        cancel: Option<&CancellationToken>,
    ) -> Result<PathBuf, FileError> {
        check_cancel_file(cancel, None)?;
        let mut out = PathBuf::new();
        for p in parts {
            out.push(p);
        }
        Ok(out)
    }

    async fn read_text_file(
        &self,
        path: &str,
        cancel: Option<&CancellationToken>,
    ) -> Result<String, FileError> {
        check_cancel_file(cancel, Some(path))?;
        let abs = Self::resolve_path(&self.cwd, path);
        let bytes = read_cancellable(&abs, cancel).await?;
        String::from_utf8(bytes).map_err(|e| {
            FileError::new(FileErrorCode::Invalid, format!("invalid utf-8: {e}"))
                .with_path(abs.to_string_lossy())
        })
    }

    async fn read_text_lines(
        &self,
        path: &str,
        max_lines: Option<usize>,
        cancel: Option<&CancellationToken>,
    ) -> Result<Vec<String>, FileError> {
        check_cancel_file(cancel, Some(path))?;
        if max_lines.map(|m| m == 0).unwrap_or(false) {
            return Ok(Vec::new());
        }
        let abs = Self::resolve_path(&self.cwd, path);
        read::read_text_lines(&abs, max_lines, cancel).await
    }

    async fn read_binary_file(
        &self,
        path: &str,
        cancel: Option<&CancellationToken>,
    ) -> Result<Vec<u8>, FileError> {
        check_cancel_file(cancel, Some(path))?;
        let abs = Self::resolve_path(&self.cwd, path);
        read_cancellable(&abs, cancel).await
    }

    async fn write_file(
        &self,
        path: &str,
        content: FileContent,
        cancel: Option<&CancellationToken>,
    ) -> Result<(), FileError> {
        check_cancel_file(cancel, Some(path))?;
        let abs = Self::resolve_path(&self.cwd, path);
        // mkdir parent (recursive).
        if let Some(parent) = abs.parent() {
            if !parent.as_os_str().is_empty() {
                if let Err(e) = tokio::fs::create_dir_all(parent).await {
                    return Err(io_to_file_error(e, Some(&abs.to_string_lossy())));
                }
            }
        }
        check_cancel_file(cancel, Some(&abs.to_string_lossy()))?;
        write_cancellable(&abs, content.as_bytes(), cancel).await
    }

    async fn append_file(
        &self,
        path: &str,
        content: FileContent,
        cancel: Option<&CancellationToken>,
    ) -> Result<(), FileError> {
        check_cancel_file(cancel, Some(path))?;
        let abs = Self::resolve_path(&self.cwd, path);
        if let Some(parent) = abs.parent() {
            if !parent.as_os_str().is_empty() {
                let _ = tokio::fs::create_dir_all(parent).await;
            }
        }
        use tokio::io::AsyncWriteExt;
        let res = match tokio::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&abs)
            .await
        {
            Ok(mut f) => {
                // Tokio may acknowledge a buffered write before the blocking
                // filesystem operation completes. Await it before returning so
                // an immediate read/metadata call observes the appended bytes.
                match f.write_all(content.as_bytes()).await {
                    Ok(()) => f.flush().await,
                    Err(error) => Err(error),
                }
            }
            Err(e) => return Err(io_to_file_error(e, Some(&abs.to_string_lossy()))),
        };
        res.map_err(|e| io_to_file_error(e, Some(&abs.to_string_lossy())))
    }

    async fn rename_file(
        &self,
        source: &str,
        dest: &str,
        cancel: Option<&CancellationToken>,
    ) -> Result<(), FileError> {
        check_cancel_file(cancel, Some(source))?;
        let src = Self::resolve_path(&self.cwd, source);
        let dst = Self::resolve_path(&self.cwd, dest);
        tokio::fs::rename(&src, &dst)
            .await
            .map_err(|e| io_to_file_error(e, Some(&src.to_string_lossy())))
    }

    async fn file_info(
        &self,
        path: &str,
        cancel: Option<&CancellationToken>,
    ) -> Result<FileInfo, FileError> {
        check_cancel_file(cancel, Some(path))?;
        let abs = Self::resolve_path(&self.cwd, path);
        let meta = tokio::fs::symlink_metadata(&abs)
            .await
            .map_err(|e| io_to_file_error(e, Some(&abs.to_string_lossy())))?;
        let ft = meta.file_type();
        let kind = if ft.is_file() {
            FileKind::File
        } else if ft.is_dir() {
            FileKind::Directory
        } else if ft.is_symlink() {
            FileKind::Symlink
        } else {
            return Err(
                FileError::new(FileErrorCode::Invalid, "Unsupported file type")
                    .with_path(abs.to_string_lossy()),
            );
        };
        let mtime_ms = meta
            .modified()
            .ok()
            .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
            .map(|d| d.as_millis() as i64)
            .unwrap_or(0);
        Ok(FileInfo {
            name: abs
                .file_name()
                .map(|n| n.to_string_lossy().into_owned())
                .unwrap_or_else(|| abs.to_string_lossy().into_owned()),
            path: abs.clone(),
            kind,
            size: meta.len(),
            mtime_ms,
        })
    }

    async fn list_dir(
        &self,
        path: &str,
        cancel: Option<&CancellationToken>,
    ) -> Result<Vec<FileInfo>, FileError> {
        check_cancel_file(cancel, Some(path))?;
        let abs = Self::resolve_path(&self.cwd, path);
        let mut entries = tokio::fs::read_dir(&abs)
            .await
            .map_err(|e| io_to_file_error(e, Some(&abs.to_string_lossy())))?;
        let mut out = Vec::new();
        while let Some(entry) = entries
            .next_entry()
            .await
            .map_err(|e| io_to_file_error(e, Some(&abs.to_string_lossy())))?
        {
            if let Some(t) = cancel {
                if t.is_cancelled() {
                    return Err(FileError::aborted().with_path(abs.to_string_lossy()));
                }
            }
            let ep = entry.path();
            let meta = match tokio::fs::symlink_metadata(&ep).await {
                Ok(m) => m,
                Err(e) => {
                    // Skip unsupported types silently; propagate real stat errors.
                    let code = crate::error::io_to_file_code(&e);
                    if code == FileErrorCode::NotSupported {
                        continue;
                    }
                    return Err(io_to_file_error(e, Some(&ep.to_string_lossy())));
                }
            };
            let ft = meta.file_type();
            let kind = if ft.is_file() {
                FileKind::File
            } else if ft.is_dir() {
                FileKind::Directory
            } else if ft.is_symlink() {
                FileKind::Symlink
            } else {
                continue; // silently skip sockets/fifos/etc.
            };
            let mtime_ms = meta
                .modified()
                .ok()
                .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
                .map(|d| d.as_millis() as i64)
                .unwrap_or(0);
            out.push(FileInfo {
                name: entry.file_name().to_string_lossy().into_owned(),
                path: ep,
                kind,
                size: meta.len(),
                mtime_ms,
            });
        }
        Ok(out)
    }

    async fn canonical_path(
        &self,
        path: &str,
        cancel: Option<&CancellationToken>,
    ) -> Result<PathBuf, FileError> {
        check_cancel_file(cancel, Some(path))?;
        let abs = Self::resolve_path(&self.cwd, path);
        tokio::fs::canonicalize(&abs)
            .await
            .map_err(|e| io_to_file_error(e, Some(&abs.to_string_lossy())))
    }

    async fn exists(
        &self,
        path: &str,
        cancel: Option<&CancellationToken>,
    ) -> Result<bool, FileError> {
        check_cancel_file(cancel, Some(path))?;
        let abs = Self::resolve_path(&self.cwd, path);
        match tokio::fs::symlink_metadata(&abs).await {
            Ok(_) => Ok(true),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(false),
            Err(e) => Err(io_to_file_error(e, Some(&abs.to_string_lossy()))),
        }
    }

    async fn create_dir(
        &self,
        path: &str,
        recursive: bool,
        cancel: Option<&CancellationToken>,
    ) -> Result<(), FileError> {
        check_cancel_file(cancel, Some(path))?;
        let abs = Self::resolve_path(&self.cwd, path);
        let res = if recursive {
            tokio::fs::create_dir_all(&abs).await
        } else {
            tokio::fs::create_dir(&abs).await
        };
        res.map_err(|e| io_to_file_error(e, Some(&abs.to_string_lossy())))
    }

    async fn remove(
        &self,
        path: &str,
        recursive: bool,
        force: bool,
        cancel: Option<&CancellationToken>,
    ) -> Result<(), FileError> {
        check_cancel_file(cancel, Some(path))?;
        let abs = Self::resolve_path(&self.cwd, path);
        let res = if recursive {
            tokio::fs::remove_dir_all(&abs).await
        } else {
            // Try file first, then empty dir.
            match tokio::fs::remove_file(&abs).await {
                Ok(()) => Ok(()),
                Err(_) => tokio::fs::remove_dir(&abs).await,
            }
        };
        match res {
            Ok(()) => Ok(()),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound && force => Ok(()),
            Err(e) => Err(io_to_file_error(e, Some(&abs.to_string_lossy()))),
        }
    }

    async fn create_temp_dir(
        &self,
        prefix: Option<&str>,
        cancel: Option<&CancellationToken>,
    ) -> Result<PathBuf, FileError> {
        check_cancel_file(cancel, None)?;
        let prefix = prefix.unwrap_or("tmp-");
        // Use tempfile's NamedTempFile-less builder for a dir.
        let tmp =
            tempfile::tempdir_in(std::env::temp_dir()).map_err(|e| io_to_file_error(e, None))?;
        // tempfile picks a random name; rename to include the prefix.
        let path = tmp.path().to_path_buf();
        std::mem::forget(tmp); // keep the dir alive; caller manages cleanup.
                               // Build a prefixed sibling.
        let final_path = std::env::temp_dir().join(format!("{}{}", prefix, random_suffix()));
        // Rename the tempdir into the prefixed path.
        if let Err(e) = tokio::fs::rename(&path, &final_path).await {
            // Fallback: just return the original random path.
            let _ = e;
            return Ok(path);
        }
        Ok(final_path)
    }

    async fn create_temp_file(
        &self,
        prefix: &str,
        suffix: &str,
        cancel: Option<&CancellationToken>,
    ) -> Result<PathBuf, FileError> {
        check_cancel_file(cancel, None)?;
        // Create an isolated temp dir (matching the TS pattern of one dir per
        // file), then write an empty file named `<prefix><random><suffix>`.
        let dir = self.create_temp_dir(Some("tmp-"), cancel).await?;
        let name = format!("{}{}{}", prefix, random_suffix(), suffix);
        let path = dir.join(name);
        tokio::fs::File::create(&path)
            .await
            .map_err(|e| io_to_file_error(e, Some(&path.to_string_lossy())))?;
        Ok(path)
    }

    async fn cleanup(&self) {
        let pids: Vec<u32> = self.active_pids.lock().await.iter().copied().collect();
        for pid in pids {
            kill_process_tree(pid).await;
        }
        self.active_pids.lock().await.clear();
    }
}

/// Read a file to bytes, honoring cooperative cancellation.
async fn read_cancellable(
    path: &Path,
    cancel: Option<&CancellationToken>,
) -> Result<Vec<u8>, FileError> {
    let read = tokio::fs::read(path);
    let res = match cancel {
        Some(t) => tokio::select! {
            r = read => r,
            _ = t.cancelled() => return Err(FileError::aborted().with_path(path.to_string_lossy())),
        },
        None => read.await,
    };
    res.map_err(|e| io_to_file_error(e, Some(&path.to_string_lossy())))
}

/// Write bytes to a file (truncate), honoring cooperative cancellation.
async fn write_cancellable(
    path: &Path,
    bytes: &[u8],
    cancel: Option<&CancellationToken>,
) -> Result<(), FileError> {
    use tokio::io::AsyncWriteExt;
    let f = tokio::fs::File::create(path)
        .await
        .map_err(|e| io_to_file_error(e, Some(&path.to_string_lossy())))?;
    let write = async {
        let mut f = f;
        f.write_all(bytes).await?;
        f.flush().await?;
        Ok::<(), std::io::Error>(())
    };
    let res = match cancel {
        Some(t) => tokio::select! {
            r = write => r,
            _ = t.cancelled() => return Err(FileError::aborted().with_path(path.to_string_lossy())),
        },
        None => write.await,
    };
    res.map_err(|e| io_to_file_error(e, Some(&path.to_string_lossy())))
}

fn random_suffix() -> String {
    // Short random suffix via uuid v4 (no Time—it's a UUID, not a timestamp).
    uuid::Uuid::new_v4().simple().to_string()
}

#[async_trait]
impl Shell for OsExecutionEnv {
    async fn exec<'a>(
        &'a self,
        command: &str,
        options: ShellExecOptions<'a>,
    ) -> Result<ShellOutput, ExecutionError> {
        // Pre-flight abort.
        check_cancel_exec(options.cancel)?;
        // Resolve timeout.
        let sandbox = crate::sandbox::policy();
        // The sandbox caps every foreground command, whatever was asked.
        let timeout = match resolve_timeout(sandbox.clamp_timeout(options.timeout)) {
            Ok(t) => t,
            Err(e) => return Err(e),
        };
        // Resolve cwd.
        let cwd = match &options.cwd {
            Some(c) => Self::resolve_path(&self.cwd, &c.to_string_lossy()),
            None => self.cwd.clone(),
        };
        // Shell config. An explicit override is used by native shell tools
        // such as PowerShell; otherwise preserve the default Bash behavior.
        let shell_cfg = match &options.shell {
            Some(override_shell) => ShellConfig {
                shell: override_shell.program.clone(),
                args: override_shell.args.clone(),
                transport: CommandTransport::Argv,
            },
            None => {
                let mut cfg = self.get_shell_config().await?;
                // "Load shell profile": a login shell reads ~/.bash_profile or ~/.profile.
                if sandbox.load_profile() {
                    cfg.args.insert(0, "-l".to_string());
                }
                cfg
            }
        };
        // Verify cwd exists.
        if !cwd.exists() {
            return Err(ExecutionError::new(
                ExecutionErrorCode::SpawnError,
                format!(
                    "Working directory does not exist: {}\nCannot execute bash commands.",
                    cwd.display()
                ),
            ));
        }

        // Build the spawn.
        let mut cmd = tokio::process::Command::new(&shell_cfg.shell);
        cmd.current_dir(&cwd);
        cmd.env_clear();
        // Environment: inherit + shell_env + per-call. The host's own private
        // plumbing (`HOST_PRIVATE_ENV`) is skipped: it describes *this* process,
        // not the shell or anything the shell runs, and inheriting it makes a
        // nested `evo` misreport its session. A caller that genuinely wants a
        // value passed down can still set it explicitly through `env`/`shell_env`
        // below (those are applied after this loop and win).
        // With the sandbox's "inherit host environment" off, only what a shell
        // needs to work passes (PATH, home, locale, terminal, temp, system).
        if options.inherit_env {
            let inherit_all = sandbox.inherit_env();
            for (k, v) in std::env::vars() {
                if is_host_private_env(&k) || !(inherit_all || crate::sandbox::is_minimal_env(&k)) {
                    continue;
                }
                cmd.env(k, v);
            }
        }
        // MSYS2/Git Bash's login profile changes to $HOME unless told to stay.
        if options.shell.is_none() && sandbox.load_profile() {
            cmd.env("CHERE_INVOKING", "1");
        }
        if let Some(base) = &self.shell_env {
            for (k, v) in base {
                cmd.env(k, v);
            }
        }
        if let Some(provider) = &self.shell_env_provider {
            apply_shell_env(&mut cmd, provider(), options.inherit_env);
        }
        if let Some(extra) = &options.env {
            for (k, v) in extra {
                cmd.env(k, v);
            }
        }
        // stdio.
        cmd.stdin(std::process::Stdio::piped());
        cmd.stdout(std::process::Stdio::piped());
        cmd.stderr(std::process::Stdio::piped());
        #[cfg(unix)]
        {
            cmd.process_group(0); // child becomes its own group leader.
        }
        #[cfg(windows)]
        {
            use windows_sys::Win32::System::Threading::{CREATE_NO_WINDOW, CREATE_SUSPENDED};
            // Suspended until it is in its job (see `shell_jobs::start`).
            cmd.creation_flags(CREATE_NO_WINDOW | CREATE_SUSPENDED);
        }

        // Args: stdin transport → `bash -s` (no command argv); argv → append.
        let transport = shell_cfg.transport;
        cmd.args(&shell_cfg.args);
        if matches!(transport, CommandTransport::Argv) {
            cmd.arg(command);
        }

        let mut child = match cmd.spawn() {
            Ok(c) => c,
            Err(e) => {
                return Err(ExecutionError::new(
                    ExecutionErrorCode::SpawnError,
                    format!("failed to spawn shell: {e}"),
                ));
            }
        };
        let pid = child.id();
        #[cfg(windows)]
        {
            let started = match (pid, child.raw_handle()) {
                (Some(pid), Some(process)) => shell_jobs::start(pid, process),
                _ => Err("the shell has no process handle".to_owned()),
            };
            if let Err(error) = started {
                if let Some(pid) = pid {
                    shell_jobs::forget(pid);
                }
                let _ = child.start_kill();
                return Err(ExecutionError::new(
                    ExecutionErrorCode::SpawnError,
                    format!("failed to start shell: {error}"),
                ));
            }
        }
        if let Some(pid) = pid {
            self.active_pids.lock().await.insert(pid);
        }

        // Stdin transport: write command then close. Closing happens on BOTH
        // transports, and deliberately: anything that prompts (`npx` asking to
        // install, `npm init`, a `read` in a script) must see EOF and fail fast,
        // not block on a pipe that nothing will ever write to or close. tokio's
        // `Child::wait` also drops stdin as a deadlock guard, but relying on that
        // would make the guarantee a side effect of an implementation detail.
        let mut stdin = child.stdin.take();
        if matches!(transport, CommandTransport::Stdin) {
            if let Some(stdin) = stdin.as_mut() {
                use tokio::io::AsyncWriteExt;
                let _ = stdin.write_all(command.as_bytes()).await;
                let _ = stdin.flush().await;
            }
        }
        drop(stdin);

        // Collect stdout/stderr via separate read tasks, firing callbacks.
        let mut stdout_buf = String::new();
        let mut stderr_buf = String::new();
        let cancel = options.cancel;
        let stop_readers = CancellationToken::new();
        let mut on_stdout = options.on_stdout;
        let mut on_stderr = options.on_stderr;

        let mut stdout = child.stdout.take();
        let mut stderr = child.stderr.take();

        let stdout_task = async {
            if let Some(s) = stdout.as_mut() {
                let mut buf = vec![0u8; 8192];
                let mut decoder = crate::output_decode::StreamDecoder::new();
                use tokio::io::AsyncReadExt;
                loop {
                    let read_result = tokio::select! {
                        biased;
                        _ = stop_readers.cancelled() => break,
                        _ = async {
                            match cancel {
                                Some(token) => token.cancelled().await,
                                None => std::future::pending::<()>().await,
                            }
                        } => break,
                        result = s.read(&mut buf) => result,
                    };
                    let n = match read_result {
                        Ok(0) => break,
                        Ok(n) => n,
                        Err(_) => break,
                    };
                    let chunk = decoder.push(&buf[..n]);
                    if chunk.is_empty() {
                        continue;
                    }
                    if let Some(cb) = on_stdout.as_mut() {
                        // Callback errors are swallowed (TS sets callbackError;
                        // v1 simplifies — the callback contract is best-effort).
                        cb(&chunk);
                    }
                    stdout_buf.push_str(&chunk);
                }
                let tail = decoder.finish();
                if !tail.is_empty() {
                    if let Some(cb) = on_stdout.as_mut() {
                        cb(&tail);
                    }
                    stdout_buf.push_str(&tail);
                }
            }
        };
        let stderr_task = async {
            if let Some(s) = stderr.as_mut() {
                let mut buf = vec![0u8; 8192];
                let mut decoder = crate::output_decode::StreamDecoder::new();
                use tokio::io::AsyncReadExt;
                loop {
                    let read_result = tokio::select! {
                        biased;
                        _ = stop_readers.cancelled() => break,
                        _ = async {
                            match cancel {
                                Some(token) => token.cancelled().await,
                                None => std::future::pending::<()>().await,
                            }
                        } => break,
                        result = s.read(&mut buf) => result,
                    };
                    let n = match read_result {
                        Ok(0) => break,
                        Ok(n) => n,
                        Err(_) => break,
                    };
                    let chunk = decoder.push(&buf[..n]);
                    if chunk.is_empty() {
                        continue;
                    }
                    if let Some(cb) = on_stderr.as_mut() {
                        cb(&chunk);
                    }
                    stderr_buf.push_str(&chunk);
                }
                let tail = decoder.finish();
                if !tail.is_empty() {
                    if let Some(cb) = on_stderr.as_mut() {
                        cb(&tail);
                    }
                    stderr_buf.push_str(&tail);
                }
            }
        };

        // Wait for the child, with timeout + cancellation.
        let mut timed_out = false;
        let exit_status = {
            // We pin stdout/stderr take handles + the wait future, then drive
            // them concurrently inside a single select! block. `child` is only
            // touched again AFTER the join completes (kill + reap), so the
            // borrow ends cleanly.
            let status_fut = async {
                match (timeout, cancel) {
                    (Some(to), Some(token)) => {
                        tokio::select! {
                            status = child.wait() => status,
                            _ = tokio::time::sleep(to) => {
                                timed_out = true;
                                if let Some(pid) = child.id() {
                                    kill_process_tree(pid).await;
                                }
                                child.wait().await
                            }
                            _ = token.cancelled() => {
                                if let Some(pid) = child.id() {
                                    kill_process_tree(pid).await;
                                }
                                child.wait().await
                            }
                        }
                    }
                    (Some(to), None) => match tokio::time::timeout(to, child.wait()).await {
                        Ok(status) => status,
                        Err(_) => {
                            timed_out = true;
                            if let Some(pid) = child.id() {
                                kill_process_tree(pid).await;
                            }
                            child.wait().await
                        }
                    },
                    (None, Some(token)) => {
                        tokio::select! {
                            status = child.wait() => status,
                            _ = token.cancelled() => {
                                if let Some(pid) = child.id() {
                                    kill_process_tree(pid).await;
                                }
                                child.wait().await
                            }
                        }
                    }
                    (None, None) => child.wait().await,
                }
            };
            // Run stdio + status concurrently — but the CHILD is the driver:
            // once it is reaped the command is over, and the call has to end even
            // if something else still holds the stdout/stderr pipes open.
            //
            // This is the "`npm run` is stuck" shape. A script that starts a watcher,
            // a dev-server or a background daemon leaves a grandchild running with
            // the inherited pipes, so reading to EOF waits for a process the
            // command no longer owns. No timeout rescues that: the timeout wraps
            // `child.wait()` and the child already exited successfully.
            //
            // The pipes are still read while the child runs: a command that writes
            // more than the pipe buffer (64 KiB on Linux) blocks until someone
            // reads, so waiting for the child first would deadlock on any broad
            // `rg` or build log.
            tokio::pin!(status_fut, stdout_task, stderr_task);
            let (mut stdout_done, mut stderr_done) = (false, false);
            let status_res = loop {
                tokio::select! {
                    status = &mut status_fut => break status,
                    () = &mut stdout_task, if !stdout_done => stdout_done = true,
                    () = &mut stderr_task, if !stderr_done => stderr_done = true,
                }
            };
            // Drain what is already in the pipe — a completed write is already in
            // the pipe buffer, so this is not a race — then stop, without waiting
            // for an EOF that may never come. A command whose own process is gone
            // should not be able to hold the call open.
            let drain = async {
                tokio::join!(
                    async {
                        if !stdout_done {
                            (&mut stdout_task).await;
                        }
                    },
                    async {
                        if !stderr_done {
                            (&mut stderr_task).await;
                        }
                    },
                );
            };
            tokio::pin!(drain);
            if tokio::time::timeout(
                std::time::Duration::from_millis(EXIT_STDIO_GRACE_MS),
                &mut drain,
            )
            .await
            .is_err()
            {
                // Stop reads, not their futures: both decoders must finish and
                // deliver already-read tails to callbacks and captured output.
                stop_readers.cancel();
                drain.await;
            }
            status_res
        };

        // Give trailing stdio a brief grace period. Only the timed-out and
        // cancelled paths still owe a wait: on the normal path the drain above
        // already capped it.
        if timed_out {
            let _ = tokio::time::sleep(std::time::Duration::from_millis(EXIT_STDIO_GRACE_MS)).await;
        }

        // Remove from tracked pids.
        if let Some(pid) = pid {
            #[cfg(windows)]
            shell_jobs::forget(pid);
            self.active_pids.lock().await.remove(&pid);
        }

        // Resolution priority: timedOut → cancelled → status.
        let status = match exit_status {
            Ok(s) => s,
            Err(e) => {
                return Err(ExecutionError::new(
                    ExecutionErrorCode::SpawnError,
                    format!("child wait failed: {e}"),
                ));
            }
        };
        if timed_out {
            return Err(ExecutionError::timeout(
                options.timeout.map(|f| f as u64).unwrap_or(0),
            ));
        }
        if cancel.map(|t| t.is_cancelled()).unwrap_or(false) {
            return Err(ExecutionError::aborted());
        }
        let exit_code = status.code().unwrap_or(0);
        Ok(ShellOutput {
            stdout: stdout_buf,
            stderr: stderr_buf,
            exit_code,
        })
    }

    async fn cleanup(&self) {
        FileSystem::cleanup(self).await
    }
}

#[async_trait]
impl ExecutionEnv for OsExecutionEnv {}

#[async_trait]
impl MutatingEnv for OsExecutionEnv {
    fn as_env(&self) -> &dyn ExecutionEnv {
        self
    }
    fn mutation_registry(&self) -> &MutationQueueRegistry {
        &self.registry
    }
}

/// Validate a timeout (seconds). Mirrors `resolveTimeoutMs` semantics.
fn resolve_timeout(timeout: Option<f64>) -> Result<Option<std::time::Duration>, ExecutionError> {
    match timeout {
        None => Ok(None),
        Some(secs) => {
            if !secs.is_finite() || secs <= 0.0 {
                return Err(ExecutionError::new(
                    ExecutionErrorCode::Timeout,
                    "Invalid timeout: must be a finite number of seconds",
                ));
            }
            let ms = secs * 1000.0;
            if ms > MAX_TIMEOUT_MS as f64 {
                return Err(ExecutionError::new(
                    ExecutionErrorCode::Timeout,
                    format!(
                        "Invalid timeout: maximum is {} seconds",
                        MAX_TIMEOUT_SECONDS
                    ),
                ));
            }
            Ok(Some(std::time::Duration::from_secs_f64(secs)))
        }
    }
}
