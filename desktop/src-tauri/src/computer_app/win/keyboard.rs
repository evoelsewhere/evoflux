//! `key`: key presses and shortcuts posted to the app, with Ctrl/Shift/Alt
//! held in the app thread's own key state rather than on the real keyboard.

use super::*;

pub(super) fn resolve_key(name: &str) -> Option<(VIRTUAL_KEY, bool)> {
    let vk = match name.to_lowercase().as_str() {
        "a" => VK_A, "b" => VK_B, "c" => VK_C, "d" => VK_D, "e" => VK_E, "f" => VK_F,
        "g" => VK_G, "h" => VK_H, "i" => VK_I, "j" => VK_J, "k" => VK_K, "l" => VK_L,
        "m" => VK_M, "n" => VK_N, "o" => VK_O, "p" => VK_P, "q" => VK_Q, "r" => VK_R,
        "s" => VK_S, "t" => VK_T, "u" => VK_U, "v" => VK_V, "w" => VK_W, "x" => VK_X,
        "y" => VK_Y, "z" => VK_Z,
        "0" => VK_0, "1" => VK_1, "2" => VK_2, "3" => VK_3, "4" => VK_4,
        "5" => VK_5, "6" => VK_6, "7" => VK_7, "8" => VK_8, "9" => VK_9,
        "f1" => VK_F1, "f2" => VK_F2, "f3" => VK_F3, "f4" => VK_F4, "f5" => VK_F5,
        "f6" => VK_F6, "f7" => VK_F7, "f8" => VK_F8, "f9" => VK_F9, "f10" => VK_F10,
        "f11" => VK_F11, "f12" => VK_F12,
        "return" | "enter" => VK_RETURN,
        "escape" | "esc" => VK_ESCAPE,
        "tab" => VK_TAB,
        "backspace" | "back" => VK_BACK,
        "space" | " " => VK_SPACE,
        "delete" | "del" => VK_DELETE,
        "insert" | "ins" => VK_INSERT,
        "home" => VK_HOME,
        "end" => VK_END,
        "pageup" | "pgup" => VK_PRIOR,
        "pagedown" | "pgdn" => VK_NEXT,
        "up" | "arrowup" => VK_UP,
        "down" | "arrowdown" => VK_DOWN,
        "left" | "arrowleft" => VK_LEFT,
        "right" | "arrowright" => VK_RIGHT,
        "menu" | "apps" | "contextmenu" => VK_APPS,
        ";" => VK_OEM_1, "=" | "plus" => VK_OEM_PLUS, "," => VK_OEM_COMMA,
        "-" | "minus" => VK_OEM_MINUS, "." => VK_OEM_PERIOD, "/" => VK_OEM_2,
        "`" => VK_OEM_3, "[" => VK_OEM_4, "\\" => VK_OEM_5, "]" => VK_OEM_6, "'" => VK_OEM_7,
        "numpadadd" => VK_ADD, "numpadsubtract" => VK_SUBTRACT,
        "numpadmultiply" => VK_MULTIPLY, "numpaddivide" => VK_DIVIDE,
        "numpaddecimal" => VK_DECIMAL,
        "printscreen" | "prtsc" => VK_SNAPSHOT,
        "scrolllock" => VK_SCROLL,
        "pause" => VK_PAUSE,
        "capslock" | "caps" => VK_CAPITAL,
        "numlock" => VK_NUMLOCK,
        // A modifier on its own: Alt alone opens a Win32 menu bar.
        "alt" => VK_MENU,
        "ctrl" | "control" => VK_CONTROL,
        "shift" => VK_SHIFT,
        name if name.len() == 7 && name.starts_with("numpad") => {
            let digit = name.as_bytes()[6];
            if !digit.is_ascii_digit() {
                return None;
            }
            // VK_NUMPAD0 … VK_NUMPAD9.
            VIRTUAL_KEY(0x60 + u16::from(digit - b'0'))
        }
        name if name.starts_with('f') && matches!(name[1..].parse::<u16>(), Ok(13..=24)) => {
            // VK_F13 … VK_F24.
            VIRTUAL_KEY(0x7C + name[1..].parse::<u16>().unwrap_or(13) - 13)
        }
        other => {
            // Any other single character: ask the keyboard layout.
            let mut chars = other.chars();
            let (Some(ch), None) = (chars.next(), chars.next()) else {
                return None;
            };
            let mut units = [0u16; 2];
            if ch.encode_utf16(&mut units).len() != 1 {
                return None;
            }
            let scan = unsafe { VkKeyScanW(units[0]) };
            if scan == -1 {
                return None;
            }
            let needs_shift = (scan as u16 >> 8) & 1 == 1;
            return Some((VIRTUAL_KEY(scan as u16 & 0xff), needs_shift));
        }
    };
    Some((vk, false))
}

