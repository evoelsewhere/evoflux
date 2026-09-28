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

/// Whether `action` on `element` opens a menu: a pop-up or menu button
/// pressed, or any element's context menu.
pub(super) fn opens_menu(element: &Ax, action: &UiAction) -> bool {
    match action {
        UiAction::Action("AXShowMenu") => true,
        UiAction::Action("AXPress") => {
            matches!(element.role().as_str(), "AXPopUpButton" | "AXMenuButton" | "AXMenuBarItem")
        }
        _ => false,
    }
}

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
    let opens_menu = opens_menu(element, action);
    let label = match action {
        UiAction::Action(name) => match *name {
            "AXPress" => "press",
            "AXConfirm" => "confirm",
            "AXPick" => "pick",
            "AXShowMenu" => "show_menu",
            _ => "open",
        },
        UiAction::Disclose(open) => if *open { "expand" } else { "collapse" },
        UiAction::Select => "select",
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
    if opens_menu(&element, &action) {
        settle_menu(target, &element, None, &mut result)?;
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
    if element.role() == "AXPopUpButton" {
        return choose_option(target, &element, reference, value);
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

// ── Menus a press opens ─────────────────────────────────────────────────
//
// macOS keeps a menu on a display: one a parked app opens shows in the
// corner of the user's screen, and EvoFlux cannot move another app's menu.
// So a menu is dealt with within the action that opened it — its item
// pressed (`menu_item`, `set_value` on a pop-up) or, while the app is
// parked, its items read and the menu closed — instead of staying up over
// the user's work until the agent's next call.

pub(super) const PARKED_MENU_NOTE: &str = "The app is kept off-screen, where macOS would have shown this menu on the user's screen, so it was read and closed. To pick one of its items, repeat this click with menu_item set to the item's title (set_value for a pop-up list).";

/// The app's menu windows on screen: pop-up menus and context menus sit
/// at the pop-up menu level (101), above the window.
fn menu_windows(target: &Target) -> Vec<CgWindow> {
    cg_windows(kCGWindowListOptionAll, kCGNullWindowID)
        .into_iter()
        .filter(|window| window.onscreen && window.pid == target.pid && window.id != target.window_id)
        .filter(|window| window.layer >= 101)
        .filter(|window| !window.bounds.is_empty())
        .collect()
}

fn has_items(menu: &Ax) -> bool {
    menu.elements("AXChildren").iter().any(|item| item.role() == "AXMenuItem")
}

/// The menu `opener` has open. Where a menu is in the tree varies — a child
/// of the opener (a pop-up or menu button, a menu bar item), a child of the
/// app, or only reachable from the menu window — so the menu window is
/// hit-tested at its centre first, then the children are tried. Only a menu
/// drawn in a menu window on screen counts: Chromium keeps a `<select>`'s
/// last menu, items and all, as a child after it closed, and pressing its
/// items did nothing. Waited for until the menu has items, since Chromium
/// adds the element before it fills it in.
fn wait_for_menu(target: &Target, opener: &Ax) -> Option<Ax> {
    let is_menu = |element: &Ax| element.role() == "AXMenu" && has_items(element);
    for attempt in 0..15 {
        let windows = menu_windows(target);
        let shown = |menu: &Ax| {
            menu.frame().is_some_and(|frame| windows.iter().any(|window| window.bounds.intersects(&frame)))
        };
        let menu = windows
            .iter()
            .find_map(|window| {
                let hit = target.app.element_at_position(window.bounds.center())?;
                with_ancestors(hit).into_iter().rev().find(|element| is_menu(element))
            })
            .or_else(|| {
                opener
                    .elements("AXChildren")
                    .into_iter()
                    .chain(target.app.elements("AXChildren"))
                    .find(|child| is_menu(child) && shown(child))
            });
        if menu.is_some() {
            return menu;
        }
        if attempt < 14 {
            pause(100);
        }
    }
    None
}

/// Close the open menu and wait until its window is gone; Escape is posted
/// to the app when `AXCancel` did not close it.
fn close_menu(target: &Target, menu: &Ax) {
    let closed = || {
        (0..6).any(|_| {
            pause(50);
            menu_windows(target).is_empty()
        })
    };
    let _ = menu.perform("AXCancel");
    if !closed() {
        let _ = post_keycode(target.pid, KEY_ESCAPE, CGEventFlags::CGEventFlagNull, 1);
        if !closed() {
            log::warn!("computer app: a menu of {} did not close", target.app_name);
        }
    }
}

fn menu_items(menu: &Ax) -> (Vec<Ax>, Vec<String>) {
    let items: Vec<Ax> = menu.elements("AXChildren").into_iter().filter(|item| item.role() == "AXMenuItem").collect();
    // Chromium's <select> options have no AXTitle; their name is elsewhere.
    let titles = items.iter().map(Ax::label).collect();
    (items, titles)
}

/// The item whose title is `wanted`, or else the only one starting with it.
pub(super) fn matching_option(titles: &[String], wanted: &str) -> Option<usize> {
    let wanted = wanted.trim().to_lowercase();
    let lowered: Vec<String> = titles.iter().map(|title| title.trim().to_lowercase()).collect();
    if let Some(exact) = lowered.iter().position(|title| *title == wanted) {
        return Some(exact);
    }
    let mut starting = lowered.iter().enumerate().filter(|(_, title)| title.starts_with(&wanted));
    match (starting.next(), starting.next()) {
        (Some((index, _)), None) => Some(index),
        _ => None,
    }
}

/// Press the item of the open `menu` titled `wanted`; its title. The menu
/// is closed when no item matches or the press is refused.
fn press_menu_item(target: &Target, menu: &Ax, wanted: &str) -> Result<String, String> {
    let (items, titles) = menu_items(menu);
    let Some(index) = matching_option(&titles, wanted) else {
        close_menu(target, menu);
        let offered: Vec<&str> = titles.iter().map(String::as_str).filter(|title| !title.is_empty()).take(40).collect();
        return Err(format!("The menu has no item {wanted:?}. Its items: {}", offered.join(", ")));
    };
    let item = &items[index];
    let shown: Vec<u32> = menu_windows(target).iter().map(|window| window.id).collect();
    item.set_timeout(0.5);
    let pressed = item.perform("AXPress");
    item.set_timeout(AX_TIMEOUT_SECONDS);
    // An item may answer only once its menu has finished closing.
    match pressed {
        Ok(()) | Err(AX_CANNOT_COMPLETE) => {
            // Never leave a menu up on the user's screen: one still showing
            // after the press (it went to a menu that was not the one
            // drawn) is closed. macOS fades a menu out, so it is given a
            // second; windows the item itself opened do not count.
            let gone = || !menu_windows(target).iter().any(|window| shown.contains(&window.id));
            if !(0..20).any(|_| {
                pause(50);
                gone()
            }) {
                close_menu(target, menu);
                return Err(format!(
                    "The menu stayed open after pressing {:?}, so it was closed; the item may not have been chosen. Take a snapshot to check.",
                    titles[index]
                ));
            }
            Ok(titles[index].clone())
        }
        Err(error) => {
            close_menu(target, menu);
            Err(format!("The menu item {:?} refused the press: {}", titles[index], ax_error(error)))
        }
    }
}

/// After a press that opens a menu: press `menu_item` in it, or — while the
/// app is parked — read the menu into `result` and close it.
pub(super) fn settle_menu(target: &Target, opener: &Ax, menu_item: Option<&str>, result: &mut Value) -> Result<(), String> {
    if menu_item.is_none() && !target.hidden {
        return Ok(());
    }
    let Some(menu) = wait_for_menu(target, opener) else {
        return match menu_item {
            Some(_) => Err("The click opened no menu to pick menu_item from. Take a snapshot to see what it did.".into()),
            None => Ok(()),
        };
    };
    let object = result.as_object_mut().expect("click results are objects");
    // The menu is dealt with here; nothing is left running.
    object.remove("note");
    match menu_item {
        Some(wanted) => {
            let chosen = press_menu_item(target, &menu, wanted)?;
            if opener.role() == "AXPopUpButton" {
                object.insert("value".into(), json!(read_back_option(opener, &chosen)));
            }
            object.insert("menu_item".into(), json!(chosen));
        }
        None => {
            let (items, titles) = menu_items(&menu);
            let listed: Vec<String> = items
                .iter()
                .zip(titles)
                .filter(|(_, title)| !title.is_empty())
                .map(|(item, title)| if item.flag("AXEnabled") == Some(false) { format!("{title} (disabled)") } else { title })
                .collect();
            close_menu(target, &menu);
            object.insert("menu".into(), json!(listed));
            object.insert("menu_closed".into(), json!(true));
            object.insert("note".into(), json!(PARKED_MENU_NOTE));
        }
    }
    Ok(())
}

/// A pop-up button's value once it shows `chosen`, or after a second what
/// it shows then: Chromium reports the new value a moment after the menu
/// closes.
fn read_back_option(button: &Ax, chosen: &str) -> String {
    let mut now = String::new();
    for _ in 0..8 {
        pause(125);
        now = button.string("AXValue").unwrap_or_default();
        if matching_option(std::slice::from_ref(&now), chosen).is_some() {
            break;
        }
    }
    now
}

/// Pick an option of a pop-up button (a `<select>`, an NSPopUpButton):
/// its value is not settable and typing into it does nothing. The menu is
/// opened, the item pressed and the value read back in one action.
fn choose_option(target: &Target, button: &Ax, reference: &str, value: &str) -> Result<Value, String> {
    let before = button.string("AXValue").unwrap_or_default();
    let result = |pattern: &str, now: String| {
        json!({
            "ref": reference,
            "value_chars": value.chars().count(),
            "value": now,
            "confirmed": matching_option(std::slice::from_ref(&now), value).is_some(),
            "delivered_via": "accessibility",
            "pattern": pattern,
            "window": target.title(),
        })
    };
    if matching_option(std::slice::from_ref(&before), value).is_some() {
        return Ok(result("already_set", before));
    }
    perform(button, &target.app, &UiAction::Action("AXPress"))
        .map_err(|error| format!("{reference} did not open its options: {}", ax_error(error)))?;
    let menu = wait_for_menu(target, button)
        .ok_or_else(|| format!("{reference} opened no list of options. Take a snapshot to see it."))?;
    let chosen = press_menu_item(target, &menu, value).map_err(|error| format!("{reference}: {error}"))?;
    Ok(result("choose", read_back_option(button, &chosen)))
}
