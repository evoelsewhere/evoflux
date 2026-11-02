//! Port of `app/core/runtime_settings.py`: the `settings.yaml` schema, its
//! tolerant load (`load_runtime_settings_report`) and its whole-file save
//! (`save_runtime_settings`), shared by every unit that reads or writes the
//! file (settings-providers, imports, webbridge, conductor).
//!
//! Validation follows pydantic v2 lax mode with python input: `"3"` and
//! `3.0` are ints, `"yes"` is a bool, `2.5` for an int is an error, and the
//! errors carry pydantic's `type`, `loc`, `msg` and `ctx`
//! ([`Section::validate`] gives them to routes for their 422 bodies).
//!
//! Every read-modify-write goes through [`modify`], which holds one lock per
//! path in this process across the load and the save. Writers in other
//! processes (Python before its cutover) can still interleave: the atomic
//! rename keeps the file whole, not merged.
//!
//! Known differences: the `YAML parse error` text after the prefix is not
//! PyYAML's; an undecodable (non-UTF-8) file is an I/O error rather than
//! Python's `UnicodeDecodeError` text; the "ignored fields" warning is not
//! logged; integers beyond `i128` are refused by the YAML loader.

#![forbid(unsafe_code)]

mod sections;
mod url;
mod validate;

use std::collections::HashMap;
use std::io::Write as _;
use std::path::{Path, PathBuf};
use std::sync::{Arc, LazyLock, Mutex};

use evoflux_shared_yaml::{DumpOpts, Value};

pub use sections::*;
pub use validate::{Loc, ValidationError};

/// One hand-edited value that failed validation and was dropped.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct IgnoredSetting {
    /// Dotted path into `settings.yaml`, e.g. `context.summary_trigger_tokens`.
    pub field: String,
    /// Why it was rejected, in the validator's own words.
    pub message: String,
}

/// Why `settings.yaml` could not be loaded or saved. The first two are the
/// `ValueError`s Python raises (routes answer 422, or 500 where Python does).
#[derive(Debug, thiserror::Error)]
pub enum SettingsError {
    #[error("settings.yaml YAML parse error: {0}")]
    Parse(String),
    #[error("settings.yaml must contain a YAML mapping.")]
    NotAMapping,
    #[error("settings.yaml I/O error: {0}")]
    Io(#[from] std::io::Error),
}

/// Give up after this many prune-and-revalidate rounds (`_MAX_PRUNE_ROUNDS`).
const MAX_PRUNE_ROUNDS: usize = 8;

/// `runtime_settings_path()`: `<EVOFLUX_CONFIG_DIR>/settings.yaml`.
pub fn settings_path(config_dir: &Path) -> PathBuf {
    config_dir.join("settings.yaml")
}

/// Python's truthiness of what `yaml.safe_load` returned (`... or {}`).
fn is_falsy(value: &Value) -> bool {
    match value {
        Value::Null => true,
        Value::Bool(b) => !b,
        Value::Int(i) => *i == 0,
        Value::Float(f) => *f == 0.0,
        Value::Str(s) => s.is_empty(),
        Value::Seq(items) => items.is_empty(),
        Value::Map(map) => map.is_empty(),
        Value::Timestamp(_) => false,
    }
}

/// `_drop_path`: remove the value at `loc` from `raw`; true if one was removed.
fn drop_path(raw: &mut Value, loc: &[Loc]) -> bool {
    let Some((last, parents)) = loc.split_last() else {
        return false;
    };
    let mut node = raw;
    for part in parents {
        let Loc::Key(key) = part else {
            return false;
        };
        let Value::Map(map) = node else {
            return false;
        };
        let Some(child) = map.get_value_mut(key) else {
            return false;
        };
        node = child;
    }
    match (node, last) {
        (Value::Map(map), Loc::Key(key)) => map.remove_value(key).is_some(),
        _ => false,
    }
}

/// `load_runtime_settings_report` over already-read text: the settings
/// with every invalid value dropped, and what was dropped.
pub fn parse_report(text: &str) -> Result<(RuntimeSettings, Vec<IgnoredSetting>), SettingsError> {
    let text = text.strip_prefix('\u{FEFF}').unwrap_or(text);
    let raw = evoflux_shared_yaml::load(text).map_err(|e| SettingsError::Parse(e.to_string()))?;
    let mut raw = if is_falsy(&raw) {
        Value::Map(evoflux_shared_yaml::Mapping::new())
    } else {
        raw
    };
    if !matches!(raw, Value::Map(_)) {
        return Err(SettingsError::NotAMapping);
    }
    let mut ignored = Vec::new();
    for _ in 0..MAX_PRUNE_ROUNDS {
        match RuntimeSettings::validate(&raw) {
            Ok(loaded) => return Ok((loaded, ignored)),
            Err(errors) => {
                let mut dropped_any = false;
                for error in errors {
                    if error.loc.is_empty() || !drop_path(&mut raw, &error.loc) {
                        continue;
                    }
                    dropped_any = true;
                    ignored.push(IgnoredSetting {
                        field: error.dotted_loc(),
                        message: error.msg,
                    });
                }
                if !dropped_any {
                    break;
                }
            }
        }
    }
    // Nothing could be pruned into a valid shape: the whole file is unusable.
    Ok((RuntimeSettings::default(), ignored))
}

/// `load_runtime_settings_report(path)`: defaults when the file is missing.
pub async fn load_report(
    path: &Path,
) -> Result<(RuntimeSettings, Vec<IgnoredSetting>), SettingsError> {
    match tokio::fs::read(path).await {
        Ok(bytes) => {
            let text = String::from_utf8(bytes)
                .map_err(|e| std::io::Error::new(std::io::ErrorKind::InvalidData, e))?;
            parse_report(&text)
        }
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
            Ok((RuntimeSettings::default(), Vec::new()))
        }
        Err(e) => Err(e.into()),
    }
}

