#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    clippy::disallowed_methods
)]

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::process::Command;

use evoflux_core::config::Settings;
use evoflux_core::paths::Paths;

fn vars(pairs: &[(&str, &str)]) -> HashMap<String, String> {
    pairs
        .iter()
        .map(|(k, v)| ((*k).to_owned(), (*v).to_owned()))
        .collect()
}

#[test]
fn defaults_are_production_with_documented_values() {
    let home = Path::new("/home/u");
    let settings = Settings::from_vars(&vars(&[]), Some(home), Path::new("/cwd"))
        .unwrap_or_else(|e| panic!("{e}"));
    assert_eq!(settings.app_env, "production");
    assert_eq!(settings.log_level, "INFO");
    assert_eq!(settings.api_host, "0.0.0.0");
    assert_eq!(settings.api_port, 4082);
    assert_eq!(
        settings.data_dir,
        home.join(".local").join("share").join("evoflux")
    );
}

#[test]
fn invalid_port_is_a_config_error() {
    let err = Settings::from_vars(&vars(&[("API_PORT", "nope")]), None, Path::new("/cwd"));
    assert!(err.is_err());
    let err = Settings::from_vars(&vars(&[("API_PORT", "70000")]), None, Path::new("/cwd"));
    assert!(err.is_err());
}

#[test]
fn env_names_match_case_insensitively_like_pydantic_settings() {
    let settings = Settings::from_vars(&vars(&[("api_port", "9000")]), None, Path::new("/cwd"))
        .unwrap_or_else(|e| panic!("{e}"));
    assert_eq!(settings.api_port, 9000);
}

#[test]
fn paths_derive_db_and_log_dir() {
    let settings = Settings::from_vars(
        &vars(&[
            ("EVOFLUX_DATA_DIR", "/d"),
            ("EVOFLUX_STATE_DIR", "/s"),
            ("EVOFLUX_CONFIG_DIR", "/c"),
        ]),
        None,
        Path::new("/cwd"),
    )
    .unwrap_or_else(|e| panic!("{e}"));
    let paths = Paths::resolve(&settings);
    assert_eq!(paths.db_file, PathBuf::from("/d").join("evoflux.db"));
    assert_eq!(paths.log_dir, PathBuf::from("/s").join("logs").join("app"));
    assert_eq!(paths.config_dir, PathBuf::from("/c"));
}

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..")
}

/// Run Python's `Settings` in an isolated directory and return its resolved roots.
fn python_paths(env: &[(&str, &str)], home: &Path, cwd: &Path) -> Option<Vec<String>> {
    let mut cmd = Command::new("uv");
    cmd.args(["run", "--project"])
        .arg(repo_root())
        .args(["python", "-c"])
        .arg(
            "from app.core.config import settings as s; \
             print(s.EVOFLUX_DATA_DIR); print(s.EVOFLUX_CONFIG_DIR); \
             print(s.EVOFLUX_STATE_DIR); print(s.APP_ENV); print(s.LOG_LEVEL); \
             print(s.API_HOST); print(s.API_PORT); print(s.DATABASE_URL.get_secret_value())",
        )
        .current_dir(cwd)
        .env("PYTHONPATH", repo_root())
        .env("HOME", home)
        .env("USERPROFILE", home);
    for key in [
        "APP_ENV",
        "EVOFLUX_DATA_DIR",
        "EVOFLUX_CONFIG_DIR",
        "EVOFLUX_STATE_DIR",
        "LOG_LEVEL",
        "API_HOST",
        "API_PORT",
        "DATABASE_URL",
    ] {
        cmd.env_remove(key);
    }
    for (k, v) in env.iter().filter(|(k, _)| !k.ends_with("_DOTENV")) {
        cmd.env(k, v);
    }
    let output = match cmd.output() {
        Ok(o) => o,
        Err(_) => return None,
    };
    assert!(
        output.status.success(),
        "python failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    Some(
        String::from_utf8_lossy(&output.stdout)
            .lines()
            .map(str::to_owned)
            .collect(),
    )
}

fn norm(p: &Path) -> String {
    p.to_string_lossy().replace(std::path::MAIN_SEPARATOR, "/")
}

