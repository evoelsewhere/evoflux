//! Input carried out through UI Automation (and IAccessible2) rather than
//! posted messages: clicks and scrolls that web content would ignore,
//! `invoke`, and `set_value`.

use super::*;

/// Scroll the innermost element in `chain` that can scroll that way, inside
/// the page, through IAccessible2. Returns its name, or `None` when nothing
/// there scrolls that way or IAccessible2 cannot be reached.
///
/// UI Automation's Scroll has Chromium focus its widget, which activates the
/// window: scrolling took the foreground from the user's window whenever
/// Windows let it. Posted wheels do not help: Chromium reroutes them to the
/// window under the point, and a hidden Edge page does not scroll to them.
/// IAccessible2's scrollToPoint — what screen readers call — goes to the
/// page's own accessibility code: the scroller's first child is asked to move
/// its top-left corner by the distance to scroll, so the scroller scrolls by
/// that much. It cannot be read back: a hidden Edge page stops updating its
/// accessibility values.
pub(super) fn scroll_in_page(chain: &[IUIAutomationElement], direction: &str, amount: i32) -> Option<String> {
    use windows::Win32::System::Com::{IDispatch, IServiceProvider};
    const IID_IACCESSIBLE2: windows::core::GUID = windows::core::GUID::from_u128(0xE89F726E_C4F4_4c19_BB19_B647D7FA8478);
    // IAccessible2's vtable (IA2 IDL): IUnknown 0–2, IDispatch 3–6,
    // IAccessible 7–27, then get_nRelations, get_relation, get_relations,
    // role, scrollTo, scrollToPoint. The windows crate has no IAccessible2.
    const SCROLL_TO_POINT: usize = 33;
    const RELEASE: usize = 2;
    const IA2_COORDTYPE_SCREEN_RELATIVE: i32 = 0;
    /// Roughly one wheel notch in Chromium.
    const PIXELS_PER_NOTCH: i32 = 100;

    let vertical = matches!(direction, "up" | "down");
    let scroller = chain.iter().rev().find(|element| {
        pattern::<IUIAutomationScrollPattern>(element, UIA_ScrollPatternId).is_some_and(|scroller| {
            unsafe {
                if vertical {
                    scroller.CurrentVerticallyScrollable()
                } else {
                    scroller.CurrentHorizontallyScrollable()
                }
            }
            .is_ok_and(|flag| flag.as_bool())
        })
    })?;
    let walker = unsafe { automation().ok()?.ControlViewWalker() }.ok()?;
    let child = unsafe { walker.GetFirstChildElement(scroller) }.ok()?;
    let at = unsafe { child.CurrentBoundingRectangle() }.ok()?;
    // The page's MSAA root, from the nearest window: the render host, or the
    // top-level window for a WebView2 without one. Its hit test gives the
    // child's own IAccessible (Chromium's UI Automation elements have none).
    let mut current = Some(scroller.clone());
    let mut host = None;
    while let Some(element) = current {
        if let Ok(hwnd) = unsafe { element.CurrentNativeWindowHandle() } {
            if !hwnd.0.is_null() {
                host = Some(hwnd);
                break;
            }
        }
        current = unsafe { walker.GetParentElement(&element) }.ok();
    }
    let mut object: *mut core::ffi::c_void = std::ptr::null_mut();
    unsafe { AccessibleObjectFromWindow(host?, 0xFFFF_FFFC, &IAccessible::IID, &mut object) }.ok()?; // OBJID_CLIENT
    if object.is_null() {
        return None;
    }
    let root = unsafe { IAccessible::from_raw(object) };
    let hit = unsafe { root.accHitTest((at.left + at.right) / 2, (at.top + at.bottom) / 2) }.ok()?;
    let accessible: IAccessible = IDispatch::try_from(&hit).ok()?.cast().ok()?;
    let provider: IServiceProvider = accessible.cast().ok()?;
    let mut ia2: *mut core::ffi::c_void = std::ptr::null_mut();
    unsafe { (Interface::vtable(&provider).QueryService)(provider.as_raw(), &IAccessible::IID, &IID_IACCESSIBLE2, &mut ia2) }
        .ok()
        .ok()?;
    if ia2.is_null() {
        return None;
    }
    let step = PIXELS_PER_NOTCH * amount;
    let (x, y) = match direction {
        "down" => (at.left, at.top - step),
        "up" => (at.left, at.top + step),
        "right" => (at.left - step, at.top),
        _ => (at.left + step, at.top),
    };
    let scrolled = unsafe {
        let vtable = *(ia2 as *const *const usize);
        let scroll_to_point: unsafe extern "system" fn(*mut core::ffi::c_void, i32, i32, i32) -> windows::core::HRESULT =
            std::mem::transmute(*vtable.add(SCROLL_TO_POINT));
        let release: unsafe extern "system" fn(*mut core::ffi::c_void) -> u32 = std::mem::transmute(*vtable.add(RELEASE));
        let result = scroll_to_point(ia2, IA2_COORDTYPE_SCREEN_RELATIVE, x, y);
        release(ia2);
        result.is_ok()
    };
    scrolled.then(|| bstr(unsafe { scroller.CurrentName() }))
}

