//! Computer App Control: an agent drives ONE desktop application window.
//!
//! This is deliberately not "computer use". The agent attaches to a single
//! top-level window and every capture and input is addressed to that window
//! (and the modal dialogs it opens), never to the desktop:
//!
//! - Capture uses `PrintWindow`, so the app can sit behind other windows.
//! - Input is posted to the window's own message queue (`PostMessage`) or
//!   performed through UI Automation patterns. The user's real cursor,
//!   keyboard focus and foreground window are never touched, which is also
//!   why some apps (UWP, games, raw-input apps) cannot be driven by
//!   coordinates and need `invoke` / `set_value` instead.
//!
//! The user watches through a picture-in-picture card in the web UI that
//! polls [`app_computer_frame`] and draws a virtual cursor from the
//! [`POINTER_EVENT`] events emitted here, and can revoke control with
//! [`app_computer_stop`].
//!
//! Ported from the Windows backend of `evo-computer-use` (window listing,
//! `PrintWindow` capture, UIA walking, key names); the background input path
//! is new because that project only injects global `SendInput`.
//!
//! macOS has its own backend (`mac.rs`) with the same contract, built on the
//! Accessibility API, window-server capture and events posted to the app's
//! process.

#[cfg(target_os = "macos")]
mod mac;
#[cfg(target_os = "windows")]
mod win;

/// The backend for this platform.
#[cfg(target_os = "macos")]
use mac as native;
#[cfg(target_os = "windows")]
use win as native;

use serde_json::{json, Value};

/// Tauri event carrying the agent's virtual pointer for the preview card.
pub const POINTER_EVENT: &str = "computer-app:pointer";

/// Longest edge of the screenshot handed to the agent, in pixels. Larger
/// windows are scaled down and coordinates are mapped back, so the agent only
/// ever sees one coordinate system: the screenshot's.
pub(crate) const SCREENSHOT_MAX_EDGE: u32 = 1568;

/// Processes the agent may never attach to: the shell, session and security
/// processes whose windows are the desktop itself rather than an app.
#[cfg(not(target_os = "macos"))]
const PROTECTED_PROCESS_NAMES: &[&str] = &[
    "explorer.exe",
    "csrss.exe",
    "winlogon.exe",
    "wininit.exe",
    "services.exe",
    "lsass.exe",
    "smss.exe",
    "dwm.exe",
    "logonui.exe",
    "consent.exe",
    "lockapp.exe",
    "searchhost.exe",
    "startmenuexperiencehost.exe",
    "shellexperiencehost.exe",
    "textinputhost.exe",
    "system",
];

/// The macOS counterparts, by executable name. System Settings is here
/// because it is where apps are granted Accessibility and Screen Recording
/// access — an agent must not be able to grant itself more.
#[cfg(target_os = "macos")]
const PROTECTED_PROCESS_NAMES: &[&str] = &[
    "finder",
    "dock",
    "windowserver",
    "loginwindow",
    "systemuiserver",
    "controlcenter",
    "notificationcenter",
    "spotlight",
    "securityagent",
    "coreautha",
    "screensaverengine",
    "windowmanager",
    "system settings",
    "system preferences",
    "keychain access",
    "passwords",
];

pub(crate) fn is_protected_process_name(identifier: &str) -> bool {
    let name = identifier
        .rsplit(['\\', '/'])
        .next()
        .unwrap_or(identifier)
        .to_lowercase();
    PROTECTED_PROCESS_NAMES.contains(&name.as_str())
}

/// Screenshot pixels per window pixel for a window of this size.
pub(crate) fn screenshot_scale(width: u32, height: u32) -> f64 {
    let edge = width.max(height);
    if edge <= SCREENSHOT_MAX_EDGE || edge == 0 {
        1.0
    } else {
        f64::from(SCREENSHOT_MAX_EDGE) / f64::from(edge)
    }
}

