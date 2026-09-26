//! macOS implementation of Computer App Control.
//!
//! The same contract as the Windows backend, built on what macOS offers for
//! driving an app that is not in front:
//!
//! - Capture uses `CGWindowListCreateImage…`, which renders the window's own
//!   backing store, so the app can sit behind other windows. It needs the
//!   Screen Recording permission.
//! - The element tree, clicks by ref, typing and values go through the
//!   Accessibility API (`AXUIElement`), which apps answer without being
//!   activated. It needs the Accessibility permission.
//! - Coordinate input that has no accessible element is posted to the app's
//!   process with `CGEventPostToPid`, addressed to the window. The user's
//!   cursor and frontmost app are never moved.
//! - Keyboard shortcuts are pressed through the app's menu bar when a menu
//!   item carries that shortcut, since AppKit only hands posted key events
//!   to an app's key window, which a background app does not have.
//!
//! Coordinates are points (the unit window bounds and accessibility frames
//! use), top-left origin. Screenshots are taken at nominal resolution, so one
//! screenshot pixel is one point before scaling.

use std::cell::RefCell;
use std::collections::{HashMap, HashSet};
use std::ffi::c_void;
use std::sync::Mutex;
use std::time::{Duration, Instant};

use base64::{engine::general_purpose::STANDARD as BASE64, Engine as _};
use core_foundation::array::{CFArray, CFArrayRef};
use core_foundation::base::{CFIndex, CFRange, CFType, CFTypeID, CFTypeRef, TCFType};
use core_foundation::boolean::CFBoolean;
use core_foundation::dictionary::{CFDictionary, CFDictionaryRef};
use core_foundation::number::CFNumber;
use core_foundation::string::{CFString, CFStringRef};
use core_graphics::display::CGDisplay;
use core_graphics::event::{
    CGEvent, CGEventFlags, CGEventType, CGMouseButton, EventField, ScrollEventUnit,
};
use core_graphics::event_source::{CGEventSource, CGEventSourceStateID};
use core_graphics::geometry::{CGPoint, CGRect, CGSize};
use core_graphics::window::{
    copy_window_info, create_image, create_image_from_array, kCGNullWindowID,
    kCGWindowBounds, kCGWindowImageBoundsIgnoreFraming, kCGWindowImageNominalResolution,
    kCGWindowImageShouldBeOpaque, kCGWindowIsOnscreen, kCGWindowLayer,
    kCGWindowListExcludeDesktopElements, kCGWindowListOptionAll,
    kCGWindowListOptionIncludingWindow, kCGWindowListOptionOnScreenAboveWindow, kCGWindowName,
    kCGWindowNumber, kCGWindowOwnerName, kCGWindowOwnerPID,
    CGWindowListCreateDescriptionFromArray,
};
use image::{imageops, DynamicImage, RgbaImage};
use once_cell::sync::Lazy;
use serde_json::{json, Value};

use super::{
    blocked_combo_reason, interrupted, is_protected_process_name, on_worker, parse_key_combo,
    post_to_worker, screenshot_scale, KeyCombo,
};

const POINTER_TRAVEL: Duration = Duration::from_millis(220);
const DEFAULT_TYPE_DELAY_MS: u64 = 8;
const MAX_TYPE_CHARS: usize = 20_000;
/// How long one accessibility call may wait for the app. A hung app must not
/// hang the worker (and every action queued behind it).
const AX_TIMEOUT_SECONDS: f32 = 2.0;

// ── Accessibility and system FFI ────────────────────────────────────────

type AXUIElementRef = CFTypeRef;
type AXError = i32;
const AX_SUCCESS: AXError = 0;
const AX_VALUE_CGPOINT: u32 = 1;
const AX_VALUE_CGSIZE: u32 = 2;
const AX_VALUE_CFRANGE: u32 = 4;

#[link(name = "ApplicationServices", kind = "framework")]
extern "C" {
    static kAXTrustedCheckOptionPrompt: CFStringRef;
    fn AXIsProcessTrustedWithOptions(options: CFDictionaryRef) -> u8;
    fn AXUIElementCreateApplication(pid: i32) -> AXUIElementRef;
    fn AXUIElementCreateSystemWide() -> AXUIElementRef;
    fn AXUIElementGetTypeID() -> CFTypeID;
    fn AXUIElementCopyAttributeValue(
        element: AXUIElementRef,
        attribute: CFStringRef,
        value: *mut CFTypeRef,
    ) -> AXError;
    fn AXUIElementCopyMultipleAttributeValues(
        element: AXUIElementRef,
        attributes: CFArrayRef,
        options: u32,
        values: *mut CFArrayRef,
    ) -> AXError;
    fn AXUIElementSetAttributeValue(
        element: AXUIElementRef,
        attribute: CFStringRef,
        value: CFTypeRef,
    ) -> AXError;
    fn AXUIElementIsAttributeSettable(
        element: AXUIElementRef,
        attribute: CFStringRef,
        settable: *mut u8,
    ) -> AXError;
    fn AXUIElementCopyActionNames(element: AXUIElementRef, names: *mut CFArrayRef) -> AXError;
    fn AXUIElementPerformAction(element: AXUIElementRef, action: CFStringRef) -> AXError;
    fn AXUIElementGetPid(element: AXUIElementRef, pid: *mut i32) -> AXError;
    fn AXUIElementSetMessagingTimeout(element: AXUIElementRef, seconds: f32) -> AXError;
    fn AXValueCreate(kind: u32, value: *const c_void) -> CFTypeRef;
    fn AXValueGetTypeID() -> CFTypeID;
    fn AXValueGetValue(value: CFTypeRef, kind: u32, out: *mut c_void) -> u8;
    /// Private but long-stable (window managers such as yabai and Rectangle
    /// rely on it): the window server id of an accessibility window, which
    /// is how an `AXUIElement` window is matched to a captured window.
    fn _AXUIElementGetWindow(element: AXUIElementRef, window: *mut u32) -> AXError;
}

#[link(name = "CoreGraphics", kind = "framework")]
extern "C" {
    fn CGPreflightScreenCaptureAccess() -> bool;
    fn CGRequestScreenCaptureAccess() -> bool;
}

extern "C" {
    fn proc_pidpath(pid: i32, buffer: *mut c_void, size: u32) -> i32;
}

/// An accessibility element: an app, a window or a control in one.
#[derive(Clone)]
struct Ax(CFType);

fn cf_string(text: &str) -> CFString {
    CFString::new(text)
}

impl Ax {
    fn wrap(raw: AXUIElementRef) -> Option<Self> {
        (!raw.is_null()).then(|| Self(unsafe { CFType::wrap_under_create_rule(raw) }))
    }

    fn application(pid: i32) -> Option<Self> {
        static GLOBAL_TIMEOUT: std::sync::Once = std::sync::Once::new();
        GLOBAL_TIMEOUT.call_once(|| {
            // Set on the system-wide element, the timeout covers every
            // element this process asks about, not just the app itself.
            if let Some(system) = Self::system_wide() {
                unsafe { AXUIElementSetMessagingTimeout(system.raw(), AX_TIMEOUT_SECONDS) };
            }
        });
        Self::wrap(unsafe { AXUIElementCreateApplication(pid) })
    }

    fn system_wide() -> Option<Self> {
        Self::wrap(unsafe { AXUIElementCreateSystemWide() })
    }

    fn from_value(value: &CFType) -> Option<Self> {
        (value.type_of() == unsafe { AXUIElementGetTypeID() }).then(|| Self(value.clone()))
    }

    fn raw(&self) -> AXUIElementRef {
        self.0.as_CFTypeRef()
    }

    fn same(&self, other: &Ax) -> bool {
        self.0 == other.0
    }

    fn attribute(&self, name: &str) -> Option<CFType> {
        let key = cf_string(name);
        let mut value: CFTypeRef = std::ptr::null();
        let error =
            unsafe { AXUIElementCopyAttributeValue(self.raw(), key.as_concrete_TypeRef(), &mut value) };
        (error == AX_SUCCESS && !value.is_null()).then(|| unsafe { CFType::wrap_under_create_rule(value) })
    }

    /// Several attributes in one round trip to the app. A missing attribute
    /// comes back as an AXValue holding the error, which none of the
    /// `cf_*` conversions accept.
    fn attributes<const N: usize>(&self, names: &CFArray<CFString>) -> [Option<CFType>; N] {
        let mut out: CFArrayRef = std::ptr::null();
        let error = unsafe {
            AXUIElementCopyMultipleAttributeValues(self.raw(), names.as_concrete_TypeRef(), 0, &mut out)
        };
        if error != AX_SUCCESS || out.is_null() {
            return std::array::from_fn(|_| None);
        }
        let array: CFArray = unsafe { CFArray::wrap_under_create_rule(out) };
        std::array::from_fn(|index| {
            array
                .get(index as CFIndex)
                .map(|value| unsafe { CFType::wrap_under_get_rule(*value as CFTypeRef) })
        })
    }

    fn string(&self, name: &str) -> Option<String> {
        self.attribute(name).and_then(|value| cf_text(&value))
    }

    fn flag(&self, name: &str) -> Option<bool> {
        self.attribute(name).and_then(|value| cf_bool(&value))
    }

    fn element(&self, name: &str) -> Option<Ax> {
        self.attribute(name).and_then(|value| Ax::from_value(&value))
    }

    fn elements(&self, name: &str) -> Vec<Ax> {
        self.attribute(name)
            .map(|value| cf_elements(&value))
            .unwrap_or_default()
    }

    fn position(&self) -> Option<CGPoint> {
        self.attribute("AXPosition").and_then(|value| ax_point(&value))
    }

    fn frame(&self) -> Option<Rect> {
        let origin = self.position()?;
        let size = self.attribute("AXSize").and_then(|value| ax_size(&value))?;
        Some(Rect { x: origin.x, y: origin.y, w: size.width, h: size.height })
    }

    fn set(&self, name: &str, value: &CFType) -> Result<(), AXError> {
        let key = cf_string(name);
        let error = unsafe {
            AXUIElementSetAttributeValue(self.raw(), key.as_concrete_TypeRef(), value.as_CFTypeRef())
        };
        if error == AX_SUCCESS {
            Ok(())
        } else {
            Err(error)
        }
    }

    fn set_flag(&self, name: &str, on: bool) -> Result<(), AXError> {
        let value = if on { CFBoolean::true_value() } else { CFBoolean::false_value() };
        self.set(name, &value.as_CFType())
    }

    fn settable(&self, name: &str) -> bool {
        let key = cf_string(name);
        let mut settable = 0u8;
        let error = unsafe {
            AXUIElementIsAttributeSettable(self.raw(), key.as_concrete_TypeRef(), &mut settable)
        };
        error == AX_SUCCESS && settable != 0
    }

    fn actions(&self) -> Vec<String> {
        let mut names: CFArrayRef = std::ptr::null();
        let error = unsafe { AXUIElementCopyActionNames(self.raw(), &mut names) };
        if error != AX_SUCCESS || names.is_null() {
            return Vec::new();
        }
        let names: CFArray<CFType> = unsafe { CFArray::wrap_under_create_rule(names) };
        names.iter().filter_map(|name| cf_text(&name)).collect()
    }

    fn perform(&self, action: &str) -> Result<(), AXError> {
        let name = cf_string(action);
        let error = unsafe { AXUIElementPerformAction(self.raw(), name.as_concrete_TypeRef()) };
        if error == AX_SUCCESS {
            Ok(())
        } else {
            Err(error)
        }
    }

    fn pid(&self) -> Option<i32> {
        let mut pid = 0;
        (unsafe { AXUIElementGetPid(self.raw(), &mut pid) } == AX_SUCCESS).then_some(pid)
    }

    fn window_id(&self) -> Option<u32> {
        let mut id = 0u32;
        (unsafe { _AXUIElementGetWindow(self.raw(), &mut id) } == AX_SUCCESS && id != 0).then_some(id)
    }

    fn role(&self) -> String {
        self.string("AXRole").unwrap_or_default()
    }

    /// What a person would call the element: its title, description, or
    /// (for static text) the text itself.
    fn label(&self) -> String {
        for attribute in ["AXTitle", "AXDescription"] {
            if let Some(text) = self.string(attribute).filter(|text| !text.trim().is_empty()) {
                return text;
            }
        }
        if self.role() == "AXStaticText" {
            return self.string("AXValue").unwrap_or_default();
        }
        String::new()
    }

    fn value_text(&self) -> Option<String> {
        self.attribute("AXValue").and_then(|value| cf_text(&value))
    }
}

fn cf_text(value: &CFType) -> Option<String> {
    if let Some(text) = value.downcast::<CFString>() {
        return Some(text.to_string());
    }
    value.downcast::<CFNumber>().and_then(|number| {
        number
            .to_i64()
            .map(|n| n.to_string())
            .or_else(|| number.to_f64().map(|n| n.to_string()))
    })
}

fn cf_bool(value: &CFType) -> Option<bool> {
    if let Some(flag) = value.downcast::<CFBoolean>() {
        return Some(flag.into());
    }
    value.downcast::<CFNumber>().and_then(|number| number.to_i64()).map(|n| n != 0)
}

fn cf_number(value: &CFType) -> Option<f64> {
    value.downcast::<CFNumber>().and_then(|number| number.to_f64())
}

fn cf_elements(value: &CFType) -> Vec<Ax> {
    let Some(array) = value.downcast::<CFArray>() else {
        return Vec::new();
    };
    array
        .iter()
        .filter_map(|item| Ax::from_value(&unsafe { CFType::wrap_under_get_rule(*item as CFTypeRef) }))
        .collect()
}

