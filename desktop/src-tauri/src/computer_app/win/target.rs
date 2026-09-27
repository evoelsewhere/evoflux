//! The window an action addresses — the attached window, or the modal
//! dialog it is blocked on — with its coordinate mapping, and how web
//! content (Chromium, Electron, WebView2) is recognised and reached.

use super::*;

/// How long the preview's cursor gets to travel before the input lands.
const POINTER_TRAVEL: Duration = Duration::from_millis(220);

// ── The window being driven ─────────────────────────────────────────────

pub(super) struct Target {
    pub(super) session_id: String,
    pub(super) top: HWND,
    /// `top`, or the modal dialog it is currently blocked on.
    pub(super) window: HWND,
    pub(super) pid: u32,
    pub(super) app: String,
    pub(super) frame: RECT,
    pub(super) scale: f64,
    pub(super) restored: bool,
    /// Parked off-screen at the user's request.
    pub(super) hidden: bool,
    /// Chromium/WebView2/Electron content (see [`is_web_host`]).
    pub(super) web: bool,
    /// Menus and dropdowns the window has open, topmost first. `frame`
    /// covers them too (see [`open_popups`]).
    pub(super) popups: Vec<HWND>,
    /// The window's own frame, without its popups.
    pub(super) window_frame: RECT,
}

impl Target {
    pub(super) fn resolve(session_id: &str) -> Result<Self, String> {
        let attached = registry()
            .attached
            .get(session_id)
            .cloned()
            .ok_or("No app is attached. Call list_windows, then attach to one window.")?;
        let top = to_hwnd(attached.hwnd);
        if !unsafe { IsWindow(Some(top)) }.as_bool() {
            registry().attached.remove(session_id);
            clear_refs(session_id);
            return Err(format!(
                "The attached window ({} — {}) was closed. Call list_windows and attach again.",
                attached.app, attached.title
            ));
        }
        let mut restored = false;
        unsafe {
            if IsIconic(top).as_bool() {
                // Restore without activating: the window comes back so it can
                // render, but focus stays wherever the user left it.
                let _ = ShowWindow(top, SW_SHOWNOACTIVATE);
                std::thread::sleep(Duration::from_millis(200));
                restored = true;
            }
        }
        if attached.parked.is_some() && !is_off_screen(top) {
            // The user clicked it on the taskbar, or the app moved itself
            // back onto a monitor: keep it out of sight while controlled.
            move_off_screen(top);
            restored = false;
        }
        let window = effective_window(top, attached.pid);
        if attached.parked.is_some() && window != top {
            // One that opened before it was parked, or that the app moved
            // back onto a monitor.
            park_dialog(window, top);
        }
        let window_frame = frame_rect(window);
        let popups = open_popups(window, top, attached.pid);
        if attached.parked.is_some() && !popups.is_empty() {
            bring_popups_along(session_id, top, window_frame, &popups);
        }
        let frame = popups
            .iter()
            .fold(window_frame, |frame, popup| union(frame, frame_rect(*popup)));
        let width = (frame.right - frame.left).max(1) as u32;
        let height = (frame.bottom - frame.top).max(1) as u32;
        Ok(Self {
            session_id: session_id.to_string(),
            top,
            window,
            pid: attached.pid,
            app: attached.app,
            frame,
            scale: screenshot_scale(width, height),
            restored,
            hidden: attached.parked.is_some(),
            web: is_web_host(window),
            popups,
            window_frame,
        })
    }

    /// The open popup under `point`, if any; the topmost one wins.
    pub(super) fn popup_at(&self, point: POINT) -> Option<HWND> {
        self.popups.iter().copied().find(|popup| {
            let frame = frame_rect(*popup);
            point.x >= frame.left && point.x < frame.right && point.y >= frame.top && point.y < frame.bottom
        })
    }

    pub(super) fn width(&self) -> i32 {
        (self.frame.right - self.frame.left).max(1)
    }

    pub(super) fn height(&self) -> i32 {
        (self.frame.bottom - self.frame.top).max(1)
    }

    pub(super) fn screenshot_size(&self) -> (u32, u32) {
        (
            ((self.width() as f64) * self.scale).round().max(1.0) as u32,
            ((self.height() as f64) * self.scale).round().max(1.0) as u32,
        )
    }

