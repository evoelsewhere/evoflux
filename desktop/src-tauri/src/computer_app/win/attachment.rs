//! `status`, `attach` and `detach`: taking one window under control and
//! letting it go.

use super::*;

pub(super) fn status(session_id: &str) -> Value {
    let registry = registry();
    let stopped = registry.stopped.contains(session_id);
    match registry.attached.get(session_id) {
        Some(attached) => {
            let hwnd = to_hwnd(attached.hwnd);
            let open = unsafe { IsWindow(Some(hwnd)) }.as_bool();
            json!({
                "attached": true,
                "open": open,
                "window": {
                    "id": attached.hwnd as u64,
                    "app": attached.app,
                    "title": if open { window_title(hwnd) } else { attached.title.clone() },
                    "pid": attached.pid,
                    "minimized": open && unsafe { IsIconic(hwnd) }.as_bool(),
                    "hidden": attached.parked.is_some(),
                },
                "stopped": stopped,
            })
        }
        None => json!({ "attached": false, "stopped": stopped }),
    }
}

pub(super) fn attach(session_id: &str, params: &Value) -> Result<Value, String> {
    refuse_if_stopped(session_id)?;
    let window_id = params.get("window_id").and_then(Value::as_u64);
    let rows: Vec<WindowRow> = top_level_windows()
        .into_iter()
        .filter_map(describe_window)
        .collect();
    let chosen = if let Some(id) = window_id {
        rows.into_iter()
            .find(|row| hwnd_id(row.hwnd) == id)
            .ok_or_else(|| format!("No visible window with id {id}. Call list_windows again."))?
    } else {
        let app = params.get("app").and_then(Value::as_str).map(str::to_lowercase);
        let title = params.get("title").and_then(Value::as_str).map(str::to_lowercase);
        if app.is_none() && title.is_none() {
            return Err("attach needs window_id (from list_windows), app, or title.".into());
        }
        rows.into_iter()
            .filter(|row| attach_refusal(row).is_none())
            .find(|row| {
                app.as_ref()
                    .map_or(true, |app| row.app.to_lowercase().contains(app))
                    && title
                        .as_ref()
                        .map_or(true, |title| row.title.to_lowercase().contains(title))
            })
            .ok_or("No controllable window matches. Call list_windows to see what is open.")?
    };
    if let Some(reason) = attach_refusal(&chosen) {
        return Err(reason);
    }
    // A dialog is driven through the window that owns it, so the card keeps
    // following the app when the dialog closes.
    let chosen = match chosen.owner {
        Some(owner) if window_pid(owner) == chosen.pid => describe_window(owner).unwrap_or(chosen),
        _ => chosen,
    };
    // One chat per window: two would interleave their input, and the second
    // would save the first one's off-screen spot as the window's own place.
    let held_elsewhere = registry()
        .attached
        .iter()
        .any(|(other, attached)| other != session_id && attached.hwnd == chosen.hwnd.0 as isize);
    if held_elsewhere {
        return Err(format!(
            "\"{}\" is already controlled from another chat. Finish or detach there first, or pick another window.",
            chosen.title
        ));
    }
    // Attaching to another window hands the previous one back first.
    release(session_id);
    let hide = params.get("hide").and_then(Value::as_bool).unwrap_or(false);
    let web = is_web_host(chosen.hwnd);
    if web {
        // Chromium only exposes a page's tree once an assistive client asks
        // for it, builds it asynchronously, and stops building it for a
        // window that is off-screen. Ask while the window is still where the
        // user left it, and wait until the page is there before parking.
        wait_for_page_tree(chosen.hwnd);
    }
    let parked = if hide {
        watch_for_dialogs();
        let parked = park(chosen.hwnd);
        if web {
            // Let Chromium finish reacting to being hidden before the first
            // action arrives: keys typed sooner were lost now and then
            // (measured: with this wait, none in repeated runs).
            pause(800);
        }
        parked
    } else {
        unsafe {
            if IsIconic(chosen.hwnd).as_bool() {
                let _ = ShowWindow(chosen.hwnd, SW_SHOWNOACTIVATE);
            }
        }
        None
    };
    // Stop pressed while this attach was parking the window: hand it back
    // instead of registering a window nobody may drive.
    if let Err(stopped) = interrupted() {
        if let Some(placement) = parked {
            unpark(chosen.hwnd, placement, false);
        }
        return Err(stopped);
    }
    let attached = Attached {
        hwnd: chosen.hwnd.0 as isize,
        pid: chosen.pid,
        app: chosen.app.clone(),
        title: chosen.title.clone(),
        parked,
    };
    registry()
        .attached
        .insert(session_id.to_string(), attached);
    let target = Target::resolve(session_id)?;
    Ok(json!({
        "attached": true,
        "window": target.describe(),
    }))
}

pub(super) fn detach(session_id: &str) -> Value {
    let removed = release(session_id);
    json!({ "detached": removed.is_some() })
}