/// `load_runtime_settings(path)`.
pub async fn load(path: &Path) -> Result<RuntimeSettings, SettingsError> {
    Ok(load_report(path).await?.0)
}

impl RuntimeSettings {
    /// The exact text `save_runtime_settings` writes:
    /// `yaml.safe_dump(model_dump(mode="json", exclude_none=True), sort_keys=False)`.
    pub fn to_yaml(&self) -> String {
        evoflux_shared_yaml::dump(&Value::Map(self.dump()), DumpOpts::default())
    }

    /// `save_runtime_settings(cfg, path)`: create the folder, write a
    /// temporary file next to the target (owner-only, like `mkstemp`), fsync,
    /// and rename it over the target. Callers that loaded the file first use
    /// [`modify`] so the lock covers the whole read-modify-write.
    pub async fn save(&self, path: &Path) -> Result<PathBuf, SettingsError> {
        let _guard = lock_for(path).lock_owned().await;
        self.save_unlocked(path).await
    }

    async fn save_unlocked(&self, path: &Path) -> Result<PathBuf, SettingsError> {
        let text = self.to_yaml();
        let target = path.to_path_buf();
        tokio::task::spawn_blocking(move || write_atomic(&target, text.as_bytes()))
            .await
            .map_err(|e| std::io::Error::other(e.to_string()))??;
        Ok(path.to_path_buf())
    }
}

fn write_atomic(target: &Path, bytes: &[u8]) -> std::io::Result<()> {
    let parent = match target.parent() {
        Some(p) if !p.as_os_str().is_empty() => p.to_path_buf(),
        _ => PathBuf::from("."),
    };
    std::fs::create_dir_all(&parent)?;
    let name = target
        .file_name()
        .map(|n| n.to_string_lossy().into_owned())
        .unwrap_or_default();
    let mut temp = tempfile::Builder::new()
        .prefix(&format!(".{name}."))
        .suffix(".tmp")
        .tempfile_in(&parent)?;
    temp.write_all(bytes)?;
    temp.flush()?;
    temp.as_file().sync_all()?;
    temp.persist(target).map_err(|e| e.error)?;
    Ok(())
}

