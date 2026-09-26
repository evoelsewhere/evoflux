//! Accessibility actions — what "clicking" an element means and how it is
//! carried out without being fooled by a menu or dialog it opens — and the
//! `invoke` and `set_value` actions built on them.

use super::*;

/// What "clicking" an element means through accessibility.
pub(super) enum UiAction {
    Action(&'static str),
    /// Expand or collapse an outline row.
    Disclose(bool),
    Select,
}

pub(super) fn ui_action_for(element: &Ax) -> Option<UiAction> {
    let actions = element.actions();
    for action in ["AXPress", "AXConfirm", "AXPick", "AXOpen"] {
        if actions.iter().any(|name| name == action) {
            return Some(UiAction::Action(action));
        }
    }
    if element.settable("AXDisclosing") {
        return Some(UiAction::Disclose(!element.flag("AXDisclosing").unwrap_or(false)));
    }
    if element.settable("AXSelected") && !element.flag("AXSelected").unwrap_or(false) {
        return Some(UiAction::Select);
    }
    None
}

const AX_CANNOT_COMPLETE: AXError = -25204;

pub(super) const STILL_RUNNING_NOTE: &str = "The app is still handling this, most likely in a menu or dialog it opened. Take a snapshot to see it; do not repeat the action.";

/// Perform `action` on `element`. Returns the pattern used, and whether the
/// app is still busy with it.
///
/// A pop-up button or menu button answers AXPress (and anything answers
/// AXShowMenu) only once the menu it opened closes, and a button that runs a
/// modal dialog only once the dialog is dismissed: the call timed out after
/// two seconds and was reported as refused while the menu sat open, inviting
/// a second press. A timeout from an app that still answers a quick question
/// right after is that case, and is reported as delivered. Menu openers get
/// a short timeout so the worker is not held for two seconds.
pub(super) fn perform(element: &Ax, app: &Ax, action: &UiAction) -> Result<(&'static str, bool), AXError> {
    let (label, opens_menu) = match action {
        UiAction::Action(name) => {
            let label = match *name {
                "AXPress" => "press",
                "AXConfirm" => "confirm",
                "AXPick" => "pick",
                "AXShowMenu" => "show_menu",
                _ => "open",
            };
            let menu_role = matches!(element.role().as_str(), "AXPopUpButton" | "AXMenuButton" | "AXMenuBarItem");
            (label, *name == "AXShowMenu" || (*name == "AXPress" && menu_role))
        }
        UiAction::Disclose(open) => (if *open { "expand" } else { "collapse" }, false),
        UiAction::Select => ("select", false),
    };
    if opens_menu {
        element.set_timeout(0.5);
    }
    let result = match action {
        UiAction::Action(name) => element.perform(name),
        UiAction::Disclose(open) => element.set_flag("AXDisclosing", *open),
        UiAction::Select => element.set_flag("AXSelected", true),
    };
    if opens_menu {
        element.set_timeout(AX_TIMEOUT_SECONDS);
    }
    match result {
        Ok(()) => Ok((label, false)),
        Err(AX_CANNOT_COMPLETE) if matches!(action, UiAction::Action(_)) && app.attribute("AXRole").is_some() => {
            Ok((label, true))
        }
        Err(error) => Err(error),
    }
}

pub(super) fn ax_error(error: AXError) -> String {
    let meaning = match error {
        -25200 => "the app refused",
        -25201 => "illegal argument",
        -25202 => "the element is gone",
        -25204 => "the app did not answer in time",
        -25205 => "the attribute is not supported",
        -25206 => "the action is not supported",
        -25211 => "accessibility is not allowed for EvoFlux",
        _ => "accessibility error",
    };
    format!("{meaning} ({error})")
}

// ── Element actions ─────────────────────────────────────────────────────

pub(super) fn invoke(emit: &dyn Fn(Value), target: &Target, params: &Value) -> Result<Value, String> {
    let reference = params.get("ref").and_then(Value::as_str).ok_or("invoke needs a ref.")?;
    let element = element_for(&target.session_id, reference)?;
    let name = element.label();
    let action = ui_action_for(&element).ok_or_else(|| {
        format!("{reference} (\"{name}\") has no press/select/expand action. Click it by ref or coordinates instead.")
    })?;
    if let Some(point) = element_center(&element).filter(|point| target.frame.contains(*point)) {
        target.travel(emit, point)?;
        target.emit_pointer(emit, point, "click");
    }
    if is_editable(&element) {
        remember_editable(&target.session_id, &element);
    }
    let (used, busy) = perform(&element, &target.app, &action)
        .map_err(|error| format!("{reference} (\"{name}\") refused the action: {}", ax_error(error)))?;
    let mut result = json!({ "ref": reference, "name": name, "pattern": used, "window": target.title() });
    if busy {
        result["note"] = json!(STILL_RUNNING_NOTE);
    }
    Ok(result)
}

pub(super) fn set_value(emit: &dyn Fn(Value), target: &Target, params: &Value) -> Result<Value, String> {
    let reference = params.get("ref").and_then(Value::as_str).ok_or("set_value needs a ref.")?;
    let value = params.get("value").and_then(Value::as_str).ok_or("set_value needs a value.")?;
    let element = element_for(&target.session_id, reference)?;
    let direct = params.get("direct").and_then(Value::as_bool).unwrap_or(false);
    if let Some(point) = element_center(&element) {
        target.travel(emit, point)?;
        target.emit_pointer(emit, point, "click");
    }
    // Sliders, steppers and other number-valued controls take a number.
    let current = element.attribute("AXValue");
    if let (Some(number), Some(true)) = (value.trim().parse::<f64>().ok(), current.as_ref().map(|v| cf_number(v).is_some() && v.downcast::<CFBoolean>().is_none())) {
        if !is_text_role(&element.role()) {
            let minimum = element.attribute("AXMinValue").as_ref().and_then(cf_number);
            let maximum = element.attribute("AXMaxValue").as_ref().and_then(cf_number);
            let clamped = match (minimum, maximum) {
                (Some(minimum), Some(maximum)) if maximum > minimum => number.clamp(minimum, maximum),
                _ => number,
            };
            element
                .set("AXValue", &CFNumber::from(clamped).as_CFType())
                .map_err(|error| format!("{reference} refused the value: {}", ax_error(error)))?;
            return Ok(json!({
                "ref": reference,
                "value_chars": value.chars().count(),
                "delivered_via": "accessibility",
                "pattern": "range_value",
                "window": target.title(),
            }));
        }
    }
    if !direct {
        // Replace the text the way typing would, so editors see input (see
        // `fill`); `direct` writes the value without that.
        remember_editable(&target.session_id, &element);
        let mut result = fill(target, Some(&element), value, true, DEFAULT_TYPE_DELAY_MS)?;
        result["ref"] = json!(reference);
        result["value_chars"] = json!(value.chars().count());
        return Ok(result);
    }
    if !element.settable("AXValue") {
        return Err(format!("{reference} does not accept a value. Click it and use type instead."));
    }
    element
        .set("AXValue", &cf_string(value).as_CFType())
        .map_err(|error| format!("{reference} refused the value: {}", ax_error(error)))?;
    Ok(json!({ "ref": reference, "value_chars": value.chars().count(), "window": target.title() }))
}
