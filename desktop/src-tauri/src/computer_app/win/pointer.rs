//! Pointer input posted to the attached window in the background: `click`,
//! `hover`, `scroll`, `drag`. Web content goes through UI Automation first
//! (see `uia_input`), since posted mouse messages do not reach the page.

use super::*;

const HTCLIENT: isize = 1;
const HTTRANSPARENT: isize = -1;
const MK_LBUTTON: usize = 0x0001;
const MK_RBUTTON: usize = 0x0002;
const MK_MBUTTON: usize = 0x0010;
const WHEEL_DELTA: i32 = 120;

/// Where a pointer action lands: a ref's centre or screenshot coordinates.
fn pointer_target(target: &Target, params: &Value) -> Result<POINT, String> {
    if let Some(reference) = params.get("ref").and_then(Value::as_str) {
        let element = element_for(target, reference)?;
        let rect = unsafe { element.CurrentBoundingRectangle() }
            .map_err(|error| format!("{reference} has no position: {error}"))?;
        if rect.right <= rect.left || rect.bottom <= rect.top {
            return Err(format!("{reference} is not visible on screen; try invoke instead."));
        }
        return Ok(POINT {
            x: (rect.left + rect.right) / 2,
            y: (rect.top + rect.bottom) / 2,
        });
    }
    let x = params.get("x").and_then(Value::as_f64);
    let y = params.get("y").and_then(Value::as_f64);
    match (x, y) {
        (Some(x), Some(y)) => target.screen_point(x, y),
        _ => Err("Give either a ref or both x and y (screenshot pixels).".into()),
    }
}

/// Refuse points on the window frame: posted clicks there would start a
/// system move/size loop or hit a caption button the app does not own.
fn ensure_client_area(target: &Target, hwnd: HWND, point: POINT) -> Result<(), String> {
    if hwnd != target.window {
        return Ok(());
    }
    let mut hit: usize = 0;
    let answered = unsafe {
        SendMessageTimeoutW(
            hwnd,
            WM_NCHITTEST,
            WPARAM(0),
            screen_lparam(hwnd, point),
            SMTO_ABORTIFHUNG,
            200,
            Some(&mut hit),
        )
    };
    let hit = hit as isize;
    if answered.0 == 0 || hit == HTCLIENT || hit == HTTRANSPARENT {
        return Ok(());
    }
    Err(format!(
        "That point is on the window's frame or title bar (hit-test {hit}). Background control only reaches the app's content; use key shortcuts or invoke for window-level commands."
    ))
}

fn button_messages(button: &str) -> Result<(u32, u32, u32, usize), String> {
    match button {
        "left" => Ok((WM_LBUTTONDOWN, WM_LBUTTONUP, WM_LBUTTONDBLCLK, MK_LBUTTON)),
        "right" => Ok((WM_RBUTTONDOWN, WM_RBUTTONUP, WM_RBUTTONDBLCLK, MK_RBUTTON)),
        "middle" => Ok((WM_MBUTTONDOWN, WM_MBUTTONUP, WM_MBUTTONDBLCLK, MK_MBUTTON)),
        other => Err(format!("Unknown mouse button {other:?}")),
    }
}

fn pointer_result(target: &Target, hwnd: HWND, point: POINT, extra: Value) -> Value {
    let (x, y) = target.screenshot_point(point);
    merge(
        json!({
            "pointer": { "x": x, "y": y },
            "delivered_to": class_name(hwnd),
            "window": window_title(target.window),
        }),
        extra,
    )
}

