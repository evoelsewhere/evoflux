//! Pointer input: `click`, `hover`, `scroll`, `drag`. Accessibility first,
//! since it reaches a background app exactly; otherwise events posted to
//! the app's process, addressed to its window.

use super::*;

// ── Pointer input ───────────────────────────────────────────────────────

pub(super) fn event_source() -> Result<CGEventSource, String> {
    // A private state: what the user holds on the real keyboard does not
    // leak into the agent's events, nor the other way round.
    CGEventSource::new(CGEventSourceStateID::Private)
        .map_err(|()| "Could not create an input event source.".to_string())
}

fn point_cg(point: Point) -> CGPoint {
    CGPoint::new(point.x, point.y)
}

/// Post a mouse event to the app's process, addressed to its window, so
/// AppKit routes it there without the event passing the window server's
/// hit-testing (which would pick whatever is on screen at that point) and
/// without moving the user's cursor.
fn post_mouse(
    target: &Target,
    kind: CGEventType,
    point: Point,
    button: CGMouseButton,
    click_state: i64,
) -> Result<(), String> {
    let event = CGEvent::new_mouse_event(event_source()?, kind, point_cg(point), button)
        .map_err(|()| "Could not create a mouse event.".to_string())?;
    stamp_window(&event, target);
    if click_state > 0 {
        event.set_integer_value_field(EventField::MOUSE_EVENT_CLICK_STATE, click_state);
    }
    event.post_to_pid(target.pid);
    Ok(())
}

fn stamp_window(event: &CGEvent, target: &Target) {
    let window = i64::from(target.window_id);
    event.set_integer_value_field(EventField::MOUSE_EVENT_WINDOW_UNDER_MOUSE_POINTER, window);
    event.set_integer_value_field(
        EventField::MOUSE_EVENT_WINDOW_UNDER_MOUSE_POINTER_THAT_CAN_HANDLE_THIS_EVENT,
        window,
    );
}

/// Where a pointer action lands: a ref's centre or screenshot coordinates.
fn pointer_target(target: &Target, params: &Value) -> Result<Point, String> {
    if let Some(reference) = params.get("ref").and_then(Value::as_str) {
        let element = element_for(&target.session_id, reference)?;
        return element_center(&element)
            .ok_or_else(|| format!("{reference} is not visible on screen; try invoke instead."));
    }
    let x = params.get("x").and_then(Value::as_f64);
    let y = params.get("y").and_then(Value::as_f64);
    match (x, y) {
        (Some(x), Some(y)) => target.screen_point(x, y),
        _ => Err("Give either a ref or both x and y (screenshot pixels).".into()),
    }
}

fn pointer_result(target: &Target, point: Point, delivered_to: &str, extra: Value) -> Value {
    let (x, y) = target.screenshot_point(point);
    merge(
        json!({
            "pointer": { "x": x, "y": y },
            "delivered_to": delivered_to,
            "delivered_via": "posted_event",
            "window": target.title(),
        }),
        extra,
    )
}

/// Said whenever posted mouse events had to be used.
const POSTED_INPUT_NOTE: &str = "macOS apps may ignore mouse events while they are in the background. If nothing changed, use snapshot or find, then click or invoke by ref.";

pub(super) fn click(emit: &dyn Fn(Value), target: &Target, params: &Value) -> Result<Value, String> {
    let point = pointer_target(target, params)?;
    let button = params.get("button").and_then(Value::as_str).unwrap_or("left");
    let clicks = params.get("clicks").and_then(Value::as_u64).unwrap_or(1).clamp(1, 3) as i64;
    let (down, up, mouse_button) = match button {
        "left" => (CGEventType::LeftMouseDown, CGEventType::LeftMouseUp, CGMouseButton::Left),
        "right" => (CGEventType::RightMouseDown, CGEventType::RightMouseUp, CGMouseButton::Right),
        "middle" => (CGEventType::OtherMouseDown, CGEventType::OtherMouseUp, CGMouseButton::Center),
        other => return Err(format!("Unknown mouse button {other:?}")),
    };
    let chain = match params.get("ref").and_then(Value::as_str) {
        Some(reference) => with_ancestors(element_for(&target.session_id, reference)?),
        None => elements_at(target, point),
    };

    // Accessibility first: it reaches a background app exactly, while
    // posted mouse events may be dropped or bring the app forward.
    if clicks == 1 {
        let done = match button {
            "left" => click_via_accessibility(emit, target, &chain, point, params.get("ref").is_none())?,
            "right" => menu_via_accessibility(emit, target, &chain, point)?,
            _ => None,
        };
        if let Some(done) = done {
            return Ok(done);
        }
    }

    target.travel(emit, point)?;
    target.emit_pointer(emit, point, "press");
    post_mouse(target, CGEventType::MouseMoved, point, CGMouseButton::Left, 0)?;
    for index in 1..=clicks {
        interrupted()?;
        post_mouse(target, down, point, mouse_button, index)?;
        pause(25);
        post_mouse(target, up, point, mouse_button, index)?;
        pause(40);
    }
    target.emit_pointer(emit, point, "click");
    let delivered_to = chain.last().map(|element| info(element).short_role().to_string()).unwrap_or_default();
    Ok(pointer_result(
        target,
        point,
        &delivered_to,
        json!({ "button": button, "clicks": clicks, "note": POSTED_INPUT_NOTE }),
    ))
}

