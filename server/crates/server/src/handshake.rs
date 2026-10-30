//! The desktop handshake line (`_emit_handshake` in `app/cli/commands/serve.py`,
//! parsed by `desktop/src-tauri/src/sidecar.rs`) and the token generator.

use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine;
use serde_json::Value;

pub const PREFIX: &str = "EVOFLUX_HANDSHAKE ";

/// The product version, `app/version.txt` (Python's `app.core.version.VERSION`).
pub fn version() -> &'static str {
    include_str!("../../../../app/version.txt").trim()
}

/// `secrets.token_urlsafe(32)`: 32 random bytes, URL-safe base64 without padding.
pub fn generate_token() -> Result<String, getrandom::Error> {
    let mut bytes = [0u8; 32];
    getrandom::fill(&mut bytes)?;
    Ok(URL_SAFE_NO_PAD.encode(bytes))
}

/// `EVOFLUX_HANDSHAKE {"port":…,"pid":…,"version":"…","token":"…"}`, in that
/// key order. The shell requires `token`, so it is `""` when auth is off.
pub fn line(port: u16, pid: u32, token: Option<&str>) -> String {
    let version = Value::from(version());
    let token = Value::from(token.unwrap_or_default());
    format!("{PREFIX}{{\"port\":{port},\"pid\":{pid},\"version\":{version},\"token\":{token}}}")
}
