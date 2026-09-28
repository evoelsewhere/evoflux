//! The window an action addresses — the attached window, or the dialog the
//! app shows over it — with its coordinate mapping and where accessibility
//! walks start.

use super::*;

const POINTER_TRAVEL: Duration = Duration::from_millis(220);

// ── The window being driven ─────────────────────────────────────────────

pub(super) struct Target {
    pub(super) session_id: String,
    pub(super) top_id: u32,
    /// `top_id`, or the dialog window the app is currently showing over it.
    pub(super) window_id: u32,
    pub(super) pid: i32,
    pub(super) app_name: String,
    pub(super) app: Ax,
    /// The accessibility element of `window_id`.
    pub(super) window: Ax,
    pub(super) frame: Rect,
    pub(super) scale: f64,
    pub(super) restored: bool,
    /// Parked out of sight at the user's request.
    pub(super) hidden: bool,
    /// Chromium/Electron content.
    pub(super) web: bool,
}

impl Target {
    pub(super) fn resolve(session_id: &str) -> Result<Self, String> {
        let attached = registry()
            .attached
            .get(session_id)
            .cloned()
            .ok_or("No app is attached. Call list_windows, then attach to one window.")?;
        // The window server knows a window by id wherever it is (another
        // Space, full screen); only a window that is gone is missing there.
        if cg_window(attached.window_id).is_none() {
            registry().attached.remove(session_id);
            clear_refs(session_id);
            forget_parked(attached.window_id);
            return Err(format!(
                "The attached window ({} — {}) was closed. Call list_windows and attach again.",
                attached.app, attached.title
            ));
        }
        // Accessibility can fail for a moment — the app is busy past the
        // messaging timeout, the window is on another Space or entering
        // full screen. Dropping the session then left a parked window in
        // its corner for good; it stays attached instead.
        let unreachable = || {
            format!(
                "\"{}\" did not answer through accessibility just now (it may be busy, full screen, or on another Space). It is still attached: try again in a moment, or ask the user to bring it to this desktop.",
                attached.title
            )
        };
        let app = Ax::application(attached.pid).ok_or_else(unreachable)?;
        let top = ax_window(&app, attached.window_id).ok_or_else(unreachable)?;
        let mut restored = false;
        if app.flag("AXHidden").unwrap_or(false) {
            // Hidden with ⌘H: show it again without activating it.
            let _ = app.set_flag("AXHidden", false);
            pause(300);
            restored = true;
        }
        if top.flag("AXMinimized").unwrap_or(false) {
            let _ = top.set_flag("AXMinimized", false);
            pause(450);
            restored = true;
        }
        if attached.parked.is_some() && top.frame().is_some_and(|frame| !mostly_off_screen(&frame)) {
            // The user brought it back, or the app moved itself onto a
            // display: keep it out of sight while controlled.
            move_out_of_sight(&top);
            restored = false;
        }
        // A dialog the app shows as a window of its own (a sheet is part of
        // its window already) takes the input while it is up.
        let (window_id, window) = match app.element("AXFocusedWindow") {
            Some(focus) if !focus.same(&top) && is_dialog(&focus) => match focus.window_id() {
                Some(id) => (id, focus),
                None => (attached.window_id, top),
            },
            _ => (attached.window_id, top),
        };
        let frame = cg_window(window_id)
            .map(|window| window.bounds)
            .or_else(|| window.frame())
            .filter(|frame| !frame.is_empty())
            .ok_or("The window has no size.")?;
        Ok(Self {
            session_id: session_id.to_string(),
            top_id: attached.window_id,
            window_id,
            pid: attached.pid,
            app_name: attached.app,
            app,
            window,
            scale: screenshot_scale(frame.w.round().max(1.0) as u32, frame.h.round().max(1.0) as u32),
            frame,
            restored,
            hidden: attached.parked.is_some(),
            web: attached.web,
        })
    }

    pub(super) fn title(&self) -> String {
        self.window.string("AXTitle").unwrap_or_default()
    }

    pub(super) fn screenshot_size(&self) -> (u32, u32) {
        (
            (self.frame.w * self.scale).round().max(1.0) as u32,
            (self.frame.h * self.scale).round().max(1.0) as u32,
        )
    }

    pub(super) fn describe(&self) -> Value {
        let (width, height) = self.screenshot_size();
        let top_title = if self.window_id == self.top_id {
            self.title()
        } else {
            ax_window(&self.app, self.top_id)
                .and_then(|top| top.string("AXTitle"))
                .unwrap_or_default()
        };
        json!({
            "id": self.top_id,
            "app": self.app_name,
            "title": top_title,
            "pid": self.pid,
            "dialog": if self.window_id != self.top_id { Some(self.title()) } else { None },
            "screenshot_size": [width, height],
            "hidden": self.hidden,
            "web_content": self.web,
            "platform": "macos",
        })
    }

    /// Screenshot coordinates → a point on screen inside the window.
    pub(super) fn screen_point(&self, x: f64, y: f64) -> Result<Point, String> {
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
        Ok(Point { x: self.frame.x + x / self.scale, y: self.frame.y + y / self.scale })
    }

    /// A point on screen → screenshot coordinates, for reporting back.
    pub(super) fn screenshot_point(&self, point: Point) -> (i64, i64) {
        (
            ((point.x - self.frame.x) * self.scale).round() as i64,
            ((point.y - self.frame.y) * self.scale).round() as i64,
        )
    }

    pub(super) fn emit_pointer(&self, emit: &dyn Fn(Value), point: Point, phase: &str) {
        let x = (point.x - self.frame.x) / self.frame.w.max(1.0);
        let y = (point.y - self.frame.y) / self.frame.h.max(1.0);
        emit(json!({ "sessionId": self.session_id, "x": x, "y": y, "phase": phase }));
    }

    /// Move the preview's cursor to `point` and give it time to get there,
    /// so the user sees where the agent is about to act before it does.
    pub(super) fn travel(&self, emit: &dyn Fn(Value), point: Point) -> Result<(), String> {
        self.emit_pointer(emit, point, "move");
        std::thread::sleep(POINTER_TRAVEL);
        interrupted()
    }

    /// Where accessibility walks start: a context menu the app has open (it
    /// belongs to the app, not to any window), the window, then any dialog
    /// window of the app sitting over it.
    pub(super) fn roots(&self) -> Vec<Ax> {
        let mut roots: Vec<Ax> = self
            .app
            .elements("AXChildren")
            .into_iter()
            .filter(|child| child.role() == "AXMenu" && child.frame().is_some_and(|frame| !frame.is_empty()))
            .collect();
        roots.push(self.window.clone());
        if self.window_id != self.top_id {
            if let Some(top) = ax_window(&self.app, self.top_id) {
                roots.push(top);
            }
        }
        roots
    }
}