/// Click through accessibility: the innermost element under the point that
/// has an action gets it, and a text field there gets focus for typing —
/// with the caret where the click landed, when it is a click at a point
/// (`at_point`) rather than on a ref's centre.
/// Returns `None` when nothing there does, and the caller falls back to
/// posted mouse events.
fn click_via_accessibility(
    emit: &dyn Fn(Value),
    target: &Target,
    chain: &[Ax],
    point: Point,
    at_point: bool,
) -> Result<Option<Value>, String> {
    let editable = chain.iter().rev().find(|element| is_editable(element));
    if let Some(editable) = editable {
        remember_editable(&target.session_id, editable);
    }
    for element in chain.iter().rev() {
        if editable.is_some_and(|field| field.same(element)) {
            break;
        }
        let Some(action) = ui_action_for(element) else {
            continue;
        };
        let name = element.label();
        target.travel(emit, point)?;
        target.emit_pointer(emit, point, "click");
        let (used, busy) = perform(element, &target.app, &action)
            .map_err(|error| format!("\"{name}\" refused the click: {}", ax_error(error)))?;
        let (x, y) = target.screenshot_point(point);
        let mut result = json!({
            "pointer": { "x": x, "y": y },
            "delivered_to": name,
            "delivered_via": "accessibility",
            "pattern": used,
            "window": target.title(),
            "button": "left",
            "clicks": 1,
        });
        if busy {
            result["note"] = json!(STILL_RUNNING_NOTE);
        }
        return Ok(Some(result));
    }
    if let Some(field) = editable {
        target.travel(emit, point)?;
        target.emit_pointer(emit, point, "click");
        let _ = field.set_flag("AXFocused", true);
        // Focusing alone left the caret wherever it was, so text typed after
        // "click here" went somewhere else in the field.
        let caret_placed = at_point && place_caret(field, point);
        let (x, y) = target.screenshot_point(point);
        return Ok(Some(json!({
            "pointer": { "x": x, "y": y },
            "delivered_to": field.label(),
            "delivered_via": "accessibility",
            "pattern": if caret_placed { "place_caret" } else { "focus_for_typing" },
            "window": target.title(),
            "button": "left",
            "clicks": 1,
        })));
    }
    Ok(None)
}

/// Put the field's caret at the character under `point`
/// (`AXRangeForPosition`, then an empty `AXSelectedTextRange` there).
fn place_caret(field: &Ax, point: Point) -> bool {
    let Some(position) = ax_point_value(point.x, point.y) else {
        return false;
    };
    let Some(range) = field
        .parameterized("AXRangeForPosition", &position)
        .as_ref()
        .and_then(|value| ax_value::<RangeValue>(value, AX_VALUE_CFRANGE))
    else {
        return false;
    };
    match ax_range_value(range.location.max(0) as usize, 0) {
        Some(caret) => field.set("AXSelectedTextRange", &caret).is_ok(),
        None => false,
    }
}

/// A right click is a request for the context menu, which accessibility
/// opens directly.
fn menu_via_accessibility(
    emit: &dyn Fn(Value),
    target: &Target,
    chain: &[Ax],
    point: Point,
) -> Result<Option<Value>, String> {
    let Some(element) = chain
        .iter()
        .rev()
        .find(|element| element.actions().iter().any(|name| name == "AXShowMenu"))
    else {
        return Ok(None);
    };
    target.travel(emit, point)?;
    target.emit_pointer(emit, point, "click");
    let (_, busy) = perform(element, &target.app, &UiAction::Action("AXShowMenu"))
        .map_err(|error| format!("The context menu did not open: {}", ax_error(error)))?;
    let (x, y) = target.screenshot_point(point);
    let mut result = json!({
        "pointer": { "x": x, "y": y },
        "delivered_to": element.label(),
        "delivered_via": "accessibility",
        "pattern": "show_menu",
        "window": target.title(),
        "button": "right",
        "clicks": 1,
    });
    if busy {
        result["note"] = json!(STILL_RUNNING_NOTE);
    }
    Ok(Some(result))
}

