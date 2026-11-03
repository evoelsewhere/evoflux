//! Port of app/agent/sandbox_config.py: legacy-tolerant file validation,
//! non-creating reads and atomic writes serialized by sandbox.yaml path.

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, LazyLock, Mutex};

use evoflux_area_commands::support::py_strip;
use evoflux_shared_yaml::{self as yaml, DumpOpts};
use serde_json::{json, Map, Value};
use tokio::io::AsyncWriteExt;

use crate::body;
use crate::models;
use crate::sections::Result;
use crate::settings_service::{internal, invalid};

static LOCKS: LazyLock<Mutex<HashMap<PathBuf, Arc<tokio::sync::Mutex<()>>>>> =
    LazyLock::new(|| Mutex::new(HashMap::new()));
static NEXT_TEMP: AtomicU64 = AtomicU64::new(0);

fn lock_for(path: &Path) -> Arc<tokio::sync::Mutex<()>> {
    let key = std::path::absolute(path).unwrap_or_else(|_| path.to_path_buf());
    LOCKS
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
        .entry(key)
        .or_default()
        .clone()
}

pub(crate) async fn load(path: &Path) -> Result<Value> {
    let raw = match tokio::fs::read(path).await {
        Ok(bytes) => {
            let text = String::from_utf8(bytes).map_err(|e| invalid(e.to_string()))?;
            let text = text.strip_prefix('\u{feff}').unwrap_or(&text);
            yaml::load(text)
                .map_err(|e| invalid(format!("Invalid YAML in {}: {e}", path.display())))?
                .to_json()
        }
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => json!({}),
        Err(_) => return Err(internal()),
    };
    // `yaml.safe_load(...) or {}`: empty scalars and collections use defaults.
    let raw = match &raw {
        Value::Null => json!({}),
        Value::Bool(false) => json!({}),
        Value::Number(n) if n.as_f64() == Some(0.0) => json!({}),
        Value::String(s) if s.is_empty() => json!({}),
        Value::Array(v) if v.is_empty() => json!({}),
        _ => raw,
    };
    let Value::Object(mut object) = raw else {
        return Err(invalid(format!(
            "{}: expected a YAML mapping at top level",
            path.display()
        )));
    };
    object.remove("native_process_isolation");
    object.remove("allow_network");
    let mut validated = body::validate(&models::sandbox_file(), &object, &[])
        .map_err(|errors| invalid(validation_error(&errors)))?;
    clean_patterns(&mut validated, false);
    Ok(Value::Object(validated))
}

fn clean_patterns(body: &mut Map<String, Value>, trim: bool) {
    if let Some(Value::Array(patterns)) = body.get_mut("denied_patterns") {
        patterns.retain(|p| p.as_str().is_some_and(|s| !py_strip(s).is_empty()));
        if trim {
            for pattern in patterns {
                if let Value::String(text) = pattern {
                    *text = py_strip(text).to_owned();
                }
            }
        }
    }
}

pub(crate) async fn save(path: &Path, mut body: Map<String, Value>) -> Result<Value> {
    clean_patterns(&mut body, true);
    let body = Value::Object(body);
    let text = yaml::dump(
        &yaml::Value::from_json(&body),
        DumpOpts {
            sort_keys: false,
            allow_unicode: false,
        },
    );
    // Python's os.fdopen(..., "w", encoding="utf-8") uses native newlines.
    #[cfg(windows)]
    let text = text.replace('\n', "\r\n");
    let _guard = lock_for(path).lock_owned().await;
    write_atomic(path, &text).await.map_err(|_| internal())?;
    Ok(body)
}

async fn write_atomic(path: &Path, text: &str) -> std::io::Result<()> {
    let parent = path.parent().unwrap_or_else(|| Path::new("."));
    tokio::fs::create_dir_all(parent).await?;
    let name = path.file_name().unwrap_or_default().to_string_lossy();
    let temp = parent.join(format!(
        ".{name}.{}.{}.tmp",
        std::process::id(),
        NEXT_TEMP.fetch_add(1, Ordering::Relaxed)
    ));
    let mut options = tokio::fs::OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    options.mode(0o600);
    let mut file = options.open(&temp).await?;
    let result = async {
        file.write_all(text.as_bytes()).await?;
        file.flush().await?;
        file.sync_all().await
    }
    .await;
    drop(file);
    let result = match result {
        Ok(()) => tokio::fs::rename(&temp, path).await,
        error => error,
    };
    if result.is_err() {
        let _ = tokio::fs::remove_file(&temp).await;
    }
    result
}

// Pydantic's human-readable file errors differ from FastAPI's JSON detail list.
// Keep the model, field, message, type and input; NOTES records the repr limits.
fn validation_error(errors: &[Value]) -> String {
    let count = errors.len();
    let mut out = format!(
        "{count} validation error{} for SandboxFileConfig",
        if count == 1 { "" } else { "s" }
    );
    for error in errors {
        let loc = error
            .get("loc")
            .and_then(Value::as_array)
            .map(|parts| {
                parts
                    .iter()
                    .map(|v| {
                        v.as_str()
                            .map(str::to_owned)
                            .unwrap_or_else(|| v.to_string())
                    })
                    .collect::<Vec<_>>()
                    .join(".")
            })
            .unwrap_or_default();
        let msg = error.get("msg").and_then(Value::as_str).unwrap_or_default();
        let kind = error
            .get("type")
            .and_then(Value::as_str)
            .unwrap_or_default();
        let input = error.get("input").unwrap_or(&Value::Null);
        let (repr, ty) = match input {
            Value::Null => ("None".into(), "NoneType"),
            Value::Bool(b) => (if *b { "True" } else { "False" }.into(), "bool"),
            Value::String(s) => (
                format!(
                    "'{}'",
                    s.replace('\\', "\\\\")
                        .replace('\'', "\\'")
                        .replace('\n', "\\n")
                        .replace('\r', "\\r")
                        .replace('\t', "\\t")
                ),
                "str",
            ),
            Value::Number(n) => (n.to_string(), if n.is_f64() { "float" } else { "int" }),
            Value::Array(_) => (input.to_string(), "list"),
            Value::Object(_) => (input.to_string(), "dict"),
        };
        out.push_str(&format!("\n{loc}\n  {msg} [type={kind}, input_value={repr}, input_type={ty}]\n    For further information visit https://errors.pydantic.dev/2.13/v/{kind}"));
    }
    out
}

#[cfg(test)]
mod tests {
    use super::lock_for;
    use std::path::Path;
    use std::sync::Arc;

    #[test]
    fn sandbox_writers_share_one_lock_per_file() {
        let first = lock_for(Path::new("sandbox-one.yaml"));
        let same = lock_for(Path::new("sandbox-one.yaml"));
        let other = lock_for(Path::new("sandbox-two.yaml"));
        assert!(Arc::ptr_eq(&first, &same));
        assert!(!Arc::ptr_eq(&first, &other));
    }
}