fn ax_value<T: Default>(value: &CFType, kind: u32) -> Option<T> {
    if value.type_of() != unsafe { AXValueGetTypeID() } {
        return None;
    }
    let mut out = T::default();
    let ok = unsafe { AXValueGetValue(value.as_CFTypeRef(), kind, &mut out as *mut T as *mut c_void) };
    (ok != 0).then_some(out)
}

#[derive(Default, Clone, Copy)]
#[repr(C)]
struct PointValue {
    x: f64,
    y: f64,
}

#[derive(Default, Clone, Copy)]
#[repr(C)]
struct SizeValue {
    width: f64,
    height: f64,
}

fn ax_point(value: &CFType) -> Option<CGPoint> {
    ax_value::<PointValue>(value, AX_VALUE_CGPOINT).map(|p| CGPoint::new(p.x, p.y))
}

fn ax_size(value: &CFType) -> Option<CGSize> {
    ax_value::<SizeValue>(value, AX_VALUE_CGSIZE).map(|s| CGSize::new(s.width, s.height))
}

fn make_ax_value<T>(kind: u32, value: &T) -> Option<CFType> {
    let raw = unsafe { AXValueCreate(kind, value as *const T as *const c_void) };
    (!raw.is_null()).then(|| unsafe { CFType::wrap_under_create_rule(raw) })
}

fn ax_point_value(x: f64, y: f64) -> Option<CFType> {
    make_ax_value(AX_VALUE_CGPOINT, &PointValue { x, y })
}

fn ax_range_value(location: usize, length: usize) -> Option<CFType> {
    let range = CFRange { location: location as CFIndex, length: length as CFIndex };
    make_ax_value(AX_VALUE_CFRANGE, &range)
}

/// Whether EvoFlux may use the Accessibility API. With `prompt`, macOS shows
/// its "allow in System Settings" dialog the first time.
fn accessibility_trusted(prompt: bool) -> bool {
    let key = unsafe { CFString::wrap_under_get_rule(kAXTrustedCheckOptionPrompt) };
    let value = if prompt { CFBoolean::true_value() } else { CFBoolean::false_value() };
    let options = CFDictionary::from_CFType_pairs(&[(key.as_CFType(), value.as_CFType())]);
    unsafe { AXIsProcessTrustedWithOptions(options.as_concrete_TypeRef()) != 0 }
}

const ACCESSIBILITY_REFUSAL: &str = "macOS has not given EvoFlux Accessibility access, which Computer App Control needs to read and operate apps. Ask the user to allow EvoFlux in System Settings → Privacy & Security → Accessibility, then try again.";
const SCREEN_RECORDING_REFUSAL: &str = "macOS has not given EvoFlux Screen Recording access, so app windows cannot be captured. Ask the user to allow EvoFlux in System Settings → Privacy & Security → Screen & System Audio Recording and restart EvoFlux. snapshot, find, invoke and set_value work without it.";

fn screen_capture_allowed() -> bool {
    unsafe { CGPreflightScreenCaptureAccess() }
}

/// What Settings → Computer App Control shows: which of the two macOS
/// permissions EvoFlux has.
pub(crate) fn permissions() -> Value {
    json!({
        "required": true,
        "accessibility": accessibility_trusted(false),
        "screen_recording": screen_capture_allowed(),
    })
}

/// Ask for one permission from Settings. The system call puts EvoFlux in
/// the pane's list (macOS only shows its own prompt the first time), and the
/// pane itself is opened so the user lands on the switch to turn on.
pub(crate) fn request_permission(kind: &str) -> Result<Value, String> {
    let pane = match kind {
        "accessibility" => {
            accessibility_trusted(true);
            "Privacy_Accessibility"
        }
        "screen_recording" => {
            unsafe { CGRequestScreenCaptureAccess() };
            "Privacy_ScreenCapture"
        }
        other => return Err(format!("Unknown macOS permission {other:?}.")),
    };
    std::process::Command::new("open")
        .arg(format!("x-apple.systempreferences:com.apple.preference.security?{pane}"))
        .spawn()
        .map_err(|error| format!("Could not open System Settings: {error}"))?;
    Ok(permissions())
}

// ── Geometry ────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Copy, Default, PartialEq)]
struct Rect {
    x: f64,
    y: f64,
    w: f64,
    h: f64,
}

#[derive(Debug, Clone, Copy, PartialEq)]
struct Point {
    x: f64,
    y: f64,
}

impl Rect {
    fn from_cg(rect: &CGRect) -> Self {
        Self { x: rect.origin.x, y: rect.origin.y, w: rect.size.width, h: rect.size.height }
    }

    fn to_cg(self) -> CGRect {
        CGRect::new(&CGPoint::new(self.x, self.y), &CGSize::new(self.w, self.h))
    }

    fn right(&self) -> f64 {
        self.x + self.w
    }

    fn bottom(&self) -> f64 {
        self.y + self.h
    }

    fn is_empty(&self) -> bool {
        self.w <= 0.0 || self.h <= 0.0
    }

    fn contains(&self, point: Point) -> bool {
        !self.is_empty()
            && point.x >= self.x
            && point.x < self.right()
            && point.y >= self.y
            && point.y < self.bottom()
    }

    fn intersects(&self, other: &Rect) -> bool {
        self.x < other.right() && other.x < self.right() && self.y < other.bottom() && other.y < self.bottom()
    }

    fn overlap_area(&self, other: &Rect) -> f64 {
        let w = self.right().min(other.right()) - self.x.max(other.x);
        let h = self.bottom().min(other.bottom()) - self.y.max(other.y);
        if w > 0.0 && h > 0.0 {
            w * h
        } else {
            0.0
        }
    }

    fn center(&self) -> Point {
        Point { x: self.x + self.w / 2.0, y: self.y + self.h / 2.0 }
    }
}

fn displays() -> Vec<Rect> {
    CGDisplay::active_displays()
        .unwrap_or_default()
        .into_iter()
        .map(|id| Rect::from_cg(&CGDisplay::new(id).bounds()))
        .collect()
}

/// Whether next to nothing of `frame` shows on any display.
fn mostly_off_screen(frame: &Rect) -> bool {
    let area = frame.w * frame.h;
    if area <= 0.0 {
        return true;
    }
    let visible: f64 = displays().iter().map(|display| display.overlap_area(frame)).sum();
    visible / area < 0.02
}

// ── Session registry ────────────────────────────────────────────────────

#[derive(Clone, Copy)]
struct Parked {
    /// Where the window's top-left corner was before it was parked.
    origin: (f64, f64),
    /// It was minimized, and goes back to the Dock on release.
    minimized: bool,
}

#[derive(Clone)]
struct Attached {
    window_id: u32,
    pid: i32,
    app: String,
    title: String,
    parked: Option<Parked>,
    /// Chromium/Electron content, whose accessibility tree EvoFlux turned on.
    web: bool,
}

#[derive(Default)]
struct Registry {
    attached: HashMap<String, Attached>,
    /// Sessions whose user pressed Stop. Attaching is refused until the user
    /// resumes from the preview card; the agent cannot lift this itself.
    stopped: HashSet<String>,
}

static REGISTRY: Lazy<Mutex<Registry>> = Lazy::new(|| Mutex::new(Registry::default()));

fn registry() -> std::sync::MutexGuard<'static, Registry> {
    REGISTRY.lock().unwrap_or_else(|poisoned| poisoned.into_inner())
}

/// Forget the session's window and put it back where the user left it.
fn release(session_id: &str) -> Option<Attached> {
    let released = registry().attached.remove(session_id);
    clear_refs(session_id);
    if let Some(attached) = &released {
        let still_used = registry().attached.values().any(|other| other.pid == attached.pid);
        if let Some(app) = Ax::application(attached.pid) {
            if let Some(parked) = attached.parked {
                match reach_window(&app, attached.window_id) {
                    Some(window) => unpark(&window, parked, false),
                    None => put_back_later(attached.pid, attached.window_id, parked),
                }
            }
            if attached.web && !still_used {
                // Chromium does extra accessibility work while this is on
                // (and window managers stop animating it); hand it back off.
                let _ = app.set_flag("AXEnhancedUserInterface", false);
            }
        }
    }
    released
}

/// The window, asked for a few times: accessibility can fail for a moment
/// (see [`Target::resolve`]). `None` at once for a window that is gone.
fn reach_window(app: &Ax, id: u32) -> Option<Ax> {
    for attempt in 0..3 {
        if let Some(window) = ax_window(app, id) {
            return Some(window);
        }
        if cg_window(id).is_none() {
            return None;
        }
        if attempt < 2 {
            pause(300);
        }
    }
    None
}

/// Keep trying for two minutes to put back a parked window that
/// accessibility cannot reach now (the user is on another Space, the app is
/// busy). Its own thread looks the app up itself: accessibility elements do
/// not cross threads.
fn put_back_later(pid: i32, window_id: u32, parked: Parked) {
    let _ = std::thread::Builder::new()
        .name("computer-app-put-back".into())
        .spawn(move || {
            for _ in 0..60 {
                pause(2000);
                // Gone, or attached (and parked) again meanwhile.
                if cg_window(window_id).is_none()
                    || registry().attached.values().any(|attached| attached.window_id == window_id)
                {
                    return;
                }
                if let Some(window) = Ax::application(pid).and_then(|app| ax_window(&app, window_id)) {
                    unpark(&window, parked, false);
                    return;
                }
            }
        });
}

pub(crate) fn stop(session_id: &str) {
    registry().stopped.insert(session_id.to_string());
    release(session_id);
}

pub(crate) fn resume(session_id: &str) {
    registry().stopped.remove(session_id);
}

/// Put every parked window back. Called when EvoFlux exits so no app is
/// left stranded in a corner of the screen.
pub(crate) fn release_all() {
    let sessions: Vec<String> = registry().attached.keys().cloned().collect();
    for session in sessions {
        release(&session);
    }
}

pub(crate) fn reveal(session_id: &str) -> Result<Value, String> {
    let attached = {
        let mut registry = registry();
        let entry = registry
            .attached
            .get_mut(session_id)
            .ok_or("No app is attached in this chat.")?;
        // The user is taking the app back; it stays attached but is no
        // longer kept out of sight.
        let snapshot = entry.clone();
        entry.parked = None;
        snapshot
    };
    let app = Ax::application(attached.pid).ok_or("The attached app is gone.")?;
    let window = ax_window(&app, attached.window_id).ok_or("The attached window was closed.")?;
    let _ = app.set_flag("AXHidden", false);
    match attached.parked {
        Some(parked) => unpark(&window, parked, true),
        None => {
            let _ = window.set_flag("AXMinimized", false);
        }
    }
    // The user clicked a button in EvoFlux, the frontmost app, so handing
    // the front over to the app they asked for is theirs to do.
    let _ = window.perform("AXRaise");
    let _ = window.set_flag("AXMain", true);
    let _ = app.set_flag("AXFrontmost", true);
    Ok(json!({ "revealed": true }))
}

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

fn move_out_of_sight(window: &Ax) {
    let (x, y) = hidden_origin();
    if let Some(value) = ax_point_value(x, y) {
        let _ = window.set("AXPosition", &value);
    }
}

fn park(window: &Ax) -> Option<Parked> {
    let minimized = window.flag("AXMinimized").unwrap_or(false);
    if minimized {
        let _ = window.set_flag("AXMinimized", false);
        pause(450);
    }
    let origin = window.position()?;
    move_out_of_sight(window);
    Some(Parked { origin: (origin.x, origin.y), minimized })
}

fn unpark(window: &Ax, parked: Parked, activate: bool) {
    if let Some(value) = ax_point_value(parked.origin.0, parked.origin.1) {
        let _ = window.set("AXPosition", &value);
    }
    if parked.minimized && !activate {
        let _ = window.set_flag("AXMinimized", true);
    }
}

// ── Worker threads ──────────────────────────────────────────────────────
//
// Element refs are Core Foundation objects that have to outlive a single
// command and are not `Send`. Each session's worker thread (see `mod.rs`)
// owns its own and runs its actions one at a time; nothing needs setting up.

pub(crate) fn init_worker_thread() {}

/// Whether `session_id` has a window attached (its worker is still needed).
pub(crate) fn is_attached(session_id: &str) -> bool {
    registry().attached.contains_key(session_id)
}

thread_local! {
    static REFS: RefCell<HashMap<String, SessionRefs>> = RefCell::new(HashMap::new());
    /// The editable element each session last clicked, where `type` goes
    /// when the app reports no focused field of its own.
    static LAST_EDITABLE: RefCell<HashMap<String, Ax>> = RefCell::new(HashMap::new());
}

#[derive(Default)]
struct SessionRefs {
    next: u32,
    elements: HashMap<String, Ax>,
}

/// Drop the session's element refs. They live on the thread that ran the
/// action — the session's worker, in the app — so a release from elsewhere
/// (Stop, exit) also hands the clean-up to that worker, behind whatever it
/// is running.
fn clear_refs(session_id: &str) {
    if !on_worker(session_id) {
        let session = session_id.to_string();
        post_to_worker(session_id, move || clear_refs(&session));
    }
    REFS.with(|refs| {
        refs.borrow_mut().remove(session_id);
    });
    LAST_EDITABLE.with(|last| {
        last.borrow_mut().remove(session_id);
    });
}

// ── Dispatch ────────────────────────────────────────────────────────────

