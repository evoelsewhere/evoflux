//! Keyboard shortcuts pressed through the app's menu bar: AppKit hands
//! posted key events only to an app's key window, which a background app
//! does not have, but a menu item runs its command wherever the app is.

use super::*;

/// The menu bar's modifier mask for a combo: 0 is ⌘ alone, then +1 Shift,
/// +2 Option, +4 Control, +8 "no ⌘".
fn menu_modifiers(combo: &KeyCombo) -> i64 {
    let mut mask = 0;
    if combo.shift {
        mask |= 1;
    }
    if combo.alt {
        mask |= 2;
    }
    if combo.ctrl {
        mask |= 4;
    }
    if !combo.cmd {
        mask |= 8;
    }
    mask
}

/// The enabled menu item whose keyboard shortcut is `combo`, if the app has
/// one. Pressing it runs the command without the app being in front.
pub(super) fn menu_item_for(app: &Ax, combo: &KeyCombo) -> Option<(Ax, String)> {
    let key = combo.key.to_lowercase();
    if !(combo.cmd || combo.ctrl || combo.alt) {
        return None;
    }
    let (chars, glyphs) = menu_key_equivalents(&key)?;
    let virtual_key = (key.chars().count() > 1).then(|| resolve_key(&key).map(|(code, _)| i64::from(code))).flatten();
    let wanted = menu_modifiers(combo);
    let mut stack: Vec<(Ax, u32)> = app_menus(app).into_iter().map(|item| (item, 0)).collect();
    let mut visited = 0;
    while let Some((element, depth)) = stack.pop() {
        visited += 1;
        if visited > 5_000 || depth > 6 {
            continue;
        }
        // One round trip per item: a menu bar has hundreds of them.
        let [role, cmd_char, cmd_modifiers, enabled, children, cmd_glyph, cmd_virtual_key] =
            MENU_NAMES.with(|names| element.attributes(names));
        let role = role.as_ref().and_then(cf_text).unwrap_or_default();
        if role == "AXMenuItem" {
            let number = |value: &Option<CFType>| value.as_ref().and_then(cf_number).map(|n| n as i64);
            let char_matches = cmd_char
                .as_ref()
                .and_then(cf_text)
                .is_some_and(|ch| chars.contains(&ch.to_lowercase()));
            let glyph_matches = number(&cmd_glyph).is_some_and(|glyph| glyphs.contains(&glyph));
            let key_matches = virtual_key.is_some() && number(&cmd_virtual_key) == virtual_key;
            let modifiers = number(&cmd_modifiers);
            if (char_matches || glyph_matches || key_matches) && modifiers == Some(wanted) {
                if enabled.as_ref().and_then(cf_bool).unwrap_or(true) {
                    let label = element.label();
                    return Some((element, label));
                }
                return None;
            }
        }
        let children = children.as_ref().map(cf_elements).unwrap_or_default();
        stack.extend(children.into_iter().map(|child| (child, depth + 1)));
    }
    None
}

const MENU_ATTRIBUTES: [&str; 7] = [
    "AXRole",
    "AXMenuItemCmdChar",
    "AXMenuItemCmdModifiers",
    "AXEnabled",
    "AXChildren",
    "AXMenuItemCmdGlyph",
    "AXMenuItemCmdVirtualKey",
];

/// How a menu item can show the key of a shortcut: the characters its
/// `AXMenuItemCmdChar` may hold (lower-cased), and the `AXMenuItemCmdGlyph`
/// codes (Carbon's `kMenu…Glyph`). A letter is itself; a special key —
/// ⌘⌫, ⌘←, ⌘Return, F-keys — is a function-key character or a glyph, and
/// was never found, so its shortcut went out as a key event a background
/// app ignores.
pub(super) fn menu_key_equivalents(key: &str) -> Option<(Vec<String>, Vec<i64>)> {
    if key.chars().count() == 1 {
        return Some((vec![key.to_string()], Vec::new()));
    }
    let (chars, glyphs): (&[&str], &[i64]) = match key {
        "backspace" | "back" => (&["\u{8}", "\u{7f}"], &[0x17]),
        "delete" | "del" | "forwarddelete" => (&["\u{f728}"], &[0x0A]),
        "return" | "enter" => (&["\r", "\u{3}"], &[0x0B, 0x04]),
        "escape" | "esc" => (&["\u{1b}"], &[0x1B]),
        "tab" => (&["\t"], &[0x02]),
        "space" => (&[" "], &[0x09]),
        "left" | "arrowleft" => (&["\u{f702}"], &[0x64]),
        "right" | "arrowright" => (&["\u{f703}"], &[0x65]),
        "up" | "arrowup" => (&["\u{f700}"], &[0x68]),
        "down" | "arrowdown" => (&["\u{f701}"], &[0x6A]),
        "home" => (&["\u{f729}"], &[0x66]),
        "end" => (&["\u{f72b}"], &[0x69]),
        "pageup" | "pgup" => (&["\u{f72c}"], &[0x62]),
        "pagedown" | "pgdn" => (&["\u{f72d}"], &[0x6B]),
        name => {
            // F1 … F12: U+F704 … and glyphs 0x6F ….
            let number: u32 = name.strip_prefix('f')?.parse().ok().filter(|n| (1..=12).contains(n))?;
            let ch = char::from_u32(0xF704 + number - 1)?;
            return Some((vec![ch.to_string()], vec![0x6F + i64::from(number) - 1]));
        }
    };
    Some((chars.iter().map(|ch| ch.to_string()).collect(), glyphs.to_vec()))
}

thread_local! {
    static MENU_NAMES: CFArray<CFString> = CFArray::from_CFTypes(&MENU_ATTRIBUTES.map(cf_string));
}

/// Make the attached window its app's main window, where menu commands go.
///
/// A menu item acts on the app's main window, not on the window the agent
/// drives: with two TextEdit documents open, ⌘S saved whichever was main.
/// Setting `AXMain` orders it first among the app's own windows without
/// activating the app. An app that will not switch, while it has another
/// window the command could reach, gets the command refused.
pub(super) fn make_main(target: &Target) -> Result<(), String> {
    // A dialog of the app takes its commands itself.
    if target.window_id != target.top_id {
        return Ok(());
    }
    let window = &target.window;
    let is_main = || target.app.element("AXMainWindow").is_some_and(|main| main.same(window));
    if is_main() {
        return Ok(());
    }
    let _ = window.set_flag("AXMain", true);
    pause(80);
    if is_main() {
        return Ok(());
    }
    let others = target
        .app
        .elements("AXWindows")
        .into_iter()
        .filter(|other| !other.same(window) && other.string("AXSubrole").as_deref() == Some("AXStandardWindow"))
        .count();
    if others == 0 {
        return Ok(());
    }
    Err(format!(
        "{} would not make the attached window its main window, so this shortcut could act on another of its windows. Look for the control with find and invoke it by ref instead.",
        target.app_name
    ))
}