/// Pack a point into the `LPARAM` layout mouse messages use: x in the low
/// word, y in the high word, each a signed 16-bit value.
#[cfg_attr(not(target_os = "windows"), allow(dead_code))]
pub(crate) fn pack_point(x: i32, y: i32) -> isize {
    let low = (x as i16 as u16) as u32;
    let high = (y as i16 as u16) as u32;
    ((high << 16) | low) as i32 as isize
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct KeyCombo {
    pub ctrl: bool,
    pub alt: bool,
    pub shift: bool,
    pub win: bool,
    /// ⌘ on macOS. Elsewhere "cmd" means Ctrl and this stays false.
    pub cmd: bool,
    pub key: String,
}

/// Parse "ctrl+shift+s", "Alt+F4", "cmd+s", "Enter" or "ctrl++" into a combo.
pub(crate) fn parse_key_combo(spec: &str) -> Result<KeyCombo, String> {
    let spec = spec.trim();
    if spec.is_empty() {
        return Err("key is empty".into());
    }
    let (mods, key) = if spec.len() > 1 && spec.ends_with("++") {
        (&spec[..spec.len() - 2], "+")
    } else if let Some(index) = spec.rfind('+').filter(|&i| i > 0) {
        (&spec[..index], &spec[index + 1..])
    } else {
        ("", spec)
    };
    let mut combo = KeyCombo {
        ctrl: false,
        alt: false,
        shift: false,
        win: false,
        cmd: false,
        key: key.trim().to_string(),
    };
    for part in mods.split('+').map(str::trim).filter(|part| !part.is_empty()) {
        match part.to_lowercase().as_str() {
            "ctrl" | "control" => combo.ctrl = true,
            "cmd" | "command" | "meta" => combo.cmd = true,
            "alt" | "option" | "opt" => combo.alt = true,
            "shift" => combo.shift = true,
            "win" | "windows" | "super" => combo.win = true,
            other => return Err(format!("unknown modifier {other:?} in {spec:?}")),
        }
    }
    if combo.key.is_empty() {
        return Err(format!("missing key in {spec:?}"));
    }
    #[cfg(not(target_os = "macos"))]
    {
        // Outside macOS "cmd+s" is what a Mac user calls Ctrl+S.
        combo.ctrl |= combo.cmd;
        combo.cmd = false;
    }
    Ok(combo)
}

/// Shortcuts that act on the whole desktop or session rather than the app.
pub(crate) fn blocked_combo_reason(combo: &KeyCombo) -> Option<&'static str> {
    let key = combo.key.to_lowercase();
    if combo.win || matches!(key.as_str(), "win" | "lwin" | "rwin" | "windows") {
        return Some("Windows-key shortcuts act on the desktop, not the attached app");
    }
    if combo.ctrl && combo.alt && matches!(key.as_str(), "delete" | "del") {
        return Some("Ctrl+Alt+Delete is a secure system sequence");
    }
    if combo.cmd && combo.ctrl && key == "q" {
        return Some("Control+Command+Q locks the Mac");
    }
    if combo.cmd && combo.shift && key == "q" {
        return Some("Shift+Command+Q logs the user out");
    }
    if combo.cmd && combo.alt && matches!(key.as_str(), "escape" | "esc") {
        return Some("Option+Command+Esc opens Force Quit for every app");
    }
    None
}

#[cfg(not(any(target_os = "windows", target_os = "macos")))]
fn unsupported() -> String {
    "Computer App Control is only available in EvoFlux Desktop on Windows and macOS.".to_string()
}

/// Run one agent action against the session's attached window.
#[tauri::command]
pub async fn app_computer_action(
    app: tauri::AppHandle,
    session_id: String,
    action: String,
    params: Option<Value>,
) -> Result<Value, String> {
    let params = params.unwrap_or(Value::Null);
    #[cfg(any(target_os = "windows", target_os = "macos"))]
    {
        use tauri::Emitter;
        native::run_on_worker(move || {
            let emit = |payload: Value| {
                let _ = app.emit(POINTER_EVENT, payload);
            };
            native::run_action(&emit, &session_id, &action, &params)
        })
        .await
    }
    #[cfg(not(any(target_os = "windows", target_os = "macos")))]
    {
        let _ = (app, session_id, action, params);
        Err(unsupported())
    }
}