pub(crate) fn run_action(
    emit: &dyn Fn(Value),
    session_id: &str,
    action: &str,
    params: &Value,
) -> Result<Value, String> {
    match action {
        "status" => Ok(status(session_id)),
        "list_windows" => Ok(list_windows(session_id, params)),
        "attach" => attach(session_id, params),
        "detach" => Ok(detach(session_id)),
        _ => {
            let target = Target::resolve(session_id)?;
            match action {
                "screenshot" => screenshot(&target),
                "snapshot" => snapshot(&target, params),
                "find" => find(&target, params),
                "click" => click(emit, &target, params),
                "hover" => hover(emit, &target, params),
                "scroll" => scroll(emit, &target, params),
                "drag" => drag(emit, &target, params),
                "type" => type_text(emit, &target, params),
                "key" => press_key(&target, params),
                "invoke" => invoke(emit, &target, params),
                "set_value" => set_value(emit, &target, params),
                "restore" => Ok(json!({ "restored": target.restored, "window": target.describe() })),
                other => Err(format!("Unknown Computer App Control action: {other}")),
            }
        }
    }
}

fn pause(ms: u64) {
    std::thread::sleep(Duration::from_millis(ms));
}

fn merge(mut base: Value, extra: Value) -> Value {
    if let (Some(base), Value::Object(extra)) = (base.as_object_mut(), extra) {
        base.extend(extra);
    }
    base
}

// ── Windows and apps ────────────────────────────────────────────────────

/// One window as the window server lists it.
struct CgWindow {
    id: u32,
    pid: i32,
    owner: String,
    name: String,
    bounds: Rect,
    layer: i64,
    onscreen: bool,
}

fn dict_value(dict: &CFDictionary, key: CFStringRef) -> Option<CFType> {
    dict.find(key as *const c_void)
        .map(|value| unsafe { CFType::wrap_under_get_rule(*value as CFTypeRef) })
}

fn parse_cg_window(item: *const c_void) -> Option<CgWindow> {
    let dict: CFDictionary = unsafe { CFDictionary::wrap_under_get_rule(item as CFDictionaryRef) };
    let number = |key| dict_value(&dict, key).as_ref().and_then(cf_number);
    let text = |key| dict_value(&dict, key).as_ref().and_then(cf_text).unwrap_or_default();
    let bounds = dict_value(&dict, unsafe { kCGWindowBounds }).and_then(|value| {
        let bounds: CFDictionary =
            unsafe { CFDictionary::wrap_under_get_rule(value.as_CFTypeRef() as CFDictionaryRef) };
        CGRect::from_dict_representation(&bounds)
    })?;
    Some(CgWindow {
        id: number(unsafe { kCGWindowNumber })? as u32,
        pid: number(unsafe { kCGWindowOwnerPID })? as i32,
        owner: text(unsafe { kCGWindowOwnerName }),
        name: text(unsafe { kCGWindowName }),
        bounds: Rect::from_cg(&bounds),
        layer: number(unsafe { kCGWindowLayer }).unwrap_or(0.0) as i64,
        onscreen: dict_value(&dict, unsafe { kCGWindowIsOnscreen })
            .as_ref()
            .and_then(cf_bool)
            .unwrap_or(false),
    })
}

/// Windows front to back, as `CGWindowListCopyWindowInfo` gives them.
fn cg_windows(option: u32, relative_to: u32) -> Vec<CgWindow> {
    let Some(array) = copy_window_info(option, relative_to) else {
        return Vec::new();
    };
    array.iter().filter_map(|item| parse_cg_window(*item)).collect()
}

fn window_id_array(ids: &[u32]) -> CFArray {
    let values: Vec<*const c_void> = ids.iter().map(|&id| id as usize as *const c_void).collect();
    CFArray::from_copyable(&values)
}

/// The window server's description of one window, if it still exists.
fn cg_window(id: u32) -> Option<CgWindow> {
    let ids = window_id_array(&[id]);
    let raw = unsafe { CGWindowListCreateDescriptionFromArray(ids.as_concrete_TypeRef()) };
    if raw.is_null() {
        return None;
    }
    let array: CFArray = unsafe { CFArray::wrap_under_create_rule(raw) };
    let first = array.iter().next().and_then(|item| parse_cg_window(*item));
    first
}

fn process_path(pid: i32) -> Option<String> {
    let mut buffer = vec![0u8; 4096];
    let len = unsafe { proc_pidpath(pid, buffer.as_mut_ptr() as *mut c_void, buffer.len() as u32) };
    (len > 0).then(|| String::from_utf8_lossy(&buffer[..len as usize]).into_owned())
}

fn file_name(path: &str) -> &str {
    path.rsplit('/').next().unwrap_or(path)
}

/// The executable's name, which is what the allow/block policy matches on
/// (the macOS counterpart of Windows' `notepad.exe`).
fn process_name(pid: i32, fallback: &str) -> String {
    process_path(pid)
        .map(|path| file_name(&path).to_string())
        .filter(|name| !name.is_empty())
        .unwrap_or_else(|| fallback.to_string())
}

/// The `.app` bundle a process runs from.
fn bundle_of(path: &str) -> Option<std::path::PathBuf> {
    let index = path.find(".app/")?;
    Some(std::path::PathBuf::from(&path[..index + 4]))
}

/// Whether the app renders its UI with Chromium (Chrome, Edge, Electron
/// apps such as Slack or VS Code). Such apps keep their accessibility tree
/// off until an assistive client turns it on.
fn is_chromium_app(pid: i32) -> bool {
    let Some(bundle) = process_path(pid).as_deref().and_then(bundle_of) else {
        return false;
    };
    let Ok(entries) = std::fs::read_dir(bundle.join("Contents").join("Frameworks")) else {
        return false;
    };
    entries.filter_map(Result::ok).any(|entry| {
        let name = entry.file_name().to_string_lossy().to_lowercase();
        name.ends_with("framework.framework")
            && ["electron", "chrom", "edge", "brave", "vivaldi", "opera", "arc"]
                .iter()
                .any(|engine| name.contains(engine))
    })
}

fn ax_window(app: &Ax, id: u32) -> Option<Ax> {
    app.elements("AXWindows").into_iter().find(|window| window.window_id() == Some(id))
}

fn frontmost_pid() -> Option<i32> {
    Ax::system_wide()?.element("AXFocusedApplication")?.pid()
}

struct WindowRow {
    id: u32,
    pid: i32,
    app: String,
    title: String,
    minimized: bool,
    frame: Rect,
    /// The app's main window, when this one is a dialog of it.
    owner: Option<u32>,
    focused: bool,
}

impl WindowRow {
    fn to_json(&self, front: Option<i32>) -> Value {
        json!({
            "id": self.id,
            "title": self.title,
            "app": self.app,
            "pid": self.pid,
            "minimized": self.minimized,
            "bounds": [self.frame.x.round(), self.frame.y.round(), self.frame.w.round(), self.frame.h.round()],
            "dialog_of": self.owner,
            "foreground": front == Some(self.pid) && self.focused,
        })
    }
}

fn is_dialog(window: &Ax) -> bool {
    matches!(
        window.string("AXSubrole").as_deref(),
        Some("AXDialog" | "AXSystemDialog")
    )
}

/// Every app window a person would call a window: normal-level windows the
/// app also reports through accessibility (which drops the invisible helper
/// windows many apps keep), on this Space or minimized.
fn window_rows() -> Vec<WindowRow> {
    let own = std::process::id() as i32;
    let listed = cg_windows(kCGWindowListOptionAll | kCGWindowListExcludeDesktopElements, kCGNullWindowID);
    let trusted = accessibility_trusted(false);
    let mut apps: HashMap<i32, Option<(Ax, Vec<(u32, Ax)>)>> = HashMap::new();
    let mut names: HashMap<i32, String> = HashMap::new();
    let mut rows = Vec::new();
    for window in listed {
        if window.layer != 0 || window.pid == own || window.bounds.w < 40.0 || window.bounds.h < 40.0 {
            continue;
        }
        let app_windows = apps.entry(window.pid).or_insert_with(|| {
            if !trusted {
                return None;
            }
            let app = Ax::application(window.pid)?;
            let windows = app
                .elements("AXWindows")
                .into_iter()
                .filter_map(|ax| ax.window_id().map(|id| (id, ax)))
                .collect();
            Some((app, windows))
        });
        let ax = app_windows
            .as_ref()
            .and_then(|(_, windows)| windows.iter().find(|(id, _)| *id == window.id))
            .map(|(_, ax)| ax.clone());
        if ax.is_none() && (trusted || !window.onscreen || window.name.trim().is_empty()) {
            continue;
        }
        let app = names
            .entry(window.pid)
            .or_insert_with(|| process_name(window.pid, &window.owner))
            .clone();
        let title = ax
            .as_ref()
            .and_then(|ax| ax.string("AXTitle"))
            .filter(|title| !title.trim().is_empty())
            .or_else(|| Some(window.name.clone()).filter(|name| !name.trim().is_empty()))
            .unwrap_or_else(|| window.owner.clone());
        let (owner, focused) = match (&ax, app_windows) {
            (Some(ax), Some((app, _))) => {
                let main = app.element("AXMainWindow").and_then(|main| main.window_id());
                let owner = main.filter(|main| is_dialog(ax) && *main != window.id);
                let focused = app.element("AXFocusedWindow").is_some_and(|focus| focus.same(ax));
                (owner, focused)
            }
            _ => (None, false),
        };
        rows.push(WindowRow {
            id: window.id,
            pid: window.pid,
            app,
            title,
            minimized: ax.as_ref().and_then(|ax| ax.flag("AXMinimized")).unwrap_or(!window.onscreen),
            frame: window.bounds,
            owner,
            focused,
        });
    }
    rows
}

fn attach_refusal(row: &WindowRow) -> Option<String> {
    if row.pid == std::process::id() as i32 {
        return Some("EvoFlux cannot control its own window.".into());
    }
    if row.app.is_empty() {
        return Some(format!(
            "macOS did not let EvoFlux inspect the process behind \"{}\", so it cannot be controlled.",
            row.title
        ));
    }
    if is_protected_process_name(&row.app) {
        return Some(format!(
            "{} is part of the macOS system or its security settings and cannot be controlled.",
            row.app
        ));
    }
    None
}

fn missing_permissions() -> Vec<&'static str> {
    let mut missing = Vec::new();
    if !accessibility_trusted(false) {
        missing.push("accessibility");
    }
    if !screen_capture_allowed() {
        missing.push("screen_recording");
    }
    missing
}

fn list_windows(session_id: &str, params: &Value) -> Value {
    let filter = params
        .get("app")
        .or_else(|| params.get("query"))
        .and_then(Value::as_str)
        .map(|value| value.trim().to_lowercase())
        .filter(|value| !value.is_empty());
    let front = frontmost_pid();
    // Windows another chat controls: attaching them is refused.
    let held: HashSet<u32> = registry()
        .attached
        .iter()
        .filter(|(other, _)| other.as_str() != session_id)
        .map(|(_, attached)| attached.window_id)
        .collect();
    let windows: Vec<Value> = window_rows()
        .into_iter()
        .filter(|row| attach_refusal(row).is_none())
        .filter(|row| match &filter {
            Some(needle) => {
                row.app.to_lowercase().contains(needle) || row.title.to_lowercase().contains(needle)
            }
            None => true,
        })
        .map(|row| {
            let mut json = row.to_json(front);
            json["controlled_elsewhere"] = json!(held.contains(&row.id));
            json
        })
        .collect();
    let mut result = json!({ "count": windows.len(), "windows": windows, "platform": "macos" });
    let missing = missing_permissions();
    if !missing.is_empty() {
        result["missing_permissions"] = json!(missing);
    }
    result
}

// ── The app picker (Settings → Computer App Control) ────────────────────

static ICONS: Lazy<Mutex<HashMap<String, Option<String>>>> = Lazy::new(|| Mutex::new(HashMap::new()));

/// The app's own icon as a PNG data URL, cached per path.
fn icon_data_url(path: &str) -> Option<String> {
    if let Some(cached) = ICONS.lock().ok()?.get(path) {
        return cached.clone();
    }
    let icon = std::panic::catch_unwind(|| file_icon_provider::get_file_icon(path, 32))
        .ok()
        .and_then(Result::ok);
    let encoded = icon.and_then(|icon| {
        let image = RgbaImage::from_raw(icon.width, icon.height, icon.pixels)?;
        encode_png(&image).ok().map(|data| format!("data:image/png;base64,{data}"))
    });
    if let Ok(mut cache) = ICONS.lock() {
        cache.insert(path.to_string(), encoded.clone());
    }
    encoded
}

/// The executable inside an `.app` bundle: `Contents/MacOS/<name>`, the one
/// named like the bundle when there are several.
fn bundle_executable(bundle: &std::path::Path) -> Option<String> {
    let stem = bundle.file_stem()?.to_str()?.to_string();
    let entries: Vec<String> = std::fs::read_dir(bundle.join("Contents").join("MacOS"))
        .ok()?
        .filter_map(Result::ok)
        .filter(|entry| entry.file_type().map(|kind| kind.is_file()).unwrap_or(false))
        .filter_map(|entry| entry.file_name().to_str().map(str::to_string))
        .collect();
    entries
        .iter()
        .find(|name| name.eq_ignore_ascii_case(&stem))
        .or_else(|| entries.first())
        .cloned()
}

fn application_dirs() -> Vec<std::path::PathBuf> {
    let mut dirs = vec![
        std::path::PathBuf::from("/Applications"),
        std::path::PathBuf::from("/System/Applications"),
    ];
    if let Some(home) = std::env::var_os("HOME") {
        dirs.push(std::path::PathBuf::from(home).join("Applications"));
    }
    dirs.into_iter().filter(|dir| dir.is_dir()).collect()
}

struct AppEntry {
    name: String,
    icon_path: String,
    running: bool,
}