static LOCKS: LazyLock<Mutex<HashMap<PathBuf, Arc<tokio::sync::Mutex<()>>>>> =
    LazyLock::new(|| Mutex::new(HashMap::new()));

/// The process-wide lock of one settings file.
fn lock_for(path: &Path) -> Arc<tokio::sync::Mutex<()>> {
    let key = std::path::absolute(path).unwrap_or_else(|_| path.to_path_buf());
    let mut locks = LOCKS
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    locks.entry(key).or_default().clone()
}

/// Load, change and save `settings.yaml` under its lock, the way every
/// Python writer does it (`load_runtime_settings`, mutate,
/// `save_runtime_settings`). When `change` fails nothing is written.
pub async fn modify<T, E>(
    path: &Path,
    change: impl FnOnce(&mut RuntimeSettings) -> Result<T, E>,
) -> Result<T, E>
where
    E: From<SettingsError>,
{
    let _guard = lock_for(path).lock_owned().await;
    let mut settings = load(path).await?;
    let out = change(&mut settings)?;
    settings.save_unlocked(path).await?;
    Ok(out)
}

#[cfg(test)]
#[allow(clippy::unwrap_used)]
mod tests {
    use super::*;

    #[test]
    fn falsy_documents_are_empty_settings() {
        for text in ["", "0\n", "false\n", "[]\n", "''\n", "~\n"] {
            assert_eq!(
                parse_report(text).unwrap().0,
                RuntimeSettings::default(),
                "{text:?}"
            );
        }
        assert!(matches!(
            parse_report("[1]\n"),
            Err(SettingsError::NotAMapping)
        ));
        assert!(matches!(
            parse_report("a: [1\n"),
            Err(SettingsError::Parse(_))
        ));
    }

    #[test]
    fn a_bom_is_skipped() {
        let (settings, _) = parse_report("\u{FEFF}git:\n  prune_on_fetch: false\n").unwrap();
        assert!(!settings.git.prune_on_fetch);
    }

    #[tokio::test]
    async fn modify_round_trips_and_failed_changes_write_nothing() {
        let dir = tempfile::tempdir().unwrap();
        let path = settings_path(&dir.path().join("cfg"));
        assert_eq!(load(&path).await.unwrap(), RuntimeSettings::default());
        modify(&path, |s| {
            s.follow_up.delivery = "steer";
            Ok::<_, SettingsError>(())
        })
        .await
        .unwrap();
        assert_eq!(load(&path).await.unwrap().follow_up.delivery, "steer");
        let before = tokio::fs::read(&path).await.unwrap();
        let failed: Result<(), SettingsError> = modify(&path, |s| {
            s.follow_up.delivery = "queue";
            Err(SettingsError::NotAMapping)
        })
        .await;
        assert!(failed.is_err());
        assert_eq!(tokio::fs::read(&path).await.unwrap(), before);
        let leftovers = std::fs::read_dir(path.parent().unwrap()).unwrap().count();
        assert_eq!(leftovers, 1, "only settings.yaml remains");
    }

    #[tokio::test]
    async fn concurrent_modifies_do_not_lose_updates() {
        let dir = tempfile::tempdir().unwrap();
        let path = Arc::new(settings_path(dir.path()));
        let mut tasks = Vec::new();
        for i in 0..16 {
            let path = path.clone();
            tasks.push(tokio::spawn(async move {
                modify(&path, |s| {
                    s.set_provider(&format!("p{i}"), ProviderUiSettings::default());
                    Ok::<_, SettingsError>(())
                })
                .await
                .unwrap();
            }));
        }
        for task in tasks {
            task.await.unwrap();
        }
        assert_eq!(load(&path).await.unwrap().providers.len(), 16);
    }
}
