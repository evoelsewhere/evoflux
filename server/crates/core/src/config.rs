//! Port of the settings subset of `app/core/config.py`.
//!
//! Only the variables the Rust server needs are modelled. Like Python, values
//! come from the process environment, then `~/.config/evoflux/.env`, then
//! `./.env` (earlier wins).

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

/// A `SecretStr` setting: `Debug` never prints the value.
#[derive(Clone, PartialEq, Eq)]
pub struct Secret(String);

impl Secret {
    pub fn expose(&self) -> &str {
        &self.0
    }
}

impl std::fmt::Debug for Secret {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("Secret(**********)")
    }
}

/// Resolved settings (`APP_ENV`, `EVOFLUX_*_DIR`, `LOG_LEVEL`, `API_HOST`, `API_PORT`, `NINJA_API_KEY`).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Settings {
    pub app_env: String,
    pub data_dir: PathBuf,
    pub config_dir: PathBuf,
    pub state_dir: PathBuf,
    pub cache_dir: PathBuf,
    /// `Path.home()`; empty when the home directory is unknown.
    pub home_dir: PathBuf,
    pub log_level: String,
    pub api_host: String,
    pub api_port: u16,
    pub ninja_api_key: Option<Secret>,
    sqlite_database_path: Option<PathBuf>,
}

impl Settings {
    pub fn sqlite_database_path(&self) -> Option<PathBuf> {
        self.sqlite_database_path.clone()
    }
    /// Resolve settings from the process environment.
    pub fn from_env() -> Result<Self, ConfigError> {
        let vars: HashMap<String, String> = std::env::vars().collect();
        let home = home_from_vars(&vars);
        let cwd = std::env::current_dir()?;
        Self::from_vars_and_dotenv(&vars, home.as_deref(), &cwd)
    }

    /// [`Self::from_vars`] after merging the `.env` files Python reads.
    pub fn from_vars_and_dotenv(
        vars: &HashMap<String, String>,
        home: Option<&Path>,
        cwd: &Path,
    ) -> Result<Self, ConfigError> {
        let mut merged = HashMap::new();
        let mut files = vec![cwd.join(".env")];
        if let Some(home) = home {
            files.push(home.join(".config").join("evoflux").join(".env"));
        }
        // Later files win over earlier ones; the process environment wins over both.
        for file in files {
            for (key, value) in read_dotenv(&file) {
                merged.insert(key.to_uppercase(), value);
            }
        }
        for (key, value) in vars {
            merged.retain(|k: &String, _| !k.eq_ignore_ascii_case(key));
            merged.insert(key.clone(), value.clone());
        }
        Self::from_vars(&merged, home, cwd)
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
        let data_dir = dir("EVOFLUX_DATA_DIR", defaults.data);
        let sqlite_database_path = match get("DATABASE_URL").filter(|v| !v.is_empty()) {
            None => Some(data_dir.join("evoflux.db")),
            Some(url) => url
                .strip_prefix("sqlite+aiosqlite:///")
                .or_else(|| url.strip_prefix("sqlite:///"))
                .filter(|path| {
                    !path.is_empty()
                        && *path != ":memory:"
                        && !path.contains(['?', '#'])
                        && !path.starts_with("file:")
                })
                .map(PathBuf::from),
        };
        let sqlite_database_path =
            sqlite_database_path.filter(|path| !path.to_string_lossy().contains("${"));
        Ok(Self {
            data_dir,
            sqlite_database_path,
            config_dir: dir("EVOFLUX_CONFIG_DIR", defaults.config),
            state_dir: dir("EVOFLUX_STATE_DIR", defaults.state),
            cache_dir: dir("EVOFLUX_CACHE_DIR", defaults.cache),
            home_dir: home.map(Path::to_path_buf).unwrap_or_default(),
            log_level: get("LOG_LEVEL").unwrap_or_else(|| "INFO".to_owned()),
            api_host: get("API_HOST").unwrap_or_else(|| "0.0.0.0".to_owned()),
            api_port,
            ninja_api_key: get("NINJA_API_KEY").map(Secret),
            app_env,
        })
    }
}

struct DefaultDirs {
    data: PathBuf,
    config: PathBuf,
    state: PathBuf,
    cache: PathBuf,
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
            cache: home.join(".cache").join("evoflux"),
        };
    }
    let root = cwd.join(".evoflux").join("dev");
    DefaultDirs {
        data: root.join("data"),
        config: root.join("config"),
        state: root.join("state"),
        cache: root.join("cache"),
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

/// Startup-only synchronous read of a `.env` file; missing or unreadable
/// files count as empty, as in pydantic-settings.
#[allow(clippy::disallowed_methods)]
fn read_dotenv(path: &Path) -> Vec<(String, String)> {
    match std::fs::read(path) {
        Ok(bytes) => parse_dotenv(&String::from_utf8_lossy(&bytes)),
        Err(_) => Vec::new(),
    }
}

/// The subset of python-dotenv syntax used for settings: `KEY=value`, an
/// optional `export ` prefix, `#` comments, and single or double quotes.
pub fn parse_dotenv(text: &str) -> Vec<(String, String)> {
    let mut out = Vec::new();
    for line in text.trim_start_matches('\u{feff}').lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let line = line.strip_prefix("export ").map_or(line, str::trim_start);
        let Some((key, raw)) = line.split_once('=') else {
            continue;
        };
        out.push((key.trim().to_owned(), dotenv_value(raw.trim())));
    }
    out
}

const BACKSLASH: char = '\u{5c}';

fn dotenv_value(raw: &str) -> String {
    for quote in ['"', '\''] {
        if let Some(rest) = raw.strip_prefix(quote) {
            let mut value = String::new();
            let mut chars = rest.chars();
            while let Some(c) = chars.next() {
                if c == quote {
                    break;
                }
                if c != BACKSLASH {
                    value.push(c);
                    continue;
                }
                match (quote, chars.next()) {
                    ('"', Some('n')) => value.push('\n'),
                    ('"', Some('t')) => value.push('\t'),
                    (_, Some(next @ (BACKSLASH | '"' | '\''))) => value.push(next),
                    (_, Some(next)) => {
                        value.push(BACKSLASH);
                        value.push(next);
                    }
                    (_, None) => value.push(BACKSLASH),
                }
            }
            return value;
        }
    }
    // Unquoted: a ` #` starts a comment.
    match raw.find(" #") {
        Some(i) => raw.get(..i).unwrap_or(raw).trim_end().to_owned(),
        None => raw.to_owned(),
    }
}
