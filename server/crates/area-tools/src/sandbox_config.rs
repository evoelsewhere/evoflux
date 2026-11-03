//! Saved deny patterns from app/agent/sandbox_config.py and SandboxConfig.__init__.

use evoflux_shared_yaml::Value;
use std::path::PathBuf;

/// Read the saved policy for a new turn, off the runtime. The sandbox keeps its
/// built-in .env floor even when this returns no user patterns.
pub async fn load_denied_patterns(config_dir: PathBuf) -> Vec<String> {
    match evoflux_core::blocking::run(move || read_patterns(config_dir.join("sandbox.yaml"))).await
    {
        Ok(Ok(patterns)) => patterns,
        Ok(Err(error)) => {
            tracing::warn!(%error, "sandbox_config_load_failed");
            Vec::new()
        }
        Err(error) => {
            tracing::warn!(%error, "sandbox_config_load_failed");
            Vec::new()
        }
    }
}

#[allow(clippy::disallowed_methods)] // Called only on the bounded blocking pool.
fn read_patterns(path: PathBuf) -> Result<Vec<String>, String> {
    let text = match std::fs::read_to_string(path) {
        Ok(text) => text,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(Vec::new()),
        Err(error) => return Err(error.to_string()),
    };
    let value = evoflux_shared_yaml::load(&text).map_err(|error| error.to_string())?;
    // safe_load(...) or {} in Python accepts empty/null documents.
    let empty = match &value {
        Value::Null | Value::Bool(false) | Value::Int(0) => true,
        Value::Float(n) => *n == 0.0,
        Value::Str(s) => s.is_empty(),
        Value::Seq(s) => s.is_empty(),
        _ => false,
    };
    if empty {
        return Ok(Vec::new());
    }
    let map = value
        .as_map()
        .ok_or("expected a YAML mapping at top level")?;
    let Some(patterns) = map.get("denied_patterns") else {
        return Ok(Vec::new());
    };
    let Value::Seq(patterns) = patterns else {
        return Err("denied_patterns must be a list of strings".into());
    };
    let mut result = Vec::new();
    for pattern in patterns {
        let Value::Str(pattern) = pattern else {
            return Err("denied_patterns must be a list of strings".into());
        };
        if !pattern.trim().is_empty() {
            result.push(pattern.clone());
        }
    }
    Ok(result)
}

#[cfg(test)]
#[allow(clippy::unwrap_used, clippy::disallowed_methods)]
mod tests {
    use super::*;

    #[test]
    fn malformed_policy_is_an_error_but_missing_and_python_falsy_documents_are_defaults() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("sandbox.yaml");
        assert_eq!(read_patterns(path.clone()).unwrap(), Vec::<String>::new());
        for text in ["", "null", "false", "0", "0.0", "\"\"", "[]", "{}"] {
            std::fs::write(&path, text).unwrap();
            assert!(read_patterns(path.clone()).is_ok(), "{text}");
        }
        for text in [
            "true",
            "1.5",
            "['not a mapping']",
            "denied_patterns: [off]",
            "denied_patterns: [",
            "denied_patterns: ['**/secret*', 1]",
        ] {
            std::fs::write(&path, text).unwrap();
            assert!(read_patterns(path.clone()).is_err(), "{text}");
        }
        std::fs::remove_file(&path).unwrap();
        std::fs::create_dir(&path).unwrap();
        assert!(read_patterns(path).is_err());
    }

    #[tokio::test]
    async fn saved_patterns_use_yaml_11_and_drop_only_blank_strings() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("sandbox.yaml");
        std::fs::write(
            &path,
            "<<: &policy {denied_patterns: ['**/secret*', '', '  ', ' **/Key.PEM ']}\n",
        )
        .unwrap();
        assert_eq!(
            load_denied_patterns(dir.path().into()).await,
            ["**/secret*", " **/Key.PEM "]
        );
        // YAML 1.1 booleans are not strings, just as with PyYAML/Pydantic.
        std::fs::write(&path, "denied_patterns: [off]").unwrap();
        assert!(load_denied_patterns(dir.path().into()).await.is_empty());
    }

    #[tokio::test]
    async fn missing_empty_malformed_or_unreadable_policy_keeps_the_floor() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("sandbox.yaml");
        assert!(load_denied_patterns(dir.path().into()).await.is_empty());
        for text in [
            "",
            "null",
            "false",
            "0",
            "0.0",
            "\"\"",
            "{}",
            "[]",
            "worktree_location: repository",
            "denied_patterns: []",
            "[not a mapping]",
            "denied_patterns: [",
            "denied_patterns: null",
            "denied_patterns: '**/secret*'",
            "denied_patterns: ['**/secret*', 1]",
        ] {
            std::fs::write(&path, text).unwrap();
            let patterns = load_denied_patterns(dir.path().into()).await;
            assert!(patterns.is_empty(), "{text}");
            let sandbox = crate::sandbox::Sandbox::new(dir.path()).with_denied_patterns(patterns);
            assert!(sandbox.validate_path(".env").is_err());
        }
        std::fs::remove_file(&path).unwrap();
        std::fs::create_dir(&path).unwrap();
        assert!(load_denied_patterns(dir.path().into()).await.is_empty());
    }
}
