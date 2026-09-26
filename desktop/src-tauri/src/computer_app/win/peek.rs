//! Making a hidden or covered web page paint for one gesture without the
//! user seeing it (see [`Peek`]).

use super::*;

/// Whether any part of `window` can be seen: sampled with `WindowFromPoint`
/// across its frame, since a window counts as occluded by Chromium only when
/// nothing of it shows.
pub(super) fn partly_visible(window: HWND) -> bool {
    if is_off_screen(window) || unsafe { IsIconic(window) }.as_bool() {
        return false;
    }
    let frame = frame_rect(window);
    let (width, height) = (frame.right - frame.left, frame.bottom - frame.top);
    (1..=4).any(|row| {
        (1..=4).any(|column| {
            let point = POINT {
                x: frame.left + width * column / 5,
                y: frame.top + height * row / 5,
            };
            let hit = unsafe { windows::Win32::UI::WindowsAndMessaging::WindowFromPoint(point) };
            !hit.0.is_null() && unsafe { GetAncestor(hit, GA_ROOT) } == window
        })
    })
}

/// Makes a web page that cannot be seen — parked off-screen, or completely
/// covered — paint again for one gesture, without the user seeing it.
///
/// Chromium delivers pointer moves in step with painted frames and stops
/// painting a window it considers hidden, so a drag there moves nothing
/// (measured: 0 px). While this guard lives, the window is on screen, at the
/// very top of the z-order so nothing covers it, fully transparent and
/// click-through (`WS_EX_LAYERED | WS_EX_TRANSPARENT`, alpha 1/255): Chromium
/// sees a visible window, the user sees and clicks straight through it.
/// Dropping the guard restores the style, z-order and position — also when
/// the gesture fails half-way.
pub(super) struct Peek {
    window: HWND,
    /// Dropped after `Peek::drop` has run: the window turns opaque again
    /// last, once it is back in place.
    _see_through: SeeThrough,
    was_topmost: bool,
    /// The window just above it, to slot it back under afterwards.
    above: Option<HWND>,
    repark: bool,
    session_id: String,
}

impl Peek {
    pub(super) fn begin(target: &Target) -> Option<Self> {
        let window = target.window;
        let parked = registry()
            .attached
            .get(&target.session_id)
            .and_then(|attached| attached.parked);
        let repark = parked.is_some() && is_off_screen(window);
        if !repark && partly_visible(window) {
            return None;
        }
        unsafe {
            let ex_style = GetWindowLongPtrW(window, GWL_EXSTYLE);
            let was_topmost = ex_style as u32 & WS_EX_TOPMOST.0 != 0;
            let above = GetWindow(window, GW_HWNDPREV).ok().filter(|above| {
                !above.0.is_null()
                    && GetWindowLongPtrW(*above, GWL_EXSTYLE) as u32 & WS_EX_TOPMOST.0 == 0
            });
            let see_through = SeeThrough::apply(window)?;
            let (x, y, keep_place) = match parked.filter(|_| repark) {
                Some(placement) => (placement.rcNormalPosition.left, placement.rcNormalPosition.top, SET_WINDOW_POS_FLAGS(0)),
                None => (0, 0, SWP_NOMOVE),
            };
            let _ = SetWindowPos(
                window,
                Some(HWND(-1isize as _)), // HWND_TOPMOST
                x,
                y,
                0,
                0,
                SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER | keep_place,
            );
            // Let the page notice it is visible and resume painting.
            pause(500);
            Some(Self { window, _see_through: see_through, was_topmost, above, repark, session_id: target.session_id.clone() })
        }
    }

    pub(super) fn offset(&self, target: &Target, point: POINT) -> POINT {
        let frame = frame_rect(self.window);
        POINT {
            x: frame.left + (point.x - target.window_frame.left),
            y: frame.top + (point.y - target.window_frame.top),
        }
    }
}

impl Drop for Peek {
    fn drop(&mut self) {
        pause(150);
        let order = SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER;
        unsafe {
            if !self.was_topmost {
                // Leaving the topmost band puts it above every normal window;
                // slot it back under the one that covered it before.
                let _ = SetWindowPos(self.window, Some(HWND(-2isize as _)), 0, 0, 0, 0, order);
                if let Some(above) = self.above.filter(|above| IsWindow(Some(*above)).as_bool()) {
                    let _ = SetWindowPos(self.window, Some(above), 0, 0, 0, 0, order);
                }
            }
        }
        // Only while it is still parked: the user may have pressed Stop (or
        // Show the app) during the gesture, and the window was handed back.
        let still_parked = registry()
            .attached
            .get(&self.session_id)
            .is_some_and(|attached| attached.parked.is_some());
        if self.repark && still_parked {
            move_off_screen(self.window);
        }
        // `_see_through` is dropped next, restoring the window's own style.
    }
}

/// A window made fully transparent and click-through (alpha 1/255,
/// `WS_EX_LAYERED | WS_EX_TRANSPARENT`) until this is dropped.
///
/// A window that was layered already keeps its own opacity or colour key:
/// putting the style back alone left it at alpha 1 — all but invisible for
/// good.
pub(super) struct SeeThrough {
    window: HWND,
    ex_style: isize,
    /// The window's own layered attributes, when it had some.
    layered: Option<(COLORREF, u8, LAYERED_WINDOW_ATTRIBUTES_FLAGS)>,
}

impl SeeThrough {
    /// `None` for a layered window without attributes to read — one drawn
    /// with `UpdateLayeredWindow`, whose drawing setting any would change.
    pub(super) fn apply(window: HWND) -> Option<Self> {
        unsafe {
            let ex_style = GetWindowLongPtrW(window, GWL_EXSTYLE);
            let layered = if ex_style as u32 & WS_EX_LAYERED.0 != 0 {
                let (mut key, mut alpha, mut flags) = (COLORREF(0), 0u8, LAYERED_WINDOW_ATTRIBUTES_FLAGS(0));
                GetLayeredWindowAttributes(window, Some(&mut key), Some(&mut alpha), Some(&mut flags)).ok()?;
                Some((key, alpha, flags))
            } else {
                None
            };
            SetWindowLongPtrW(window, GWL_EXSTYLE, ex_style | (WS_EX_LAYERED.0 | WS_EX_TRANSPARENT.0) as isize);
            let _ = SetLayeredWindowAttributes(window, COLORREF(0), 1, LWA_ALPHA);
            Some(Self { window, ex_style, layered })
        }
    }
}

impl Drop for SeeThrough {
    fn drop(&mut self) {
        unsafe {
            if let Some((key, alpha, flags)) = self.layered {
                let _ = SetLayeredWindowAttributes(self.window, key, alpha, flags);
            }
            // Dropping WS_EX_LAYERED from a window that did not have it
            // clears the attributes set above along with it.
            SetWindowLongPtrW(self.window, GWL_EXSTYLE, self.ex_style);
        }
    }
}