/// Apps a user might allow or block: everything with a window right now,
/// plus the installed applications. Keyed by executable name, which is what
/// the policy matches on.
pub(crate) fn list_apps() -> Value {
    let mut apps: HashMap<String, AppEntry> = HashMap::new();
    for row in window_rows() {
        if attach_refusal(&row).is_some() {
            continue;
        }
        let Some(path) = process_path(row.pid) else {
            continue;
        };
        let bundle = bundle_of(&path);
        let name = bundle
            .as_ref()
            .and_then(|bundle| bundle.file_stem()?.to_str().map(str::to_string))
            .unwrap_or_else(|| row.app.clone());
        let icon_path = bundle
            .map(|bundle| bundle.to_string_lossy().into_owned())
            .unwrap_or(path);
        apps.entry(row.app.to_lowercase())
            .and_modify(|entry| entry.running = true)
            .or_insert(AppEntry { name, icon_path, running: true });
    }
    for dir in application_dirs() {
        let bundles = walkdir::WalkDir::new(&dir)
            .max_depth(2)
            .into_iter()
            .filter_map(Result::ok)
            .filter(|entry| entry.path().extension().and_then(|ext| ext.to_str()) == Some("app"));
        for entry in bundles {
            let bundle = entry.path();
            // Skip helper apps nested inside other bundles.
            if bundle.parent().is_some_and(|parent| parent.to_string_lossy().contains(".app")) {
                continue;
            }
            let (Some(executable), Some(name)) = (
                bundle_executable(bundle),
                bundle.file_stem().and_then(|stem| stem.to_str()).map(str::to_string),
            ) else {
                continue;
            };
            if is_protected_process_name(&executable) {
                continue;
            }
            apps.entry(executable.to_lowercase())
                .and_modify(|entry| entry.name = name.clone())
                .or_insert(AppEntry {
                    name,
                    icon_path: bundle.to_string_lossy().into_owned(),
                    running: false,
                });
        }
    }
    let mut list: Vec<(String, AppEntry)> = apps.into_iter().collect();
    list.sort_by(|(_, a), (_, b)| {
        b.running.cmp(&a.running).then_with(|| a.name.to_lowercase().cmp(&b.name.to_lowercase()))
    });
    let apps: Vec<Value> = list
        .into_iter()
        .map(|(exe, entry)| {
            json!({
                "exe": exe,
                "name": entry.name,
                "running": entry.running,
                "icon": icon_data_url(&entry.icon_path),
            })
        })
        .collect();
    json!({ "apps": apps })
}

fn status(session_id: &str) -> Value {
    let registry = registry();
    let stopped = registry.stopped.contains(session_id);
    match registry.attached.get(session_id) {
        Some(attached) => {
            let window = cg_window(attached.window_id);
            let ax = Ax::application(attached.pid).and_then(|app| ax_window(&app, attached.window_id));
            json!({
                "attached": true,
                "open": window.is_some(),
                "window": {
                    "id": attached.window_id,
                    "app": attached.app,
                    "title": ax.as_ref().and_then(|ax| ax.string("AXTitle")).unwrap_or_else(|| attached.title.clone()),
                    "pid": attached.pid,
                    "minimized": ax.as_ref().and_then(|ax| ax.flag("AXMinimized")).unwrap_or(false),
                    "hidden": attached.parked.is_some(),
                },
                "stopped": stopped,
            })
        }
        None => json!({ "attached": false, "stopped": stopped }),
    }
}

/// Turn on a Chromium app's accessibility tree and wait (up to ~4 s) until
/// its page content shows up in it.
fn enable_web_accessibility(app: &Ax, window: &Ax) {
    // Electron reads the first, Chrome and Edge the second.
    let _ = app.set_flag("AXManualAccessibility", true);
    let _ = app.set_flag("AXEnhancedUserInterface", true);
    let deadline = Instant::now() + Duration::from_secs(4);
    while Instant::now() < deadline {
        let mut budget = 400;
        let ready = find_role(window, "AXWebArea", 12, &mut budget)
            .is_some_and(|area| !area.elements("AXChildren").is_empty());
        if ready {
            return;
        }
        pause(200);
    }
}

/// The first element with `role` at most `depth` levels down, looking at no
/// more than `budget` elements: a browser's own toolbar alone has hundreds.
fn find_role(element: &Ax, role: &str, depth: u32, budget: &mut u32) -> Option<Ax> {
    if *budget == 0 {
        return None;
    }
    *budget -= 1;
    if element.role() == role {
        return Some(element.clone());
    }
    if depth == 0 {
        return None;
    }
    element
        .elements("AXChildren")
        .iter()
        .find_map(|child| find_role(child, role, depth - 1, budget))
}

fn attach(session_id: &str, params: &Value) -> Result<Value, String> {
    if registry().stopped.contains(session_id) {
        return Err("The user stopped Computer App Control in this chat. Ask them before trying again: the preview card is showing again, and they can press Allow again there.".into());
    }
    if !accessibility_trusted(true) {
        return Err(ACCESSIBILITY_REFUSAL.into());
    }
    let window_id = params.get("window_id").and_then(Value::as_u64);
    let rows = window_rows();
    let chosen = if let Some(id) = window_id {
        rows.into_iter()
            .find(|row| u64::from(row.id) == id)
            .ok_or_else(|| format!("No window with id {id}. Call list_windows again."))?
    } else {
        let app = params.get("app").and_then(Value::as_str).map(str::to_lowercase);
        let title = params.get("title").and_then(Value::as_str).map(str::to_lowercase);
        if app.is_none() && title.is_none() {
            return Err("attach needs window_id (from list_windows), app, or title.".into());
        }
        rows.into_iter()
            .filter(|row| attach_refusal(row).is_none())
            .find(|row| {
                app.as_ref().map_or(true, |app| row.app.to_lowercase().contains(app))
                    && title.as_ref().map_or(true, |title| row.title.to_lowercase().contains(title))
            })
            .ok_or("No controllable window matches. Call list_windows to see what is open.")?
    };
    if let Some(reason) = attach_refusal(&chosen) {
        return Err(reason);
    }
    let app = Ax::application(chosen.pid).ok_or("macOS would not open the app for accessibility.")?;
    // A dialog is driven through the window that owns it, so the card keeps
    // following the app when the dialog closes.
    let (id, title) = match chosen.owner.and_then(|owner| ax_window(&app, owner).map(|ax| (owner, ax))) {
        Some((owner, ax)) => (owner, ax.string("AXTitle").unwrap_or_else(|| chosen.title.clone())),
        None => (chosen.id, chosen.title.clone()),
    };
    let window = ax_window(&app, id).ok_or(
        "That window is not reachable through accessibility (it may be on another Space). Ask the user to bring it to this desktop.",
    )?;
    // One chat per window: two would interleave their input, and the second
    // would save the first one's parking spot as the window's own place.
    let held_elsewhere = registry()
        .attached
        .iter()
        .any(|(other, attached)| other != session_id && attached.window_id == id);
    if held_elsewhere {
        return Err(format!(
            "\"{title}\" is already controlled from another chat. Finish or detach there first, or pick another window."
        ));
    }
    // Attaching to another window hands the previous one back first.
    release(session_id);
    let _ = app.set_flag("AXHidden", false);
    let hide = params.get("hide").and_then(Value::as_bool).unwrap_or(false);
    let parked = if hide {
        park(&window)
    } else {
        if window.flag("AXMinimized").unwrap_or(false) {
            let _ = window.set_flag("AXMinimized", false);
            pause(450);
        }
        None
    };
    // After parking: while Chromium's enhanced accessibility is on, window
    // moves through accessibility are animated and can be ignored.
    let web = is_chromium_app(chosen.pid);
    if web {
        enable_web_accessibility(&app, &window);
    }
    // Stop pressed while this attach was parking the window: hand it back
    // instead of registering a window nobody may drive.
    if let Err(stopped) = interrupted() {
        if web {
            let _ = app.set_flag("AXEnhancedUserInterface", false);
        }
        if let Some(parked) = parked {
            unpark(&window, parked, false);
        }
        return Err(stopped);
    }
    registry().attached.insert(
        session_id.to_string(),
        Attached { window_id: id, pid: chosen.pid, app: chosen.app.clone(), title, parked, web },
    );
    let target = Target::resolve(session_id)?;
    Ok(json!({ "attached": true, "window": target.describe() }))
}

fn detach(session_id: &str) -> Value {
    let removed = release(session_id);
    json!({ "detached": removed.is_some() })
}

// ── The window being driven ─────────────────────────────────────────────

struct Target {
    session_id: String,
    top_id: u32,
    /// `top_id`, or the dialog window the app is currently showing over it.
    window_id: u32,
    pid: i32,
    app_name: String,
    app: Ax,
    /// The accessibility element of `window_id`.
    window: Ax,
    frame: Rect,
    scale: f64,
    restored: bool,
    /// Parked out of sight at the user's request.
    hidden: bool,
    /// Chromium/Electron content.
    web: bool,
}

