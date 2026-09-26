//! Posting window messages: where they go, the coordinates they carry
//! (DPI), and waiting for the app to take them in. Shared by pointer and
//! keyboard input.

use super::*;

/// The deepest visible, enabled child window of `top` under `point`.
pub(super) fn child_at(top: HWND, point: POINT) -> HWND {
    let mut current = top;
    for _ in 0..32 {
        let mut local = point;
        unsafe {
            let _ = ScreenToClient(current, &mut local);
            let child = ChildWindowFromPointEx(
                current,
                local,
                CWP_SKIPINVISIBLE | CWP_SKIPDISABLED | CWP_SKIPTRANSPARENT,
            );
            if child.0.is_null() || child == current {
                break;
            }
            current = child;
        }
    }
    current
}

// ── DPI ─────────────────────────────────────────────────────────────────
//
// EvoFlux is per-monitor DPI aware, so every coordinate it measures (window
// frames, UI Automation rectangles, ScreenToClient) is in physical pixels.
// Windows stretches a DPI-unaware or system-aware app on a scaled display
// and hands it logical coordinates instead — but a posted message carries
// whatever numbers were put in it, untranslated. Clicks at 150% landed
// half as far again down and to the right. Coordinates are converted to
// what the receiving window expects before they are packed.

/// Window (logical) pixels per physical pixel for `hwnd`: 1 for a
/// per-monitor aware window, 96/dpi for an unaware one, and system dpi /
/// monitor dpi for a system-aware one.
fn logical_scale(hwnd: HWND) -> f64 {
    use windows::Win32::Graphics::Gdi::{MonitorFromWindow, MONITOR_DEFAULTTONEAREST};
    use windows::Win32::UI::HiDpi::{GetDpiForMonitor, GetDpiForWindow, MDT_EFFECTIVE_DPI};
    unsafe {
        let window_dpi = GetDpiForWindow(hwnd);
        let monitor = MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST);
        let (mut monitor_dpi, mut unused) = (0u32, 0u32);
        if window_dpi == 0
            || GetDpiForMonitor(monitor, MDT_EFFECTIVE_DPI, &mut monitor_dpi, &mut unused).is_err()
            || monitor_dpi == 0
        {
            return 1.0;
        }
        f64::from(window_dpi) / f64::from(monitor_dpi)
    }
}

/// A physical point scaled into a window's logical space.
pub(super) fn to_logical(x: i32, y: i32, scale: f64) -> (i32, i32) {
    if (scale - 1.0).abs() < 1e-6 {
        return (x, y);
    }
    ((f64::from(x) * scale).round() as i32, (f64::from(y) * scale).round() as i32)
}

/// A screen point as `hwnd` sees screen coordinates, packed for the
/// messages that carry screen coordinates (the wheel, hit-testing).
pub(super) fn screen_lparam(hwnd: HWND, point: POINT) -> LPARAM {
    use windows::Win32::UI::HiDpi::PhysicalToLogicalPointForPerMonitorDPI;
    let mut logical = point;
    unsafe {
        let _ = PhysicalToLogicalPointForPerMonitorDPI(Some(hwnd), &mut logical);
    }
    LPARAM(pack_point(logical.x, logical.y))
}

pub(super) fn client_lparam(hwnd: HWND, point: POINT) -> LPARAM {
    let mut local = point;
    unsafe {
        let _ = ScreenToClient(hwnd, &mut local);
    }
    let (x, y) = to_logical(local.x, local.y, logical_scale(hwnd));
    LPARAM(pack_point(x, y))
}

pub(super) fn post(hwnd: HWND, message: u32, wparam: usize, lparam: LPARAM) -> Result<(), String> {
    unsafe { PostMessageW(Some(hwnd), message, WPARAM(wparam), lparam) }.map_err(|error| {
        if error.code().0 as u32 == 0x8007_0005 {
            "Windows blocked input to this app. It probably runs as administrator, which a normal EvoFlux cannot drive.".to_string()
        } else {
            format!("Could not post input to the window: {error}")
        }
    })
}

pub(super) fn pause(ms: u64) {
    std::thread::sleep(Duration::from_millis(ms));
}

/// Wait until `hwnd`'s thread has worked through the input posted to it.
///
/// A sent message is handled the next time the thread asks for a message,
/// ahead of anything posted, so the first round trip only proves the thread
/// is awake; each further one proves it came back for another message after
/// handling the next posted one. A key's down, the character it is
/// translated to and its up take three; Excel then finishes a cell change
/// through messages it posts to itself, and with four round trips the first
/// letter after a Tab still went to the editor it was closing. A nested
/// modal loop (a dialog the key opened) answers too, once the dialog is up.
/// An idle thread answers at once, so the spare trips cost next to nothing;
/// a hung app, or one busy past the timeout, ends the wait, not the action.
pub(super) fn settle(hwnd: HWND) {
    for _ in 0..8 {
        let mut ignored = 0usize;
        let answered = unsafe {
            SendMessageTimeoutW(hwnd, WM_NULL, WPARAM(0), LPARAM(0), SMTO_ABORTIFHUNG, 500, Some(&mut ignored))
        };
        if answered.0 == 0 {
            return;
        }
    }
}
