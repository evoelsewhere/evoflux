//! `key`: shortcuts pressed through the menu bar when the app has them
//! (see `menus`), Enter and Escape through accessibility, and otherwise key
//! events posted to the app.

use super::*;

// macOS virtual key codes (Carbon's kVK_*).
pub(super) const KEY_A: u16 = 0x00;
pub(super) const KEY_RETURN: u16 = 0x24;
const KEY_TAB: u16 = 0x30;
const KEY_ESCAPE: u16 = 0x35;

/// A key name → (virtual key code, needs Shift on a US layout).
pub(super) fn resolve_key(name: &str) -> Option<(u16, bool)> {
    let code = match name.to_lowercase().as_str() {
        "a" => 0x00, "s" => 0x01, "d" => 0x02, "f" => 0x03, "h" => 0x04, "g" => 0x05,
        "z" => 0x06, "x" => 0x07, "c" => 0x08, "v" => 0x09, "b" => 0x0B, "q" => 0x0C,
        "w" => 0x0D, "e" => 0x0E, "r" => 0x0F, "y" => 0x10, "t" => 0x11, "o" => 0x1F,
        "u" => 0x20, "i" => 0x22, "p" => 0x23, "l" => 0x25, "j" => 0x26, "k" => 0x28,
        "n" => 0x2D, "m" => 0x2E,
        "1" => 0x12, "2" => 0x13, "3" => 0x14, "4" => 0x15, "6" => 0x16, "5" => 0x17,
        "9" => 0x19, "7" => 0x1A, "8" => 0x1C, "0" => 0x1D,
        "=" | "plus" => 0x18, "-" | "minus" => 0x1B, "]" => 0x1E, "[" => 0x21, "'" => 0x27,
        ";" => 0x29, "\\" => 0x2A, "," => 0x2B, "/" => 0x2C, "." => 0x2F, "`" => 0x32,
        "return" | "enter" => KEY_RETURN,
        "tab" => KEY_TAB,
        "space" | " " => 0x31,
        "backspace" | "back" => 0x33,
        "escape" | "esc" => KEY_ESCAPE,
        "delete" | "del" | "forwarddelete" => 0x75,
        "home" => 0x73,
        "end" => 0x77,
        "pageup" | "pgup" => 0x74,
        "pagedown" | "pgdn" => 0x79,
        "left" | "arrowleft" => 0x7B,
        "right" | "arrowright" => 0x7C,
        "down" | "arrowdown" => 0x7D,
        "up" | "arrowup" => 0x7E,
        "insert" | "ins" | "help" => 0x72,
        "capslock" | "caps" => 0x39,
        "f1" => 0x7A, "f2" => 0x78, "f3" => 0x63, "f4" => 0x76, "f5" => 0x60, "f6" => 0x61,
        "f7" => 0x62, "f8" => 0x64, "f9" => 0x65, "f10" => 0x6D, "f11" => 0x67, "f12" => 0x6F,
        "numpadadd" => 0x45, "numpadsubtract" => 0x4E, "numpadmultiply" => 0x43,
        "numpaddivide" => 0x4B, "numpaddecimal" => 0x41, "numpadenter" => 0x4C,
        other => {
            // The shifted symbols of a US layout.
            let mut chars = other.chars();
            let (Some(ch), None) = (chars.next(), chars.next()) else {
                return None;
            };
            let unshifted = match ch {
                '!' => '1', '@' => '2', '#' => '3', '$' => '4', '%' => '5', '^' => '6',
                '&' => '7', '*' => '8', '(' => '9', ')' => '0', '_' => '-', '+' => '=',
                '{' => '[', '}' => ']', '|' => '\\', ':' => ';', '"' => '\'', '<' => ',',
                '>' => '.', '?' => '/', '~' => '`',
                _ => return None,
            };
            return resolve_key(&unshifted.to_string()).map(|(code, _)| (code, true));
        }
    };
    // A single upper-case letter ("A") is that letter with Shift.
    Some((code, name.chars().count() == 1 && name.chars().all(|ch| ch.is_ascii_uppercase())))
}

