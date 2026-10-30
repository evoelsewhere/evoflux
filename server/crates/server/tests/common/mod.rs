//! Shared helpers: the binary, a Python interpreter, the fake sidecar and a raw HTTP client.
#![allow(
    dead_code,
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    clippy::indexing_slicing,
    clippy::disallowed_methods
)]

use std::path::{Path, PathBuf};
use std::process::Stdio;
use tempfile::TempDir;
use tokio::io::{AsyncReadExt, AsyncWriteExt};

pub fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../..")
}

pub fn tests_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests")
}

pub fn fake_upstream() -> PathBuf {
    repo_root().join("contract-tests/gateway/fake_upstream.py")
}

pub fn app_version() -> String {
    std::fs::read_to_string(repo_root().join("app/version.txt"))
        .unwrap()
        .trim()
        .to_owned()
}

/// `EVOFLUX_TEST_PYTHON`, else the repository venv, else `python3`/`python` on PATH.
pub fn python() -> PathBuf {
    if let Some(path) = std::env::var_os("EVOFLUX_TEST_PYTHON") {
        return PathBuf::from(path);
    }
    let venv = if cfg!(windows) {
        repo_root().join(".venv/Scripts/python.exe")
    } else {
        repo_root().join(".venv/bin/python")
    };
    if venv.is_file() {
        return venv;
    }
    PathBuf::from(if cfg!(windows) { "python" } else { "python3" })
}

/// `evoflux-server serve --host 127.0.0.1 --port 0 --handshake <args>` in
/// front of the Python script `entry`, with its directories under `home`.
pub fn spawn_server(
    home: &TempDir,
    entry: &Path,
    args: &[&str],
    env: &[(&str, &str)],
) -> tokio::process::Child {
    let root = home.path();
    let cwd = root.join("cwd");
    std::fs::create_dir_all(&cwd).unwrap();
    let mut command = tokio::process::Command::new(env!("CARGO_BIN_EXE_evoflux-server"));
    command
        .args(["serve", "--host", "127.0.0.1", "--port", "0", "--handshake"])
        .args(args)
        .current_dir(&cwd)
        .env_remove("EVOFLUX_DESKTOP_TOKEN")
        .env_remove("EVOFLUX_ACCESS_KEY")
        .env_remove("EVOFLUX_SIDECAR_ROOT")
        .env_remove("EVOFLUX_TSNET_BIN")
        .env("HOME", root.join("home"))
        .env("USERPROFILE", root.join("home"))
        .env("APP_ENV", "production")
        .env("EVOFLUX_DATA_DIR", root.join("data"))
        .env("EVOFLUX_CONFIG_DIR", root.join("config"))
        .env("EVOFLUX_STATE_DIR", root.join("state"))
        .env("EVOFLUX_GATEWAY_PYTHON_BIN", python())
        .env("EVOFLUX_GATEWAY_SITE_PACKAGES", entry.parent().unwrap())
        .env("EVOFLUX_GATEWAY_CLI_ENTRY", entry)
        .envs(env.iter().copied())
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true);
    command.spawn().unwrap()
}

/// Stop the server the way the desktop shell's crash path would: hard.
pub async fn stop(mut server: tokio::process::Child) {
    let _ = server.kill().await;
}

/// A minimal HTTP/1.1 GET with `Connection: close`: `(status, body)`.
pub async fn http_get(port: u64, path: &str, headers: &[(&str, &str)]) -> (u16, String) {
    let mut stream = tokio::net::TcpStream::connect(("127.0.0.1", port as u16))
        .await
        .unwrap();
    let mut request = format!("GET {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n");
    for (name, value) in headers {
        request.push_str(&format!("{name}: {value}\r\n"));
    }
    request.push_str("\r\n");
    stream.write_all(request.as_bytes()).await.unwrap();
    let mut raw = Vec::new();
    stream.read_to_end(&mut raw).await.unwrap();
    let text = String::from_utf8_lossy(&raw).into_owned();
    let status = text
        .split(' ')
        .nth(1)
        .and_then(|code| code.parse().ok())
        .unwrap_or_else(|| panic!("bad response: {text:?}"));
    let body = text
        .split_once("\r\n\r\n")
        .map(|(_, body)| body.to_owned())
        .unwrap_or_default();
    (status, body)
}
