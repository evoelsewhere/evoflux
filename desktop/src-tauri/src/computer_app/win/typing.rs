//! `type`: text posted character by character to the control that has the
//! app's keyboard focus, and checked by reading the field back.

use super::*;

const DEFAULT_TYPE_DELAY_MS: u64 = 8;
/// How long typing rests after an Enter or Tab, on top of [`settle`]. Excel
/// recalculates after a cell is committed and, while it does, drops
/// characters posted to it even though it answers sent messages: the first
/// letters of the cell after a formula went missing ("=D2/B2-1" arrived as
/// "2/B2-1").
const CELL_CHANGE_PAUSE_MS: u64 = 60;
const MAX_TYPE_CHARS: usize = 20_000;

thread_local! {
    /// The child window each session last clicked, used when the app's
    /// thread reports no keyboard focus of its own.
    pub(super) static LAST_INPUT: RefCell<HashMap<String, isize>> = RefCell::new(HashMap::new());
}

pub(super) fn remember_input_window(session_id: &str, hwnd: HWND) {
    LAST_INPUT.with(|last| {
        last.borrow_mut()
            .insert(session_id.to_string(), hwnd.0 as isize);
    });
}

fn belongs_to(target: &Target, hwnd: HWND) -> bool {
    if hwnd.0.is_null() || !unsafe { IsWindow(Some(hwnd)) }.as_bool() {
        return false;
    }
    let root = unsafe { GetAncestor(hwnd, GA_ROOT) };
    root == target.window || root == target.top
}

/// The window keystrokes should go to: the app thread's own focus (tracked
/// per thread even while the app is in the background), else the last
/// window the agent clicked, else the window itself.
pub(super) fn keyboard_target(target: &Target) -> HWND {
    let thread = unsafe { GetWindowThreadProcessId(target.window, None) };
    let mut info = GUITHREADINFO {
        cbSize: std::mem::size_of::<GUITHREADINFO>() as u32,
        ..Default::default()
    };
    if unsafe { GetGUIThreadInfo(thread, &mut info) }.is_ok() && belongs_to(target, info.hwndFocus) {
        return info.hwndFocus;
    }
    let last = LAST_INPUT.with(|last| last.borrow().get(&target.session_id).copied());
    if let Some(raw) = last {
        let hwnd = to_hwnd(raw);
        if belongs_to(target, hwnd) {
            return hwnd;
        }
    }
    target.window
}

