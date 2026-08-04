//! Chrome/Edge Native Messaging discovery for the bundled WebBridge extension.
//!
//! The desktop backend binds an ephemeral loopback port. This module installs
//! the per-user native-host manifest and exposes that current endpoint to the
//! extension without copying a URL or handing it the all-powerful desktop
//! bearer token.

use anyhow::{anyhow, Context, Result};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::env;
use std::fs;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
#[cfg(windows)]
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};
use tauri::{AppHandle, Manager};

const HOST_NAME: &str = "com.evoflux.webbridge";
const HOST_BASENAME: &str = "evoflux-webbridge-host";
const CONNECTION_FILENAME: &str = "connection.json";
const EXTENSION_ID: &str = "lghglpnddenmebbhkfachafichhglafi";
const MAX_MESSAGE_BYTES: usize = 1024 * 1024;

#[derive(Debug, Serialize)]
struct NativeHostManifest {
    name: &'static str,
    description: &'static str,
    path: String,
    #[serde(rename = "type")]
    host_type: &'static str,
    allowed_origins: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NativeConnectionState {
    protocol_version: u8,
    base_url: String,
    discovery_token: String,
    app_pid: u32,
    updated_at_ms: u128,
}

#[derive(Debug, Deserialize)]
struct NativeRequest {
    #[serde(rename = "type")]
    request_type: String,
}

pub fn invoked_as_native_host() -> bool {
    env::args_os()
        .next()
        .and_then(|value| PathBuf::from(value).file_stem().map(|stem| stem.to_owned()))
        .and_then(|value| value.to_str().map(str::to_ascii_lowercase))
        .is_some_and(|name| name.contains(HOST_BASENAME))
}

pub fn run_native_host() -> Result<()> {
    let response = match read_native_request().and_then(discover) {
        Ok(state) => serde_json::json!({
            "ok": true,
            "protocol_version": state.protocol_version,
            "base_url": state.base_url,
            "discovery_token": state.discovery_token,
            "app_pid": state.app_pid,
        }),
        Err(error) => serde_json::json!({
            "ok": false,
            "error": format!("{error:#}"),
        }),
    };
    write_native_message(&response)
}

pub fn install(app: &AppHandle) -> Result<()> {
    let root = native_root(app)?;
    fs::create_dir_all(&root)
        .with_context(|| format!("create native messaging directory at {}", root.display()))?;
    let host_path = root.join(host_executable_name());
    install_host_executable(&host_path)?;
    let manifest = NativeHostManifest {
        name: HOST_NAME,
        description: "Discover the running EvoFlux Desktop WebBridge relay",
        path: host_path.to_string_lossy().into_owned(),
        host_type: "stdio",
        allowed_origins: vec![format!("chrome-extension://{EXTENSION_ID}/")],
    };
    let bytes = serde_json::to_vec_pretty(&manifest).context("encode native host manifest")?;
    install_browser_manifests(&root, &bytes)?;
    Ok(())
}

pub fn publish_connection(app: &AppHandle, base_url: &str, discovery_token: &str) -> Result<()> {
    validate_connection(base_url, discovery_token)?;
    let state = NativeConnectionState {
        protocol_version: 1,
        base_url: base_url.trim_end_matches('/').to_string(),
        discovery_token: discovery_token.to_string(),
        app_pid: std::process::id(),
        updated_at_ms: SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_millis(),
    };
    let root = native_root(app)?;
    fs::create_dir_all(&root)?;
    write_private_atomic(
        &root.join(CONNECTION_FILENAME),
        &serde_json::to_vec(&state).context("encode native connection state")?,
    )
}

pub fn clear_connection(app: &AppHandle) {
    let Ok(root) = native_root(app) else {
        return;
    };
    let path = root.join(CONNECTION_FILENAME);
    if let Err(error) = fs::remove_file(&path) {
        if error.kind() != std::io::ErrorKind::NotFound {
            log::warn!("could not clear WebBridge native discovery: {error}");
        }
    }
}

fn native_root(app: &AppHandle) -> Result<PathBuf> {
    Ok(app
        .path()
        .app_local_data_dir()
        .context("resolve app local data directory")?
        .join("native-messaging"))
}

fn host_executable_name() -> &'static str {
    if cfg!(windows) {
        "evoflux-webbridge-host.exe"
    } else {
        HOST_BASENAME
    }
}