impl Target {
    fn resolve(session_id: &str) -> Result<Self, String> {
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

    fn title(&self) -> String {
        self.window.string("AXTitle").unwrap_or_default()
    }

    fn screenshot_size(&self) -> (u32, u32) {
        (
            (self.frame.w * self.scale).round().max(1.0) as u32,
            (self.frame.h * self.scale).round().max(1.0) as u32,
        )
    }

    fn describe(&self) -> Value {
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
    fn screen_point(&self, x: f64, y: f64) -> Result<Point, String> {
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
    fn screenshot_point(&self, point: Point) -> (i64, i64) {
        (
            ((point.x - self.frame.x) * self.scale).round() as i64,
            ((point.y - self.frame.y) * self.scale).round() as i64,
        )
    }

    fn emit_pointer(&self, emit: &dyn Fn(Value), point: Point, phase: &str) {
        let x = (point.x - self.frame.x) / self.frame.w.max(1.0);
        let y = (point.y - self.frame.y) / self.frame.h.max(1.0);
        emit(json!({ "sessionId": self.session_id, "x": x, "y": y, "phase": phase }));
    }

    /// Move the preview's cursor to `point` and give it time to get there,
    /// so the user sees where the agent is about to act before it does.
    fn travel(&self, emit: &dyn Fn(Value), point: Point) -> Result<(), String> {
        self.emit_pointer(emit, point, "move");
        std::thread::sleep(POINTER_TRAVEL);
        interrupted()
    }

    /// Where accessibility walks start: the window, then any dialog window
    /// of the app sitting over it.
    fn roots(&self) -> Vec<Ax> {
        let mut roots = vec![self.window.clone()];
        if self.window_id != self.top_id {
            if let Some(top) = ax_window(&self.app, self.top_id) {
                roots.push(top);
            }
        }
        roots
    }
}

// ── Capture ─────────────────────────────────────────────────────────────

/// Render the window (with the app's own sheets, alerts and menus stacked
/// over it) from the window server's copy of it: works behind other windows
/// and while parked.
fn capture(window_id: u32, pid: i32, frame: Rect) -> Result<RgbaImage, String> {
    if !screen_capture_allowed() {
        // Shows macOS's own prompt the first time; later it only answers.
        unsafe { CGRequestScreenCaptureAccess() };
        return Err(SCREEN_RECORDING_REFUSAL.into());
    }
    let options =
        kCGWindowImageBoundsIgnoreFraming | kCGWindowImageNominalResolution | kCGWindowImageShouldBeOpaque;
    let mut ids: Vec<u32> = cg_windows(kCGWindowListOptionOnScreenAboveWindow, window_id)
        .into_iter()
        .filter(|window| window.pid == pid && window.bounds.intersects(&frame))
        .map(|window| window.id)
        .collect();
    ids.push(window_id);
    let image = create_image_from_array(frame.to_cg(), window_id_array(&ids), options)
        .or_else(|| create_image(frame.to_cg(), kCGWindowListOptionIncludingWindow, window_id, options))
        .ok_or("macOS returned no image of the window.")?;
    let (width, height) = (image.width(), image.height());
    if width == 0 || height == 0 || image.bits_per_pixel() != 32 {
        return Err("macOS returned an empty or unexpected image of the window.".into());
    }
    let bytes_per_row = image.bytes_per_row();
    let data = image.data();
    let bytes = data.bytes();
    let mut pixels = Vec::with_capacity(width * height * 4);
    for row in bytes.chunks(bytes_per_row).take(height) {
        pixels.extend_from_slice(&row[..width * 4]);
    }
    for pixel in pixels.chunks_exact_mut(4) {
        // Window images are BGRA in memory.
        pixel.swap(0, 2);
        pixel[3] = 255;
    }
    let captured = RgbaImage::from_raw(width as u32, height as u32, pixels)
        .ok_or("Captured pixels did not match the window size.")?;
    // One screenshot pixel per point, whatever the display's scale.
    let (points_w, points_h) = (frame.w.round().max(1.0) as u32, frame.h.round().max(1.0) as u32);
    Ok(if captured.width() != points_w || captured.height() != points_h {
        imageops::resize(&captured, points_w, points_h, imageops::FilterType::Triangle)
    } else {
        captured
    })
}

fn encode_png(image: &RgbaImage) -> Result<String, String> {
    let mut bytes = std::io::Cursor::new(Vec::new());
    image
        .write_to(&mut bytes, image::ImageFormat::Png)
        .map_err(|error| format!("PNG encoding failed: {error}"))?;
    Ok(BASE64.encode(bytes.into_inner()))
}

fn encode_jpeg(image: &RgbaImage, quality: u8) -> Result<String, String> {
    let rgb = DynamicImage::ImageRgba8(image.clone()).to_rgb8();
    let mut bytes = Vec::new();
    image::codecs::jpeg::JpegEncoder::new_with_quality(&mut bytes, quality)
        .encode_image(&rgb)
        .map_err(|error| format!("JPEG encoding failed: {error}"))?;
    Ok(BASE64.encode(bytes))
}

fn screenshot(target: &Target) -> Result<Value, String> {
    let captured = capture(target.window_id, target.pid, target.frame)?;
    let (width, height) = target.screenshot_size();
    let image = if target.scale < 1.0 {
        imageops::resize(&captured, width, height, imageops::FilterType::Triangle)
    } else {
        captured
    };
    Ok(json!({
        "kind": "image",
        "data": encode_png(&image)?,
        "media_type": "image/png",
        "width": image.width(),
        "height": image.height(),
        "window": target.describe(),
        "restored": target.restored,
    }))
}

/// A small JPEG of the attached window for the preview card. Never restores
/// a minimized window: watching must not change what is on screen.
pub(crate) fn preview_frame(session_id: &str, max_width: u32) -> Result<Value, String> {
    let (attached, stopped) = {
        let registry = registry();
        (registry.attached.get(session_id).cloned(), registry.stopped.contains(session_id))
    };
    let Some(attached) = attached else {
        return Ok(json!({ "attached": false, "stopped": stopped }));
    };
    let base = json!({
        "attached": true,
        "stopped": stopped,
        "app": attached.app,
        "title": attached.title,
    });
    let Some(top) = cg_window(attached.window_id) else {
        return Ok(merge(base, json!({ "closed": true })));
    };
    let app = Ax::application(attached.pid);
    let ax = app.as_ref().and_then(|app| ax_window(app, attached.window_id));
    let title = ax
        .as_ref()
        .and_then(|ax| ax.string("AXTitle"))
        .unwrap_or_else(|| attached.title.clone());
    if ax.as_ref().and_then(|ax| ax.flag("AXMinimized")).unwrap_or(false)
        || app.as_ref().and_then(|app| app.flag("AXHidden")).unwrap_or(false)
    {
        return Ok(merge(base, json!({ "minimized": true, "title": title })));
    }
    let dialog = app.as_ref().and_then(|app| app.element("AXFocusedWindow")).filter(|focus| {
        ax.as_ref().is_some_and(|ax| !focus.same(ax)) && is_dialog(focus)
    });
    let (window_id, frame) = match dialog.as_ref().and_then(Ax::window_id).and_then(cg_window) {
        Some(window) => (window.id, window.bounds),
        None => (top.id, top.bounds),
    };
    let captured = capture(window_id, attached.pid, frame)?;
    let (width, height) = (captured.width(), captured.height());
    let preview = if width > max_width {
        let scaled_height = ((height as f64) * (max_width as f64) / (width as f64)).round() as u32;
        imageops::thumbnail(&captured, max_width, scaled_height.max(1))
    } else {
        captured
    };
    Ok(merge(
        base,
        json!({
            "title": title,
            "dialog": window_id != attached.window_id,
            "width": width,
            "height": height,
            "media_type": "image/jpeg",
            "data": encode_jpeg(&preview, 72)?,
        }),
    ))
}

// ── The accessibility tree ──────────────────────────────────────────────

/// Attributes read for every element in one round trip to the app.
const INFO_ATTRIBUTES: [&str; 9] = [
    "AXRole",
    "AXSubrole",
    "AXTitle",
    "AXDescription",
    "AXValue",
    "AXPosition",
    "AXSize",
    "AXEnabled",
    "AXIdentifier",
];

struct Info {
    role: String,
    title: String,
    description: String,
    value: Option<CFType>,
    frame: Option<Rect>,
    enabled: bool,
    identifier: String,
}

impl Info {
    /// "AXButton" → "Button": the names the agent reads and searches.
    fn short_role(&self) -> &str {
        self.role.strip_prefix("AX").unwrap_or(&self.role)
    }

    fn name(&self) -> String {
        if !self.title.trim().is_empty() {
            return self.title.clone();
        }
        if !self.description.trim().is_empty() {
            return self.description.clone();
        }
        if self.role == "AXStaticText" {
            return self.value.as_ref().and_then(cf_text).unwrap_or_default();
        }
        String::new()
    }
}

thread_local! {
    static INFO_NAMES: CFArray<CFString> =
        CFArray::from_CFTypes(&INFO_ATTRIBUTES.map(cf_string));
}

fn info(element: &Ax) -> Info {
    let values: [Option<CFType>; INFO_ATTRIBUTES.len()] = INFO_NAMES.with(|names| element.attributes(names));
    let text = |index: usize| values[index].as_ref().and_then(cf_text).unwrap_or_default();
    let origin = values[5].as_ref().and_then(ax_point);
    let size = values[6].as_ref().and_then(ax_size);
    Info {
        role: text(0),
        title: text(2),
        description: text(3),
        value: values[4].clone(),
        frame: origin.zip(size).map(|(origin, size)| Rect {
            x: origin.x,
            y: origin.y,
            w: size.width,
            h: size.height,
        }),
        enabled: values[7].as_ref().and_then(cf_bool).unwrap_or(true),
        identifier: text(8),
    }
}

/// Containers that carry no meaning of their own when unnamed. They are
/// walked through but not listed, which keeps a snapshot readable.
fn is_structural(role: &str) -> bool {
    matches!(
        role,
        "AXGroup" | "AXScrollArea" | "AXSplitGroup" | "AXUnknown" | "AXLayoutArea" | "AXLayoutItem"
            | "AXSplitter" | "AXWindow" | "AXMatte" | "AXGrowArea" | "AXScrollBar" | "AXValueIndicator"
            | "AXColumn" | "AXRuler" | "AXGenericElement" | ""
    )
}

fn is_text_role(role: &str) -> bool {
    matches!(role, "AXTextField" | "AXTextArea" | "AXComboBox" | "AXSearchField")
}

fn is_editable(element: &Ax) -> bool {
    is_text_role(&element.role()) && (element.settable("AXValue") || element.settable("AXSelectedText"))
}

fn truncate(text: &str, max: usize) -> String {
    let clean: String = text.chars().map(|ch| if ch.is_control() { ' ' } else { ch }).collect();
    if clean.chars().count() <= max {
        clean
    } else {
        let mut cut: String = clean.chars().take(max).collect();
        cut.push('…');
        cut
    }
}

struct Walk<'a> {
    target: &'a Target,
    refs: &'a mut SessionRefs,
    max_depth: u32,
    max_elements: usize,
    /// Only list elements matching this (lower-cased) text; `None` lists all.
    query: Option<String>,
    /// Keep elements outside the window (the menu bar is).
    anywhere: bool,
    lines: Vec<String>,
    visited: usize,
}

impl Walk<'_> {
    fn element_line(&mut self, element: &Ax, info: &Info, depth: u32) -> bool {
        let frame = info.frame.unwrap_or_default();
        // Judged against the window rather than the screen: a parked window
        // is nearly all off-screen, yet every control in it is usable.
        // Elements scrolled out of the window are still skipped.
        if !self.anywhere && !frame.intersects(&self.target.frame) {
            return false;
        }
        let role = info.short_role().to_string();
        let name = info.name();
        let listed = match &self.query {
            Some(query) => {
                name.to_lowercase().contains(query)
                    || info.identifier.to_lowercase().contains(query)
                    || role.to_lowercase() == *query
            }
            None => !(is_structural(&info.role) && name.trim().is_empty()),
        };
        if listed && (self.anywhere || !frame.is_empty()) {
            self.refs.next += 1;
            let reference = format!("e{}", self.refs.next);
            self.refs.elements.insert(reference.clone(), element.clone());
            let indent = if self.query.is_some() { 0 } else { depth as usize };
            let mut line = format!("{}- {role}", "  ".repeat(indent.min(24)));
            if !name.trim().is_empty() {
                line.push_str(&format!(" \"{}\"", truncate(&name, 120)));
            }
            let value = info.value.as_ref();
            match info.role.as_str() {
                "AXCheckBox" | "AXRadioButton" | "AXSwitch" => {
                    if let Some(on) = value.and_then(cf_bool) {
                        line.push_str(if on { " [checked]" } else { " [unchecked]" });
                    }
                }
                role if is_text_role(role) || matches!(role, "AXSlider" | "AXIncrementor" | "AXPopUpButton" | "AXValueIndicator") => {
                    if let Some(text) = value.and_then(cf_text).filter(|text| !text.is_empty()) {
                        line.push_str(&format!(" value=\"{}\"", truncate(&text, 200)));
                    }
                }
                _ => {}
            }
            if !info.enabled {
                line.push_str(" [disabled]");
            }
            if frame.is_empty() || !frame.intersects(&self.target.frame) {
                line.push_str(&format!(" [ref={reference}]"));
            } else {
                let (x, y) = self.target.screenshot_point(Point { x: frame.x, y: frame.y });
                let width = (frame.w * self.target.scale).round() as i64;
                let height = (frame.h * self.target.scale).round() as i64;
                line.push_str(&format!(" [ref={reference}] @{x},{y} {width}x{height}"));
            }
            self.lines.push(line);
        }
        listed
    }

    fn walk(&mut self, element: &Ax, depth: u32) {
        if depth > self.max_depth || self.lines.len() >= self.max_elements || self.visited > 20_000 {
            return;
        }
        self.visited += 1;
        let info = info(element);
        let listed = self.element_line(element, &info, depth);
        // Closed menus hold hundreds of items; only a search goes into them.
        if info.role == "AXMenu" && self.query.is_none() {
            return;
        }
        let child_depth = if listed { depth + 1 } else { depth };
        for child in element.elements("AXChildren") {
            self.walk(&child, child_depth);
            if self.lines.len() >= self.max_elements {
                return;
            }
        }
    }
}

fn walk_roots(
    target: &Target,
    roots: &[Ax],
    query: Option<String>,
    anywhere: bool,
    max_depth: u32,
    max_elements: usize,
    reset: bool,
) -> (Vec<String>, bool) {
    REFS.with(|refs| {
        let mut refs = refs.borrow_mut();
        if reset {
            refs.remove(&target.session_id);
        }
        let session_refs = refs.entry(target.session_id.clone()).or_default();
        let mut walk = Walk {
            target,
            refs: session_refs,
            max_depth,
            max_elements,
            query,
            anywhere,
            lines: Vec::new(),
            visited: 0,
        };
        for root in roots {
            walk.walk(root, 0);
        }
        let truncated = walk.lines.len() >= max_elements;
        (walk.lines, truncated)
    })
}

fn snapshot(target: &Target, params: &Value) -> Result<Value, String> {
    let max_depth = params.get("max_depth").and_then(Value::as_u64).unwrap_or(30).clamp(1, 80) as u32;
    let max_elements = params.get("max_elements").and_then(Value::as_u64).unwrap_or(400).clamp(10, 2000) as usize;
    let (lines, truncated) = walk_roots(target, &target.roots(), None, false, max_depth, max_elements, true);
    let (width, height) = target.screenshot_size();
    let mut text = format!(
        "UI of {} — \"{}\" (coordinates are screenshot pixels of a {width}x{height} screenshot)\n",
        target.app_name,
        target.title()
    );
    if lines.is_empty() {
        text.push_str("(This app exposes no accessibility tree; use screenshot and coordinates.)");
    } else {
        text.push_str(&lines.join("\n"));
    }
    if truncated {
        text.push_str("\n(Truncated: use find to search for a specific control.)");
    }
    text.push_str("\n(Menu bar commands are not listed: find them by name, e.g. find \"Save\", then invoke the ref.)");
    Ok(Value::String(text))
}

fn find(target: &Target, params: &Value) -> Result<Value, String> {
    let query = params
        .get("query")
        .and_then(Value::as_str)
        .map(|query| query.trim().to_lowercase())
        .filter(|query| !query.is_empty())
        .ok_or("find needs a query.")?;
    let limit = params.get("limit").and_then(Value::as_u64).unwrap_or(20).clamp(1, 100) as usize;
    let (mut lines, _) = walk_roots(target, &target.roots(), Some(query.clone()), false, 60, limit, false);
    if lines.len() < limit {
        let menus = app_menus(&target.app);
        let (menu_lines, _) = walk_roots(target, &menus, Some(query.clone()), true, 8, limit - lines.len(), false);
        lines.extend(menu_lines.into_iter().map(|line| format!("{line} (menu bar)")));
    }
    Ok(Value::String(if lines.is_empty() {
        format!("No control matching \"{query}\" in {}.", target.app_name)
    } else {
        lines.join("\n")
    }))
}

/// The app's own menus in its menu bar. The first menu bar item is the
/// Apple menu, which belongs to the system (Log Out, Shut Down, Force Quit,
/// System Settings) and is never offered to the agent.
fn app_menus(app: &Ax) -> Vec<Ax> {
    app.element("AXMenuBar")
        .map(|bar| bar.elements("AXChildren").into_iter().skip(1).collect())
        .unwrap_or_default()
}

fn element_for(session_id: &str, reference: &str) -> Result<Ax, String> {
    let reference = reference.trim().trim_start_matches("ref=").trim_start_matches('@');
    REFS.with(|refs| {
        refs.borrow()
            .get(session_id)
            .and_then(|session| session.elements.get(reference).cloned())
    })
    .ok_or_else(|| format!("Unknown ref {reference:?}. Take a new snapshot or find, then use a ref from it."))
}

fn element_center(element: &Ax) -> Option<Point> {
    element.frame().filter(|frame| !frame.is_empty()).map(|frame| frame.center())
}

/// The chain of elements under `point` in the attached window, outermost
/// first. Walks the window's own tree rather than hit-testing the screen:
/// the app may be behind other windows or parked, where a screen hit-test
/// would find something else.
fn elements_at(target: &Target, point: Point) -> Vec<Ax> {
    target
        .roots()
        .into_iter()
        .map(|root| chain_at(root, point))
        .max_by_key(Vec::len)
        .unwrap_or_default()
}

fn chain_at(root: Ax, point: Point) -> Vec<Ax> {
    let mut chain = vec![root.clone()];
    let mut current = root;
    let mut visited = 0usize;
    'descend: loop {
        let children = current.elements("AXChildren");
        // Later siblings draw over earlier ones.
        for child in children.into_iter().rev() {
            visited += 1;
            if visited > 20_000 {
                break 'descend;
            }
            if child.frame().is_some_and(|frame| frame.contains(point)) {
                chain.push(child.clone());
                current = child;
                continue 'descend;
            }
        }
        break;
    }
    chain
}