fn is_extended(vk: VIRTUAL_KEY) -> bool {
    matches!(
        vk,
        VK_UP | VK_DOWN | VK_LEFT | VK_RIGHT | VK_HOME | VK_END | VK_PRIOR | VK_NEXT
            | VK_INSERT | VK_DELETE | VK_DIVIDE | VK_NUMLOCK | VK_RCONTROL | VK_RMENU | VK_APPS
    )
}

pub(super) fn key_lparam(vk: VIRTUAL_KEY, up: bool, alt_context: bool) -> LPARAM {
    let scan = unsafe { MapVirtualKeyW(u32::from(vk.0), MAPVK_VK_TO_VSC) } & 0xff;
    let mut value: u32 = 1 | (scan << 16);
    if is_extended(vk) {
        value |= 1 << 24;
    }
    if alt_context {
        value |= 1 << 29;
    }
    if up {
        value |= (1 << 30) | (1 << 31);
    }
    LPARAM(value as i32 as isize)
}

/// Hold modifiers in the app thread's key-state table while `post` runs.
fn with_modifiers(thread: u32, combo: &KeyCombo, post: impl FnOnce() -> Result<(), String>) -> Result<(), String> {
    let mut keys = Vec::new();
    if combo.ctrl {
        keys.extend([VK_CONTROL, VK_LCONTROL]);
    }
    if combo.shift {
        keys.extend([VK_SHIFT, VK_LSHIFT]);
    }
    if combo.alt {
        keys.extend([VK_MENU, VK_LMENU]);
    }
    with_held_keys(thread, &keys, post)
}

/// How long the user must have left the keyboard and mouse alone.
const USER_PAUSE_MS: u32 = 400;

/// Wait for a pause in the user's own typing and clicking when `thread` is
/// the foreground thread — the one their input goes to.
///
/// That thread's key-state table is the one the real keyboard updates, and
/// held keys go into it (see [`with_held_keys`]): a key the user typed into
/// the app meanwhile read Ctrl as down — an "s" became Ctrl+S — and a click
/// became a Ctrl+click. A user who keeps typing gets a refusal after a few
/// seconds rather than a surprise.
fn wait_for_user_pause(thread: u32) -> Result<(), String> {
    use windows::Win32::System::SystemInformation::GetTickCount;
    use windows::Win32::UI::Input::KeyboardAndMouse::{GetLastInputInfo, LASTINPUTINFO};
    let foreground = unsafe { GetForegroundWindow() };
    if foreground.0.is_null() || unsafe { GetWindowThreadProcessId(foreground, None) } != thread {
        return Ok(());
    }
    for _ in 0..30 {
        let mut last = LASTINPUTINFO { cbSize: std::mem::size_of::<LASTINPUTINFO>() as u32, dwTime: 0 };
        if !unsafe { GetLastInputInfo(&mut last) }.as_bool() {
            return Ok(());
        }
        if unsafe { GetTickCount() }.wrapping_sub(last.dwTime) >= USER_PAUSE_MS {
            return Ok(());
        }
        interrupted()?;
        pause(100);
    }
    Err("The user is typing or clicking in this app right now, and holding Ctrl/Shift/Alt or a mouse button for this action would change their input. Wait until they pause, or invoke the command by ref (snapshot or find) instead.".into())
}

/// Mark `keys` as held in the app thread's key-state table while `post` runs.
///
/// Apps read Ctrl/Shift — and whether a mouse button is still down — with
/// `GetKeyState`, which posted messages do not update. Attaching to the app's
/// input queue shares its key-state table, so setting it here is what the app
/// sees, without pressing a real key or button and without moving focus. The
/// table is restored before detaching.
pub(super) fn with_held_keys(thread: u32, keys: &[VIRTUAL_KEY], post: impl FnOnce() -> Result<(), String>) -> Result<(), String> {
    wait_for_user_pause(thread)?;
    let me = unsafe { GetCurrentThreadId() };
    let attached = thread != me && unsafe { AttachThreadInput(me, thread, true) }.as_bool();
    if thread != me && !attached {
        // Without the shared key state the app would read the keys without
        // their modifiers: ctrl+s would type an "s". Say so instead.
        return Err("Windows would not let EvoFlux hold Ctrl/Shift/Alt for this app, so the shortcut was not sent. Look for the command as a button or menu item (snapshot or find) and invoke it instead.".into());
    }
    let mut saved = [0u8; 256];
    let have_state = unsafe { GetKeyboardState(&mut saved) }.is_ok();
    if have_state {
        let mut state = saved;
        for key in keys {
            state[key.0 as usize] |= 0x80;
        }
        let _ = unsafe { SetKeyboardState(&state) };
    }
    let outcome = post();
    // Give the app's message loop time to read the messages while the keys
    // are still held.
    pause(90);
    if have_state {
        let _ = unsafe { SetKeyboardState(&saved) };
    }
    if attached {
        let _ = unsafe { AttachThreadInput(me, thread, false) };
    }
    outcome
}

