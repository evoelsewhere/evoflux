//! Windows implementation of Computer App Control.
//!
//! Every function here addresses the attached window's own message queue or
//! its UI Automation tree. Nothing calls `SendInput`, `SetCursorPos` or
//! `SetForegroundWindow` on the agent's behalf: the user keeps their mouse,
//! keyboard and foreground window while the agent works.
//!
//! # Layout
//!
//! This file is the factory's Windows product ([`WindowsBackend`]) and the
//! dispatch of each [`Action`]; the work lives in one module per concern:
//!
//! | Module         | Concern                                                        |
//! |----------------|----------------------------------------------------------------|
//! | `registry`     | Which window each chat drives; Stop, Resume, Reveal; refs      |
//! | `parking`      | Off-screen stage for an app; putting it back (also on crash)   |
//! | `listing`      | Enumerating windows and processes; what may never be attached  |
//! | `catalog`      | Installed and running apps (Settings picker, `search_apps`)    |
//! | `attachment`   | `status`, `attach`, `detach`                                   |
//! | `lifecycle`    | `search_apps`, `open_app`, `close_app`, `kill_app`             |
//! | `target`       | The window an action addresses; web-content hosts              |
//! | `popups`       | Menus, drop-downs and panes the app opens                      |
//! | `capture`      | `PrintWindow` capture, screenshots, preview frames             |
//! | `messages`     | Posting messages: target child, DPI, waiting for the app       |
//! | `pointer`      | Posted mouse input: `click`, `hover`, `scroll`, `drag`         |
//! | `peek`         | Letting a hidden web page paint for one gesture                |
//! | `typing`       | `type`: posted characters, read back                           |
//! | `keyboard`     | `key`: shortcuts with modifiers held in the app's key state    |
//! | `page_tree`    | Getting Chromium/WebView2 to build its accessibility tree      |
//! | `uia_tree`     | UI Automation tree: `snapshot`, `find`, refs                   |
//! | `uia_patterns` | UI Automation patterns and hit-testing                         |
//! | `uia_input`    | Input through UI Automation: clicks, scrolls, `invoke`, `set_value` |
//! | `web_fill`     | Typing into web page fields with real keyboard events          |
//!
//! Every module starts with `use super::*;` and this file re-exports each
//! module's `pub(super)` items, so they share one namespace: the imports
//! below are the single list of what the backend uses from Windows.

use std::cell::RefCell;
use std::collections::{HashMap, HashSet};
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::{mpsc, Arc, Mutex};
use std::time::Duration;

