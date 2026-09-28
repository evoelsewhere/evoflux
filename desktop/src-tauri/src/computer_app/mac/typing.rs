//! `type`: text inserted through accessibility where the field takes it,
//! else posted to the app as key events, and read back to confirm.

use super::*;

pub(super) const DEFAULT_TYPE_DELAY_MS: u64 = 8;
const MAX_TYPE_CHARS: usize = 20_000;

// ── Keyboard input ──────────────────────────────────────────────────────

/// The field keystrokes should go to: the app's own focused element (tracked
/// per app even while it is in the background) when it is in the attached
/// window, else the field the agent last clicked.
pub(super) fn focused_field(target: &Target) -> Option<Ax> {
    let focused = target.app.element("AXFocusedUIElement").filter(|element| {
        element.element("AXWindow").is_some_and(|window| {
            let id = window.window_id();
            id == Some(target.window_id) || id == Some(target.top_id)
        })
    });
    let last = LAST_EDITABLE.with(|last| last.borrow().get(&target.session_id).cloned());
    // A web page often reports its document, not a field, as focused.
    match focused {
        Some(focused) if is_editable(&focused) => Some(focused),
        focused => last.or(focused),
    }
}

fn in_web_area(element: &Ax) -> bool {
    with_ancestors(element.clone()).iter().any(|ancestor| ancestor.role() == "AXWebArea")
}

fn char_count(text: &str) -> usize {
    text.encode_utf16().count()
}

/// Compare what a field holds with what was typed, ignoring the line-break
/// and whitespace differences editors introduce.
fn squash(text: &str) -> String {
    text.split_whitespace().collect::<Vec<_>>().join(" ")
}

/// What reading a field back says about text put into it.
enum Landed {
    Confirmed,
    /// The field holds something new that is not exactly the text (an
    /// editor reformatted it, or autocorrect ran). Typing again would
    /// double it.
    Changed,
    /// The field did not change: the text did not arrive.
    Unchanged,
    /// The field does not report its value (a password field, say).
    Unreadable,
}

fn landed(before: &Option<String>, after: &Option<String>, text: &str, replace: bool) -> Landed {
    let Some(after_text) = after else {
        return Landed::Unreadable;
    };
    let contains = squash(after_text).contains(&squash(text));
    let grew = before.as_ref().map_or(true, |before| after_text.len() > before.len());
    if contains && (replace || grew) {
        Landed::Confirmed
    } else if after == before {
        Landed::Unchanged
    } else {
        Landed::Changed
    }
}

/// Put `text` into `field` through accessibility: replace its selection
/// (the caret, when nothing is selected) the way typing would, and read the
/// value back. With `replace`, the whole content is selected first. Web
/// editors see this as text input, unlike a plain value write.
fn insert_via_accessibility(field: &Ax, text: &str, replace: bool) -> Result<Landed, AXError> {
    let _ = field.set_flag("AXFocused", true);
    let before = field.value_text();
    if replace {
        let length = before.as_deref().map(char_count).unwrap_or(0);
        if let Some(range) = ax_range_value(0, length) {
            let _ = field.set("AXSelectedTextRange", &range);
        }
    }
    field.set("AXSelectedText", &cf_string(text).as_CFType())?;
    pause(120);
    Ok(landed(&before, &field.value_text(), text, replace))
}

/// Type `text` as key events posted to the app's process. Characters travel
/// as Unicode strings (no keyboard layout involved), line breaks as Return
/// — or Shift+Return in web content, so a chat message is not sent.
fn type_via_keyboard(target: &Target, text: &str, web: bool, delay: u64) -> Result<(), String> {
    let mut chunk: Vec<u16> = Vec::new();
    let flush = |chunk: &mut Vec<u16>| -> Result<(), String> {
        if chunk.is_empty() {
            return Ok(());
        }
        interrupted()?;
        for down in [true, false] {
            let event = CGEvent::new_keyboard_event(event_source()?, 0, down)
                .map_err(|()| "Could not create a key event.".to_string())?;
            event.set_string_from_utf16_unchecked(chunk);
            event.post_to_pid(target.pid);
        }
        chunk.clear();
        if delay > 0 {
            pause(delay);
        }
        Ok(())
    };
    let mut previous = '\0';
    for ch in text.chars() {
        match ch {
            '\n' if previous == '\r' => {}
            '\n' | '\r' => {
                flush(&mut chunk)?;
                let shift = if web { CGEventFlags::CGEventFlagShift } else { CGEventFlags::CGEventFlagNull };
                post_keycode(target.pid, KEY_RETURN, shift, 1)?;
            }
            other => {
                let mut units = [0u16; 2];
                chunk.extend_from_slice(other.encode_utf16(&mut units));
                // CGEventKeyboardSetUnicodeString takes up to 20 units.
                if chunk.len() >= 18 {
                    flush(&mut chunk)?;
                }
            }
        }
        previous = ch;
    }
    flush(&mut chunk)
}