    pub(super) fn describe(&self) -> Value {
        let (width, height) = self.screenshot_size();
        json!({
            "id": hwnd_id(self.top),
            "app": self.app,
            "title": window_title(self.top),
            "pid": self.pid,
            "dialog": if self.window != self.top { Some(window_title(self.window)) } else { None },
            "screenshot_size": [width, height],
            "hidden": self.hidden,
            "web_content": self.web,
        })
    }

    /// Screenshot coordinates → a point on screen inside the window.
    pub(super) fn screen_point(&self, x: f64, y: f64) -> Result<POINT, String> {
        let (width, height) = self.screenshot_size();
        if !(x.is_finite() && y.is_finite())
            || x < 0.0
            || y < 0.0
            || x >= f64::from(width)
            || y >= f64::from(height)
        {
            return Err(format!(
                "({x}, {y}) is outside the {width}x{height} screenshot of the attached window."
            ));
        }
        Ok(POINT {
            x: self.frame.left + (x / self.scale).round() as i32,
            y: self.frame.top + (y / self.scale).round() as i32,
        })
    }

    /// A point on screen → screenshot coordinates, for reporting back.
    pub(super) fn screenshot_point(&self, point: POINT) -> (i64, i64) {
        (
            (f64::from(point.x - self.frame.left) * self.scale).round() as i64,
            (f64::from(point.y - self.frame.top) * self.scale).round() as i64,
        )
    }

    pub(super) fn emit_pointer(&self, emit: &dyn Fn(Value), point: POINT, phase: &str) {
        let x = f64::from(point.x - self.frame.left) / f64::from(self.width());
        let y = f64::from(point.y - self.frame.top) / f64::from(self.height());
        emit(json!({ "sessionId": self.session_id, "x": x, "y": y, "phase": phase }));
    }

    /// Move the preview's cursor to `point` and give it time to get there,
    /// so the user sees where the agent is about to act before it does —
    /// and can still stop it.
    pub(super) fn travel(&self, emit: &dyn Fn(Value), point: POINT) -> Result<(), String> {
        self.emit_pointer(emit, point, "move");
        std::thread::sleep(POINTER_TRAVEL);
        interrupted()
    }
}

/// A window disabled by a modal dialog cannot take input; the dialog can.
///
/// A dialog owned by a hidden window of the app (see `is_dialog_of`) is not
/// the window's enabled popup to Windows, and the app may not disable the
/// window for it either: a spreadsheet left its workbook enabled behind its
/// Create Table dialog while taking no input but the dialog's. While one is
/// shown, it is the window acted on — and seen in screenshots and snapshots.
pub(super) fn effective_window(top: HWND, pid: u32) -> HWND {
    let app_dialog = || {
        top_level_windows().into_iter().find(|hwnd| unsafe {
            *hwnd != top
                && window_pid(*hwnd) == pid
                && IsWindowVisible(*hwnd).as_bool()
                && IsWindowEnabled(*hwnd).as_bool()
                && !is_cloaked(*hwnd)
                // A palette or floating pane (a tool window) sits beside
                // the window without stopping it; a dialog does not.
                && GetWindowLongPtrW(*hwnd, GWL_EXSTYLE) as u32 & WS_EX_TOOLWINDOW.0 == 0
                && owned_by_hidden_window_of(*hwnd, top)
                && is_dialog_of(*hwnd, top)
        })
    };
    unsafe {
        if IsWindowEnabled(top).as_bool() {
            return app_dialog().unwrap_or(top);
        }
        match GetWindow(top, GW_ENABLEDPOPUP) {
            Ok(popup)
                if !popup.0.is_null()
                    && popup != top
                    && IsWindowVisible(popup).as_bool()
                    && window_pid(popup) == pid =>
            {
                popup
            }
            _ => app_dialog().unwrap_or(top),
        }
    }
}

// ── Web content ─────────────────────────────────────────────────────────