use base64::{engine::general_purpose::STANDARD as BASE64, Engine as _};
use image::{imageops, DynamicImage, RgbaImage};
use once_cell::sync::Lazy;
use serde_json::{json, Value};
use windows::core::{Interface, BOOL, BSTR, PWSTR};
use windows::Win32::Foundation::{CloseHandle, COLORREF, HWND, LPARAM, POINT, RECT, WPARAM};
use windows::Win32::Graphics::Dwm::{
    DwmGetWindowAttribute, DWMWA_CLOAKED, DWMWA_EXTENDED_FRAME_BOUNDS,
};
use windows::Win32::Graphics::Gdi::{
    BitBlt, CreateCompatibleBitmap, CreateCompatibleDC, DeleteDC, DeleteObject, GetDC, GetDIBits,
    GetWindowDC, ReleaseDC, ScreenToClient, SelectObject, BITMAPINFO, BITMAPINFOHEADER, DIB_RGB_COLORS,
    HBITMAP, HDC, SRCCOPY,
};
use windows::Win32::Storage::Xps::{PrintWindow, PRINT_WINDOW_FLAGS};
use windows::Win32::System::Com::{
    CoCreateInstance, CoInitializeEx, CoUninitialize, CLSCTX_INPROC_SERVER, COINIT_MULTITHREADED,
};
use windows::Win32::System::Threading::{
    AttachThreadInput, GetCurrentProcessId, GetCurrentThreadId, OpenProcess,
    QueryFullProcessImageNameW, PROCESS_NAME_WIN32, PROCESS_QUERY_LIMITED_INFORMATION,
};
use windows::Win32::UI::Accessibility::{
    AccessibleObjectFromWindow, CUIAutomation, SetWinEventHook, HWINEVENTHOOK, ExpandCollapseState_Collapsed,
    ExpandCollapseState_PartiallyExpanded, IAccessible, IUIAutomation, IUIAutomationElement,
    IUIAutomationExpandCollapsePattern, IUIAutomationInvokePattern,
    IUIAutomationLegacyIAccessiblePattern, IUIAutomationSelectionItemPattern,
    IUIAutomationRangeValuePattern, IUIAutomationScrollPattern, IUIAutomationTogglePattern,
    IUIAutomationTreeWalker, IUIAutomationValuePattern, ScrollAmount_NoAmount,
    ScrollAmount_SmallDecrement, ScrollAmount_SmallIncrement, ToggleState_On,
    UIA_ExpandCollapsePatternId, UIA_InvokePatternId, UIA_RangeValuePatternId,
    UIA_ScrollPatternId,
    UIA_LegacyIAccessiblePatternId, UIA_SelectionItemPatternId, UIA_TogglePatternId,
    UIA_ValuePatternId,
};
use windows::Win32::UI::HiDpi::GetDpiForWindow;
use windows::Win32::UI::Input::KeyboardAndMouse::{
    GetKeyboardState, IsWindowEnabled, MapVirtualKeyW, SetKeyboardState, VkKeyScanW,
    MAPVK_VK_TO_VSC, VIRTUAL_KEY, VK_0, VK_1, VK_2, VK_3, VK_4, VK_5, VK_6, VK_7, VK_8, VK_9,
    VK_A, VK_ADD, VK_APPS, VK_B, VK_BACK, VK_C, VK_CAPITAL, VK_CONTROL, VK_D, VK_DECIMAL,
    VK_DELETE, VK_DIVIDE, VK_DOWN, VK_E, VK_END, VK_ESCAPE, VK_F, VK_F1, VK_F10, VK_F11, VK_F12,
    VK_F2, VK_F3, VK_F4, VK_F5, VK_F6, VK_F7, VK_F8, VK_F9, VK_G, VK_H, VK_HOME, VK_I, VK_INSERT,
    VK_J, VK_K, VK_L, VK_LCONTROL, VK_LEFT, VK_LMENU, VK_LSHIFT, VK_M, VK_MENU, VK_MULTIPLY, VK_N,
    VK_NEXT, VK_NUMLOCK, VK_O, VK_OEM_1, VK_OEM_2, VK_OEM_3, VK_OEM_4, VK_OEM_5, VK_OEM_6,
    VK_OEM_7, VK_OEM_COMMA, VK_OEM_MINUS, VK_OEM_PERIOD, VK_OEM_PLUS, VK_P, VK_PAUSE, VK_PRIOR,
    VK_Q, VK_R, VK_RCONTROL, VK_RETURN, VK_RIGHT, VK_RMENU, VK_S, VK_SCROLL, VK_SHIFT, VK_SNAPSHOT,
    VK_SPACE, VK_SUBTRACT, VK_T, VK_TAB, VK_U, VK_UP, VK_V, VK_W, VK_X, VK_Y, VK_Z,
};
use windows::Win32::UI::WindowsAndMessaging::{
    BM_CLICK, ChildWindowFromPointEx, EnumWindows, GetAncestor, GetClassNameW, GetForegroundWindow,
    GetGUIThreadInfo, GetSystemMetrics, GetWindow, GetWindowLongPtrW, GetWindowPlacement,
    GetWindowRect, GetWindowTextW, IsZoomed, SetWindowPlacement, SetWindowPos,
    SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN, SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN,
    SET_WINDOW_POS_FLAGS, SWP_NOACTIVATE, SWP_NOMOVE, SWP_NOOWNERZORDER, SWP_NOSIZE,
    SWP_NOZORDER, SW_SHOWMAXIMIZED, GetLayeredWindowAttributes, SetLayeredWindowAttributes, SetWindowLongPtrW,
    LAYERED_WINDOW_ATTRIBUTES_FLAGS,
    GW_HWNDPREV, LWA_ALPHA, WS_EX_LAYERED, WS_EX_TOPMOST, WS_EX_TRANSPARENT,
    SW_SHOWMINIMIZED, SW_SHOWMINNOACTIVE, WINDOWPLACEMENT, WINDOWPLACEMENT_FLAGS,
    WPF_RESTORETOMAXIMIZED,
    GetWindowThreadProcessId, IsHungAppWindow, IsIconic, IsWindow, IsWindowVisible, PostMessageW,
    SendMessageTimeoutW, SetForegroundWindow, ShowWindow, CWP_SKIPDISABLED, CWP_SKIPINVISIBLE,
    CWP_SKIPTRANSPARENT, GA_ROOT, GUITHREADINFO, GWL_EXSTYLE, GW_ENABLEDPOPUP, GW_OWNER,
    GWL_STYLE, WS_CAPTION, WS_CHILD, WS_POPUP, WS_THICKFRAME, CHILDID_SELF, EVENT_OBJECT_SHOW, OBJID_WINDOW,
    WINEVENT_OUTOFCONTEXT, WINEVENT_SKIPOWNPROCESS, MSG, GetMessageW, DispatchMessageW,
    SMTO_ABORTIFHUNG, SW_RESTORE, SW_SHOWNOACTIVATE, WM_CHAR, WM_KEYDOWN, WM_KEYUP,
    WM_LBUTTONDBLCLK, WM_LBUTTONDOWN, WM_LBUTTONUP, WM_MBUTTONDBLCLK, WM_MBUTTONDOWN,
    WM_MBUTTONUP, WM_MOUSEHWHEEL, WM_MOUSEMOVE, WM_MOUSEWHEEL, WM_NCHITTEST, WM_NULL, WM_RBUTTONDBLCLK,
    WM_RBUTTONDOWN, WM_RBUTTONUP, WM_SYSKEYDOWN, WM_SYSKEYUP, WS_EX_TOOLWINDOW,
};