fn combo_flags(combo: &KeyCombo) -> CGEventFlags {
    let mut flags = CGEventFlags::CGEventFlagNull;
    if combo.cmd {
        flags |= CGEventFlags::CGEventFlagCommand;
    }
    if combo.ctrl {
        flags |= CGEventFlags::CGEventFlagControl;
    }
    if combo.alt {
        flags |= CGEventFlags::CGEventFlagAlternate;
    }
    if combo.shift {
        flags |= CGEventFlags::CGEventFlagShift;
    }
    flags
}

pub(super) fn post_keycode(pid: i32, code: u16, flags: CGEventFlags, repeat: u64) -> Result<(), String> {
    for _ in 0..repeat {
        // Each press carries its own flags, so stopping between presses
        // leaves no modifier held.
        interrupted()?;
        for down in [true, false] {
            let event = CGEvent::new_keyboard_event(event_source()?, code, down)
                .map_err(|()| "Could not create a key event.".to_string())?;
            event.set_flags(flags);
            event.post_to_pid(pid);
            pause(20);
        }
    }
    Ok(())
}

pub(super) fn press_key(target: &Target, params: &Value) -> Result<Value, String> {
    let spec = params
        .get("key")
        .and_then(Value::as_str)
        .ok_or("key needs a key name such as Enter or cmd+s.")?;
    let combo = parse_key_combo(spec)?;
    if let Some(reason) = blocked_combo_reason(&combo) {
        return Err(format!("Refused {spec}: {reason}."));
    }
    let repeat = params.get("repeat").and_then(Value::as_u64).unwrap_or(1).clamp(1, 50);
    if let Some((item, title)) = menu_item_for(&target.app, &combo) {
        make_main(target)?;
        for _ in 0..repeat {
            interrupted()?;
            item.perform("AXPress")
                .map_err(|error| format!("The menu command \"{title}\" failed: {}", ax_error(error)))?;
            pause(60);
        }
        return Ok(json!({
            "key": spec,
            "repeat": repeat,
            "delivered_to": title,
            "delivered_via": "menu",
            "window": target.title(),
        }));
    }
    // Enter and Escape mean confirm and cancel, which the focused control or
    // the window's default and cancel buttons take through accessibility.
    let key = combo.key.to_lowercase();
    let plain = !(combo.cmd || combo.ctrl || combo.alt || combo.shift);
    if plain && repeat == 1 {
        if let Some(done) = confirm_or_cancel(target, &key)? {
            return Ok(merge(json!({ "key": spec, "repeat": repeat }), done));
        }
    }
    let (code, needs_shift) =
        resolve_key(&combo.key).ok_or_else(|| format!("Unknown key name {:?}.", combo.key))?;
    let mut combo = combo.clone();
    combo.shift |= needs_shift;
    post_keycode(target.pid, code, combo_flags(&combo), repeat)?;
    Ok(json!({
        "key": spec,
        "repeat": repeat,
        "delivered_to": "app",
        "delivered_via": "keyboard",
        "window": target.title(),
        "note": "Posted as a key event. macOS delivers keys only to an app's key window, which a background app may not have; if nothing changed, look for the command with find (menu items are included) and invoke it.",
    }))
}

fn confirm_or_cancel(target: &Target, key: &str) -> Result<Option<Value>, String> {
    let (action, button) = match key {
        "return" | "enter" => ("AXConfirm", "AXDefaultButton"),
        "escape" | "esc" => ("AXCancel", "AXCancelButton"),
        _ => return Ok(None),
    };
    let focused = focused_field(target);
    if let Some(focused) = &focused {
        if focused.actions().iter().any(|name| name == action) {
            focused.perform(action).map_err(ax_error)?;
            return Ok(Some(json!({ "delivered_to": focused.label(), "delivered_via": "accessibility", "window": target.title() })));
        }
        // Enter in a multi-line field is a line break (or a chat's "send"),
        // not the dialog's default button.
        if focused.role() == "AXTextArea" {
            return Ok(None);
        }
    }
    // A sheet over the window is what Enter and Escape answer first.
    let sheets = target
        .window
        .elements("AXChildren")
        .into_iter()
        .filter(|child| child.role() == "AXSheet");
    for window in sheets.chain(std::iter::once(target.window.clone())) {
        if let Some(pressable) = window.element(button) {
            pressable.perform("AXPress").map_err(ax_error)?;
            return Ok(Some(json!({ "delivered_to": pressable.label(), "delivered_via": "accessibility", "window": target.title() })));
        }
    }
    Ok(None)
}