pub(super) fn type_text(emit: &dyn Fn(Value), target: &Target, params: &Value) -> Result<Value, String> {
    let text = params.get("text").and_then(Value::as_str).ok_or("type needs text.")?;
    if text.chars().count() > MAX_TYPE_CHARS {
        return Err(format!("type accepts at most {MAX_TYPE_CHARS} characters per call."));
    }
    let field = match params.get("ref").and_then(Value::as_str) {
        Some(reference) => {
            // Put the caret in the field first, the way a person would.
            click(emit, target, &json!({ "ref": reference }))?;
            pause(60);
            Some(element_for(&target.session_id, reference)?)
        }
        None => focused_field(target),
    };
    let delay = params
        .get("delay_ms")
        .and_then(Value::as_u64)
        .unwrap_or(DEFAULT_TYPE_DELAY_MS)
        .min(200);
    fill(target, field.as_ref(), text, false, delay)
}

/// Type into `field` (or wherever the app's focus is): through
/// accessibility when the field takes text that way and confirms it, else
/// as posted key events.
pub(super) fn fill(target: &Target, field: Option<&Ax>, text: &str, replace: bool, delay: u64) -> Result<Value, String> {
    let web = target.web || field.is_some_and(in_web_area);
    if let Some(field) = field {
        let name = field.label();
        let result = |via: &str, landed: Landed| {
            let mut result = json!({
                "typed_chars": text.chars().count(),
                "delivered_to": name,
                "delivered_via": via,
                "window": target.title(),
            });
            match landed {
                Landed::Confirmed => result["confirmed"] = json!(true),
                Landed::Changed | Landed::Unreadable => {
                    result["confirmed"] = Value::Null;
                    result["note"] = json!("The field changed but does not show exactly this text (or does not report its text). Check with a screenshot before typing again.");
                }
                Landed::Unchanged => {
                    result["confirmed"] = json!(false);
                    result["note"] = json!("The field did not change. macOS may not deliver keys to an app in the background; set_value with direct: true writes the text instead.");
                }
            }
            result
        };
        if field.settable("AXSelectedText") {
            match insert_via_accessibility(field, text, replace) {
                // Only a field that did not change at all is safe to type
                // into again.
                Ok(Landed::Unchanged) | Err(_) => {}
                Ok(landed) => return Ok(result("accessibility", landed)),
            }
        }
        let before = field.value_text();
        let _ = field.set_flag("AXFocused", true);
        // Posted keys go wherever the app's focus is, and Chromium moves it
        // a moment later: typed before then, the text was lost.
        for _ in 0..10 {
            if field.flag("AXFocused") == Some(true) {
                break;
            }
            pause(50);
        }
        if replace {
            post_keycode(target.pid, KEY_A, CGEventFlags::CGEventFlagCommand, 1)?;
        }
        type_via_keyboard(target, text, web, delay)?;
        // A web page reports its new value a little later still. Only read
        // again, never typed again: a late read-back would double the text.
        let mut landed = Landed::Unchanged;
        for _ in 0..6 {
            pause(if web { 150 } else { 100 });
            landed = self::landed(&before, &field.value_text(), text, replace);
            if !matches!(landed, Landed::Unchanged) {
                break;
            }
        }
        return Ok(result("keyboard", landed));
    }
    type_via_keyboard(target, text, web, delay)?;
    Ok(json!({
        "typed_chars": text.chars().count(),
        "delivered_to": "focused element",
        "delivered_via": "keyboard",
        "window": target.title(),
        "note": "No focused field was found, so the keys were posted to the app. Click the field (or pass ref) first so typing is confirmed.",
    }))
}