use super::action::Action;
use super::apps::{self, sorted, AppEntry, Catalog};
use super::backend::{ComputerAppBackend, STOPPED_REFUSAL};
use super::geometry::{pack_point, screenshot_scale};
use super::interrupt::interrupted;
use super::keys::{blocked_combo_reason, parse_key_combo, KeyCombo};
use super::policy::is_protected_process_name;
use super::workers::{on_worker, post as post_to_worker};

mod attachment;
mod capture;
mod catalog;
mod keyboard;
mod lifecycle;
mod listing;
mod messages;
mod page_tree;
mod parking;
mod peek;
mod pointer;
mod popups;
mod registry;
mod target;
mod typing;
mod uia_input;
mod uia_patterns;
mod uia_tree;
mod web_fill;

#[cfg(test)]
mod live_tests;
#[cfg(test)]
mod tests;

use attachment::*;
use capture::*;
use catalog::*;
use keyboard::*;
use lifecycle::*;
use listing::*;
use messages::*;
use page_tree::*;
use parking::*;
use peek::*;
use pointer::*;
use popups::*;
use registry::*;
use target::*;
use typing::*;
use uia_input::*;
use uia_patterns::*;
use uia_tree::*;
use web_fill::*;

// ── The factory's Windows product ───────────────────────────────────────

/// Computer App Control on Windows, as handed out by
/// [`super::backend::backend`].
pub(crate) struct WindowsBackend;

impl ComputerAppBackend for WindowsBackend {
    /// UI Automation objects are COM objects bound to the apartment that
    /// created them, so every worker joins the multithreaded apartment first.
    fn init_worker_thread(&self) {
        unsafe {
            let _ = CoInitializeEx(None, COINIT_MULTITHREADED);
        }
    }

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

    fn recover_stranded(&self, state_dir: std::path::PathBuf) {
        recover_stranded(state_dir);
    }
}

// ── Dispatch ────────────────────────────────────────────────────────────

fn dispatch(emit: &dyn Fn(Value), session_id: &str, action: Action, params: &Value) -> Result<Value, String> {
    // The window is resolved per action, not per session: the agent may
    // have been detached, or the window closed, since the last one.
    let target = || -> Result<Target, String> {
        let target = Target::resolve(session_id)?;
        if action.is_input() {
            claim_page_focus(&target);
        }
        Ok(target)
    };
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

/// `base` with the fields of `extra` added (or replaced).
fn merge(mut base: Value, extra: Value) -> Value {
    if let (Some(base), Value::Object(extra)) = (base.as_object_mut(), extra) {
        base.extend(extra);
    }
    base
}
