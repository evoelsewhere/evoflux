//! How the shell launches `evoflux-server serve` (Phase 0 Task 12).
//!
//! The Rust gateway sits in front of the Python sidecar: it starts Python from
//! the same sidecar root and prints the shell's handshake only after Python
//! printed its own. These helpers have no Tauri dependency so
//! `tests/sidecar_gateway.rs` can include this file directly.

use anyhow::{anyhow, Result};
use std::ffi::OsString;
use std::path::{Path, PathBuf};

/// Placed by `scripts/build_sidecar.py` at the sidecar root, next to `python/`.
#[cfg(windows)]
pub const GATEWAY_BIN_NAME: &str = "evoflux-server.exe";
#[cfg(not(windows))]
pub const GATEWAY_BIN_NAME: &str = "evoflux-server";

/// Python's handshake budget on retry attempts. The shell gives a retry 45 s
/// (`SIDECAR_RETRY_HANDSHAKE_TIMEOUT`), so the gateway must give up on Python
/// first and exit with the Python log tail instead of being timed out blind.
/// The first attempt keeps the gateway's 85 s default under the shell's 90 s.
const RETRY_PYTHON_WAIT_S: &str = "40";

pub fn resolve_gateway_bin(sidecar_root: &Path) -> Result<PathBuf> {
    let candidate = sidecar_root.join(GATEWAY_BIN_NAME);
    if candidate.is_file() {
        Ok(candidate)
    } else {
        Err(anyhow!(
            "sidecar bundle missing the gateway binary {GATEWAY_BIN_NAME} at {}",
            candidate.display()
        ))
    }
}

/// Whether `EVOFLUX_RUST_FORWARD` opts out of Rust-forward: `0`, `false` or
/// `off` (any case). The server only turns forwarding on for `1`, `true` or
/// `on`, so an opted-out value leaves it Python-only too.
pub fn rust_forward_opted_out(value: Option<&str>) -> bool {
    value.is_some_and(|raw| {
        let raw = raw.trim();
        raw == "0" || raw.eq_ignore_ascii_case("false") || raw.eq_ignore_ascii_case("off")
    })
}

/// `evoflux-server serve` takes the flags Python's `serve` took, plus
/// `--rust-forward` unless `rust_forward_env` (the shell's
/// `EVOFLUX_RUST_FORWARD`) opts out.
pub fn gateway_args(
    generate_token: bool,
    parent_pid: u32,
    rust_forward_env: Option<&str>,
) -> Vec<String> {
    let mut args: Vec<String> = ["serve", "--host", "127.0.0.1", "--port", "0", "--handshake"]
        .into_iter()
        .map(String::from)
        .collect();
    if generate_token {
        args.push("--generate-token".to_string());
    }
    args.push("--parent-pid".to_string());
    args.push(parent_pid.to_string());
    if !rust_forward_opted_out(rust_forward_env) {
        args.push("--rust-forward".to_string());
    }
    args
}

/// `attempt` is 1-based, as in `start_bundled_backend_with_retry`.
pub fn gateway_env(sidecar_root: &Path, attempt: u32) -> Vec<(&'static str, OsString)> {
    let mut env = vec![("EVOFLUX_SIDECAR_ROOT", sidecar_root.as_os_str().to_owned())];
    if attempt > 1 {
        env.push((
            "EVOFLUX_GATEWAY_PYTHON_WAIT_S",
            OsString::from(RETRY_PYTHON_WAIT_S),
        ));
    }
    env
}
