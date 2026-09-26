//! Typing into web page fields with real keyboard events, and reading the
//! field back to confirm — or saying why it cannot be confirmed.

use super::*;

pub(super) fn field_value(element: &IUIAutomationElement) -> Option<String> {
    let value: IUIAutomationValuePattern = pattern(element, UIA_ValuePatternId)?;
    Some(bstr(unsafe { value.CurrentValue() }))
}

/// Compare what a field holds with what was typed, ignoring the line-break
/// and whitespace differences editors introduce.
pub(super) fn squash(text: &str) -> String {
    text.split_whitespace().collect::<Vec<_>>().join(" ")
}

/// Whether typing into a web field a second time is safe: the read-back is
/// live, both reads worked, the text is not there and nothing changed at
/// all. A field that reports no value (no Value pattern, a stale element)
/// reads "unchanged" every time — retyping it only doubled the text.
pub(super) fn should_retype(readback_is_live: bool, before: &Option<String>, after: &Option<String>, landed: bool) -> bool {
    readback_is_live && before.is_some() && after.is_some() && !landed && after == before
}

/// Move the page's keyboard focus to `field` without activating its window.
///
/// UI Automation's SetFocus has Chromium focus its widget, which activates
/// the window: typing into a WebView2 app (Teams) or a parked Edge took the
/// foreground from whatever the user was working in. The MSAA "take focus"
/// selection, reached through the LegacyIAccessible pattern, focuses the
/// element inside the page only. SetFocus stays for a window in front
/// already, where it takes nothing from anyone.
fn focus_in_page(target: &Target, field: &IUIAutomationElement) {
    const SELFLAG_TAKEFOCUS: i32 = 0x1;
    let taken = pattern::<IUIAutomationLegacyIAccessiblePattern>(field, UIA_LegacyIAccessiblePatternId)
        .is_some_and(|legacy| unsafe { legacy.Select(SELFLAG_TAKEFOCUS) }.is_ok());
    if !taken && unsafe { GetForegroundWindow() } == target.window {
        let _ = unsafe { field.SetFocus() };
    }
}

/// Type into a web page field the way a keyboard would.
///
/// Chromium takes characters posted to its window and delivers them to the
/// page's focused element with real `beforeinput`/`input` events — which is
/// what rich editors (the Teams compose box, anything built on React) need to
/// notice the text at all. Setting the value through UI Automation changes the
/// DOM without those events, so it is never done behind the agent's back;
/// `set_value` with `direct` asks for it explicitly.
///
/// The field's value is read back to confirm, but a hidden page may report a
/// stale value (Chromium pauses accessibility updates for it), so an
/// unconfirmed result is reported as such rather than "repaired" — writing a
/// value computed from a stale read would erase what was really typed.
///
/// The field is focused inside the page (see [`focus_in_page`]), which does
/// not activate the window; the user's foreground stays put.
pub(super) fn web_fill(
    target: &Target,
    field: Option<&IUIAutomationElement>,
    text: &str,
    replace: bool,
) -> Result<Value, String> {
    let before = field.and_then(field_value);
    // Keys go to the Chromium widget showing the field — for a WebView2 host
    // such as Teams that is a window of the WebView2 process, not the app's.
    let input = chromium_input_window(target, field.and_then(element_center));
    let thread = unsafe { GetWindowThreadProcessId(input, None) };
    let chord = |spec: &str| -> Result<(), String> {
        let combo = parse_key_combo(spec)?;
        post_key(input, thread, &combo, 1)
    };
    let type_once = || -> Result<(), String> {
        // A window that was never activated has never been told it has
        // focus, and Chromium then has no focused view to hand keys to — the
        // first field typed into after attaching got nothing. Tell the
        // widget first (the system's focus does not move), then focus the
        // field: the widget's own focus handling would otherwise put focus
        // back on whatever it had before.
        if unsafe { GetForegroundWindow() } != target.window {
            post(input, windows::Win32::UI::WindowsAndMessaging::WM_SETFOCUS, 0, LPARAM(0))?;
            pause(80);
        }
        // A hidden Chromium page dropped the very first keys it was sent now
        // and then; a lone Shift press types nothing and gets its input
        // pipeline going before the real keys arrive.
        post(input, WM_KEYDOWN, VK_SHIFT.0 as usize, key_lparam(VK_SHIFT, false, false))?;
        post(input, WM_KEYUP, VK_SHIFT.0 as usize, key_lparam(VK_SHIFT, true, false))?;
        pause(150);
        if let Some(field) = field {
            focus_in_page(target, field);
            // Wait for the field to report focus; a hidden page may never
            // say so, hence the cap.
            for _ in 0..6 {
                pause(100);
                if unsafe { field.CurrentHasKeyboardFocus() }.map(|focused| focused.as_bool()).unwrap_or(false) {
                    break;
                }
            }
        }
        // Where the text goes: over the whole field, or after what is there.
        chord(if replace { "ctrl+a" } else { "ctrl+end" })?;
        let mut previous = 0u16;
        for unit in text.encode_utf16() {
            interrupted()?;
            match unit {
                0x0A if previous == 0x0D => {}
                // A line break in a chat box must not press Enter: that sends.
                0x0A | 0x0D => chord("shift+enter")?,
                other => post(input, WM_CHAR, other as usize, LPARAM(1))?,
            }
            previous = unit;
            pause(4);
        }
        pause(300);
        Ok(())
    };
    type_once()?;

    let Some(field) = field else {
        return Ok(json!({
            "typed_chars": text.chars().count(),
            "delivered_to": "focused element",
            "delivered_via": "keyboard",
            "window": window_title(target.window),
        }));
    };
    let name = bstr(unsafe { field.CurrentName() });
    let landed = |after: &Option<String>| match (&before, after) {
        (_, None) => false,
        (_, Some(after)) if replace => squash(after).contains(&squash(text)),
        (Some(before), Some(after)) => {
            squash(after).contains(&squash(text)) && squash(after).len() > squash(before).len()
        }
        (None, Some(after)) => squash(after).contains(&squash(text)),
    };
    let mut after = field_value(field);
    // A parked Edge/Electron window reports stale values, so there a miss
    // proves nothing and retyping could double the text. Elsewhere the read
    // is live: a field that did not change at all never got the keys, and
    // one more attempt is safe.
    let readback_is_live = !(target.hidden && class_name(target.window).starts_with("Chrome_WidgetWin"));
    if should_retype(readback_is_live, &before, &after, landed(&after)) {
        type_once()?;
        after = field_value(field);
    }
    let confirmed = landed(&after);
    let mut result = json!({
        "typed_chars": text.chars().count(),
        "delivered_to": name,
        "delivered_via": "keyboard",
        "confirmed": confirmed,
        "window": window_title(target.window),
    });
    if after.is_none() {
        result["confirmed"] = Value::Null;
        result["note"] = json!(
            "The keys were delivered, but this field does not report its text, so it could not be checked. Take a screenshot before typing again."
        );
    } else if !confirmed && target.hidden {
        // Measured: a parked Chromium page keeps reporting the value it had
        // when it was hidden, while the page itself has the new text. Saying
        // "not confirmed" would only make the agent type it twice.
        result["confirmed"] = Value::Null;
        result["note"] = json!(
            "The keys were delivered. While the app is hidden its accessibility values and picture lag behind, so snapshot or screenshot may still show the old text."
        );
    } else if !confirmed {
        result["note"] = json!(
            "The field did not report the new text yet. Check with a screenshot before typing again; if the keys really did not arrive, use set_value with direct: true."
        );
    }
    Ok(result)
}