/// Whether the window draws web content (Chromium, Electron, WebView2).
///
/// These apps do not take posted mouse or keyboard messages reliably: a
/// WebView2 app in composition mode (new Teams, for one) is a single window
/// with no child for the page at all, and forwards only real input to it.
/// For them, pointer actions go through UI Automation first, which Chromium
/// supports fully and which works while the window is hidden.
///
/// A native app that merely hosts a small web pane — an Office add-in or
/// Copilot pane, a help panel — is not one: its keys belong to its own
/// focused control, not to the pane. Only a Chromium widget covering most
/// of the window makes it web content.
pub(super) fn is_web_host(window: HWND) -> bool {
    let class = class_name(window).to_lowercase();
    if class.starts_with("chrome_") || class.contains("webview") {
        return true;
    }
    let Some(widget) = largest_chromium_widget(window) else {
        return false;
    };
    let area = |hwnd: HWND| {
        let mut rect = RECT::default();
        unsafe {
            let _ = GetWindowRect(hwnd, &mut rect);
        }
        f64::from((rect.right - rect.left).max(0)) * f64::from((rect.bottom - rect.top).max(0))
    };
    let window_area = area(window);
    window_area > 0.0 && area(widget) / window_area >= WEB_COVERAGE
}

/// The share of the window a Chromium widget must cover for the app to
/// count as web content.
const WEB_COVERAGE: f64 = 0.5;

/// The Chromium window that actually handles input for web content.
///
/// An Electron app or Edge *is* one (`Chrome_WidgetWin_1` at the top). A
/// WebView2 host is not: Teams' `TeamsWebView` window holds a
/// `Chrome_WidgetWin_0` from its own process, which holds the WebView2
/// browser's `Chrome_WidgetWin_1` — and only that last one turns posted
/// messages into page input. Its render-host and D3D children serve
/// accessibility and drawing, not input.
pub(super) fn chromium_input_window(target: &Target, point: Option<POINT>) -> HWND {
    if class_name(target.window).starts_with("Chrome_WidgetWin") {
        return target.window;
    }
    if let Some(point) = point {
        if let Some(widget) = chromium_widget_ancestor(target, child_at(target.window, point)) {
            return widget;
        }
    }
    largest_chromium_widget(target.window).unwrap_or(target.window)
}

/// `hwnd` or its nearest ancestor below the attached window that is a
/// Chromium browser widget.
fn chromium_widget_ancestor(target: &Target, hwnd: HWND) -> Option<HWND> {
    let mut current = hwnd;
    for _ in 0..16 {
        if current.0.is_null() || current == target.window {
            return None;
        }
        if class_name(current) == "Chrome_WidgetWin_1" {
            return Some(current);
        }
        current = unsafe { windows::Win32::UI::WindowsAndMessaging::GetParent(current) }.ok()?;
    }
    None
}

fn largest_chromium_widget(window: HWND) -> Option<HWND> {
    unsafe extern "system" fn collect(hwnd: HWND, lparam: LPARAM) -> BOOL {
        if class_name(hwnd) == "Chrome_WidgetWin_1" && unsafe { IsWindowVisible(hwnd) }.as_bool() {
            unsafe { &mut *(lparam.0 as *mut Vec<HWND>) }.push(hwnd);
        }
        BOOL(1)
    }
    let mut widgets: Vec<HWND> = Vec::new();
    unsafe {
        let _ = windows::Win32::UI::WindowsAndMessaging::EnumChildWindows(
            Some(window),
            Some(collect),
            LPARAM(&mut widgets as *mut Vec<HWND> as isize),
        );
    }
    widgets.into_iter().max_by_key(|widget| {
        let mut rect = RECT::default();
        unsafe {
            let _ = GetWindowRect(*widget, &mut rect);
        }
        i64::from(rect.right - rect.left) * i64::from(rect.bottom - rect.top)
    })
}

// ── Frameworks that drop posted input ───────────────────────────────────

/// UI toolkits known to ignore some kinds of posted input, as trycua's
/// cua-driver measured them (its `would_be_silently_dropped` table). The
/// message is posted all the same — EvoFlux also holds modifiers in the
/// app's key state, which cua does not — but the result says the input may
/// not have landed, rather than reporting a click nobody received.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) enum Toolkit {
    Wpf,
    Gtk,
    Tk,
    /// LibreOffice's VCL.
    Vcl,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) enum PostedInput {
    Pointer,
    Keys,
    Text,
}

