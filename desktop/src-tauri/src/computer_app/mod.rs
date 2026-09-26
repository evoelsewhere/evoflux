//! Computer App Control: an agent drives ONE desktop application window.
//!
//! This is deliberately not "computer use". The agent attaches to a single
//! top-level window and every capture and input is addressed to that window
//! (and the modal dialogs it opens), never to the desktop:
//!
//! - Capture reads the window's own pixels (`PrintWindow` on Windows, the
//!   window server on macOS), so the app can sit behind other windows or be
//!   parked just outside the screen.
//! - Input is posted to the window's own message queue / process or
//!   performed through the accessibility tree. The user's real cursor,
//!   keyboard focus and foreground window are never touched, which is also
//!   why some apps (UWP, games, raw-input apps) cannot be driven by
//!   coordinates and need `invoke` / `set_value` instead.
//!
//! The user watches through a picture-in-picture card in the web UI that
//! polls [`app_computer_frame`] and draws a virtual cursor from the
//! [`POINTER_EVENT`] events emitted here, and can revoke control with
//! [`app_computer_stop`].
//!
//! # Layout
//!
//! - [`backend`]: the [`ComputerAppBackend`](backend::ComputerAppBackend)
//!   trait and the factory [`backend()`](backend::backend) that returns the
//!   platform's implementation. The commands below only ever talk to it.
//! - `win.rs` / `mac.rs`: the Windows and macOS products of the factory.
//! - [`action`]: the closed set of agent actions, parsed once here.
//! - [`workers`], [`interrupt`]: per-session worker threads and Stop.
//! - [`apps`]: the app catalog behind `search_apps` / `open_app` and the
//!   Settings picker.
//! - [`keys`], [`policy`], [`geometry`]: helpers the backends share.

mod action;
mod backend;
mod interrupt;
mod workers;

// Helpers only the platform backends use.
#[cfg_attr(not(any(target_os = "windows", target_os = "macos")), allow(dead_code))]
mod apps;
#[cfg_attr(not(any(target_os = "windows", target_os = "macos")), allow(dead_code))]
mod geometry;
#[cfg_attr(not(any(target_os = "windows", target_os = "macos")), allow(dead_code))]
mod keys;
#[cfg_attr(not(any(target_os = "windows", target_os = "macos")), allow(dead_code))]
mod policy;

#[cfg(target_os = "macos")]
mod mac;
#[cfg(target_os = "windows")]
mod win;

use serde_json::{json, Value};
use tauri::Emitter;

use action::Action;
use backend::backend;
use interrupt::{generation, interrupt, with_ticket};

/// Tauri event carrying the agent's virtual pointer for the preview card.
pub const POINTER_EVENT: &str = "computer-app:pointer";

/// Run one agent action against the session's attached window.
#[tauri::command]
pub async fn app_computer_action(
    app: tauri::AppHandle,
    session_id: String,
    action: String,
    params: Option<Value>,
) -> Result<Value, String> {
    let action: Action = action.parse()?;
    let params = params.unwrap_or(Value::Null);
    if action == Action::Detach {
        // Closing the card (or the agent letting go) ends anything still
        // running for the session rather than queueing behind it.
        interrupt(&session_id);
    }
    let ticket = generation(&session_id);
    let key = session_id.clone();
    workers::run(&key, move || {
        let emit = |payload: Value| {
            let _ = app.emit(POINTER_EVENT, payload);
        };
        with_ticket(&session_id, ticket, || backend().run_action(&emit, &session_id, action, &params))
    })
    .await
}

/// Apps the user can allow or block in Settings: running ones and the
/// installed ones (the Start menu's programs, or the Applications folders
/// on macOS), each with its icon.
#[tauri::command]
pub async fn app_computer_list_apps() -> Result<Value, String> {
    // A worker of its own, so a long scan never waits behind (or holds up)
    // a chat's actions. On Windows it is COM work, which workers are set up
    // for.
    workers::run(workers::APP_PICKER, || Ok(backend().list_apps())).await
}

/// One preview frame of the session's attached window, JPEG-encoded.
#[tauri::command]
pub async fn app_computer_frame(session_id: String, max_width: Option<u32>) -> Result<Value, String> {
    let max_width = max_width.unwrap_or(960).clamp(160, 1920);
    tauri::async_runtime::spawn_blocking(move || backend().preview_frame(&session_id, max_width))
        .await
        .map_err(|error| format!("preview frame task failed: {error}"))?
}

/// The user revoked control: detach and refuse re-attaching until resumed.
#[tauri::command]
pub fn app_computer_stop(session_id: String) -> Result<Value, String> {
    interrupt(&session_id);
    backend().stop(&session_id)?;
    Ok(json!({ "stopped": true }))
}

/// End the session's action in progress (and any waiting behind it) without
/// revoking control. The backend sends this when it stopped waiting for an
/// action, so a retry cannot run the same input a second time.
#[tauri::command]
pub fn app_computer_interrupt(session_id: String) -> Value {
    interrupt(&session_id);
    json!({ "interrupted": true })
}

/// The user allowed control again after stopping it.
#[tauri::command]
pub fn app_computer_resume(session_id: String) -> Result<Value, String> {
    backend().resume(&session_id)?;
    Ok(json!({ "stopped": false }))
}

/// The operating-system permissions Computer App Control depends on. Only
/// macOS has any (Accessibility and Screen Recording); elsewhere nothing is
/// `required`.
#[tauri::command]
pub fn app_computer_permissions() -> Value {
    backend().permissions()
}

/// Ask macOS for one permission (`accessibility` or `screen_recording`) and
/// open its pane in System Settings. Only ever invoked by a click in
/// Settings, never by the agent.
#[tauri::command]
pub fn app_computer_request_permission(kind: String) -> Result<Value, String> {
    backend().request_permission(&kind)
}

/// Bring the attached app to the front for the user. Only ever invoked by a
/// click in the preview card, never by the agent.
#[tauri::command]
pub fn app_computer_reveal(session_id: String) -> Result<Value, String> {
    backend().reveal(&session_id)
}

/// Hand every controlled window back (un-parking hidden ones). Called when
/// EvoFlux exits so no app is left stranded off-screen.
pub fn release_all() {
    backend().release_all();
}

/// Record parked windows in `state_dir` from now on, and put back any a
/// previous run left off-screen (EvoFlux crashed or was killed first).
pub fn recover_stranded(state_dir: std::path::PathBuf) {
    backend().recover_stranded(state_dir);
}
