//! Getting a web page's accessibility tree out of Chromium, Electron and
//! WebView2, which build it only when asked and only while it shows.

use super::*;

/// Chromium/Electron/WebView2 keep their accessibility tree minimal until an
/// assistive client asks for it through MSAA on the render widget window.
///
/// Returns the render hosts found. Their page tree does not appear as a
/// descendant of the top-level window, so callers walk them as roots of
/// their own. The first activation of a host waits briefly: Chromium builds
/// the tree asynchronously, and the first query would otherwise see an empty
/// page.
fn activate_chromium_accessibility(top: HWND) -> Vec<HWND> {
    thread_local! {
        static ACTIVATED: RefCell<HashSet<isize>> = RefCell::new(HashSet::new());
    }
    let hosts = render_hosts(top);
    let mut fresh = false;
    for host in &hosts {
        let mut object: *mut core::ffi::c_void = std::ptr::null_mut();
        unsafe {
            // OBJID_CLIENT; the interface is released straight away, only the
            // activation side effect matters.
            if AccessibleObjectFromWindow(*host, 0xFFFF_FFFC, &IAccessible::IID, &mut object).is_ok()
                && !object.is_null()
            {
                drop(IAccessible::from_raw(object));
            }
        }
        fresh |= ACTIVATED.with(|activated| activated.borrow_mut().insert(host.0 as isize));
    }
    if fresh {
        pause(600);
    }
    hosts
}

/// The Chromium render host windows inside `top` (at most four).
pub(super) fn render_hosts(top: HWND) -> Vec<HWND> {
    unsafe extern "system" fn find_render_host(hwnd: HWND, lparam: LPARAM) -> BOOL {
        if class_name(hwnd) == "Chrome_RenderWidgetHostHWND" {
            let found = unsafe { &mut *(lparam.0 as *mut Vec<HWND>) };
            found.push(hwnd);
        }
        BOOL(1)
    }
    let mut hosts: Vec<HWND> = Vec::new();
    unsafe {
        let _ = windows::Win32::UI::WindowsAndMessaging::EnumChildWindows(
            Some(top),
            Some(find_render_host),
            LPARAM(&mut hosts as *mut Vec<HWND> as isize),
        );
    }
    hosts.truncate(4);
    hosts
}

/// Make Chromium see a window it has never seen showing, so it creates the
/// render host its page's accessibility tree hangs from.
///
/// An Edge or Chrome window that opened completely covered counts as
/// occluded from the start: Chromium keeps its page hidden and creates no
/// render host, so the page had no tree at all — whatever was asked of it,
/// even with accessibility forced on — and Chromium works out again whether
/// a window shows only when the window moves. For a moment the window is
/// put above everything, fully transparent and click-through (as a
/// [`Peek`]), and nudged by a pixel; then its place, z-order and style are
/// put back. The user sees nothing.
fn wake_page(window: HWND) {
    unsafe {
        let ex_style = GetWindowLongPtrW(window, GWL_EXSTYLE);
        let was_topmost = ex_style as u32 & WS_EX_TOPMOST.0 != 0;
        let above = GetWindow(window, GW_HWNDPREV).ok().filter(|above| {
            !above.0.is_null() && GetWindowLongPtrW(*above, GWL_EXSTYLE) as u32 & WS_EX_TOPMOST.0 == 0
        });
        let Some(see_through) = SeeThrough::apply(window) else {
            return;
        };
        let mut place = RECT::default();
        let _ = GetWindowRect(window, &mut place);
        let flags = SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER;
        let _ = SetWindowPos(window, Some(HWND(-1isize as _)), place.left + 1, place.top, 0, 0, flags); // HWND_TOPMOST
        for _ in 0..10 {
            pause(100);
            if !render_hosts(window).is_empty() {
                break;
            }
        }
        let _ = SetWindowPos(window, None, place.left, place.top, 0, 0, flags | SWP_NOZORDER);
        if !was_topmost {
            let order = SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER;
            let _ = SetWindowPos(window, Some(HWND(-2isize as _)), 0, 0, 0, 0, order); // HWND_NOTOPMOST
            if let Some(above) = above.filter(|above| IsWindow(Some(*above)).as_bool()) {
                let _ = SetWindowPos(window, Some(above), 0, 0, 0, 0, order);
            }
        }
        drop(see_through);
    }
}

/// Activate a Chromium window's accessibility and wait (up to ~4 s) until a
/// render host's page tree has content.
pub(super) fn wait_for_page_tree(window: HWND) {
    let Ok(automation) = automation() else {
        return;
    };
    let Ok(walker) = (unsafe { automation.ControlViewWalker() }) else {
        return;
    };
    let mut woken = false;
    for _ in 0..20 {
        if !woken && render_hosts(window).is_empty() && class_name(window).starts_with("Chrome_WidgetWin") && !partly_visible(window) {
            woken = true;
            wake_page(window);
        }
        let hosts = activate_chromium_accessibility(window);
        let ready = hosts.iter().any(|host| {
            unsafe { automation.ElementFromHandle(*host) }
                .and_then(|root| unsafe { walker.GetFirstChildElement(&root) })
                .and_then(|document| unsafe { walker.GetFirstChildElement(&document) })
                .is_ok()
        });
        // No render host at all (a composition-hosted WebView2 such as new
        // Teams): its tree hangs off the window itself; nothing to wait for.
        // Chromium's own window (Edge, Chrome, Electron) always gets one, but
        // only once its page starts rendering: returning early there parked
        // a window that was still starting before its page had a tree, and
        // the tree then stayed empty.
        let chromium_window = class_name(window).starts_with("Chrome_WidgetWin");
        if ready || (hosts.is_empty() && !chromium_window) {
            return;
        }
        pause(200);
    }
}

/// Where UI Automation walks start for this window: the window itself, then
/// each Chromium render host inside it (see [`activate_chromium_accessibility`]).
pub(super) fn automation_roots(automation: &IUIAutomation, window: HWND) -> Result<Vec<IUIAutomationElement>, String> {
    let hosts = activate_chromium_accessibility(window);
    let root = unsafe { automation.ElementFromHandle(window) }
        .map_err(|error| format!("UI Automation cannot read this window: {error}"))?;
    let mut roots = vec![root];
    for host in hosts {
        if let Ok(element) = unsafe { automation.ElementFromHandle(host) } {
            roots.push(element);
        }
    }
    Ok(roots)
}