/// Scroll the innermost element in `chain` that can scroll that way.
/// Returns its name, or `None` when nothing there scrolls.
pub(super) fn scroll_via_automation(
    chain: &[IUIAutomationElement],
    direction: &str,
    amount: i32,
) -> Result<Option<String>, String> {
    let vertical = matches!(direction, "up" | "down");
    let (horizontal_step, vertical_step) = match direction {
        "down" => (ScrollAmount_NoAmount, ScrollAmount_SmallIncrement),
        "up" => (ScrollAmount_NoAmount, ScrollAmount_SmallDecrement),
        "right" => (ScrollAmount_SmallIncrement, ScrollAmount_NoAmount),
        _ => (ScrollAmount_SmallDecrement, ScrollAmount_NoAmount),
    };
    for element in chain.iter().rev() {
        let Some(scroller) = pattern::<IUIAutomationScrollPattern>(element, UIA_ScrollPatternId) else {
            continue;
        };
        let scrollable = unsafe {
            if vertical {
                scroller.CurrentVerticallyScrollable()
            } else {
                scroller.CurrentHorizontallyScrollable()
            }
        }
        .map(|flag| flag.as_bool())
        .unwrap_or(false);
        if !scrollable {
            continue;
        }
        // Three small steps per wheel notch, like a default wheel setting.
        for _ in 0..amount * 3 {
            if unsafe { scroller.Scroll(horizontal_step, vertical_step) }.is_err() {
                break;
            }
        }
        return Ok(Some(bstr(unsafe { element.CurrentName() })));
    }
    Ok(None)
}

/// Pick an option of an open `<select>` list with the keys a person would
/// press — Down or Up from the option now chosen to this one, then Enter —
/// and return its name; `None` when `element` is not such an option.
///
/// Invoking the option through UI Automation had Chromium focus the list's
/// widget, which activated the window now and then and took the foreground
/// from the user's window; the MSAA default action does not pick it. While
/// the list is open, Chromium passes the page's keys on to it.
fn pick_popup_option(target: &Target, element: &IUIAutomationElement) -> Result<Option<String>, String> {
    const LIST_ITEM: i32 = 50007;
    if unsafe { element.CurrentControlType() }.map(|kind| kind.0) != Ok(LIST_ITEM) {
        return Ok(None);
    }
    let walker = automation().and_then(|automation| {
        unsafe { automation.ControlViewWalker() }.map_err(|error| error.to_string())
    })?;
    // Only in an open popup of the window.
    if !element_center(element).is_some_and(|centre| target.popup_at(centre).is_some()) {
        return Ok(None);
    }
    let Ok(list) = (unsafe { walker.GetParentElement(element) }) else {
        return Ok(None);
    };
    let mut options = Vec::new();
    let mut next = unsafe { walker.GetFirstChildElement(&list) }.ok();
    while let Some(option) = next {
        next = unsafe { walker.GetNextSiblingElement(&option) }.ok();
        options.push(option);
    }
    let same = |a: &IUIAutomationElement, b: &IUIAutomationElement| {
        automation()
            .ok()
            .and_then(|automation| unsafe { automation.CompareElements(a, b) }.ok())
            .is_some_and(|equal| equal.as_bool())
    };
    let Some(wanted) = options.iter().position(|option| same(option, element)) else {
        return Ok(None);
    };
    let chosen = options
        .iter()
        .position(|option| {
            pattern::<IUIAutomationSelectionItemPattern>(option, UIA_SelectionItemPatternId)
                .is_some_and(|item| unsafe { item.CurrentIsSelected() }.is_ok_and(|selected| selected.as_bool()))
        })
        .unwrap_or(0);
    let input = chromium_input_window(target, None);
    let thread = unsafe { GetWindowThreadProcessId(input, None) };
    let steps = wanted as i64 - chosen as i64;
    if steps != 0 {
        let key = parse_key_combo(if steps > 0 { "down" } else { "up" })?;
        post_key(input, thread, &key, steps.unsigned_abs())?;
    }
    post_key(input, thread, &parse_key_combo("enter")?, 1)?;
    Ok(Some(bstr(unsafe { element.CurrentName() })))
}