/// `element` and its ancestors, outermost first (the order [`elements_at`]
/// returns), so callers can look for the nearest one with a capability.
fn with_ancestors(element: Ax) -> Vec<Ax> {
    let mut chain = vec![element];
    while chain.len() < 64 {
        match chain.last().and_then(|last| last.element("AXParent")) {
            Some(parent) if parent.role() != "AXApplication" => chain.push(parent),
            _ => break,
        }
    }
    chain.reverse();
    chain
}

fn remember_editable(session_id: &str, element: &Ax) {
    LAST_EDITABLE.with(|last| {
        last.borrow_mut().insert(session_id.to_string(), element.clone());
    });
}

/// What "clicking" an element means through accessibility.
enum UiAction {
    Action(&'static str),
    /// Expand or collapse an outline row.
    Disclose(bool),
    Select,
}

fn ui_action_for(element: &Ax) -> Option<UiAction> {
    let actions = element.actions();
    for action in ["AXPress", "AXConfirm", "AXPick", "AXOpen"] {
        if actions.iter().any(|name| name == action) {
            return Some(UiAction::Action(action));
        }
    }
    if element.settable("AXDisclosing") {
        return Some(UiAction::Disclose(!element.flag("AXDisclosing").unwrap_or(false)));
    }
    if element.settable("AXSelected") && !element.flag("AXSelected").unwrap_or(false) {
        return Some(UiAction::Select);
    }
    None
}

fn perform(element: &Ax, action: &UiAction) -> Result<&'static str, AXError> {
    match action {
        UiAction::Action(name) => element.perform(name).map(|()| match *name {
            "AXPress" => "press",
            "AXConfirm" => "confirm",
            "AXPick" => "pick",
            _ => "open",
        }),
        UiAction::Disclose(open) => element
            .set_flag("AXDisclosing", *open)
            .map(|()| if *open { "expand" } else { "collapse" }),
        UiAction::Select => element.set_flag("AXSelected", true).map(|()| "select"),
    }
}

fn ax_error(error: AXError) -> String {
    let meaning = match error {
        -25200 => "the app refused",
        -25201 => "illegal argument",
        -25202 => "the element is gone",
        -25204 => "the app did not answer in time",
        -25205 => "the attribute is not supported",
        -25206 => "the action is not supported",
        -25211 => "accessibility is not allowed for EvoFlux",
        _ => "accessibility error",
    };
    format!("{meaning} ({error})")
}

// ── Pointer input ───────────────────────────────────────────────────────

fn event_source() -> Result<CGEventSource, String> {
    // A private state: what the user holds on the real keyboard does not
    // leak into the agent's events, nor the other way round.
    CGEventSource::new(CGEventSourceStateID::Private)
        .map_err(|()| "Could not create an input event source.".to_string())
}

fn point_cg(point: Point) -> CGPoint {
    CGPoint::new(point.x, point.y)
}

/// Post a mouse event to the app's process, addressed to its window, so
/// AppKit routes it there without the event passing the window server's
/// hit-testing (which would pick whatever is on screen at that point) and
/// without moving the user's cursor.
fn post_mouse(
    target: &Target,
    kind: CGEventType,
    point: Point,
    button: CGMouseButton,
    click_state: i64,
) -> Result<(), String> {
    let event = CGEvent::new_mouse_event(event_source()?, kind, point_cg(point), button)
        .map_err(|()| "Could not create a mouse event.".to_string())?;
    stamp_window(&event, target);
    if click_state > 0 {
        event.set_integer_value_field(EventField::MOUSE_EVENT_CLICK_STATE, click_state);
    }
    event.post_to_pid(target.pid);
    Ok(())
}

fn stamp_window(event: &CGEvent, target: &Target) {
    let window = i64::from(target.window_id);
    event.set_integer_value_field(EventField::MOUSE_EVENT_WINDOW_UNDER_MOUSE_POINTER, window);
    event.set_integer_value_field(
        EventField::MOUSE_EVENT_WINDOW_UNDER_MOUSE_POINTER_THAT_CAN_HANDLE_THIS_EVENT,
        window,
    );
}

/// Where a pointer action lands: a ref's centre or screenshot coordinates.
fn pointer_target(target: &Target, params: &Value) -> Result<Point, String> {
    if let Some(reference) = params.get("ref").and_then(Value::as_str) {
        let element = element_for(&target.session_id, reference)?;
        return element_center(&element)
            .ok_or_else(|| format!("{reference} is not visible on screen; try invoke instead."));
    }
    let x = params.get("x").and_then(Value::as_f64);
    let y = params.get("y").and_then(Value::as_f64);
    match (x, y) {
        (Some(x), Some(y)) => target.screen_point(x, y),
        _ => Err("Give either a ref or both x and y (screenshot pixels).".into()),
    }
}

fn pointer_result(target: &Target, point: Point, delivered_to: &str, extra: Value) -> Value {
    let (x, y) = target.screenshot_point(point);
    merge(
        json!({
            "pointer": { "x": x, "y": y },
            "delivered_to": delivered_to,
            "delivered_via": "posted_event",
            "window": target.title(),
        }),
        extra,
    )
}

/// Said whenever posted mouse events had to be used.
const POSTED_INPUT_NOTE: &str = "macOS apps may ignore mouse events while they are in the background. If nothing changed, use snapshot or find, then click or invoke by ref.";

fn click(emit: &dyn Fn(Value), target: &Target, params: &Value) -> Result<Value, String> {
    let point = pointer_target(target, params)?;
    let button = params.get("button").and_then(Value::as_str).unwrap_or("left");
    let clicks = params.get("clicks").and_then(Value::as_u64).unwrap_or(1).clamp(1, 3) as i64;
    let (down, up, mouse_button) = match button {
        "left" => (CGEventType::LeftMouseDown, CGEventType::LeftMouseUp, CGMouseButton::Left),
        "right" => (CGEventType::RightMouseDown, CGEventType::RightMouseUp, CGMouseButton::Right),
        "middle" => (CGEventType::OtherMouseDown, CGEventType::OtherMouseUp, CGMouseButton::Center),
        other => return Err(format!("Unknown mouse button {other:?}")),
    };
    let chain = match params.get("ref").and_then(Value::as_str) {
        Some(reference) => with_ancestors(element_for(&target.session_id, reference)?),
        None => elements_at(target, point),
    };

    // Accessibility first: it reaches a background app exactly, while
    // posted mouse events may be dropped or bring the app forward.
    if clicks == 1 {
        let done = match button {
            "left" => click_via_accessibility(emit, target, &chain, point)?,
            "right" => menu_via_accessibility(emit, target, &chain, point)?,
            _ => None,
        };
        if let Some(done) = done {
            return Ok(done);
        }
    }

    target.travel(emit, point)?;
    target.emit_pointer(emit, point, "press");
    post_mouse(target, CGEventType::MouseMoved, point, CGMouseButton::Left, 0)?;
    for index in 1..=clicks {
        interrupted()?;
        post_mouse(target, down, point, mouse_button, index)?;
        pause(25);
        post_mouse(target, up, point, mouse_button, index)?;
        pause(40);
    }
    target.emit_pointer(emit, point, "click");
    let delivered_to = chain.last().map(|element| info(element).short_role().to_string()).unwrap_or_default();
    Ok(pointer_result(
        target,
        point,
        &delivered_to,
        json!({ "button": button, "clicks": clicks, "note": POSTED_INPUT_NOTE }),
    ))
}

/// Click through accessibility: the innermost element under the point that
/// has an action gets it, and a text field there gets focus for typing.
/// Returns `None` when nothing there does, and the caller falls back to
/// posted mouse events.
fn click_via_accessibility(
    emit: &dyn Fn(Value),
    target: &Target,
    chain: &[Ax],
    point: Point,
) -> Result<Option<Value>, String> {
    let editable = chain.iter().rev().find(|element| is_editable(element));
    if let Some(editable) = editable {
        remember_editable(&target.session_id, editable);
    }
    for element in chain.iter().rev() {
        if editable.is_some_and(|field| field.same(element)) {
            break;
        }
        let Some(action) = ui_action_for(element) else {
            continue;
        };
        let name = element.label();
        target.travel(emit, point)?;
        target.emit_pointer(emit, point, "click");
        let used = perform(element, &action)
            .map_err(|error| format!("\"{name}\" refused the click: {}", ax_error(error)))?;
        let (x, y) = target.screenshot_point(point);
        return Ok(Some(json!({
            "pointer": { "x": x, "y": y },
            "delivered_to": name,
            "delivered_via": "accessibility",
            "pattern": used,
            "window": target.title(),
            "button": "left",
            "clicks": 1,
        })));
    }
    if let Some(field) = editable {
        target.travel(emit, point)?;
        target.emit_pointer(emit, point, "click");
        let _ = field.set_flag("AXFocused", true);
        let (x, y) = target.screenshot_point(point);
        return Ok(Some(json!({
            "pointer": { "x": x, "y": y },
            "delivered_to": field.label(),
            "delivered_via": "accessibility",
            "pattern": "focus_for_typing",
            "window": target.title(),
            "button": "left",
            "clicks": 1,
        })));
    }
    Ok(None)
}

/// A right click is a request for the context menu, which accessibility
/// opens directly.
fn menu_via_accessibility(
    emit: &dyn Fn(Value),
    target: &Target,
    chain: &[Ax],
    point: Point,
) -> Result<Option<Value>, String> {
    let Some(element) = chain
        .iter()
        .rev()
        .find(|element| element.actions().iter().any(|name| name == "AXShowMenu"))
    else {
        return Ok(None);
    };
    target.travel(emit, point)?;
    target.emit_pointer(emit, point, "click");
    element
        .perform("AXShowMenu")
        .map_err(|error| format!("The context menu did not open: {}", ax_error(error)))?;
    let (x, y) = target.screenshot_point(point);
    Ok(Some(json!({
        "pointer": { "x": x, "y": y },
        "delivered_to": element.label(),
        "delivered_via": "accessibility",
        "pattern": "show_menu",
        "window": target.title(),
        "button": "right",
        "clicks": 1,
    })))
}

fn hover(emit: &dyn Fn(Value), target: &Target, params: &Value) -> Result<Value, String> {
    let point = pointer_target(target, params)?;
    target.travel(emit, point)?;
    post_mouse(target, CGEventType::MouseMoved, point, CGMouseButton::Left, 0)?;
    Ok(pointer_result(target, point, "window", json!({})))
}

/// The scroll bar of the innermost scroll area in `chain` for a direction.
fn scroll_bar(chain: &[Ax], vertical: bool) -> Option<(Ax, Ax)> {
    let attribute = if vertical { "AXVerticalScrollBar" } else { "AXHorizontalScrollBar" };
    chain
        .iter()
        .rev()
        .find_map(|element| element.element(attribute).map(|bar| (element.clone(), bar)))
}

fn scroll_bar_value(bar: &Ax) -> Option<f64> {
    bar.attribute("AXValue").as_ref().and_then(cf_number)
}

fn scroll(emit: &dyn Fn(Value), target: &Target, params: &Value) -> Result<Value, String> {
    let point = if params.get("ref").is_some() || params.get("x").is_some() {
        pointer_target(target, params)?
    } else {
        target.frame.center()
    };
    let direction = params.get("direction").and_then(Value::as_str).unwrap_or("down");
    let amount = params.get("amount").and_then(Value::as_u64).unwrap_or(3).clamp(1, 50) as i32;
    // Line units: positive is up / left, as a wheel reports it.
    let (vertical, lines) = match direction {
        "down" => (true, -amount),
        "up" => (true, amount),
        "right" => (false, -amount),
        "left" => (false, amount),
        other => return Err(format!("Unknown scroll direction {other:?}")),
    };
    let chain = match params.get("ref").and_then(Value::as_str) {
        Some(reference) => with_ancestors(element_for(&target.session_id, reference)?),
        None => elements_at(target, point),
    };
    let bar = scroll_bar(&chain, vertical);
    let before = bar.as_ref().and_then(|(_, bar)| scroll_bar_value(bar));
    target.travel(emit, point)?;
    for _ in 0..amount {
        interrupted()?;
        let step = lines.signum();
        let (wheel1, wheel2) = if vertical { (step, 0) } else { (0, step) };
        let event = CGEvent::new_scroll_event(event_source()?, ScrollEventUnit::LINE, 2, wheel1, wheel2, 0)
            .map_err(|()| "Could not create a scroll event.".to_string())?;
        event.set_location(point_cg(point));
        stamp_window(&event, target);
        event.post_to_pid(target.pid);
        pause(30);
    }
    pause(150);
    let mut result = pointer_result(target, point, "scroll area", json!({ "direction": direction, "amount": amount }));
    // A background app may ignore the wheel. Its scroll bar tells: when the
    // position did not move, move the scroll bar itself.
    if let (Some((area, bar)), Some(before)) = (&bar, before) {
        let after = scroll_bar_value(bar).unwrap_or(before);
        if (after - before).abs() < 1e-6 && bar.settable("AXValue") {
            let delta = f64::from(-lines) * 0.05;
            let value = (before + delta).clamp(0.0, 1.0);
            bar.set("AXValue", &CFNumber::from(value).as_CFType())
                .map_err(|error| format!("The scroll bar refused to move: {}", ax_error(error)))?;
            result["delivered_to"] = json!(area.label());
            result["delivered_via"] = json!("accessibility");
            result["pattern"] = json!("scroll_bar");
        }
    }
    Ok(result)
}