pub(super) fn hover(emit: &dyn Fn(Value), target: &Target, params: &Value) -> Result<Value, String> {
    let point = pointer_target(target, params)?;
    target.travel(emit, point)?;
    post_mouse(target, CGEventType::MouseMoved, point, CGMouseButton::Left, 0)?;
    Ok(pointer_result(target, point, "window", json!({})))
}

/// The scroll bar of the innermost scroll area in `chain` for a direction.
fn scroll_bar(chain: &[Ax], vertical: bool) -> Option<(Ax, Ax)> {
    let attribute = if vertical { "AXVerticalScrollBar" } else { "AXHorizontalScrollBar" };
    chain
        .iter()
        .rev()
        .find_map(|element| element.element(attribute).map(|bar| (element.clone(), bar)))
}

fn scroll_bar_value(bar: &Ax) -> Option<f64> {
    bar.attribute("AXValue").as_ref().and_then(cf_number)
}

pub(super) fn scroll(emit: &dyn Fn(Value), target: &Target, params: &Value) -> Result<Value, String> {
    let point = if params.get("ref").is_some() || params.get("x").is_some() {
        pointer_target(target, params)?
    } else {
        target.frame.center()
    };
    let direction = params.get("direction").and_then(Value::as_str).unwrap_or("down");
    let amount = params.get("amount").and_then(Value::as_u64).unwrap_or(3).clamp(1, 50) as i32;
    // Line units: positive is up / left, as a wheel reports it.
    let (vertical, lines) = match direction {
        "down" => (true, -amount),
        "up" => (true, amount),
        "right" => (false, -amount),
        "left" => (false, amount),
        other => return Err(format!("Unknown scroll direction {other:?}")),
    };
    let chain = match params.get("ref").and_then(Value::as_str) {
        Some(reference) => with_ancestors(element_for(&target.session_id, reference)?),
        None => elements_at(target, point),
    };
    let bar = scroll_bar(&chain, vertical);
    let before = bar.as_ref().and_then(|(_, bar)| scroll_bar_value(bar));
    target.travel(emit, point)?;
    for _ in 0..amount {
        interrupted()?;
        let step = lines.signum();
        let (wheel1, wheel2) = if vertical { (step, 0) } else { (0, step) };
        let event = CGEvent::new_scroll_event(event_source()?, ScrollEventUnit::LINE, 2, wheel1, wheel2, 0)
            .map_err(|()| "Could not create a scroll event.".to_string())?;
        event.set_location(point_cg(point));
        stamp_window(&event, target);
        event.post_to_pid(target.pid);
        pause(30);
    }
    pause(150);
    let mut result = pointer_result(target, point, "scroll area", json!({ "direction": direction, "amount": amount }));
    // A background app may ignore the wheel. Its scroll bar tells: when the
    // position did not move, move the scroll bar itself.
    if let (Some((area, bar)), Some(before)) = (&bar, before) {
        let after = scroll_bar_value(bar).unwrap_or(before);
        if (after - before).abs() < 1e-6 && bar.settable("AXValue") {
            let delta = f64::from(-lines) * 0.05;
            let value = (before + delta).clamp(0.0, 1.0);
            bar.set("AXValue", &CFNumber::from(value).as_CFType())
                .map_err(|error| format!("The scroll bar refused to move: {}", ax_error(error)))?;
            result["delivered_to"] = json!(area.label());
            result["delivered_via"] = json!("accessibility");
            result["pattern"] = json!("scroll_bar");
        }
    }
    Ok(result)
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
    post_mouse(target, CGEventType::MouseMoved, from, CGMouseButton::Left, 0)?;
    post_mouse(target, CGEventType::LeftMouseDown, from, CGMouseButton::Left, 1)?;
    const STEPS: i32 = 14;
    for step in 1..=STEPS {
        let t = f64::from(step) / f64::from(STEPS);
        let point = Point { x: from.x + (to.x - from.x) * t, y: from.y + (to.y - from.y) * t };
        pause(24);
        if let Err(stopped) = interrupted() {
            // Let go of the button rather than leave the app mid-drag.
            let _ = post_mouse(target, CGEventType::LeftMouseUp, point, CGMouseButton::Left, 1);
            return Err(stopped);
        }
        post_mouse(target, CGEventType::LeftMouseDragged, point, CGMouseButton::Left, 1)?;
        target.emit_pointer(emit, point, "drag");
    }
    pause(60);
    post_mouse(target, CGEventType::LeftMouseUp, to, CGMouseButton::Left, 1)?;
    target.emit_pointer(emit, to, "click");
    let (x, y) = target.screenshot_point(to);
    Ok(pointer_result(
        target,
        from,
        "window",
        json!({ "to": { "x": x, "y": y }, "note": POSTED_INPUT_NOTE }),
    ))
}