/// Click through UI Automation: the innermost element under the point that
/// has an action gets it. Returns `None` when nothing there has one, and the
/// caller falls back to posted mouse input.
pub(super) fn click_via_automation(
    emit: &dyn Fn(Value),
    target: &Target,
    chain: &[IUIAutomationElement],
    point: POINT,
) -> Result<Option<Value>, String> {
    match chain.iter().rev().find(|element| is_editable(element)) {
        Some(editable) => remember_editable(&target.session_id, editable),
        // Clicking anything else (a button, a list item) moves focus away
        // from the field clicked before.
        None if !chain.is_empty() => forget_editable(&target.session_id),
        None => {}
    }
    if let Some(option) = chain.last().filter(|_| target.web) {
        if let Some(name) = pick_popup_option(target, option)? {
            target.travel(emit, point)?;
            target.emit_pointer(emit, point, "click");
            let (x, y) = target.screenshot_point(point);
            return Ok(Some(json!({
                "pointer": { "x": x, "y": y },
                "delivered_to": name,
                "delivered_via": "keyboard",
                "pattern": "pick_option",
                "window": window_title(target.window),
                "button": "left",
                "clicks": 1,
            })));
        }
    }
    for element in chain.iter().rev() {
        let Some(action) = ui_action_for(element, target.web) else {
            continue;
        };
        let name = bstr(unsafe { element.CurrentName() });
        target.travel(emit, point)?;
        target.emit_pointer(emit, point, "click");
        let (used, busy) = perform(element, action).map_err(|error| format!("\"{name}\" refused the click: {error}"))?;
        let (x, y) = target.screenshot_point(point);
        let mut result = json!({
            "pointer": { "x": x, "y": y },
            "delivered_to": name,
            "delivered_via": "ui_automation",
            "pattern": used,
            "window": window_title(target.window),
            "button": "left",
            "clicks": 1,
        });
        if busy {
            result["note"] = json!(STILL_RUNNING_NOTE);
        }
        return Ok(Some(result));
    }
    // In web content a text field has no action and posted clicks cannot
    // reach it; remembering it is what makes the next `type` land there.
    // Native apps get a real (posted) click instead, which places the caret.
    if target.web && chain.iter().any(|element| is_editable(element)) {
        target.travel(emit, point)?;
        target.emit_pointer(emit, point, "click");
        let (x, y) = target.screenshot_point(point);
        return Ok(Some(json!({
            "pointer": { "x": x, "y": y },
            "delivered_to": "text field",
            "delivered_via": "ui_automation",
            "pattern": "focus_for_typing",
            "window": window_title(target.window),
            "button": "left",
            "clicks": 1,
        })));
    }
    Ok(None)
}