fn install_host_executable(host_path: &Path) -> Result<()> {
    let current = env::current_exe().context("resolve EvoFlux executable")?;
    match fs::symlink_metadata(host_path) {
        Ok(_) => fs::remove_file(host_path)
            .with_context(|| format!("replace native host at {}", host_path.display()))?,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(error) => {
            return Err(error)
                .with_context(|| format!("inspect native host at {}", host_path.display()))
        }
    }
    #[cfg(unix)]
    {
        std::os::unix::fs::symlink(&current, host_path).with_context(|| {
            format!(
                "link native host {} -> {}",
                host_path.display(),
                current.display()
            )
        })?;
    }
    #[cfg(windows)]
    {
        if fs::hard_link(&current, host_path).is_err() {
            fs::copy(&current, host_path).with_context(|| {
                format!(
                    "copy native host {} -> {}",
                    current.display(),
                    host_path.display()
                )
            })?;
        }
    }
    Ok(())
}

#[cfg(target_os = "macos")]
fn install_browser_manifests(_root: &Path, bytes: &[u8]) -> Result<()> {
    let home = env::var_os("HOME").ok_or_else(|| anyhow!("HOME is not set"))?;
    let home = PathBuf::from(home);
    for relative in [
        "Library/Application Support/Google/Chrome/NativeMessagingHosts",
        "Library/Application Support/Microsoft Edge/NativeMessagingHosts",
        "Library/Application Support/Chromium/NativeMessagingHosts",
    ] {
        write_manifest(
            &home.join(relative).join(format!("{HOST_NAME}.json")),
            bytes,
        )?;
    }
    Ok(())
}

#[cfg(target_os = "linux")]
fn install_browser_manifests(_root: &Path, bytes: &[u8]) -> Result<()> {
    let config_home = env::var_os("XDG_CONFIG_HOME")
        .map(PathBuf::from)
        .or_else(|| env::var_os("HOME").map(|home| PathBuf::from(home).join(".config")))
        .ok_or_else(|| anyhow!("cannot resolve the user config directory"))?;
    for browser in ["google-chrome", "chromium", "microsoft-edge"] {
        write_manifest(
            &config_home
                .join(browser)
                .join("NativeMessagingHosts")
                .join(format!("{HOST_NAME}.json")),
            bytes,
        )?;
    }
    Ok(())
}

#[cfg(windows)]
fn install_browser_manifests(root: &Path, bytes: &[u8]) -> Result<()> {
    let manifest_path = root.join(format!("{HOST_NAME}.json"));
    write_manifest(&manifest_path, bytes)?;
    for vendor in ["Google\\Chrome", "Microsoft\\Edge"] {
        let key = format!("HKCU\\Software\\{vendor}\\NativeMessagingHosts\\{HOST_NAME}");
        let status = Command::new("reg.exe")
            .args(["ADD", &key, "/ve", "/t", "REG_SZ", "/d"])
            .arg(&manifest_path)
            .arg("/f")
            .status()
            .with_context(|| format!("register native messaging host in {key}"))?;
        if !status.success() {
            return Err(anyhow!("reg.exe failed while registering {key}: {status}"));
        }
    }
    Ok(())
}

fn write_manifest(path: &Path, bytes: &[u8]) -> Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    write_private_atomic(path, bytes)
}

fn write_private_atomic(path: &Path, bytes: &[u8]) -> Result<()> {
    let tmp = path.with_extension("tmp");
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        let mut file = fs::OpenOptions::new()
            .create(true)
            .truncate(true)
            .write(true)
            .mode(0o600)
            .open(&tmp)?;
        file.write_all(bytes)?;
        file.sync_all()?;
    }
    #[cfg(windows)]
    fs::write(&tmp, bytes)?;
    if path.exists() {
        fs::remove_file(path)?;
    }
    fs::rename(&tmp, path)?;
    Ok(())
}

fn read_native_request() -> Result<NativeRequest> {
    let value = read_native_message()?;
    serde_json::from_value(value).context("decode native messaging request")
}

fn read_native_message() -> Result<Value> {
    let mut length = [0_u8; 4];
    std::io::stdin()
        .read_exact(&mut length)
        .context("read native message length")?;
    let length = u32::from_le_bytes(length) as usize;
    if length == 0 || length > MAX_MESSAGE_BYTES {
        return Err(anyhow!("native message length is invalid"));
    }
    let mut payload = vec![0_u8; length];
    std::io::stdin()
        .read_exact(&mut payload)
        .context("read native message payload")?;
    serde_json::from_slice(&payload).context("decode native message JSON")
}

fn write_native_message(value: &Value) -> Result<()> {
    let payload = serde_json::to_vec(value).context("encode native message JSON")?;
    if payload.len() > MAX_MESSAGE_BYTES {
        return Err(anyhow!("native response is too large"));
    }
    let mut stdout = std::io::stdout().lock();
    stdout.write_all(&(payload.len() as u32).to_le_bytes())?;
    stdout.write_all(&payload)?;
    stdout.flush()?;
    Ok(())
}

