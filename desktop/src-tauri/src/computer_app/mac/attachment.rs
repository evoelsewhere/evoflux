//! `status`, `attach` and `detach`: taking one window under control and
//! letting it go.

use super::*;

pub(super) fn status(session_id: &str) -> Value {
    let registry = registry();
    let stopped = registry.stopped.contains(session_id);
    match registry.attached.get(session_id) {
        Some(attached) => {
            let window = cg_window(attached.window_id);
            let ax = Ax::application(attached.pid).and_then(|app| ax_window(&app, attached.window_id));
            json!({
                "attached": true,
                "open": window.is_some(),
                "window": {
                    "id": attached.window_id,
                    "app": attached.app,
                    "title": ax.as_ref().and_then(|ax| ax.string("AXTitle")).unwrap_or_else(|| attached.title.clone()),
                    "pid": attached.pid,
                    "minimized": ax.as_ref().and_then(|ax| ax.flag("AXMinimized")).unwrap_or(false),
                    "hidden": attached.parked.is_some(),
                },
                "stopped": stopped,
            })
        }
        None => json!({ "attached": false, "stopped": stopped }),
    }
}

/// Turn on a Chromium app's accessibility tree and wait (up to ~4 s) until
/// its page content shows up in it.
fn enable_web_accessibility(app: &Ax, window: &Ax) {
    // Electron reads the first, Chrome and Edge the second.
    let _ = app.set_flag("AXManualAccessibility", true);
    let _ = app.set_flag("AXEnhancedUserInterface", true);
    let deadline = Instant::now() + Duration::from_secs(4);
    while Instant::now() < deadline {
        let mut budget = 400;
        let ready = find_role(window, "AXWebArea", 12, &mut budget)
            .is_some_and(|area| !area.elements("AXChildren").is_empty());
        if ready {
            return;
        }
        pause(200);
    }
}

/// The first element with `role` at most `depth` levels down, looking at no
/// more than `budget` elements: a browser's own toolbar alone has hundreds.
fn find_role(element: &Ax, role: &str, depth: u32, budget: &mut u32) -> Option<Ax> {
    if *budget == 0 {
        return None;
    }
    *budget -= 1;
    if element.role() == role {
        return Some(element.clone());
    }
    if depth == 0 {
        return None;
    }
    element
        .elements("AXChildren")
        .iter()
        .find_map(|child| find_role(child, role, depth - 1, budget))
}

pub(super) fn attach(session_id: &str, params: &Value) -> Result<Value, String> {
    refuse_if_stopped(session_id)?;
    if !accessibility_trusted(true) {
        return Err(ACCESSIBILITY_REFUSAL.into());
    }
    let window_id = params.get("window_id").and_then(Value::as_u64);
    let rows = window_rows();
    let chosen = if let Some(id) = window_id {
        rows.into_iter()
            .find(|row| u64::from(row.id) == id)
            .ok_or_else(|| format!("No window with id {id}. Call list_windows again."))?
    } else {
        let app = params.get("app").and_then(Value::as_str).map(str::to_lowercase);
        let title = params.get("title").and_then(Value::as_str).map(str::to_lowercase);
        if app.is_none() && title.is_none() {
            return Err("attach needs window_id (from list_windows), app, or title.".into());
        }
        matching_window(rows, app.as_deref(), title.as_deref())?
    };
    if let Some(reason) = attach_refusal(&chosen) {
        return Err(reason);
    }
    let app = Ax::application(chosen.pid).ok_or("macOS would not open the app for accessibility.")?;
    // A dialog is driven through the window that owns it, so the card keeps
    // following the app when the dialog closes.
    let (id, title) = match chosen.owner.and_then(|owner| ax_window(&app, owner).map(|ax| (owner, ax))) {
        Some((owner, ax)) => (owner, ax.string("AXTitle").unwrap_or_else(|| chosen.title.clone())),
        None => (chosen.id, chosen.title.clone()),
    };
    let window = ax_window(&app, id).ok_or(
        "That window is not reachable through accessibility (it may be on another Space). Ask the user to bring it to this desktop.",
    )?;
    // One chat per window: two would interleave their input, and the second
    // would save the first one's parking spot as the window's own place.
    let held_elsewhere = registry()
        .attached
        .iter()
        .any(|(other, attached)| other != session_id && attached.window_id == id);
    if held_elsewhere {
        return Err(format!(
            "\"{title}\" is already controlled from another chat. Finish or detach there first, or pick another window."
        ));
    }
    // Attaching to another window hands the previous one back first.
    release(session_id);
    let _ = app.set_flag("AXHidden", false);
    let hide = params.get("hide").and_then(Value::as_bool).unwrap_or(false);
    let web = is_chromium_app(chosen.pid);
    let parked = if hide {
        if web {
            // Chromium builds a page's tree only while it considers the page
            // shown; asked for it once the window was parked, a page
            // sometimes never filled in. Asked first, where the window is.
            // Its enhanced interface is off for the move (see `hand_back`).
            enable_web_accessibility(&app, &window);
            let _ = app.set_flag("AXEnhancedUserInterface", false);
            pause(100);
        }
        park(&window, web)
    } else {
        if window.flag("AXMinimized").unwrap_or(false) {
            let _ = window.set_flag("AXMinimized", false);
            pause(450);
        }
        None
    };
    // After parking: while Chromium's enhanced accessibility is on, window
    // moves through accessibility are animated and can be ignored. Quick
    // when the page already filled in above.
    if web {
        enable_web_accessibility(&app, &window);
    }
    // Stop pressed while this attach was parking the window: hand it back
    // instead of registering a window nobody may drive.
    if let Err(stopped) = interrupted() {
        if web {
            let _ = app.set_flag("AXEnhancedUserInterface", false);
        }
        if let Some(parked) = parked {
            unpark(&window, parked, false);
        }
        return Err(stopped);
    }
    registry().attached.insert(
        session_id.to_string(),
        Attached { window_id: id, pid: chosen.pid, app: chosen.app.clone(), title, parked, web },
    );
    let target = Target::resolve(session_id)?;
    Ok(json!({ "attached": true, "window": target.describe() }))
}

/// Resolve a name-based attach without disguising a protected match as a
/// missing window. `list_windows` intentionally hides protected apps, but an
/// agent can still guess a name such as "System Settings"; tell it the safety
/// boundary it hit so it does not misdiagnose the absent PiP as a UI failure.
pub(super) fn matching_window(
    rows: Vec<WindowRow>,
    app: Option<&str>,
    title: Option<&str>,
) -> Result<WindowRow, String> {
    let mut first_refusal = None;
    for row in rows {
        let matches = app.map_or(true, |app| row.app.to_lowercase().contains(app))
            && title.map_or(true, |title| row.title.to_lowercase().contains(title));
        if !matches {
            continue;
        }
        if let Some(reason) = attach_refusal(&row) {
            first_refusal.get_or_insert(reason);
            continue;
        }
        return Ok(row);
    }
    Err(first_refusal.unwrap_or_else(|| {
        "No controllable window matches. Call list_windows to see what is open.".to_string()
    }))
}

pub(super) fn detach(session_id: &str) -> Value {
    let removed = release(session_id);
    json!({ "detached": removed.is_some() })
}