/// Apps the user can allow or block in Settings: running ones and the
/// installed ones (the Start menu's programs, or the Applications folders
/// on macOS), each with its icon.
#[tauri::command]
pub async fn app_computer_list_apps() -> Result<Value, String> {
    #[cfg(any(target_os = "windows", target_os = "macos"))]
    {
        // On Windows resolving shortcuts is COM work, which the worker is
        // already set up for.
        native::run_on_worker(|| Ok(native::list_apps())).await
    }
    #[cfg(not(any(target_os = "windows", target_os = "macos")))]
    {
        Ok(json!({ "apps": [] }))
    }
}

/// One preview frame of the session's attached window, JPEG-encoded.
#[tauri::command]
pub async fn app_computer_frame(session_id: String, max_width: Option<u32>) -> Result<Value, String> {
    #[cfg(any(target_os = "windows", target_os = "macos"))]
    {
        let max_width = max_width.unwrap_or(960).clamp(160, 1920);
        tauri::async_runtime::spawn_blocking(move || native::preview_frame(&session_id, max_width))
            .await
            .map_err(|error| format!("preview frame task failed: {error}"))?
    }
    #[cfg(not(any(target_os = "windows", target_os = "macos")))]
    {
        let _ = (session_id, max_width);
        Ok(json!({ "attached": false, "supported": false }))
    }
}

/// The user revoked control: detach and refuse re-attaching until resumed.
#[tauri::command]
pub fn app_computer_stop(session_id: String) -> Result<Value, String> {
    #[cfg(any(target_os = "windows", target_os = "macos"))]
    {
        native::stop(&session_id);
        Ok(json!({ "stopped": true }))
    }
    #[cfg(not(any(target_os = "windows", target_os = "macos")))]
    {
        let _ = session_id;
        Err(unsupported())
    }
}

/// The user allowed control again after stopping it.
#[tauri::command]
pub fn app_computer_resume(session_id: String) -> Result<Value, String> {
    #[cfg(any(target_os = "windows", target_os = "macos"))]
    {
        native::resume(&session_id);
        Ok(json!({ "stopped": false }))
    }
    #[cfg(not(any(target_os = "windows", target_os = "macos")))]
    {
        let _ = session_id;
        Err(unsupported())
    }
}

/// The operating-system permissions Computer App Control depends on. Only
/// macOS has any (Accessibility and Screen Recording); elsewhere nothing is
/// `required`.
#[tauri::command]
pub fn app_computer_permissions() -> Value {
    #[cfg(target_os = "macos")]
    {
        mac::permissions()
    }
    #[cfg(not(target_os = "macos"))]
    {
        json!({ "required": false, "accessibility": true, "screen_recording": true })
    }
}

/// Ask macOS for one permission (`accessibility` or `screen_recording`) and
/// open its pane in System Settings. Only ever invoked by a click in
/// Settings, never by the agent.
#[tauri::command]
pub fn app_computer_request_permission(kind: String) -> Result<Value, String> {
    #[cfg(target_os = "macos")]
    {
        mac::request_permission(&kind)
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = kind;
        Err("Only macOS asks for permissions to control apps.".into())
    }
}

/// Hand every controlled window back (un-parking hidden ones). Called when
/// EvoFlux exits so no app is left stranded off-screen.
pub fn release_all() {
    #[cfg(any(target_os = "windows", target_os = "macos"))]
    native::release_all();
}