fn discover(request: NativeRequest) -> Result<NativeConnectionState> {
    if request.request_type != "discover" {
        return Err(anyhow!("unsupported native messaging request"));
    }
    let executable = env::args_os()
        .next()
        .map(PathBuf::from)
        .ok_or_else(|| anyhow!("native host path is unavailable"))?;
    let state_path = executable
        .parent()
        .ok_or_else(|| anyhow!("native host directory is unavailable"))?
        .join(CONNECTION_FILENAME);
    let state: NativeConnectionState = serde_json::from_slice(
        &fs::read(&state_path)
            .with_context(|| format!("read connection state at {}", state_path.display()))?,
    )
    .context("decode connection state")?;
    if state.protocol_version != 1 {
        return Err(anyhow!("unsupported native discovery protocol"));
    }
    if !process_is_alive(state.app_pid) {
        return Err(anyhow!("EvoFlux Desktop is not running"));
    }
    validate_connection(&state.base_url, &state.discovery_token)?;
    Ok(state)
}

#[cfg(unix)]
fn process_is_alive(pid: u32) -> bool {
    use nix::errno::Errno;
    use nix::sys::signal::kill;
    use nix::unistd::Pid;

    if pid == 0 || pid > i32::MAX as u32 {
        return false;
    }
    matches!(
        kill(Pid::from_raw(pid as i32), None),
        Ok(()) | Err(Errno::EPERM)
    )
}

#[cfg(windows)]
fn process_is_alive(pid: u32) -> bool {
    use windows::Win32::Foundation::CloseHandle;
    use windows::Win32::System::Threading::{
        GetExitCodeProcess, OpenProcess, PROCESS_QUERY_LIMITED_INFORMATION,
    };

    if pid == 0 {
        return false;
    }
    unsafe {
        let Ok(handle) = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid) else {
            return false;
        };
        let mut exit_code = 0;
        const STILL_ACTIVE_EXIT_CODE: u32 = 259;
        let alive = GetExitCodeProcess(handle, &mut exit_code).is_ok()
            && exit_code == STILL_ACTIVE_EXIT_CODE;
        let _ = CloseHandle(handle);
        alive
    }
}

fn validate_connection(base_url: &str, discovery_token: &str) -> Result<()> {
    validate_base_url(base_url)?;
    if discovery_token.len() < 32 || discovery_token.len() > 256 {
        return Err(anyhow!("native discovery token is invalid"));
    }
    Ok(())
}

pub fn validate_base_url(base_url: &str) -> Result<()> {
    let parsed = url::Url::parse(base_url).context("parse native discovery URL")?;
    if parsed.scheme() != "http"
        || !matches!(parsed.host_str(), Some("127.0.0.1" | "localhost" | "::1"))
        || parsed.port().is_none()
    {
        return Err(anyhow!(
            "native discovery URL must be an explicit loopback HTTP port"
        ));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn validates_only_explicit_loopback_endpoints() {
        assert!(validate_connection("http://127.0.0.1:48211", &"x".repeat(32)).is_ok());
        assert!(validate_connection("https://127.0.0.1:48211", &"x".repeat(32)).is_err());
        assert!(validate_connection("http://example.com:48211", &"x".repeat(32)).is_err());
        assert!(validate_connection("http://127.0.0.1", &"x".repeat(32)).is_err());
    }

    #[test]
    fn native_host_name_matches_manifest_contract() {
        assert_eq!(HOST_NAME, "com.evoflux.webbridge");
        assert_eq!(EXTENSION_ID.len(), 32);
    }

    #[test]
    fn process_liveness_rejects_missing_pid() {
        assert!(process_is_alive(std::process::id()));
        assert!(!process_is_alive(0));
    }

    #[cfg(unix)]
    #[test]
    fn installer_repairs_a_dangling_host_symlink() {
        let root = env::temp_dir().join(format!(
            "evoflux-native-host-test-{}-{}",
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap_or_default()
                .as_nanos()
        ));
        fs::create_dir_all(&root).expect("create native host test directory");
        let host = root.join(HOST_BASENAME);
        std::os::unix::fs::symlink(root.join("missing-target"), &host)
            .expect("create dangling native host symlink");
        assert!(!host.exists());

        install_host_executable(&host).expect("repair dangling native host symlink");
        assert!(host.exists());

        fs::remove_file(&host).expect("remove native host test symlink");
        fs::remove_dir(&root).expect("remove native host test directory");
    }
}