pub(super) fn invoke(emit: &dyn Fn(Value), target: &Target, params: &Value) -> Result<Value, String> {
    let reference = params.get("ref").and_then(Value::as_str).ok_or("invoke needs a ref.")?;
    let element = element_for(target, reference)?;
    let name = bstr(unsafe { element.CurrentName() });
    let action = ui_action_for(&element, target.web).ok_or_else(|| {
        format!("{reference} (\"{name}\") has no invoke/toggle/select/expand action. Click it by ref or coordinates instead.")
    })?;
    if let Some(point) = element_center(&element) {
        target.travel(emit, point)?;
        target.emit_pointer(emit, point, "click");
    }
    if is_editable(&element) {
        remember_editable(&target.session_id, &element);
    } else {
        forget_editable(&target.session_id);
    }
    let (used, busy) = perform(&element, action)
        .map_err(|error| format!("{reference} (\"{name}\") refused the action: {error}"))?;
    let mut result = json!({ "ref": reference, "name": name, "pattern": used, "window": window_title(target.window) });
    if busy {
        result["note"] = json!(STILL_RUNNING_NOTE);
    }
    Ok(result)
}

pub(super) fn set_value(emit: &dyn Fn(Value), target: &Target, params: &Value) -> Result<Value, String> {
    let reference = params.get("ref").and_then(Value::as_str).ok_or("set_value needs a ref.")?;
    let value = params.get("value").and_then(Value::as_str).ok_or("set_value needs a value.")?;
    let element = element_for(target, reference)?;
    let direct = params.get("direct").and_then(Value::as_bool).unwrap_or(false);
    // Sliders, spinners and progress-like controls take a number.
    if let Some(range) = pattern::<IUIAutomationRangeValuePattern>(&element, UIA_RangeValuePatternId) {
        if let Ok(number) = value.trim().parse::<f64>() {
            if let Some(point) = element_center(&element) {
                target.travel(emit, point)?;
                target.emit_pointer(emit, point, "click");
            }
            let (minimum, maximum) = unsafe { (range.CurrentMinimum(), range.CurrentMaximum()) };
            let clamped = match (minimum, maximum) {
                (Ok(minimum), Ok(maximum)) if maximum > minimum => number.clamp(minimum, maximum),
                _ => number,
            };
            // In web content through MSAA: Chromium carries out the range
            // pattern's SetValue by focusing its widget, which activates the
            // window (see `focus_in_page`).
            let set_in_page = target.web
                && pattern::<IUIAutomationLegacyIAccessiblePattern>(&element, UIA_LegacyIAccessiblePatternId)
                    .is_some_and(|legacy| unsafe { legacy.SetValue(&windows::core::HSTRING::from(clamped.to_string())) }.is_ok());
            if !set_in_page {
                unsafe { range.SetValue(clamped) }
                    .map_err(|error| format!("{reference} refused the value: {error}"))?;
            }
            return Ok(json!({
                "ref": reference,
                "value_chars": value.chars().count(),
                "delivered_via": "ui_automation",
                "pattern": "range_value",
                "window": window_title(target.window),
            }));
        }
    }
    if target.web && !direct {
        // Replace through the keyboard so the page sees input events (see
        // web_fill); `direct` writes the value without them.
        if let Some(point) = element_center(&element) {
            target.travel(emit, point)?;
            target.emit_pointer(emit, point, "click");
        }
        remember_editable(&target.session_id, &element);
        let mut result = web_fill(target, Some(&element), value, true)?;
        result["ref"] = json!(reference);
        result["value_chars"] = json!(value.chars().count());
        return Ok(result);
    }
    let pattern: IUIAutomationValuePattern = unsafe { element.GetCurrentPattern(UIA_ValuePatternId) }
        .ok()
        .and_then(|pattern| pattern.cast().ok())
        .ok_or_else(|| format!("{reference} does not accept a value. Click it and use type instead."))?;
    if unsafe { pattern.CurrentIsReadOnly() }.map(|ro| ro.as_bool()).unwrap_or(false) {
        return Err(format!("{reference} is read-only."));
    }
    if let Some(point) = element_center(&element) {
        target.travel(emit, point)?;
        target.emit_pointer(emit, point, "click");
    }
    unsafe { pattern.SetValue(&BSTR::from(value)) }
        .map_err(|error| format!("{reference} refused the value: {error}"))?;
    Ok(json!({ "ref": reference, "value_chars": value.chars().count(), "window": window_title(target.window) }))
}