pub(super) fn press_key(target: &Target, params: &Value) -> Result<Value, String> {
    let spec = params
        .get("key")
        .and_then(Value::as_str)
        .ok_or("key needs a key name such as Enter or ctrl+s.")?;
    let combo = parse_key_combo(spec)?;
    if let Some(reason) = blocked_combo_reason(&combo) {
        return Err(format!("Refused {spec}: {reason}."));
    }
    let repeat = params.get("repeat").and_then(Value::as_u64).unwrap_or(1).clamp(1, 50);
    // Chromium reads keys on its top-level window and routes them to the
    // page's focused element itself.
    let hwnd = if target.web {
        chromium_input_window(target, None)
    } else {
        keyboard_target(target)
    };
    let thread = unsafe { GetWindowThreadProcessId(hwnd, None) };
    post_key(hwnd, thread, &combo, repeat)?;
    // The next action looks up the focus afresh: let the app act on the key
    // first, so text typed after a shortcut that opens a dialog (Ctrl+G in
    // Excel) goes into the dialog instead of landing before it opens.
    settle(hwnd);
    if moves_focus(&combo) {
        forget_editable(&target.session_id);
    }
    Ok(json!({
        "key": spec,
        "repeat": repeat,
        "delivered_to": class_name(hwnd),
        "window": window_title(target.window),
    }))
}

/// Post one key chord `repeat` times to `hwnd`, holding its modifiers in the
/// owning thread's key state (see [`with_modifiers`]).
pub(super) fn post_key(hwnd: HWND, thread: u32, combo: &KeyCombo, repeat: u64) -> Result<(), String> {
    let mut combo = combo.clone();
    let (vk, needs_shift) =
        resolve_key(&combo.key).ok_or_else(|| format!("Unknown key name {:?}.", combo.key))?;
    combo.shift |= needs_shift;
    // Alt without Ctrl is a menu/system shortcut, which Windows delivers as
    // WM_SYSKEY* with the context bit set — and so are F10 and Alt pressed
    // on its own, the keys that open a menu bar.
    let system = (combo.alt && !combo.ctrl) || vk == VK_F10 || vk == VK_MENU;
    // The context bit says Alt is down; for Alt itself too.
    let alt_context = combo.alt || vk == VK_MENU;
    let (down, up) = if system {
        (WM_SYSKEYDOWN, WM_SYSKEYUP)
    } else {
        (WM_KEYDOWN, WM_KEYUP)
    };
    let modifiers: Vec<VIRTUAL_KEY> = [
        (combo.ctrl, VK_CONTROL),
        (combo.shift, VK_SHIFT),
        (combo.alt, VK_MENU),
    ]
    .into_iter()
    .filter_map(|(held, key)| held.then_some(key))
    .collect();

    let send = || -> Result<(), String> {
        for key in &modifiers {
            let message = if system { WM_SYSKEYDOWN } else { WM_KEYDOWN };
            post(hwnd, message, key.0 as usize, key_lparam(*key, false, combo.alt))?;
        }
        for _ in 0..repeat {
            // Stopping between presses still releases the modifiers below.
            if interrupted().is_err() {
                break;
            }
            post(hwnd, down, vk.0 as usize, key_lparam(vk, false, alt_context))?;
            pause(20);
            // Releasing Alt itself clears the context bit, as a real key-up does.
            post(hwnd, up, vk.0 as usize, key_lparam(vk, true, alt_context && vk != VK_MENU))?;
            pause(20);
        }
        for key in modifiers.iter().rev() {
            let message = if system && *key == VK_MENU { WM_SYSKEYUP } else { WM_KEYUP };
            post(hwnd, message, key.0 as usize, key_lparam(*key, true, combo.alt && *key != VK_MENU))?;
        }
        interrupted()
    };
    if modifiers.is_empty() {
        send()
    } else {
        with_modifiers(thread, &combo, send)
    }
}
