//! Keeping a controlled app running but out of the user's sight, and
//! putting it back where it was.

use super::*;

// ── Parking: keep the app running but out of the user's sight ───────────
//
// macOS keeps at least a sliver of every window on a display, so a parked
// window goes to the bottom-right corner of the desktop with only a point of
// it showing — the way window managers hide windows. It keeps running and
// keeps its Dock icon; a minimized window cannot be captured, so it is
// brought back from the Dock first and returns there on release.

/// The bottom-right corner of the display furthest down and to the right.
/// Taken from one display, not the union of all: with displays of different
/// heights the union's corner may be on none of them, and macOS would pull
/// the window back onto one.
fn hidden_origin() -> (f64, f64) {
    displays()
        .into_iter()
        .max_by(|a, b| (a.right() + a.bottom()).total_cmp(&(b.right() + b.bottom())))
        .map(|display| (display.right() - 1.0, display.bottom() - 1.0))
        .unwrap_or((10_000.0, 10_000.0))
}

pub(super) fn move_out_of_sight(window: &Ax) {
    let (x, y) = hidden_origin();
    if let Some(value) = ax_point_value(x, y) {
        let _ = window.set("AXPosition", &value);
    }
}

pub(super) fn park(window: &Ax) -> Option<Parked> {
    let minimized = window.flag("AXMinimized").unwrap_or(false);
    if minimized {
        let _ = window.set_flag("AXMinimized", false);
        pause(450);
    }
    let origin = window.position()?;
    move_out_of_sight(window);
    Some(Parked { origin: (origin.x, origin.y), minimized })
}

/// Put a parked window back.
///
/// While a Chromium app's `AXEnhancedUserInterface` is on, macOS animates
/// moves made through accessibility and may drop them — release moved the
/// window first and turned the flag off after, and Chrome or Electron
/// windows stayed in their corner. The flag is off during the move, and on
/// again after only when `keep_enhanced` (the app is still being driven).
pub(super) fn hand_back(app: &Ax, window: &Ax, parked: Parked, activate: bool, web: bool, keep_enhanced: bool) {
    if web {
        let _ = app.set_flag("AXEnhancedUserInterface", false);
        pause(100);
    }
    unpark(window, parked, activate);
    if web && keep_enhanced {
        let _ = app.set_flag("AXEnhancedUserInterface", true);
    }
}

pub(super) fn unpark(window: &Ax, parked: Parked, activate: bool) {
    let (x, y) = parked.origin;
    // Asked again when the first move did not take.
    for attempt in 0..2 {
        if let Some(value) = ax_point_value(x, y) {
            let _ = window.set("AXPosition", &value);
        }
        let arrived = window
            .position()
            .is_some_and(|now| (now.x - x).abs() < 2.0 && (now.y - y).abs() < 2.0);
        if arrived || attempt == 1 {
            break;
        }
        pause(200);
    }
    if parked.minimized && !activate {
        let _ = window.set_flag("AXMinimized", true);
    }
}