pub(super) fn type_text(emit: &dyn Fn(Value), target: &Target, params: &Value) -> Result<Value, String> {
    let text = params
        .get("text")
        .and_then(Value::as_str)
        .ok_or("type needs text.")?;
    if text.chars().count() > MAX_TYPE_CHARS {
        return Err(format!("type accepts at most {MAX_TYPE_CHARS} characters per call."));
    }
    if params.get("ref").is_some() {
        // Put the caret in the field first, the way a person would.
        click(emit, target, &json!({ "ref": params["ref"] }))?;
        pause(60);
    }
    if target.web {
        // The field named by ref, else the one the agent last clicked.
        let field = match params.get("ref").and_then(Value::as_str) {
            Some(reference) => Some(element_for(target, reference)?),
            None => LAST_EDITABLE.with(|last| last.borrow().get(&target.session_id).cloned()),
        };
        return web_fill(target, field.as_ref(), text, false);
    }
    let delay = params
        .get("delay_ms")
        .and_then(Value::as_u64)
        .unwrap_or(DEFAULT_TYPE_DELAY_MS)
        .min(200);
    // A click or key just before may still be on its way, and may move the
    // focus when it lands.
    settle(keyboard_target(target));
    let mut hwnd = keyboard_target(target);
    // A Tab moves on to another control, so only text without one can be
    // looked for in the field it started in.
    let field = if text.contains('\t') { None } else { readable_field(hwnd) };
    let before = field.as_ref().and_then(field_value);
    let press = |hwnd: HWND, name: &str| {
        let thread = unsafe { GetWindowThreadProcessId(hwnd, None) };
        let combo = KeyCombo { ctrl: false, alt: false, shift: false, win: false, cmd: false, key: name.into() };
        post_key(hwnd, thread, &combo, 1)
    };
    // The focus is looked up again after every Enter or Tab, and after the
    // first character that follows one: a grid (Excel, a WinForms
    // DataGridView) moves to the next cell on the key and opens an editor
    // for that cell on its first character, and characters posted to the
    // window that had the focus before were dropped — "Aug" arrived as "g",
    // a cell went missing and the rows after it shifted.
    let mut fresh = true;
    // Preview captures wait at the gate while characters are on their way,
    // and get in at the points where the app has taken everything in: after
    // each Enter or Tab, and every so many characters of a long run.
    let gate = input_gate(&target.session_id);
    let mut held = hold_gate(&gate);
    let mut since_opened = 0usize;
    let mut opened_at = std::time::Instant::now();
    for unit in typed_units(text) {
        interrupted()?;
        match unit {
            // Enter and Tab as real key presses: dialogs, WPF, Qt and Java
            // act on the key-down (the default button, focus moving on), and
            // an edit control still gets its character when the app
            // translates the key as it does a typed one.
            0x0D | 0x09 => {
                press(hwnd, if unit == 0x0D { "enter" } else { "tab" })?;
                settle(hwnd);
                pause(CELL_CHANGE_PAUSE_MS);
                hwnd = keyboard_target(target);
                fresh = true;
                if opened_at.elapsed() >= GATE_INTERVAL {
                    held = open_gate(&gate, held);
                    opened_at = std::time::Instant::now();
                    since_opened = 0;
                }
            }
            other => {
                post(hwnd, WM_CHAR, other as usize, LPARAM(1))?;
                since_opened += 1;
                if fresh {
                    settle(hwnd);
                    hwnd = keyboard_target(target);
                    fresh = false;
                } else if since_opened >= GATE_EVERY_CHARS && opened_at.elapsed() >= GATE_INTERVAL {
                    settle(hwnd);
                    held = open_gate(&gate, held);
                    opened_at = std::time::Instant::now();
                    since_opened = 0;
                }
            }
        }
        if delay > 0 {
            pause(delay);
        }
    }
    drop(held);
    let mut result = json!({
        "typed_chars": text.chars().count(),
        "delivered_to": class_name(hwnd),
        "delivered_via": "keyboard",
        "window": window_title(target.window),
    });
    if let (Some(field), Some(before)) = (&field, &before) {
        // The keys are posted, so give the app a moment to take them in.
        pause(150);
        match field_value(field) {
            Some(after) if typed_landed(before, &after, text) => result["confirmed"] = json!(true),
            // An Enter may have submitted and cleared the field (a chat box)
            // or closed its dialog, so only text without one proves a miss.
            Some(_) if !text.contains(['\r', '\n']) => {
                result["confirmed"] = json!(false);
                // Never retyped: the letters may be there out of order, and
                // typing again would add them twice.
                result["note"] = json!(
                    "The field does not show the text as typed: letters may be missing or out of order. Check with snapshot before typing again, then correct it (select the text and retype, or set_value)."
                );
            }
            _ => {}
        }
    }
    if result.get("confirmed") != Some(&json!(true)) {
        note_dropped_input(&mut result, hwnd, PostedInput::Text);
    }
    Ok(result)
}

/// The UTF-16 units `type` sends, with every line break as one Enter (`\r`).
///
/// "\r\n" is one Enter and a lone "\n" is one too. The pair is told by the
/// characters as written: compared after "\n" had become "\r", the second
/// "\n" of a blank line looked like the end of a "\r\n" and the blank line
/// was dropped — a table typed with a blank row under its title moved up.
pub(super) fn typed_units(text: &str) -> Vec<u16> {
    let mut units = Vec::with_capacity(text.len());
    let mut previous = 0u16;
    for raw in text.encode_utf16() {
        let pair_end = raw == 0x0A && previous == 0x0D;
        previous = raw;
        if !pair_end {
            units.push(if raw == 0x0A { 0x0D } else { raw });
        }
    }
    units
}

/// The control keys go to, when it reports its text through UI Automation
/// and is not a password field. A field holding a whole large document is
/// left unread: reading it twice per `type` would cost more than it tells.
fn readable_field(hwnd: HWND) -> Option<IUIAutomationElement> {
    let element = unsafe { automation().ok()?.ElementFromHandle(hwnd) }.ok()?;
    if unsafe { element.CurrentIsPassword() }.map(|password| password.as_bool()).unwrap_or(true) {
        return None;
    }
    let length = field_value(&element)?.len();
    (length <= 200_000).then_some(element)
}

/// Whether text typed into a field shows up in it: the field changed and
/// holds the text, line breaks and runs of spaces aside (an edit control
/// keeps "\r\n", a rich edit "\r", a single-line field none).
pub(super) fn typed_landed(before: &str, after: &str, text: &str) -> bool {
    let wanted = squash(text);
    after != before && (wanted.is_empty() || squash(after).contains(&wanted))
}
