//! Menus, drop-downs, panes and palettes the app opens as top-level windows
//! of their own, and keeping those of a parked app off the user's screen.

use super::*;

// ── Popups ──────────────────────────────────────────────────────────────
//
// Context menus, dropdown lists, WPF popups and Chromium `<select>` lists
// are top-level windows of their own, not children of the app's window. A
// capture of the window alone never showed them, clicks outside the frame
// were refused, and the UI tree had none of their items. While one is open
// it counts as part of the attached window: the screenshot covers both,
// clicks inside it go to it, and snapshot and find walk it first.

/// Classes that are always popups: menus and a combo box's dropdown list.
const POPUP_CLASSES: &[&str] = &["#32768", "ComboLBox", "DropDown"];

pub(super) fn owned_by(hwnd: HWND, window: HWND, top: HWND) -> bool {
    let mut owner = hwnd;
    for _ in 0..8 {
        owner = match unsafe { GetWindow(owner, GW_OWNER) } {
            Ok(next) if !next.0.is_null() => next,
            _ => return false,
        };
        if owner == window || owner == top {
            return true;
        }
    }
    false
}

/// Whether `hwnd` is one of the attached window's open popups.
pub(super) fn is_popup_of(hwnd: HWND, window: HWND, top: HWND, pid: u32) -> bool {
    if hwnd == window || hwnd == top {
        return false;
    }
    unsafe {
        if !IsWindowVisible(hwnd).as_bool() || is_cloaked(hwnd) {
            return false;
        }
        let ex_style = GetWindowLongPtrW(hwnd, GWL_EXSTYLE) as u32;
        // Tooltips come and go with the pointer and are click-through.
        if ex_style & WS_EX_TRANSPARENT.0 != 0 {
            return false;
        }
    }
    let class = class_name(hwnd);
    if class.to_lowercase().contains("tooltip") {
        return false;
    }
    let frame = frame_rect(hwnd);
    if frame.right - frame.left < 8 || frame.bottom - frame.top < 8 {
        return false;
    }
    let owned = owned_by(hwnd, window, top);
    if POPUP_CLASSES.contains(&class.as_str()) {
        return owned || window_pid(hwnd) == pid;
    }
    // Any other captionless popup counts when the window owns it (a
    // WebView2 app's popups belong to the WebView2 process, not the app's).
    let style = unsafe { GetWindowLongPtrW(hwnd, GWL_STYLE) } as u32;
    let popup = style & WS_POPUP.0 != 0 && style & WS_CAPTION.0 != WS_CAPTION.0;
    popup && owned
}

/// The attached window's open popups, topmost first, with the palettes and
/// floating panes of its process: the capture, clicks and snapshots cover
/// them as part of the window.
pub(super) fn open_popups(window: HWND, top: HWND, pid: u32) -> Vec<HWND> {
    top_level_windows()
        .into_iter()
        .filter(|hwnd| {
            *hwnd != window && (is_popup_of(*hwnd, window, top, pid) || is_tool_window_of(*hwnd, top, pid))
        })
        .collect()
}

pub(super) fn union(a: RECT, b: RECT) -> RECT {
    RECT {
        left: a.left.min(b.left),
        top: a.top.min(b.top),
        right: a.right.max(b.right),
        bottom: a.bottom.max(b.bottom),
    }
}

fn intersects(a: &RECT, b: &RECT) -> bool {
    a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom
}

/// Where each session last clicked or hovered: a parked app's popup is
/// moved back there (see [`bring_popups_along`]). Shared, because the
/// window watcher places popups from a thread of its own.
static LAST_POINT: Lazy<Mutex<HashMap<String, POINT>>> = Lazy::new(|| Mutex::new(HashMap::new()));

pub(super) fn last_points() -> std::sync::MutexGuard<'static, HashMap<String, POINT>> {
    LAST_POINT.lock().unwrap_or_else(|poisoned| poisoned.into_inner())
}

pub(super) fn remember_point(session_id: &str, point: POINT) {
    last_points().insert(session_id.to_string(), point);
}

/// Windows moved along with a parked window, each with the parked window
/// and the spot it opened at: a pane or palette the app keeps open goes
/// back there with its window (see [`bring_moved_back`]).
static MOVED_ALONG: Lazy<Mutex<HashMap<isize, (isize, POINT)>>> = Lazy::new(|| Mutex::new(HashMap::new()));

fn moved_along() -> std::sync::MutexGuard<'static, HashMap<isize, (isize, POINT)>> {
    MOVED_ALONG.lock().unwrap_or_else(|poisoned| poisoned.into_inner())
}

