//! Port of the settings subset of `app/core/config.py`.
//!
//! Only the variables the Rust server needs are modelled. Python also reads
//! `.env` files from the working directory and `~/.config/evoflux/.env`; Rust
//! reads the process environment only, which is what the Tauri shell and the
//! gateway pass down.

use std::collections::HashMap;
use std::path::{Path, PathBuf};

/// Why settings could not be resolved.
#[derive(Debug, thiserror::Error)]
pub enum ConfigError {
    #[error("API_PORT must be an integer between 0 and 65535, got {0:?}")]
    InvalidPort(String),
    #[error("cannot determine the working directory: {0}")]
    CurrentDir(#[from] std::io::Error),
}

/// Resolved settings (`APP_ENV`, `EVOFLUX_*_DIR`, `LOG_LEVEL`, `API_HOST`, `API_PORT`).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Settings {
    pub app_env: String,
    pub data_dir: PathBuf,
    pub config_dir: PathBuf,
    pub state_dir: PathBuf,
    pub log_level: String,
    pub api_host: String,
    pub api_port: u16,
}

impl Settings {
    /// Resolve settings from the process environment.
    pub fn from_env() -> Result<Self, ConfigError> {
        let vars: HashMap<String, String> = std::env::vars().collect();
        let home = home_from_vars(&vars);
        let cwd = std::env::current_dir()?;
        Self::from_vars(&vars, home.as_deref(), &cwd)
    }

    /// Resolve settings from explicit variables, home directory and working
    /// directory. Names match case-insensitively (pydantic-settings default),
    /// an exact-case match winning.
    pub fn from_vars(
        vars: &HashMap<String, String>,
        home: Option<&Path>,
        cwd: &Path,
    ) -> Result<Self, ConfigError> {
        let get = |name: &str| lookup(vars, name);
        let app_env = get("APP_ENV").unwrap_or_else(|| "production".to_owned());
        let defaults = default_dirs(&app_env, home, cwd);
        let dir = |name: &str, default: PathBuf| match get(name) {
            Some(value) if !value.is_empty() => PathBuf::from(value),
            _ => default,
        };
        let api_port = match get("API_PORT") {
            Some(raw) => raw
                .trim()
                .parse::<u16>()
                .map_err(|_| ConfigError::InvalidPort(raw.clone()))?,
            None => 4082,
        };
        Ok(Self {
            data_dir: dir("EVOFLUX_DATA_DIR", defaults.data),
            config_dir: dir("EVOFLUX_CONFIG_DIR", defaults.config),
            state_dir: dir("EVOFLUX_STATE_DIR", defaults.state),
            log_level: get("LOG_LEVEL").unwrap_or_else(|| "INFO".to_owned()),
            api_host: get("API_HOST").unwrap_or_else(|| "0.0.0.0".to_owned()),
            api_port,
            app_env,
        })
    }
}

struct DefaultDirs {
    data: PathBuf,
    config: PathBuf,
    state: PathBuf,
}

/// `_default_dirs`: XDG-style roots under the home directory in production,
/// `.evoflux/dev/*` under the working directory otherwise.
fn default_dirs(app_env: &str, home: Option<&Path>, cwd: &Path) -> DefaultDirs {
    if app_env == "production" {
        let home = home.unwrap_or_else(|| Path::new("."));
        return DefaultDirs {
            data: home.join(".local").join("share").join("evoflux"),
            config: home.join(".config").join("evoflux"),
            state: home.join(".local").join("state").join("evoflux"),
        };
    }
    let root = cwd.join(".evoflux").join("dev");
    DefaultDirs {
        data: root.join("data"),
        config: root.join("config"),
        state: root.join("state"),
    }
}

fn lookup(vars: &HashMap<String, String>, name: &str) -> Option<String> {
    if let Some(value) = vars.get(name) {
        return Some(value.clone());
    }
    let mut matches: Vec<(&String, &String)> = vars
        .iter()
        .filter(|(key, _)| key.eq_ignore_ascii_case(name))
        .collect();
    matches.sort();
    matches.first().map(|(_, value)| (*value).clone())
}

/// `Path.home()` as Python resolves it: `USERPROFILE` (then `HOMEDRIVE` +
/// `HOMEPATH`) on Windows, `HOME` elsewhere.
fn home_from_vars(vars: &HashMap<String, String>) -> Option<PathBuf> {
    let get = |name: &str| vars.get(name).filter(|v| !v.is_empty());
    if cfg!(windows) {
        if let Some(profile) = get("USERPROFILE") {
            return Some(PathBuf::from(profile));
        }
        return match (get("HOMEDRIVE"), get("HOMEPATH")) {
            (Some(drive), Some(path)) => Some(PathBuf::from(format!("{drive}{path}"))),
            _ => None,
        };
    }
    get("HOME").map(PathBuf::from).or_else(std::env::home_dir)
}
