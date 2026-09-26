//! App lifecycle: `search_apps`, `open_app`, `close_app`, `kill_app`.
//!
//! Opening only starts what the app catalog knows (a Start menu shortcut or
//! a running program), never a path or command line from the agent. Closing
//! and killing only reach a window `list_windows` would offer, under the
//! same refusals as attaching, and never one another chat is driving.

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
        return Err(format!("{exe} is part of the Windows shell or security system and cannot be opened."));
    }
    let before: HashSet<isize> = top_level_windows().into_iter().map(|hwnd| hwnd.0 as isize).collect();
    launch(&entry.launch)?;
    let deadline = std::time::Instant::now() + OPEN_WAIT;
    loop {
        interrupted()?;
        let opened = top_level_windows()
            .into_iter()
            .filter(|hwnd| !before.contains(&(hwnd.0 as isize)))
            .filter_map(describe_window)
            .find(|row| row.app.eq_ignore_ascii_case(exe) && row.owner.is_none() && attach_refusal(row).is_none());
        if let Some(row) = opened {
            let foreground = unsafe { GetForegroundWindow() };
            return Ok(json!({ "opened": true, "exe": exe, "name": entry.name, "window": row.to_json(foreground) }));
        }
        if std::time::Instant::now() >= deadline {
            return Ok(json!({
                "opened": true,
                "exe": exe,
                "name": entry.name,
                "window": null,
                "note": "No new window of the app showed up. It may still be starting, or it reused a window that was already open: call list_windows.",
            }));
        }
        pause(250);
    }
}

/// Start `path` (a shortcut or a program) minimized and without taking the
/// foreground, so the app opens behind whatever the user is doing.
///
/// `ShellExecuteW` may hand the work to shell extensions, which expect a
/// single-threaded apartment; workers are multithreaded, so it runs on a
/// short-lived thread of its own.
fn launch(path: &str) -> Result<(), String> {
    use windows::core::{HSTRING, PCWSTR};
    use windows::Win32::System::Com::COINIT_APARTMENTTHREADED;
    use windows::Win32::UI::Shell::ShellExecuteW;
    let owned = path.to_string();
    let code = std::thread::spawn(move || unsafe {
        let _ = CoInitializeEx(None, COINIT_APARTMENTTHREADED);
        let result = ShellExecuteW(
            None,
            &HSTRING::from("open"),
            &HSTRING::from(owned.as_str()),
            PCWSTR::null(),
            PCWSTR::null(),
            SW_SHOWMINNOACTIVE,
        );
        CoUninitialize();
        result.0 as isize
    })
    .join()
    .map_err(|_| format!("Starting {path} failed."))?;
    // ShellExecute reports success as a value above 32.
    if code > 32 {
        Ok(())
    } else {
        Err(format!("Windows could not start {path} (error {code})."))
    }
}

/// The window `close_app` or `kill_app` acts on: `window_id` from
/// list_windows, or the attached one. With `whole_process`, no window of its
/// process may be driven from another chat.
fn lifecycle_target(session_id: &str, params: &Value, whole_process: bool) -> Result<WindowRow, String> {
    let rows = top_level_windows().into_iter().filter_map(describe_window);
    let row = match params.get("window_id").and_then(Value::as_u64) {
        Some(id) => rows
            .into_iter()
            .find(|row| hwnd_id(row.hwnd) == id)
            .ok_or_else(|| format!("No visible window with id {id}. Call list_windows again."))?,
        None => {
            let attached = registry()
                .attached
                .get(session_id)
                .map(|attached| attached.hwnd)
                .ok_or("No app is attached. Pass window_id from list_windows, or attach first.")?;
            rows.into_iter()
                .find(|row| row.hwnd.0 as isize == attached)
                .ok_or("The attached window is already closed.")?
        }
    };
    if let Some(reason) = attach_refusal(&row) {
        return Err(reason);
    }
    let held_elsewhere = registry().attached.iter().any(|(other, attached)| {
        other != session_id
            && (attached.hwnd == row.hwnd.0 as isize || (whole_process && attached.pid == row.pid))
    });
    if held_elsewhere {
        return Err(format!(
            "{} is controlled from another chat. Finish or detach there first.",
            row.app
        ));
    }
    Ok(row)
}

/// Forget every session's window that no longer exists, and its parked
/// place on disk, so a closed or killed app is not left registered.
/// Returns the sessions that lost their window.
fn forget_closed_windows() -> Vec<String> {
    let gone: Vec<(String, isize)> = registry()
        .attached
        .iter()
        .filter(|(_, attached)| !unsafe { IsWindow(Some(to_hwnd(attached.hwnd))) }.as_bool())
        .map(|(session, attached)| (session.clone(), attached.hwnd))
        .collect();
    for (session, hwnd) in &gone {
        take(session);
        forget_parked(to_hwnd(*hwnd));
    }
    gone.into_iter().map(|(session, _)| session).collect()
}

/// Ask the window to close, as its close button would. The app may ask
/// first (save changes?); that dialog is left for the agent to answer.
pub(super) fn close_app(session_id: &str, params: &Value) -> Result<Value, String> {
    refuse_if_stopped(session_id)?;
    let row = lifecycle_target(session_id, params, false)?;
    post(row.hwnd, windows::Win32::UI::WindowsAndMessaging::WM_CLOSE, 0, LPARAM(0))?;
    let deadline = std::time::Instant::now() + CLOSE_WAIT;
    while unsafe { IsWindow(Some(row.hwnd)) }.as_bool() {
        let asking = effective_window(row.hwnd, row.pid);
        if asking != row.hwnd {
            return Ok(json!({
                "closed": false,
                "app": row.app,
                "title": row.title,
                "asking": window_title(asking),
                "note": "The app asks something before it closes (most likely whether to save). Attach to it if it is not attached, snapshot, and answer.",
            }));
        }
        if std::time::Instant::now() >= deadline {
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

/// End the window's process at once. Unsaved work in it is lost.
pub(super) fn kill_app(session_id: &str, params: &Value) -> Result<Value, String> {
    use windows::Win32::System::Threading::{
        TerminateProcess, WaitForSingleObject, PROCESS_SYNCHRONIZE, PROCESS_TERMINATE,
    };
    refuse_if_stopped(session_id)?;
    let row = lifecycle_target(session_id, params, true)?;
    // A Store app's frame belongs to its host; the app is behind it.
    let pid = app_process(row.hwnd, row.pid);
    unsafe {
        let process = OpenProcess(PROCESS_TERMINATE | PROCESS_SYNCHRONIZE, false, pid)
            .map_err(|error| format!("Windows did not let EvoFlux end {}: {error}", row.app))?;
        let ended = TerminateProcess(process, 1);
        if ended.is_ok() {
            let _ = WaitForSingleObject(process, 3_000);
        }
        let _ = CloseHandle(process);
        ended.map_err(|error| format!("Could not end {}: {error}", row.app))?;
    }
    // A Store app's frame closes a moment after the app itself.
    pause(300);
    let released = forget_closed_windows();
    Ok(json!({
        "killed": true,
        "app": row.app,
        "pid": pid,
        "released": released.iter().any(|session| session == session_id),
    }))
}