fn drag(emit: &dyn Fn(Value), target: &Target, params: &Value) -> Result<Value, String> {
    let from = pointer_target(target, params)?;
    let to_x = params.get("to_x").and_then(Value::as_f64);
    let to_y = params.get("to_y").and_then(Value::as_f64);
    let to = match (to_x, to_y) {
        (Some(x), Some(y)) => target.screen_point(x, y)?,
        _ => return Err("drag needs to_x and to_y (screenshot pixels).".into()),
    };
    target.travel(emit, from)?;
    target.emit_pointer(emit, from, "press");
    post_mouse(target, CGEventType::MouseMoved, from, CGMouseButton::Left, 0)?;
    post_mouse(target, CGEventType::LeftMouseDown, from, CGMouseButton::Left, 1)?;
    const STEPS: i32 = 14;
    for step in 1..=STEPS {
        let t = f64::from(step) / f64::from(STEPS);
        let point = Point { x: from.x + (to.x - from.x) * t, y: from.y + (to.y - from.y) * t };
        pause(24);
        if let Err(stopped) = interrupted() {
            // Let go of the button rather than leave the app mid-drag.
            let _ = post_mouse(target, CGEventType::LeftMouseUp, point, CGMouseButton::Left, 1);
            return Err(stopped);
        }
        post_mouse(target, CGEventType::LeftMouseDragged, point, CGMouseButton::Left, 1)?;
        target.emit_pointer(emit, point, "drag");
    }
    pause(60);
    post_mouse(target, CGEventType::LeftMouseUp, to, CGMouseButton::Left, 1)?;
    target.emit_pointer(emit, to, "click");
    let (x, y) = target.screenshot_point(to);
    Ok(pointer_result(
        target,
        from,
        "window",
        json!({ "to": { "x": x, "y": y }, "note": POSTED_INPUT_NOTE }),
    ))
}

// ── Keyboard input ──────────────────────────────────────────────────────

/// The field keystrokes should go to: the app's own focused element (tracked
/// per app even while it is in the background) when it is in the attached
/// window, else the field the agent last clicked.
fn focused_field(target: &Target) -> Option<Ax> {
    let focused = target.app.element("AXFocusedUIElement").filter(|element| {
        element.element("AXWindow").is_some_and(|window| {
            let id = window.window_id();
            id == Some(target.window_id) || id == Some(target.top_id)
        })
    });
    let last = LAST_EDITABLE.with(|last| last.borrow().get(&target.session_id).cloned());
    // A web page often reports its document, not a field, as focused.
    match focused {
        Some(focused) if is_editable(&focused) => Some(focused),
        focused => last.or(focused),
    }
}

fn in_web_area(element: &Ax) -> bool {
    with_ancestors(element.clone()).iter().any(|ancestor| ancestor.role() == "AXWebArea")
}

fn char_count(text: &str) -> usize {
    text.encode_utf16().count()
}

/// Compare what a field holds with what was typed, ignoring the line-break
/// and whitespace differences editors introduce.
fn squash(text: &str) -> String {
    text.split_whitespace().collect::<Vec<_>>().join(" ")
}

/// What reading a field back says about text put into it.
enum Landed {
    Confirmed,
    /// The field holds something new that is not exactly the text (an
    /// editor reformatted it, or autocorrect ran). Typing again would
    /// double it.
    Changed,
    /// The field did not change: the text did not arrive.
    Unchanged,
    /// The field does not report its value (a password field, say).
    Unreadable,
}

fn landed(before: &Option<String>, after: &Option<String>, text: &str, replace: bool) -> Landed {
    let Some(after_text) = after else {
        return Landed::Unreadable;
    };
    let contains = squash(after_text).contains(&squash(text));
    let grew = before.as_ref().map_or(true, |before| after_text.len() > before.len());
    if contains && (replace || grew) {
        Landed::Confirmed
    } else if after == before {
        Landed::Unchanged
    } else {
        Landed::Changed
    }
}

/// Put `text` into `field` through accessibility: replace its selection
/// (the caret, when nothing is selected) the way typing would, and read the
/// value back. With `replace`, the whole content is selected first. Web
/// editors see this as text input, unlike a plain value write.
fn insert_via_accessibility(field: &Ax, text: &str, replace: bool) -> Result<Landed, AXError> {
    let _ = field.set_flag("AXFocused", true);
    let before = field.value_text();
    if replace {
        let length = before.as_deref().map(char_count).unwrap_or(0);
        if let Some(range) = ax_range_value(0, length) {
            let _ = field.set("AXSelectedTextRange", &range);
        }
    }
    field.set("AXSelectedText", &cf_string(text).as_CFType())?;
    pause(120);
    Ok(landed(&before, &field.value_text(), text, replace))
}

/// Type `text` as key events posted to the app's process. Characters travel
/// as Unicode strings (no keyboard layout involved), line breaks as Return
/// — or Shift+Return in web content, so a chat message is not sent.
fn type_via_keyboard(target: &Target, text: &str, web: bool, delay: u64) -> Result<(), String> {
    let mut chunk: Vec<u16> = Vec::new();
    let flush = |chunk: &mut Vec<u16>| -> Result<(), String> {
        if chunk.is_empty() {
            return Ok(());
        }
        interrupted()?;
        for down in [true, false] {
            let event = CGEvent::new_keyboard_event(event_source()?, 0, down)
                .map_err(|()| "Could not create a key event.".to_string())?;
            event.set_string_from_utf16_unchecked(chunk);
            event.post_to_pid(target.pid);
        }
        chunk.clear();
        if delay > 0 {
            pause(delay);
        }
        Ok(())
    };
    let mut previous = '\0';
    for ch in text.chars() {
        match ch {
            '\n' if previous == '\r' => {}
            '\n' | '\r' => {
                flush(&mut chunk)?;
                let shift = if web { CGEventFlags::CGEventFlagShift } else { CGEventFlags::CGEventFlagNull };
                post_keycode(target.pid, KEY_RETURN, shift, 1)?;
            }
            other => {
                let mut units = [0u16; 2];
                chunk.extend_from_slice(other.encode_utf16(&mut units));
                // CGEventKeyboardSetUnicodeString takes up to 20 units.
                if chunk.len() >= 18 {
                    flush(&mut chunk)?;
                }
            }
        }
        previous = ch;
    }
    flush(&mut chunk)
}

fn type_text(emit: &dyn Fn(Value), target: &Target, params: &Value) -> Result<Value, String> {
    let text = params.get("text").and_then(Value::as_str).ok_or("type needs text.")?;
    if text.chars().count() > MAX_TYPE_CHARS {
        return Err(format!("type accepts at most {MAX_TYPE_CHARS} characters per call."));
    }
    let field = match params.get("ref").and_then(Value::as_str) {
        Some(reference) => {
            // Put the caret in the field first, the way a person would.
            click(emit, target, &json!({ "ref": reference }))?;
            pause(60);
            Some(element_for(&target.session_id, reference)?)
        }
        None => focused_field(target),
    };
    let delay = params
        .get("delay_ms")
        .and_then(Value::as_u64)
        .unwrap_or(DEFAULT_TYPE_DELAY_MS)
        .min(200);
    fill(target, field.as_ref(), text, false, delay)
}

/// Type into `field` (or wherever the app's focus is): through
/// accessibility when the field takes text that way and confirms it, else
/// as posted key events.
fn fill(target: &Target, field: Option<&Ax>, text: &str, replace: bool, delay: u64) -> Result<Value, String> {
    let web = target.web || field.is_some_and(in_web_area);
    if let Some(field) = field {
        let name = field.label();
        let result = |via: &str, landed: Landed| {
            let mut result = json!({
                "typed_chars": text.chars().count(),
                "delivered_to": name,
                "delivered_via": via,
                "window": target.title(),
            });
            match landed {
                Landed::Confirmed => result["confirmed"] = json!(true),
                Landed::Changed | Landed::Unreadable => {
                    result["confirmed"] = Value::Null;
                    result["note"] = json!("The field changed but does not show exactly this text (or does not report its text). Check with a screenshot before typing again.");
                }
                Landed::Unchanged => {
                    result["confirmed"] = json!(false);
                    result["note"] = json!("The field did not change. macOS may not deliver keys to an app in the background; set_value with direct: true writes the text instead.");
                }
            }
            result
        };
        if field.settable("AXSelectedText") {
            match insert_via_accessibility(field, text, replace) {
                // Only a field that did not change at all is safe to type
                // into again.
                Ok(Landed::Unchanged) | Err(_) => {}
                Ok(landed) => return Ok(result("accessibility", landed)),
            }
        }
        let before = field.value_text();
        let _ = field.set_flag("AXFocused", true);
        if replace {
            post_keycode(target.pid, KEY_A, CGEventFlags::CGEventFlagCommand, 1)?;
        }
        type_via_keyboard(target, text, web, delay)?;
        pause(200);
        let landed = landed(&before, &field.value_text(), text, replace);
        return Ok(result("keyboard", landed));
    }
    type_via_keyboard(target, text, web, delay)?;
    Ok(json!({
        "typed_chars": text.chars().count(),
        "delivered_to": "focused element",
        "delivered_via": "keyboard",
        "window": target.title(),
        "note": "No focused field was found, so the keys were posted to the app. Click the field (or pass ref) first so typing is confirmed.",
    }))
}

// macOS virtual key codes (Carbon's kVK_*).
const KEY_A: u16 = 0x00;
const KEY_RETURN: u16 = 0x24;
const KEY_TAB: u16 = 0x30;
const KEY_ESCAPE: u16 = 0x35;

/// A key name → (virtual key code, needs Shift on a US layout).
fn resolve_key(name: &str) -> Option<(u16, bool)> {
    let code = match name.to_lowercase().as_str() {
        "a" => 0x00, "s" => 0x01, "d" => 0x02, "f" => 0x03, "h" => 0x04, "g" => 0x05,
        "z" => 0x06, "x" => 0x07, "c" => 0x08, "v" => 0x09, "b" => 0x0B, "q" => 0x0C,
        "w" => 0x0D, "e" => 0x0E, "r" => 0x0F, "y" => 0x10, "t" => 0x11, "o" => 0x1F,
        "u" => 0x20, "i" => 0x22, "p" => 0x23, "l" => 0x25, "j" => 0x26, "k" => 0x28,
        "n" => 0x2D, "m" => 0x2E,
        "1" => 0x12, "2" => 0x13, "3" => 0x14, "4" => 0x15, "6" => 0x16, "5" => 0x17,
        "9" => 0x19, "7" => 0x1A, "8" => 0x1C, "0" => 0x1D,
        "=" | "plus" => 0x18, "-" | "minus" => 0x1B, "]" => 0x1E, "[" => 0x21, "'" => 0x27,
        ";" => 0x29, "\\" => 0x2A, "," => 0x2B, "/" => 0x2C, "." => 0x2F, "`" => 0x32,
        "return" | "enter" => KEY_RETURN,
        "tab" => KEY_TAB,
        "space" | " " => 0x31,
        "backspace" | "back" => 0x33,
        "escape" | "esc" => KEY_ESCAPE,
        "delete" | "del" | "forwarddelete" => 0x75,
        "home" => 0x73,
        "end" => 0x77,
        "pageup" | "pgup" => 0x74,
        "pagedown" | "pgdn" => 0x79,
        "left" | "arrowleft" => 0x7B,
        "right" | "arrowright" => 0x7C,
        "down" | "arrowdown" => 0x7D,
        "up" | "arrowup" => 0x7E,
        "insert" | "ins" | "help" => 0x72,
        "capslock" | "caps" => 0x39,
        "f1" => 0x7A, "f2" => 0x78, "f3" => 0x63, "f4" => 0x76, "f5" => 0x60, "f6" => 0x61,
        "f7" => 0x62, "f8" => 0x64, "f9" => 0x65, "f10" => 0x6D, "f11" => 0x67, "f12" => 0x6F,
        "numpadadd" => 0x45, "numpadsubtract" => 0x4E, "numpadmultiply" => 0x43,
        "numpaddivide" => 0x4B, "numpaddecimal" => 0x41, "numpadenter" => 0x4C,
        other => {
            // The shifted symbols of a US layout.
            let mut chars = other.chars();
            let (Some(ch), None) = (chars.next(), chars.next()) else {
                return None;
            };
            let unshifted = match ch {
                '!' => '1', '@' => '2', '#' => '3', '$' => '4', '%' => '5', '^' => '6',
                '&' => '7', '*' => '8', '(' => '9', ')' => '0', '_' => '-', '+' => '=',
                '{' => '[', '}' => ']', '|' => '\\', ':' => ';', '"' => '\'', '<' => ',',
                '>' => '.', '?' => '/', '~' => '`',
                _ => return None,
            };
            return resolve_key(&unshifted.to_string()).map(|(code, _)| (code, true));
        }
    };
    // A single upper-case letter ("A") is that letter with Shift.
    Some((code, name.chars().count() == 1 && name.chars().all(|ch| ch.is_ascii_uppercase())))
}