pub(super) fn toolkit_of_class(class: &str) -> Option<Toolkit> {
    if class.starts_with("HwndWrapper[") {
        Some(Toolkit::Wpf)
    } else if class.starts_with("gdkWindow") || class.starts_with("gdkSurface") {
        Some(Toolkit::Gtk)
    } else if class.starts_with("TkTopLevel") || class == "TkChild" {
        Some(Toolkit::Tk)
    } else if matches!(class, "SALFRAME" | "SALSUBFRAME" | "SALTMPSUBFRAME" | "SALOBJECT") {
        Some(Toolkit::Vcl)
    } else {
        None
    }
}

/// The toolkit drawing `hwnd`, judged by it and its top-level window.
pub(super) fn toolkit_of(hwnd: HWND) -> Option<Toolkit> {
    toolkit_of_class(&class_name(hwnd))
        .or_else(|| toolkit_of_class(&class_name(unsafe { GetAncestor(hwnd, GA_ROOT) })))
}

/// What to tell the agent when `input` was posted to a `toolkit` window
/// that is known to drop it.
pub(super) fn dropped_input_note(toolkit: Toolkit, input: PostedInput) -> Option<&'static str> {
    use PostedInput::*;
    use Toolkit::*;
    match (toolkit, input) {
        (Wpf, Pointer) => Some("This is a WPF app, which often ignores background mouse input. If nothing changed, snapshot or find the control and invoke it by ref (or set_value for a field)."),
        (Wpf, Keys) => Some("This is a WPF app, which may ignore background keys while it is not in front. If nothing changed, invoke the command by ref instead."),
        (Gtk, Pointer) => Some("This is a GTK app, which often ignores background clicks. If nothing changed, snapshot or find the control and invoke it by ref."),
        (Tk, _) => Some("This is a Tk app, which ignores most background input. If nothing changed, use invoke or set_value by ref."),
        (Vcl, Keys) => Some("This is a LibreOffice window, which ignores background shortcuts. If nothing changed, find the command in its menus and invoke it by ref."),
        _ => None,
    }
}

/// Add `note` to a result, after any note it already has.
pub(super) fn add_note(result: &mut Value, note: &str) {
    let combined = match result.get("note").and_then(Value::as_str) {
        Some(existing) if !existing.is_empty() => format!("{existing} {note}"),
        _ => note.to_string(),
    };
    result["note"] = json!(combined);
}

/// Note on `result` that posted `input` to `hwnd` may not have landed.
pub(super) fn note_dropped_input(result: &mut Value, hwnd: HWND, input: PostedInput) {
    if let Some(note) = toolkit_of(hwnd).and_then(|toolkit| dropped_input_note(toolkit, input)) {
        add_note(result, note);
    }
}

/// Where a posted pointer message for `point` goes: the deepest window
/// there, lifted to its Chromium widget for web content.
pub(super) fn pointer_window(target: &Target, point: POINT) -> HWND {
    if let Some(popup) = target.popup_at(point) {
        return child_at(popup, point);
    }
    let hwnd = child_at(target.window, point);
    if target.web {
        chromium_widget_ancestor(target, hwnd).unwrap_or(hwnd)
    } else {
        hwnd
    }
}

/// Tell a Chromium page in a background window that it has focus, before
/// acting on it. The system's focus and the foreground do not move.
///
/// Chromium focuses its own widget when it gets input while it believes it
/// has none — a posted mouse press — and focusing the widget activates the
/// window: the user's foreground was taken whenever Windows allowed it
/// (after a few minutes without user input). Told it has focus, it has
/// none to take. An open popup (a <select>'s list) is a Chromium widget of
/// its own, focused when one of its items is picked, and is told too.
pub(super) fn claim_page_focus(target: &Target) {
    if !target.web || unsafe { GetForegroundWindow() } == target.window {
        return;
    }
    let popups = target
        .popups
        .iter()
        .copied()
        .filter(|popup| class_name(*popup).starts_with("Chrome_WidgetWin"));
    let mut told = false;
    for widget in std::iter::once(chromium_input_window(target, None)).chain(popups) {
        told |= post(widget, windows::Win32::UI::WindowsAndMessaging::WM_SETFOCUS, 0, LPARAM(0)).is_ok();
    }
    if told {
        pause(80);
    }
}
