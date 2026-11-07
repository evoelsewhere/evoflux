//! Built-in slash commands supplied by the front end.
//!
//! The engine answers `list_commands` for extensions and RPC clients, but the
//! built-in commands themselves (`/help`, `/model`, …) belong to whichever UI
//! hosts the engine — the transitional terminal UI today, the desktop app next.
//! The front end installs its list once at startup; until then the engine
//! reports no built-ins and reserves no names.

use std::sync::OnceLock;

/// The built-in command list a front end exposes.
#[derive(Clone, Copy)]
pub struct BuiltinCommands {
    /// Visible built-ins as `(name, description)`, names `/`-prefixed.
    pub entries: fn() -> Vec<(String, String)>,
    /// Every name the built-in dispatch answers to — canonical names and
    /// aliases, including hidden commands. Extensions may not shadow these.
    pub reserved_names: fn() -> Vec<String>,
}

static PROVIDER: OnceLock<BuiltinCommands> = OnceLock::new();

/// Install the front end's built-in commands. The first call wins; later calls
/// are ignored so a process cannot swap its command set mid-session.
pub fn install(commands: BuiltinCommands) {
    let _ = PROVIDER.set(commands);
}

/// Visible built-ins, or none when no front end has installed a list.
pub fn entries() -> Vec<(String, String)> {
    PROVIDER.get().map(|p| (p.entries)()).unwrap_or_default()
}

/// Reserved built-in names, or none when no front end has installed a list.
pub fn reserved_names() -> Vec<String> {
    PROVIDER
        .get()
        .map(|p| (p.reserved_names)())
        .unwrap_or_default()
}