fn combo_flags(combo: &KeyCombo) -> CGEventFlags {
    let mut flags = CGEventFlags::CGEventFlagNull;
    if combo.cmd {
        flags |= CGEventFlags::CGEventFlagCommand;
    }
    if combo.ctrl {
        flags |= CGEventFlags::CGEventFlagControl;
    }
    if combo.alt {
        flags |= CGEventFlags::CGEventFlagAlternate;
    }
    if combo.shift {
        flags |= CGEventFlags::CGEventFlagShift;
    }
    flags
}

fn post_keycode(pid: i32, code: u16, flags: CGEventFlags, repeat: u64) -> Result<(), String> {
    for _ in 0..repeat {
        // Each press carries its own flags, so stopping between presses
        // leaves no modifier held.
        interrupted()?;
        for down in [true, false] {
            let event = CGEvent::new_keyboard_event(event_source()?, code, down)
                .map_err(|()| "Could not create a key event.".to_string())?;
            event.set_flags(flags);
            event.post_to_pid(pid);
            pause(20);
        }
    }
    Ok(())
}

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
fn menu_item_for(app: &Ax, combo: &KeyCombo) -> Option<(Ax, String)> {
    let key = combo.key.to_lowercase();
    if key.chars().count() != 1 || !(combo.cmd || combo.ctrl || combo.alt) {
        return None;
    }
    let wanted = menu_modifiers(combo);
    let mut stack: Vec<(Ax, u32)> = app_menus(app).into_iter().map(|item| (item, 0)).collect();
    let mut visited = 0;
    while let Some((element, depth)) = stack.pop() {
        visited += 1;
        if visited > 5_000 || depth > 6 {
            continue;
        }
        // One round trip per item: a menu bar has hundreds of them.
        let [role, cmd_char, cmd_modifiers, enabled, children] = MENU_NAMES.with(|names| element.attributes(names));
        let role = role.as_ref().and_then(cf_text).unwrap_or_default();
        if role == "AXMenuItem" {
            let char_matches = cmd_char
                .as_ref()
                .and_then(cf_text)
                .is_some_and(|ch| ch.to_lowercase() == key);
            let modifiers = cmd_modifiers.as_ref().and_then(cf_number).map(|mask| mask as i64);
            if char_matches && modifiers == Some(wanted) {
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

const MENU_ATTRIBUTES: [&str; 5] =
    ["AXRole", "AXMenuItemCmdChar", "AXMenuItemCmdModifiers", "AXEnabled", "AXChildren"];

thread_local! {
    static MENU_NAMES: CFArray<CFString> = CFArray::from_CFTypes(&MENU_ATTRIBUTES.map(cf_string));
}

fn press_key(target: &Target, params: &Value) -> Result<Value, String> {
    let spec = params
        .get("key")
        .and_then(Value::as_str)
        .ok_or("key needs a key name such as Enter or cmd+s.")?;
    let combo = parse_key_combo(spec)?;
    if let Some(reason) = blocked_combo_reason(&combo) {
        return Err(format!("Refused {spec}: {reason}."));
    }
    let repeat = params.get("repeat").and_then(Value::as_u64).unwrap_or(1).clamp(1, 50);
    if let Some((item, title)) = menu_item_for(&target.app, &combo) {
        for _ in 0..repeat {
            interrupted()?;
            item.perform("AXPress")
                .map_err(|error| format!("The menu command \"{title}\" failed: {}", ax_error(error)))?;
            pause(60);
        }
        return Ok(json!({
            "key": spec,
            "repeat": repeat,
            "delivered_to": title,
            "delivered_via": "menu",
            "window": target.title(),
        }));
    }
    // Enter and Escape mean confirm and cancel, which the focused control or
    // the window's default and cancel buttons take through accessibility.
    let key = combo.key.to_lowercase();
    let plain = !(combo.cmd || combo.ctrl || combo.alt || combo.shift);
    if plain && repeat == 1 {
        if let Some(done) = confirm_or_cancel(target, &key)? {
            return Ok(merge(json!({ "key": spec, "repeat": repeat }), done));
        }
    }
    let (code, needs_shift) =
        resolve_key(&combo.key).ok_or_else(|| format!("Unknown key name {:?}.", combo.key))?;
    let mut combo = combo.clone();
    combo.shift |= needs_shift;
    post_keycode(target.pid, code, combo_flags(&combo), repeat)?;
    Ok(json!({
        "key": spec,
        "repeat": repeat,
        "delivered_to": "app",
        "delivered_via": "keyboard",
        "window": target.title(),
        "note": "Posted as a key event. macOS delivers keys only to an app's key window, which a background app may not have; if nothing changed, look for the command with find (menu items are included) and invoke it.",
    }))
}

fn confirm_or_cancel(target: &Target, key: &str) -> Result<Option<Value>, String> {
    let (action, button) = match key {
        "return" | "enter" => ("AXConfirm", "AXDefaultButton"),
        "escape" | "esc" => ("AXCancel", "AXCancelButton"),
        _ => return Ok(None),
    };
    let focused = focused_field(target);
    if let Some(focused) = &focused {
        if focused.actions().iter().any(|name| name == action) {
            focused.perform(action).map_err(ax_error)?;
            return Ok(Some(json!({ "delivered_to": focused.label(), "delivered_via": "accessibility", "window": target.title() })));
        }
        // Enter in a multi-line field is a line break (or a chat's "send"),
        // not the dialog's default button.
        if focused.role() == "AXTextArea" {
            return Ok(None);
        }
    }
    // A sheet over the window is what Enter and Escape answer first.
    let sheets = target
        .window
        .elements("AXChildren")
        .into_iter()
        .filter(|child| child.role() == "AXSheet");
    for window in sheets.chain(std::iter::once(target.window.clone())) {
        if let Some(pressable) = window.element(button) {
            pressable.perform("AXPress").map_err(ax_error)?;
            return Ok(Some(json!({ "delivered_to": pressable.label(), "delivered_via": "accessibility", "window": target.title() })));
        }
    }
    Ok(None)
}

// ── Element actions ─────────────────────────────────────────────────────

fn invoke(emit: &dyn Fn(Value), target: &Target, params: &Value) -> Result<Value, String> {
    let reference = params.get("ref").and_then(Value::as_str).ok_or("invoke needs a ref.")?;
    let element = element_for(&target.session_id, reference)?;
    let name = element.label();
    let action = ui_action_for(&element).ok_or_else(|| {
        format!("{reference} (\"{name}\") has no press/select/expand action. Click it by ref or coordinates instead.")
    })?;
    if let Some(point) = element_center(&element).filter(|point| target.frame.contains(*point)) {
        target.travel(emit, point)?;
        target.emit_pointer(emit, point, "click");
    }
    if is_editable(&element) {
        remember_editable(&target.session_id, &element);
    }
    let used = perform(&element, &action)
        .map_err(|error| format!("{reference} (\"{name}\") refused the action: {}", ax_error(error)))?;
    Ok(json!({ "ref": reference, "name": name, "pattern": used, "window": target.title() }))
}

fn set_value(emit: &dyn Fn(Value), target: &Target, params: &Value) -> Result<Value, String> {
    let reference = params.get("ref").and_then(Value::as_str).ok_or("set_value needs a ref.")?;
    let value = params.get("value").and_then(Value::as_str).ok_or("set_value needs a value.")?;
    let element = element_for(&target.session_id, reference)?;
    let direct = params.get("direct").and_then(Value::as_bool).unwrap_or(false);
    if let Some(point) = element_center(&element) {
        target.travel(emit, point)?;
        target.emit_pointer(emit, point, "click");
    }
    // Sliders, steppers and other number-valued controls take a number.
    let current = element.attribute("AXValue");
    if let (Some(number), Some(true)) = (value.trim().parse::<f64>().ok(), current.as_ref().map(|v| cf_number(v).is_some() && v.downcast::<CFBoolean>().is_none())) {
        if !is_text_role(&element.role()) {
            let minimum = element.attribute("AXMinValue").as_ref().and_then(cf_number);
            let maximum = element.attribute("AXMaxValue").as_ref().and_then(cf_number);
            let clamped = match (minimum, maximum) {
                (Some(minimum), Some(maximum)) if maximum > minimum => number.clamp(minimum, maximum),
                _ => number,
            };
            element
                .set("AXValue", &CFNumber::from(clamped).as_CFType())
                .map_err(|error| format!("{reference} refused the value: {}", ax_error(error)))?;
            return Ok(json!({
                "ref": reference,
                "value_chars": value.chars().count(),
                "delivered_via": "accessibility",
                "pattern": "range_value",
                "window": target.title(),
            }));
        }
    }
    if !direct {
        // Replace the text the way typing would, so editors see input (see
        // `fill`); `direct` writes the value without that.
        remember_editable(&target.session_id, &element);
        let mut result = fill(target, Some(&element), value, true, DEFAULT_TYPE_DELAY_MS)?;
        result["ref"] = json!(reference);
        result["value_chars"] = json!(value.chars().count());
        return Ok(result);
    }
    if !element.settable("AXValue") {
        return Err(format!("{reference} does not accept a value. Click it and use type instead."));
    }
    element
        .set("AXValue", &cf_string(value).as_CFType())
        .map_err(|error| format!("{reference} refused the value: {}", ax_error(error)))?;
    Ok(json!({ "ref": reference, "value_chars": value.chars().count(), "window": target.title() }))
}

/// Drives a real TextEdit window. Opt-in because it opens a window on the
/// desktop it runs on, and it needs EvoFlux's test binary (or the terminal
/// running it) to have Accessibility and Screen Recording access:
///
/// `cargo test computer_app -- --ignored --nocapture`
///
/// It opens its own document in TextEdit without bringing TextEdit forward,
/// and checks the claim this module is built on: the frontmost app and the
/// user's cursor do not change while the agent works.
#[cfg(test)]
mod live_tests {
    use super::*;

    fn cursor() -> CGPoint {
        CGEvent::new(CGEventSource::new(CGEventSourceStateID::CombinedSessionState).unwrap())
            .unwrap()
            .location()
    }

    #[test]
    #[ignore = "opens a TextEdit document on the local desktop"]
    fn drives_textedit_in_the_background() {
        assert!(accessibility_trusted(false), "grant Accessibility to the terminal running the tests");
        let dir = std::env::temp_dir().join(format!("evoflux-computer-app-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let file = dir.join("computer-app-probe.txt");
        std::fs::write(&file, "start\n").unwrap();
        let front_before = frontmost_pid();
        let cursor_before = cursor();
        // -g: open without bringing TextEdit to the front.
        let status = std::process::Command::new("open")
            .args(["-g", "-a", "TextEdit"])
            .arg(&file)
            .status()
            .unwrap();
        assert!(status.success());
        let session = "live-test";
        let emit = |_: Value| {};
        let mut attached = Err(String::new());
        for _ in 0..40 {
            pause(250);
            attached = run_action(&emit, session, "attach", &json!({ "title": "computer-app-probe", "hide": true }));
            if attached.is_ok() {
                break;
            }
        }
        let attached = attached.expect("attach to the TextEdit document");
        println!("attached: {attached}");

        let snapshot = run_action(&emit, session, "snapshot", &json!({})).unwrap();
        let snapshot = snapshot.as_str().unwrap().to_string();
        println!("{snapshot}");
        let text_area = snapshot
            .lines()
            .find(|line| line.contains("- TextArea"))
            .and_then(|line| line.split("[ref=").nth(1))
            .and_then(|rest| rest.split(']').next())
            .expect("the document's text area")
            .to_string();

        let typed = run_action(&emit, session, "type", &json!({ "ref": text_area, "text": "hello from evoflux" })).unwrap();
        println!("type: {typed}");
        assert_eq!(typed["confirmed"], json!(true));

        let saved = run_action(&emit, session, "key", &json!({ "key": "cmd+s" })).unwrap();
        println!("key: {saved}");
        assert_eq!(saved["delivered_via"], json!("menu"));
        pause(800);
        let contents = std::fs::read_to_string(&file).unwrap();
        assert!(contents.contains("hello from evoflux"), "saved contents: {contents:?}");

        let screenshot = run_action(&emit, session, "screenshot", &json!({})).unwrap();
        assert!(screenshot["width"].as_u64().unwrap() > 100);

        let closing = run_action(&emit, session, "find", &json!({ "query": "close" })).unwrap();
        println!("{closing}");
        run_action(&emit, session, "detach", &json!({})).unwrap();

        assert_eq!(frontmost_pid(), front_before, "the frontmost app changed");
        // Only reported: the agent never moves the real cursor, but a user
        // working while the test runs does.
        let cursor_after = cursor();
        println!(
            "cursor before ({}, {}), after ({}, {})",
            cursor_before.x, cursor_before.y, cursor_after.x, cursor_after.y
        );
        // Close the document window the test opened.
        let app = Ax::application(
            attached["window"]["pid"].as_i64().unwrap() as i32,
        )
        .unwrap();
        if let Some(window) = ax_window(&app, attached["window"]["id"].as_u64().unwrap() as u32) {
            if let Some(close) = window.element("AXCloseButton") {
                let _ = close.perform("AXPress");
            }
        }
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    #[ignore = "reads the local Applications folders and running apps"]
    fn lists_apps_with_icons() {
        let apps = list_apps();
        let apps = apps["apps"].as_array().unwrap();
        println!("{} apps", apps.len());
        assert!(apps.iter().any(|app| app["exe"] == json!("textedit")));
        assert!(apps.iter().filter(|app| app["icon"].is_string()).count() > apps.len() / 2);
    }
}
