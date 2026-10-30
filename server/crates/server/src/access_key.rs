//! Port of `expected_desktop_token` (`app/core/desktop_auth.py`) for the
//! routes Rust serves itself: `EVOFLUX_DESKTOP_TOKEN`, then
//! `EVOFLUX_ACCESS_KEY`, then `server.access_key` from
//! `{config}/settings.yaml` (`app/core/runtime_settings.py`).
//!
//! Python re-reads the file on every request; this is resolved once at
//! startup. Where Python would silently drop an `access_key` it cannot
//! validate (and so turn auth off), this fails instead, so the server never
//! starts unauthenticated while `settings.yaml` asks for a key.

use std::path::{Path, PathBuf};
use yaml_rust2::{Yaml, YamlLoader};

#[derive(Debug, thiserror::Error)]
pub enum AccessKeyError {
    #[error("cannot read {path}: {source}")]
    Read {
        path: PathBuf,
        source: std::io::Error,
    },
    #[error("{path} is not valid YAML, so server.access_key cannot be read: {message}")]
    Parse { path: PathBuf, message: String },
    #[error("{path}: {message}; refusing to start without the access key it may configure")]
    Invalid { path: PathBuf, message: String },
}

/// `runtime_settings_path()`.
pub fn settings_path(config_dir: &Path) -> PathBuf {
    config_dir.join("settings.yaml")
}

/// The token Rust-owned routes require, or `None` when token auth is off.
pub fn expected_token(
    env: impl Fn(&str) -> Option<String>,
    config_dir: &Path,
) -> Result<Option<String>, AccessKeyError> {
    let from_env = ["EVOFLUX_DESKTOP_TOKEN", "EVOFLUX_ACCESS_KEY"]
        .iter()
        .filter_map(|name| env(name))
        .find(|value| !value.is_empty());
    if from_env.is_some() {
        return Ok(from_env);
    }
    let path = settings_path(config_dir);
    let Some(text) = read_settings(&path)? else {
        return Ok(None);
    };
    access_key_from_yaml(&text).map_err(|message| match message {
        YamlProblem::Parse(message) => AccessKeyError::Parse {
            path: path.clone(),
            message,
        },
        YamlProblem::Invalid(message) => AccessKeyError::Invalid {
            path: path.clone(),
            message,
        },
    })
}

/// Startup-only synchronous read, before the async runtime starts. A missing
/// file means default settings, as in `load_runtime_settings_report`.
#[allow(clippy::disallowed_methods)]
fn read_settings(path: &Path) -> Result<Option<String>, AccessKeyError> {
    let bytes = match std::fs::read(path) {
        Ok(bytes) => bytes,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(source) => {
            return Err(AccessKeyError::Read {
                path: path.to_owned(),
                source,
            })
        }
    };
    // `Path.read_text(encoding="utf-8")` keeps a BOM as U+FEFF, which PyYAML skips.
    String::from_utf8(bytes)
        .map(|text| Some(text.trim_start_matches('\u{feff}').to_owned()))
        .map_err(|error| AccessKeyError::Read {
            path: path.to_owned(),
            source: std::io::Error::new(std::io::ErrorKind::InvalidData, error),
        })
}

enum YamlProblem {
    Parse(String),
    Invalid(String),
}

/// YAML 1.1 booleans that PyYAML loads as `bool` (dropped by pydantic, so
/// Python runs without a key) but YAML 1.2 loads as strings.
const YAML11_BOOLS: &[&str] = &["y", "yes", "n", "no", "on", "off"];

fn access_key_from_yaml(text: &str) -> Result<Option<String>, YamlProblem> {
    let docs = YamlLoader::load_from_str(text).map_err(|e| YamlProblem::Parse(e.to_string()))?;
    let root = match docs.as_slice() {
        [] => return Ok(None),
        [root] => root,
        _ => {
            return Err(YamlProblem::Parse(
                "expected a single document in the stream".to_owned(),
            ))
        }
    };
    let root = match root {
        Yaml::Null => return Ok(None),
        Yaml::Hash(root) => root,
        _ => {
            return Err(YamlProblem::Invalid(
                "settings.yaml must contain a YAML mapping".to_owned(),
            ))
        }
    };
    let server = match root.get(&Yaml::String("server".to_owned())) {
        None | Some(Yaml::Null) => return Ok(None),
        Some(Yaml::Hash(server)) => server,
        Some(_) => return Err(YamlProblem::Invalid("server must be a mapping".to_owned())),
    };
    match server.get(&Yaml::String("access_key".to_owned())) {
        None | Some(Yaml::Null) => Ok(None),
        Some(Yaml::String(key)) if YAML11_BOOLS.contains(&key.to_lowercase().as_str()) => {
            Err(YamlProblem::Invalid(format!(
                "server.access_key {key:?} is a boolean in YAML 1.1; choose another key"
            )))
        }
        Some(Yaml::String(key)) => Ok(Some(key.clone()).filter(|k| !k.is_empty())),
        Some(_) => Err(YamlProblem::Invalid(
            "server.access_key must be a string".to_owned(),
        )),
    }
}