pub(super) fn click(emit: &dyn Fn(Value), target: &Target, params: &Value) -> Result<Value, String> {
    let point = pointer_target(target, params)?;
    let button = params.get("button").and_then(Value::as_str).unwrap_or("left");
    let clicks = params.get("clicks").and_then(Value::as_u64).unwrap_or(1).clamp(1, 3);
    let (down, up, double, mask) = button_messages(button)?;
    remember_point(&target.session_id, point);

    // A plain left click goes through UI Automation when it can: always for
    // a ref (the element's own action is exact), and for coordinates in web
    // content, where posted mouse messages do not reach the page.
    if button == "left" && clicks == 1 {
        let reference = params.get("ref").and_then(Value::as_str);
        let mut chain = match reference {
            Some(reference) => vec![element_for(target, reference)?],
            None => Vec::new(),
        };
        if let Some(done) = click_via_automation(emit, target, &chain, point)? {
            return Ok(done);
        }
        if target.web {
            chain = elements_at(target, point)?;
            if let Some(done) = click_via_automation(emit, target, &chain, point)? {
                return Ok(done);
            }
        }
    }

    let hwnd = pointer_window(target, point);
    ensure_client_area(target, hwnd, point)?;
    let lparam = client_lparam(hwnd, point);

    target.travel(emit, point)?;
    target.emit_pointer(emit, point, "press");
    post(hwnd, WM_MOUSEMOVE, 0, lparam)?;
    for index in 0..clicks {
        interrupted()?;
        // The second press of a double click is WM_*BUTTONDBLCLK, as Windows
        // itself would deliver it to a CS_DBLCLKS window.
        let press = if index == 1 { double } else { down };
        post(hwnd, press, mask, lparam)?;
        pause(25);
        post(hwnd, up, 0, lparam)?;
        pause(40);
    }
    target.emit_pointer(emit, point, "click");
    remember_input_window(&target.session_id, hwnd);
    // A posted click put focus somewhere UI Automation did not report.
    forget_editable(&target.session_id);
    let mut extra = json!({ "button": button, "clicks": clicks });
    if target.web {
        extra["note"] = json!(WEB_INPUT_NOTE);
    }
    // A click that opened a menu or dropdown: say so, and for a parked app
    // take it off the user's screen straight away.
    pause(150);
    let popups = open_popups(target.window, target.top, target.pid);
    if popups.iter().any(|popup| !target.popups.contains(popup)) {
        if target.hidden {
            bring_popups_along(&target.session_id, target.top, frame_rect(target.window), &popups);
        }
        extra["note"] = json!("A menu or dropdown opened. Take a screenshot or snapshot to see its items (snapshot lists them first).");
    }
    Ok(pointer_result(target, hwnd, point, extra))
}

/// Said whenever posted input had to be used on web content.
const WEB_INPUT_NOTE: &str = "This app draws web content, which may ignore background mouse clicks. If nothing changed, use snapshot or find, then click or invoke by ref.";

pub(super) fn hover(emit: &dyn Fn(Value), target: &Target, params: &Value) -> Result<Value, String> {
    let point = pointer_target(target, params)?;
    remember_point(&target.session_id, point);
    let hwnd = pointer_window(target, point);
    target.travel(emit, point)?;
    post(hwnd, WM_MOUSEMOVE, 0, client_lparam(hwnd, point))?;
    Ok(pointer_result(target, hwnd, point, json!({})))
}

