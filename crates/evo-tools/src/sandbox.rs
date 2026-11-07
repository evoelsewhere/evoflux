//! Process security: one policy per engine process, set once by the host at
//! startup (the desktop's Settings → Sandbox, through `--sandbox-config`).
//!
//! * `inherit_env`: shell commands see the host environment. Off, they get
//!   only what a shell needs to work — PATH, home and user, locale, terminal,
//!   temporary directories and (Windows) system folders — not tokens or keys.
//! * `load_profile`: bash runs as a login shell (`-l`, so `~/.bash_profile`
//!   or `~/.profile`), PowerShell loads `$PROFILE`.
//! * `max_timeout_secs`: a hard cap on foreground shell commands, including a
//!   larger timeout the model asks for.
//! * `max_output_kib`: output the model sees inline; beyond it the tail is
//!   shown and the rest is in a file.
//! * `denied_patterns`: globs the file tools refuse (`**/.env`). A guardrail:
//!   shell commands can still reach those files.
//! * `worktree_location`: where the engine creates isolated Git worktrees for
//!   delegated agents (`evo-engine`'s `worktrees` module).
//!
//! Without a configured policy everything behaves as before.

use std::path::Path;
use std::sync::{Arc, RwLock};

use globset::{Glob, GlobBuilder, GlobSet, GlobSetBuilder};
use serde::Deserialize;

use crate::error::{FileError, FileErrorCode};
use crate::truncate::DEFAULT_MAX_BYTES;

#[derive(Debug, Clone, PartialEq, Deserialize)]
#[serde(rename_all = "camelCase", default)]
pub struct SandboxConfig {
    pub inherit_env: bool,
    pub load_profile: bool,
    /// Seconds; `None`: no cap.
    pub max_timeout_secs: Option<f64>,
    /// KiB; `None`: the built-in limit.
    pub max_output_kib: Option<u32>,
    pub denied_patterns: Vec<String>,
    pub worktree_location: WorktreeLocation,
}

/// Where new managed worktrees go (re-exported from `evo-worktrees`).
pub use evo_worktrees::Location as WorktreeLocation;

impl Default for SandboxConfig {
    fn default() -> Self {
        Self {
            inherit_env: true,
            load_profile: false,
            max_timeout_secs: None,
            max_output_kib: None,
            denied_patterns: Vec::new(),
            worktree_location: WorktreeLocation::UserData,
        }
    }
}

pub struct SandboxPolicy {
    config: SandboxConfig,
    denied: Option<(GlobSet, Vec<String>)>,
    /// Patterns that are not valid globs, left out (with the reason).
    invalid: Vec<String>,
}

static POLICY: RwLock<Option<Arc<SandboxPolicy>>> = RwLock::new(None);

/// Set this process's policy. Patterns that are not valid globs are left out
/// and returned, so one typo cannot stop the engine.
pub fn configure(config: SandboxConfig) -> Result<Vec<String>, String> {
    let policy = SandboxPolicy::new(config)?;
    let invalid = policy.invalid.clone();
    *POLICY.write().unwrap_or_else(|e| e.into_inner()) = Some(Arc::new(policy));
    Ok(invalid)
}

/// The current policy (the permissive default until [`configure`] runs).
pub fn policy() -> Arc<SandboxPolicy> {
    if let Some(policy) = POLICY.read().unwrap_or_else(|e| e.into_inner()).as_ref() {
        return policy.clone();
    }
    Arc::new(SandboxPolicy::new(SandboxConfig::default()).expect("default policy"))
}

fn glob(pattern: &str) -> Result<Glob, String> {
    GlobBuilder::new(pattern)
        // `*` stays within one folder; `**` crosses folders.
        .literal_separator(true)
        .case_insensitive(cfg!(any(windows, target_os = "macos")))
        .build()
        .map_err(|e| format!("invalid pattern {pattern:?}: {e}"))
}

/// Forward slashes, so one pattern fits every platform.
fn slashed(path: &str) -> String {
    path.replace('\\', "/")
}

impl SandboxPolicy {
    pub fn new(config: SandboxConfig) -> Result<Self, String> {
        let patterns: Vec<String> = config
            .denied_patterns
            .iter()
            .map(|p| p.trim().to_string())
            .filter(|p| !p.is_empty())
            .collect();
        let mut set = GlobSetBuilder::new();
        let mut valid = Vec::new();
        let mut invalid = Vec::new();
        for pattern in patterns {
            match glob(&slashed(&pattern)) {
                Ok(glob) => {
                    set.add(glob);
                    valid.push(pattern);
                }
                Err(error) => invalid.push(error),
            }
        }
        let denied = if valid.is_empty() {
            None
        } else {
            Some((set.build().map_err(|e| e.to_string())?, valid))
        };
        Ok(Self {
            config,
            denied,
            invalid,
        })
    }

    pub fn config(&self) -> &SandboxConfig {
        &self.config
    }

    pub fn inherit_env(&self) -> bool {
        self.config.inherit_env
    }

    pub fn load_profile(&self) -> bool {
        self.config.load_profile
    }

    pub fn worktree_location(&self) -> WorktreeLocation {
        self.config.worktree_location
    }

    /// The timeout to use: the requested one, capped. With a cap and no
    /// request, the cap.
    pub fn clamp_timeout(&self, requested: Option<f64>) -> Option<f64> {
        match self
            .config
            .max_timeout_secs
            .filter(|max| max.is_finite() && *max > 0.0)
        {
            None => requested,
            Some(max) => Some(requested.map_or(max, |secs| secs.min(max))),
        }
    }

    /// Bytes of shell output shown inline.
    pub fn max_output_bytes(&self) -> usize {
        self.config
            .max_output_kib
            .filter(|kib| *kib > 0)
            .map_or(DEFAULT_MAX_BYTES, |kib| kib as usize * 1024)
    }

