//! App lifecycle: `search_apps`, `open_app`, `close_app`, `kill_app`.
//!
//! Opening only starts an `.app` bundle the app catalog knows, never a path
//! or command line from the agent. Closing and killing only reach a window
//! `list_windows` would offer, under the same refusals as attaching, and
//! never one another chat is driving.

use super::*;

/// How long `open_app` waits for the new app's window.
const OPEN_WAIT: Duration = Duration::from_secs(20);
/// How long `close_app` waits for the window to go.
const CLOSE_WAIT: Duration = Duration::from_secs(5);

pub(super) fn refuse_if_stopped(session_id: &str) -> Result<(), String> {
    if registry().stopped.contains(session_id) {
        return Err(STOPPED_REFUSAL.into());
    }
    Ok(())
}

pub(super) fn search_apps(params: &Value) -> Value {
    let limit = params.get("limit").and_then(Value::as_u64).unwrap_or(20).clamp(1, 100) as usize;
    apps::search(app_catalog(), params.get("query").and_then(Value::as_str), limit)
}

pub(super) fn open_app(session_id: &str, params: &Value) -> Result<Value, String> {
    refuse_if_stopped(session_id)?;
    let wanted = params
        .get("exe")
        .and_then(Value::as_str)
        .ok_or("open_app needs exe, as search_apps lists it.")?;
    let catalog = app_catalog();
    let (exe, entry) = apps::find(&catalog, wanted)?;
    if is_protected_process_name(exe) {
        return Err(format!("{} is a system app or runs commands, so it cannot be opened from here.", entry.name));
    }
    if entry.launch.is_empty() {
        return Err(format!("{} does not run from an app bundle, so it cannot be opened from here.", entry.name));
    }
    let before: HashSet<u32> = window_rows().into_iter().map(|row| row.id).collect();
    // -g: open in the background, leaving the user's frontmost app in front.
    let status = std::process::Command::new("/usr/bin/open")
        .arg("-g")
        .arg(&entry.launch)
        .status()
        .map_err(|error| format!("Could not start {}: {error}", entry.name))?;
    if !status.success() {
        return Err(format!("macOS could not open {} ({status}).", entry.name));
    }
    let deadline = Instant::now() + OPEN_WAIT;
    loop {
        interrupted()?;
        let opened = window_rows()
            .into_iter()
            .filter(|row| !before.contains(&row.id))
            .find(|row| row.app.eq_ignore_ascii_case(exe) && row.owner.is_none() && attach_refusal(row).is_none());
        if let Some(row) = opened {
            return Ok(json!({ "opened": true, "exe": exe, "name": entry.name, "window": row.to_json(frontmost_pid()) }));
        }
        if Instant::now() >= deadline {
            return Ok(json!({
                "opened": true,
                "exe": exe,
                "name": entry.name,
                "window": null,
                "note": "No new window of the app showed up. It may still be starting, or it was already running and opened no window: call list_windows.",
            }));
        }
        pause(250);
    }
}

/// The window `close_app` or `kill_app` acts on: `window_id` from
/// list_windows, or the attached one. With `whole_process`, no window of its
/// process may be driven from another chat.
fn lifecycle_target(session_id: &str, params: &Value, whole_process: bool) -> Result<WindowRow, String> {
    let wanted = match params.get("window_id").and_then(Value::as_u64) {
        Some(id) => u32::try_from(id).map_err(|_| format!("No window with id {id}. Call list_windows again."))?,
        None => registry()
            .attached
            .get(session_id)
            .map(|attached| attached.window_id)
            .ok_or("No app is attached. Pass window_id from list_windows, or attach first.")?,
    };
    let row = window_rows()
        .into_iter()
        .find(|row| row.id == wanted)
        .ok_or_else(|| format!("No window with id {wanted} is open. Call list_windows again."))?;
    if let Some(reason) = attach_refusal(&row) {
        return Err(reason);
    }
    let held_elsewhere = registry().attached.iter().any(|(other, attached)| {
        other != session_id && (attached.window_id == row.id || (whole_process && attached.pid == row.pid))
    });
    if held_elsewhere {
        return Err(format!("{} is controlled from another chat. Finish or detach there first.", row.app));
    }
    Ok(row)
}

/// Forget every session's window that no longer exists, so a closed or
/// killed app is not left registered. Returns the sessions that lost their
/// window.
fn forget_closed_windows() -> Vec<String> {
    let attached: Vec<(String, u32)> = registry()
        .attached
        .iter()
        .map(|(session, attached)| (session.clone(), attached.window_id))
        .collect();
    let gone: Vec<String> = attached
        .into_iter()
        .filter(|(_, window_id)| cg_window(*window_id).is_none())
        .map(|(session, _)| session)
        .collect();
    for session in &gone {
        registry().attached.remove(session);
        clear_refs(session);
    }
    gone
}

/// Press the window's close button. The app may ask first (save
/// changes?); that sheet or dialog is left for the agent to answer.
pub(super) fn close_app(session_id: &str, params: &Value) -> Result<Value, String> {
    refuse_if_stopped(session_id)?;
    let row = lifecycle_target(session_id, params, false)?;
    let app = Ax::application(row.pid).ok_or("The app is gone.")?;
    let window = reach_window(&app, row.id).ok_or("macOS did not let EvoFlux reach the window.")?;
    let button = window.element("AXCloseButton").ok_or_else(|| {
        format!("\"{}\" has no close button. Use the app's own command instead (find \"Close\" or \"Quit\").", row.title)
    })?;
    button
        .perform("AXPress")
        .map_err(|error| format!("Pressing the close button failed: {}", ax_error(error)))?;
    let deadline = Instant::now() + CLOSE_WAIT;
    while cg_window(row.id).is_some() {
        let dialog = app
            .elements("AXWindows")
            .into_iter()
            .any(|other| other.window_id() != Some(row.id) && is_dialog(&other));
        if dialog || !sheet_frames(&window).is_empty() {
            return Ok(json!({
                "closed": false,
                "app": row.app,
                "title": row.title,
                "asking": true,
                "note": "The app asks something before it closes (most likely whether to save). Attach to it if it is not attached, snapshot, and answer.",
            }));
        }
        if Instant::now() >= deadline {
            return Ok(json!({
                "closed": false,
                "app": row.app,
                "title": row.title,
                "note": "The window is still open: the app may be busy or ignore the request. Look at it again; use kill_app only if it has hung.",
            }));
        }
        interrupted()?;
        pause(150);
    }
    let released = forget_closed_windows();
    Ok(json!({
        "closed": true,
        "app": row.app,
        "title": row.title,
        "released": released.iter().any(|session| session == session_id),
    }))
}

/// End the window's process at once (SIGKILL). Unsaved work in it is lost.
pub(super) fn kill_app(session_id: &str, params: &Value) -> Result<Value, String> {
    use nix::sys::signal::{kill, Signal};
    use nix::unistd::Pid;
    refuse_if_stopped(session_id)?;
    let row = lifecycle_target(session_id, params, true)?;
    let pid = Pid::from_raw(row.pid);
    kill(pid, Signal::SIGKILL).map_err(|error| format!("Could not end {}: {error}", row.app))?;
    let deadline = Instant::now() + Duration::from_secs(3);
    while kill(pid, None).is_ok() && Instant::now() < deadline {
        pause(100);
    }
    let released = forget_closed_windows();
    Ok(json!({
        "killed": true,
        "app": row.app,
        "pid": row.pid,
        "released": released.iter().any(|session| session == session_id),
    }))
}