/// A popup of a parked window opens on the user's screen: Windows keeps
/// menus on a monitor, so a menu asked for at an off-screen point lands at
/// the edge of one, and panes and palettes open where the app last had
/// them. Move such windows next to the parked `top`, where the agent last
/// pointed, so they leave the user's screen and stay in the capture.
pub(super) fn bring_popups_along(session_id: &str, top: HWND, window_frame: RECT, popups: &[HWND]) {
    let anchor = last_points()
        .get(session_id)
        .copied()
        .unwrap_or(POINT { x: window_frame.left + 40, y: window_frame.top + 40 });
    for popup in popups {
        let frame = frame_rect(*popup);
        if intersects(&frame, &window_frame) {
            continue;
        }
        if !is_off_screen(*popup) {
            moved_along()
                .entry(popup.0 as isize)
                .or_insert((top.0 as isize, POINT { x: frame.left, y: frame.top }));
        }
        let width = frame.right - frame.left;
        let height = frame.bottom - frame.top;
        // Just below and right of the point, never over it: a floating
        // button a spreadsheet shows by a new selection was put exactly on
        // the cell the next click went to, and took the click.
        const CLEAR: i32 = 4;
        let x = (anchor.x + CLEAR).min(window_frame.right - width).max(window_frame.left);
        let y = (anchor.y + CLEAR).min(window_frame.bottom - height).max(window_frame.top);
        unsafe {
            let _ = SetWindowPos(
                *popup,
                None,
                x,
                y,
                0,
                0,
                SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOOWNERZORDER,
            );
        }
    }
}

/// Whether `hwnd` is a window the app of `top` opened for itself — a
/// dialog, menu, dropdown, floating pane or palette — rather than a window
/// of its own the user works in.
///
/// Dialogs and popups count as [`is_dialog_of`] and [`is_popup_of`] say. A
/// tool window of the same process counts too, owned or not: palettes and
/// floating panes are often unowned, and a tool window has no taskbar
/// button, so it is never one of the app's main windows (a second document
/// window is, and stays where the user put it).
pub(super) fn opened_by(hwnd: HWND, top: HWND, pid: u32) -> bool {
    if hwnd == top || !unsafe { IsWindowVisible(hwnd) }.as_bool() || is_cloaked(hwnd) {
        return false;
    }
    is_dialog_of(hwnd, top) || is_popup_of(hwnd, top, top, pid) || is_tool_window_of(hwnd, top, pid)
}

/// A visible tool window of the app's process: a palette or floating pane,
/// owned or not (see [`opened_by`]).
fn is_tool_window_of(hwnd: HWND, top: HWND, pid: u32) -> bool {
    if hwnd == top || window_pid(hwnd) != pid {
        return false;
    }
    let style = unsafe { GetWindowLongPtrW(hwnd, GWL_STYLE) } as u32;
    let ex_style = unsafe { GetWindowLongPtrW(hwnd, GWL_EXSTYLE) } as u32;
    let frame = frame_rect(hwnd);
    unsafe { IsWindowVisible(hwnd) }.as_bool()
        && !is_cloaked(hwnd)
        && style & WS_CHILD.0 == 0
        && ex_style & WS_EX_TOOLWINDOW.0 != 0
        && ex_style & WS_EX_TRANSPARENT.0 == 0
        && !class_name(hwnd).to_lowercase().contains("tooltip")
        && frame.right - frame.left >= 8
        && frame.bottom - frame.top >= 8
}

/// Take a window the parked `top` opened off the user's screen: a dialog
/// over its owner, anything else next to the window.
pub(super) fn keep_along(session_id: &str, top: HWND, pid: u32, hwnd: HWND) {
    if is_off_screen(hwnd) {
        return;
    }
    if is_dialog_of(hwnd, top) {
        park_dialog(hwnd, top);
    } else {
        bring_popups_along(session_id, top, frame_rect(effective_window(top, pid)), &[hwnd]);
    }
}

/// Take everything the parked `top` has opened off the user's screen.
///
/// The window watcher catches a window as it is shown, but some apps show
/// a pane first and place it after, and one the user dragged back would
/// stay; the preview card runs this with every frame it asks for.
pub(super) fn keep_opened_windows_along(session_id: &str, top: HWND, pid: u32) {
    for hwnd in top_level_windows() {
        if !is_off_screen(hwnd) && opened_by(hwnd, top, pid) {
            keep_along(session_id, top, pid, hwnd);
        }
    }
}

/// `top` was handed back: put the panes and palettes that were moved along
/// with it back where they opened. Menus have closed by now; dialogs are
/// centred on the window by [`bring_dialogs_back`].
pub(super) fn bring_moved_back(top: HWND) {
    let moved: Vec<(isize, POINT)> = {
        let mut moved = moved_along();
        let mine: Vec<isize> = moved
            .iter()
            .filter(|(_, (owner, _))| *owner == top.0 as isize)
            .map(|(hwnd, _)| *hwnd)
            .collect();
        mine.into_iter()
            .filter_map(|hwnd| moved.remove(&hwnd).map(|(_, spot)| (hwnd, spot)))
            .collect()
    };
    for (hwnd, spot) in moved {
        let hwnd = to_hwnd(hwnd);
        let visible = unsafe { IsWindow(Some(hwnd)).as_bool() && IsWindowVisible(hwnd).as_bool() };
        if visible && is_off_screen(hwnd) {
            unsafe {
                let _ = SetWindowPos(
                    hwnd,
                    None,
                    spot.x,
                    spot.y,
                    0,
                    0,
                    SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOOWNERZORDER,
                );
            }
        }
    }
}