    /// The denied pattern `path` matches, if any. `path` is absolute; it is
    /// also matched relative to `cwd` when inside it, so `secrets/**` works.
    pub fn denied_by(&self, path: &str, cwd: Option<&Path>) -> Option<&str> {
        let (set, patterns) = self.denied.as_ref()?;
        let absolute = slashed(path);
        let mut candidates = vec![absolute.clone()];
        if let Some(cwd) = cwd {
            let root = slashed(&cwd.to_string_lossy());
            let root = root.trim_end_matches('/');
            let n = root.len();
            let same_root = absolute.len() > n
                && absolute.is_char_boundary(n)
                && if cfg!(windows) {
                    absolute[..n].eq_ignore_ascii_case(root)
                } else {
                    &absolute[..n] == root
                };
            if same_root && absolute[n..].starts_with('/') {
                candidates.push(absolute[n + 1..].to_string());
            }
        }
        candidates
            .iter()
            .find_map(|candidate| set.matches(candidate).first().copied())
            .map(|index| patterns[index].as_str())
    }

    /// Refuse a file tool's access to a denied path.
    pub fn check_path(&self, path: &str, cwd: Option<&Path>) -> Result<(), FileError> {
        match self.denied_by(path, cwd) {
            None => Ok(()),
            Some(pattern) => Err(FileError::new(
                FileErrorCode::PermissionDenied,
                format!("Access to {path} is blocked: it matches the denied pattern `{pattern}` (Settings → Sandbox)."),
            )),
        }
    }
}

/// Variables a shell keeps when the host environment is not inherited.
pub fn is_minimal_env(name: &str) -> bool {
    const NAMES: &[&str] = &[
        "PATH",
        "PATHEXT",
        "HOME",
        "USERPROFILE",
        "HOMEDRIVE",
        "HOMEPATH",
        "USER",
        "USERNAME",
        "LOGNAME",
        "SHELL",
        "LANG",
        "LANGUAGE",
        "TZ",
        "TERM",
        "COLORTERM",
        "TERM_PROGRAM",
        "NO_COLOR",
        "TMP",
        "TEMP",
        "TMPDIR",
        "SYSTEMROOT",
        "SYSTEMDRIVE",
        "WINDIR",
        "COMSPEC",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "PROGRAMW6432",
        "PROGRAMDATA",
        "COMMONPROGRAMFILES",
        "COMMONPROGRAMFILES(X86)",
        "COMMONPROGRAMW6432",
        "APPDATA",
        "LOCALAPPDATA",
        "NUMBER_OF_PROCESSORS",
        "PROCESSOR_ARCHITECTURE",
        "OS",
    ];
    let upper = name.to_ascii_uppercase();
    upper.starts_with("LC_") || NAMES.contains(&upper.as_str())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn with(patterns: &[&str]) -> SandboxPolicy {
        SandboxPolicy::new(SandboxConfig {
            denied_patterns: patterns.iter().map(|p| p.to_string()).collect(),
            ..Default::default()
        })
        .unwrap()
    }

    #[test]
    fn env_files_are_denied_anywhere() {
        let policy = with(&["**/.env", "**/.env.*"]);
        assert_eq!(policy.denied_by("/home/a/app/.env", None), Some("**/.env"));
        assert_eq!(
            policy.denied_by(r"C:\code\app\.env.local", None),
            Some("**/.env.*")
        );
        assert_eq!(policy.denied_by("/home/a/app/src/env.rs", None), None);
        assert_eq!(policy.denied_by("/home/a/app/.envrc", None), None);
    }

    #[test]
    fn patterns_match_relative_to_the_workspace() {
        let policy = with(&["secrets/**"]);
        let cwd = Path::new("/work/app");
        assert_eq!(
            policy.denied_by("/work/app/secrets/key.pem", Some(cwd)),
            Some("secrets/**")
        );
        assert_eq!(
            policy.denied_by("/work/other/secrets/key.pem", Some(cwd)),
            None
        );
        assert!(policy
            .check_path("/work/app/secrets/key.pem", Some(cwd))
            .is_err());
    }

    #[test]
    fn timeouts_are_capped() {
        let policy = SandboxPolicy::new(SandboxConfig {
            max_timeout_secs: Some(600.0),
            ..Default::default()
        })
        .unwrap();
        assert_eq!(policy.clamp_timeout(Some(3600.0)), Some(600.0));
        assert_eq!(policy.clamp_timeout(Some(30.0)), Some(30.0));
        assert_eq!(policy.clamp_timeout(None), Some(600.0));
        assert_eq!(policy_default().clamp_timeout(None), None);
    }

    #[test]
    fn output_limit_and_minimal_env() {
        let policy = SandboxPolicy::new(SandboxConfig {
            max_output_kib: Some(128),
            ..Default::default()
        })
        .unwrap();
        assert_eq!(policy.max_output_bytes(), 128 * 1024);
        assert_eq!(policy_default().max_output_bytes(), DEFAULT_MAX_BYTES);
        assert!(is_minimal_env("Path") && is_minimal_env("LC_ALL") && is_minimal_env("SystemRoot"));
        assert!(!is_minimal_env("OPENAI_API_KEY") && !is_minimal_env("GITHUB_TOKEN"));
    }

    #[test]
    fn bad_patterns_are_left_out() {
        let policy = with(&["a[", "**/.env"]);
        assert_eq!(policy.invalid.len(), 1);
        assert_eq!(policy.denied_by("/x/.env", None), Some("**/.env"));
    }

    fn policy_default() -> SandboxPolicy {
        SandboxPolicy::new(SandboxConfig::default()).unwrap()
    }
}