pub(super) fn scroll(emit: &dyn Fn(Value), target: &Target, params: &Value) -> Result<Value, String> {
    let point = if params.get("ref").is_some() || params.get("x").is_some() {
        pointer_target(target, params)?
    } else {
        POINT {
            x: (target.frame.left + target.frame.right) / 2,
            y: (target.frame.top + target.frame.bottom) / 2,
        }
    };
    let direction = params.get("direction").and_then(Value::as_str).unwrap_or("down");
    let amount = params.get("amount").and_then(Value::as_u64).unwrap_or(3).clamp(1, 50) as i32;
    let (message, delta) = match direction {
        "down" => (WM_MOUSEWHEEL, -WHEEL_DELTA),
        "up" => (WM_MOUSEWHEEL, WHEEL_DELTA),
        "right" => (WM_MOUSEHWHEEL, WHEEL_DELTA),
        "left" => (WM_MOUSEHWHEEL, -WHEEL_DELTA),
        other => return Err(format!("Unknown scroll direction {other:?}")),
    };
    if target.web {
        // Chromium reroutes wheel messages to whatever window is under the
        // user's real cursor, so a posted wheel never reaches a background
        // page. Scroll the scrollable element under the point instead.
        let chain = match params.get("ref").and_then(Value::as_str) {
            Some(reference) => with_ancestors(element_for(target, reference)?),
            None => elements_at(target, point)?,
        };
        target.travel(emit, point)?;
        if let Some(scrolled) = scroll_in_page(&chain, direction, amount) {
            let (x, y) = target.screenshot_point(point);
            return Ok(json!({
                "pointer": { "x": x, "y": y },
                "delivered_to": scrolled,
                "delivered_via": "accessibility",
                "pattern": "ia2_scroll_to_point",
                "window": window_title(target.window),
                "direction": direction,
                "amount": amount,
            }));
        }
        if let Some(scrolled) = scroll_via_automation(&chain, direction, amount)? {
            let (x, y) = target.screenshot_point(point);
            return Ok(json!({
                "pointer": { "x": x, "y": y },
                "delivered_to": scrolled,
                "delivered_via": "ui_automation",
                "pattern": "scroll",
                "window": window_title(target.window),
                "direction": direction,
                "amount": amount,
            }));
        }
    }
    let hwnd = pointer_window(target, point);
    target.travel(emit, point)?;
    // Wheel messages carry screen coordinates, unlike the button messages.
    let wparam = ((delta as i16 as u16 as usize) << 16) as usize;
    for _ in 0..amount {
        interrupted()?;
        post(hwnd, message, wparam, screen_lparam(hwnd, point))?;
        pause(30);
    }
    Ok(pointer_result(
        target,
        hwnd,
        point,
        json!({ "direction": direction, "amount": amount }),
    ))
}

pub(super) fn drag(emit: &dyn Fn(Value), target: &Target, params: &Value) -> Result<Value, String> {
    let from = pointer_target(target, params)?;
    let to_x = params.get("to_x").and_then(Value::as_f64);
    let to_y = params.get("to_y").and_then(Value::as_f64);
    let to = match (to_x, to_y) {
        (Some(x), Some(y)) => target.screen_point(x, y)?,
        _ => return Err("drag needs to_x and to_y (screenshot pixels).".into()),
    };
    target.travel(emit, from)?;
    target.emit_pointer(emit, from, "press");

    // A hidden or fully covered page paints no frames, and Chromium drops
    // every pointer move of a drag then (see Peek). Only a Chromium
    // top-level window (Edge, Electron) tracks its own occlusion like that.
    // A WebView2 control inside another app's window (Teams) is shown and
    // hidden by its host and keeps painting when parked — and making its
    // host layered would stop it painting instead (both measured).
    let occlusion_tracked = class_name(target.window).starts_with("Chrome_WidgetWin");
    let peek = if target.web && occlusion_tracked { Peek::begin(target) } else { None };
    let (from, to) = match &peek {
        Some(peek) => (peek.offset(target, from), peek.offset(target, to)),
        None => (from, to),
    };

    // Every message of a drag goes to the window pressed on: that is the
    // window that would hold mouse capture for a real drag.
    let hwnd = pointer_window(target, from);
    let outcome = ensure_client_area(target, hwnd, from).and_then(|()| {
        post(hwnd, WM_MOUSEMOVE, 0, client_lparam(hwnd, from))?;
        post(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, client_lparam(hwnd, from))?;
        const STEPS: i32 = 14;
        for step in 1..=STEPS {
            let point = POINT {
                x: from.x + (to.x - from.x) * step / STEPS,
                y: from.y + (to.y - from.y) * step / STEPS,
            };
            pause(24);
            if let Err(stopped) = interrupted() {
                // Let go of the button rather than leave the app mid-drag.
                let _ = post(hwnd, WM_LBUTTONUP, 0, client_lparam(hwnd, point));
                return Err(stopped);
            }
            post(hwnd, WM_MOUSEMOVE, MK_LBUTTON, client_lparam(hwnd, point))?;
            target.emit_pointer(emit, point, "drag");
        }
        pause(60);
        post(hwnd, WM_LBUTTONUP, 0, client_lparam(hwnd, to))
    });
    drop(peek);
    outcome?;
    target.emit_pointer(emit, to, "click");
    let (x, y) = target.screenshot_point(to);
    Ok(pointer_result(target, hwnd, from, json!({ "to": { "x": x, "y": y } })))
}