/// Bring the attached app to the front for the user. Only ever invoked by a
/// click in the preview card, never by the agent.
#[tauri::command]
pub fn app_computer_reveal(session_id: String) -> Result<Value, String> {
    #[cfg(any(target_os = "windows", target_os = "macos"))]
    {
        native::reveal(&session_id)
    }
    #[cfg(not(any(target_os = "windows", target_os = "macos")))]
    {
        let _ = session_id;
        Err(unsupported())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_plain_and_modified_keys() {
        assert_eq!(
            parse_key_combo("Enter").unwrap(),
            KeyCombo {
                ctrl: false,
                alt: false,
                shift: false,
                win: false,
                cmd: false,
                key: "Enter".into()
            }
        );
        let combo = parse_key_combo("ctrl+Shift+s").unwrap();
        assert!(combo.ctrl && combo.shift && !combo.alt && !combo.cmd);
        assert_eq!(combo.key, "s");
        assert_eq!(parse_key_combo("ctrl++").unwrap().key, "+");
        assert_eq!(parse_key_combo("+").unwrap().key, "+");
        assert!(parse_key_combo("option+left").unwrap().alt);
        assert!(parse_key_combo("hyper+x").is_err());
        assert!(parse_key_combo("ctrl+").is_err());
    }

    #[test]
    fn cmd_is_command_on_macos_and_ctrl_elsewhere() {
        let combo = parse_key_combo("cmd+s").unwrap();
        if cfg!(target_os = "macos") {
            assert!(combo.cmd && !combo.ctrl);
        } else {
            assert!(combo.ctrl && !combo.cmd);
        }
    }

    #[test]
    fn blocks_desktop_level_shortcuts() {
        assert!(blocked_combo_reason(&parse_key_combo("win+l").unwrap()).is_some());
        assert!(blocked_combo_reason(&parse_key_combo("lwin").unwrap()).is_some());
        assert!(blocked_combo_reason(&parse_key_combo("ctrl+alt+delete").unwrap()).is_some());
        assert!(blocked_combo_reason(&parse_key_combo("alt+f4").unwrap()).is_none());
        assert!(blocked_combo_reason(&parse_key_combo("ctrl+s").unwrap()).is_none());
    }

    #[cfg(target_os = "macos")]
    #[test]
    fn blocks_session_level_mac_shortcuts() {
        assert!(blocked_combo_reason(&parse_key_combo("ctrl+cmd+q").unwrap()).is_some());
        assert!(blocked_combo_reason(&parse_key_combo("cmd+shift+q").unwrap()).is_some());
        assert!(blocked_combo_reason(&parse_key_combo("cmd+option+esc").unwrap()).is_some());
        assert!(blocked_combo_reason(&parse_key_combo("cmd+q").unwrap()).is_none());
        assert!(blocked_combo_reason(&parse_key_combo("cmd+s").unwrap()).is_none());
    }

    #[cfg(not(target_os = "macos"))]
    #[test]
    fn protected_names_match_paths_case_insensitively() {
        assert!(is_protected_process_name("C:\\Windows\\Explorer.EXE"));
        assert!(is_protected_process_name("lsass.exe"));
        assert!(!is_protected_process_name("notepad.exe"));
    }

    #[cfg(target_os = "macos")]
    #[test]
    fn protected_names_match_mac_executables() {
        assert!(is_protected_process_name("/System/Library/CoreServices/Finder.app/Contents/MacOS/Finder"));
        assert!(is_protected_process_name("System Settings"));
        assert!(!is_protected_process_name("TextEdit"));
    }

    #[test]
    fn scales_only_large_windows() {
        assert_eq!(screenshot_scale(1280, 800), 1.0);
        let scale = screenshot_scale(3136, 1000);
        assert!((scale - 0.5).abs() < 1e-9);
    }

    #[test]
    fn packs_negative_points_as_signed_words() {
        assert_eq!(pack_point(10, 20), (20 << 16) | 10);
        let packed = pack_point(-5, 7) as u32;
        assert_eq!((packed & 0xffff) as u16 as i16, -5);
        assert_eq!((packed >> 16) as u16 as i16, 7);
    }
}