#[test]
fn paths_match_python() {
    let probe = Command::new("uv").arg("--version").output();
    if probe.is_err() {
        assert!(
            std::env::var_os("CI").is_none(),
            "uv is required in the gate job"
        );
        eprintln!("skipping paths_match_python: uv not found");
        return;
    }
    let combos: Vec<Vec<(&str, &str)>> = vec![
        vec![],
        vec![("APP_ENV", "development")],
        vec![
            ("EVOFLUX_DATA_DIR", "/x/data"),
            ("EVOFLUX_STATE_DIR", "/x/state"),
            ("LOG_LEVEL", "DEBUG"),
        ],
        vec![
            ("APP_ENV", "development"),
            ("EVOFLUX_CONFIG_DIR", "/x/cfg"),
            ("API_HOST", "127.0.0.1"),
            ("API_PORT", "5001"),
        ],
    ];
    for combo in combos {
        let tmp = tempdir();
        let home = tmp.join("home");
        let cwd = tmp.join("cwd");
        std::fs::create_dir_all(&home).unwrap_or_else(|e| panic!("{e}"));
        std::fs::create_dir_all(&cwd).unwrap_or_else(|e| panic!("{e}"));
        write_dotenv(&home, &cwd, &combo);
        let Some(py) = python_paths(&combo, &home, &cwd) else {
            return;
        };
        let map: HashMap<String, String> = combo
            .iter()
            .map(|(k, v)| ((*k).to_owned(), (*v).to_owned()))
            .collect();
        let settings = Settings::from_vars_and_dotenv(&map, Some(home.as_path()), &cwd)
            .unwrap_or_else(|e| panic!("{e}"));
        let paths = Paths::resolve(&settings);
        let rust = vec![
            norm(&settings.data_dir),
            norm(&settings.config_dir),
            norm(&settings.state_dir),
            settings.app_env.clone(),
            settings.log_level.clone(),
            settings.api_host.clone(),
            settings.api_port.to_string(),
        ];
        let py_norm: Vec<String> = py
            .iter()
            .take(7)
            .map(|s| s.replace(std::path::MAIN_SEPARATOR, "/"))
            .collect();
        assert_eq!(rust, py_norm, "combo {combo:?}");
        let db_url = py
            .get(7)
            .cloned()
            .unwrap_or_default()
            .replace(std::path::MAIN_SEPARATOR, "/");
        assert!(
            db_url.ends_with(&norm(&paths.db_file)),
            "{db_url} vs {:?}",
            paths.db_file
        );
    }
}

fn tempdir() -> PathBuf {
    let dir = std::env::temp_dir().join(format!(
        "evoflux-core-paths-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_nanos())
            .unwrap_or(0)
    ));
    let _ = std::fs::create_dir_all(&dir);
    dir
}

/// Materialise `HOME_DOTENV` / `PROJECT_DOTENV` pseudo-keys as `.env` files.
fn write_dotenv(home: &Path, cwd: &Path, combo: &[(&str, &str)]) {
    for (key, value) in combo {
        let path = match *key {
            "HOME_DOTENV" => home.join(".config").join("evoflux").join(".env"),
            "PROJECT_DOTENV" => cwd.join(".env"),
            _ => continue,
        };
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(path, value).unwrap();
    }
}

#[test]
fn dotenv_precedence_is_env_then_home_then_project() {
    let tmp = tempdir();
    let (home, cwd) = (tmp.join("home"), tmp.join("cwd"));
    write_dotenv(
        &home,
        &cwd,
        &[
            (
                "HOME_DOTENV",
                "EVOFLUX_DATA_DIR=/h
API_PORT=1
LOG_LEVEL=warn
",
            ),
            (
                "PROJECT_DOTENV",
                "EVOFLUX_DATA_DIR=/p
API_PORT=2
API_HOST=\"1.2.3.4\"
",
            ),
        ],
    );
    let env = vars(&[("API_PORT", "3")]);
    let s = Settings::from_vars_and_dotenv(&env, Some(home.as_path()), &cwd).unwrap();
    assert_eq!(s.api_port, 3);
    assert_eq!(s.data_dir, PathBuf::from("/h"));
    assert_eq!(s.log_level, "warn");
    assert_eq!(s.api_host, "1.2.3.4");
}

#[test]
fn ninja_api_key_is_optional_and_kept_secret() {
    let none = Settings::from_vars(&vars(&[]), None, Path::new("/cwd")).unwrap();
    assert!(none.ninja_api_key.is_none());

    let some = Settings::from_vars(
        &vars(&[("ninja_api_key", "sekret-123")]),
        None,
        Path::new("/cwd"),
    )
    .unwrap();
    assert_eq!(
        some.ninja_api_key.as_ref().map(|key| key.expose()),
        Some("sekret-123")
    );
    assert!(!format!("{some:?}").contains("sekret-123"));
    assert!(!format!("{:?}", some.ninja_api_key).contains("sekret-123"));
}

#[test]
fn an_empty_ninja_api_key_is_still_a_key_like_pydantic_secretstr() {
    let settings =
        Settings::from_vars(&vars(&[("NINJA_API_KEY", "")]), None, Path::new("/cwd")).unwrap();
    assert_eq!(
        settings.ninja_api_key.as_ref().map(|key| key.expose()),
        Some("")
    );
}
