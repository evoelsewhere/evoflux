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
//!
//! # Layout
//!
//! This file is the factory's macOS product ([`MacBackend`]) and the
//! dispatch of each [`Action`]; the work lives in one module per concern:
//!
//! | Module       | Concern                                                      |
//! |--------------|--------------------------------------------------------------|
//! | `ax`         | Accessibility FFI and the `Ax` element wrapper               |
//! | `access`     | Accessibility and Screen Recording permissions               |
//! | `rect`       | Points, rectangles and displays                              |
//! | `registry`   | Which window each chat drives; Stop, Resume, Reveal; refs    |
//! | `parking`    | Keeping an app out of sight, and putting it back             |
//! | `listing`    | Window-server windows and processes; what may not be attached |
//! | `catalog`    | Installed and running apps (Settings picker, `search_apps`)  |
//! | `attachment` | `status`, `attach`, `detach`                                 |
//! | `lifecycle`  | `search_apps`, `open_app`, `close_app`, `kill_app`           |
//! | `target`     | The window an action addresses and its coordinates           |
//! | `capture`    | Window-server capture, screenshots, preview frames           |
//! | `ax_tree`    | The accessibility tree: `snapshot`, `find`, refs, hit-testing |
//! | `ax_actions` | Accessibility actions: `invoke`, `set_value`                 |
//! | `pointer`    | Posted mouse input: `click`, `hover`, `scroll`, `drag`       |
//! | `typing`     | `type`: accessibility insertion or posted keys, read back    |
//! | `keyboard`   | `key`: key codes, posted key events, confirm and cancel      |
//! | `menus`      | Shortcuts pressed through the app's menu bar                 |
//!
//! Every module starts with `use super::*;` and this file re-exports each
//! module's `pub(super)` items, so they share one namespace: the imports
//! below are the single list of what the backend uses from macOS.

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

use super::action::Action;
use super::apps::{self, sorted, AppEntry, Catalog};
use super::backend::{ComputerAppBackend, STOPPED_REFUSAL};
use super::geometry::screenshot_scale;
use super::interrupt::interrupted;
use super::keys::{blocked_combo_reason, parse_key_combo, shifted_letter, upper_case_letter, KeyCombo};
use super::policy::{is_command_runner, is_protected_process_name};
use super::workers::{on_worker, post as post_to_worker};

mod access;
mod attachment;
mod ax;
mod ax_actions;
mod ax_tree;
mod capture;
mod catalog;
mod keyboard;
mod lifecycle;
mod listing;
mod menus;
mod parking;
mod pointer;
mod rect;
mod registry;
mod target;
mod typing;

#[cfg(test)]
mod live_tests;
#[cfg(test)]
mod tests;

use access::*;
use attachment::*;
use ax::*;
use ax_actions::*;
use ax_tree::*;
use capture::*;
use catalog::*;
use keyboard::*;
use lifecycle::*;
use listing::*;
use menus::*;
use parking::*;
use pointer::*;
use rect::*;
use registry::*;
use target::*;
use typing::*;

// ── The factory's macOS product ─────────────────────────────────────────

/// Computer App Control on macOS, as handed out by
/// [`super::backend::backend`].
pub(crate) struct MacBackend;

impl ComputerAppBackend for MacBackend {
    fn is_attached(&self, session_id: &str) -> bool {
        registry().attached.contains_key(session_id)
    }

    fn run_action(&self, emit: &dyn Fn(Value), session_id: &str, action: Action, params: &Value) -> Result<Value, String> {
        dispatch(emit, session_id, action, params)
    }

    fn list_apps(&self) -> Value {
        list_apps()
    }

    fn preview_frame(&self, session_id: &str, max_width: u32) -> Result<Value, String> {
        preview_frame(session_id, max_width)
    }

    fn stop(&self, session_id: &str) -> Result<(), String> {
        stop(session_id);
        Ok(())
    }

    fn resume(&self, session_id: &str) -> Result<(), String> {
        resume(session_id);
        Ok(())
    }

    fn reveal(&self, session_id: &str) -> Result<Value, String> {
        reveal(session_id)
    }

    fn release_all(&self) {
        release_all();
    }

    fn permissions(&self) -> Value {
        permissions()
    }

    fn request_permission(&self, kind: &str) -> Result<Value, String> {
        request_permission(kind)
    }
}

// ── Dispatch ────────────────────────────────────────────────────────────

fn dispatch(emit: &dyn Fn(Value), session_id: &str, action: Action, params: &Value) -> Result<Value, String> {
    // The window is resolved per action, not per session: the agent may
    // have been detached, or the window closed, since the last one.
    let target = || Target::resolve(session_id);
    match action {
        Action::Status => Ok(status(session_id)),
        Action::ListWindows => Ok(list_windows(session_id, params)),
        Action::Attach => attach(session_id, params),
        Action::Detach => Ok(detach(session_id)),
        Action::Screenshot => screenshot(&target()?),
        Action::Snapshot => snapshot(&target()?, params),
        Action::Find => find(&target()?, params),
        Action::Click => click(emit, &target()?, params),
        Action::Hover => hover(emit, &target()?, params),
        Action::Scroll => scroll(emit, &target()?, params),
        Action::Drag => drag(emit, &target()?, params),
        Action::Type => type_text(emit, &target()?, params),
        Action::Key => press_key(&target()?, params),
        Action::Invoke => invoke(emit, &target()?, params),
        Action::SetValue => set_value(emit, &target()?, params),
        Action::Restore => {
            let target = target()?;
            Ok(json!({ "restored": target.restored, "window": target.describe() }))
        }
        Action::SearchApps => Ok(search_apps(params)),
        Action::OpenApp => open_app(session_id, params),
        Action::CloseApp => close_app(session_id, params),
        Action::KillApp => kill_app(session_id, params),
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
