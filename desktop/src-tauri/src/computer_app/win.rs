//! Windows implementation of Computer App Control.
//!
//! Every function here addresses the attached window's own message queue or
//! its UI Automation tree. Nothing calls `SendInput`, `SetCursorPos` or
//! `SetForegroundWindow` on the agent's behalf: the user keeps their mouse,
//! keyboard and foreground window while the agent works.

use std::cell::RefCell;
use std::collections::{HashMap, HashSet};
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::{mpsc, Mutex};
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
    GWL_STYLE, WS_CAPTION, WS_CHILD, WS_POPUP, CHILDID_SELF, EVENT_OBJECT_SHOW, OBJID_WINDOW,
    WINEVENT_OUTOFCONTEXT, WINEVENT_SKIPOWNPROCESS, MSG, GetMessageW, DispatchMessageW,
    SMTO_ABORTIFHUNG, SW_RESTORE, SW_SHOWNOACTIVATE, WM_CHAR, WM_KEYDOWN, WM_KEYUP,
    WM_LBUTTONDBLCLK, WM_LBUTTONDOWN, WM_LBUTTONUP, WM_MBUTTONDBLCLK, WM_MBUTTONDOWN,
    WM_MBUTTONUP, WM_MOUSEHWHEEL, WM_MOUSEMOVE, WM_MOUSEWHEEL, WM_NCHITTEST, WM_RBUTTONDBLCLK,
    WM_RBUTTONDOWN, WM_RBUTTONUP, WM_SYSKEYDOWN, WM_SYSKEYUP, WS_EX_TOOLWINDOW,
};

use super::{
    blocked_combo_reason, interrupted, is_protected_process_name, on_worker, pack_point,
    parse_key_combo, post_to_worker, screenshot_scale, KeyCombo,
};

const PW_RENDERFULLCONTENT: PRINT_WINDOW_FLAGS = PRINT_WINDOW_FLAGS(2);
const HTCLIENT: isize = 1;
const HTTRANSPARENT: isize = -1;
const MK_LBUTTON: usize = 0x0001;
const MK_RBUTTON: usize = 0x0002;
const MK_MBUTTON: usize = 0x0010;
const WHEEL_DELTA: i32 = 120;
/// How long the preview's cursor gets to travel before the input lands.
const POINTER_TRAVEL: Duration = Duration::from_millis(220);
const DEFAULT_TYPE_DELAY_MS: u64 = 8;
const MAX_TYPE_CHARS: usize = 20_000;

// ── Session registry ────────────────────────────────────────────────────

#[derive(Clone)]
struct Attached {
    hwnd: isize,
    pid: u32,
    app: String,
    title: String,
    /// Where the window was before it was parked off-screen, while it is.
    parked: Option<WINDOWPLACEMENT>,
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

/// Forget the session's window, without touching the window yet.
fn take(session_id: &str) -> Option<Attached> {
    let taken = registry().attached.remove(session_id);
    clear_refs(session_id);
    taken
}

/// Put a released window back where the user left it.
///
/// Moving another process's window waits for that process's thread, and
/// waits indefinitely on an app that hangs. Stop, Show the app and exit run
/// on EvoFlux's UI thread, so they hand this to a thread of its own (see
/// [`off_ui_thread`]) rather than freeze EvoFlux along with the app.
fn hand_back(attached: &Attached) {
    if let Some(placement) = attached.parked {
        unpark(to_hwnd(attached.hwnd), placement, false);
    }
}

fn off_ui_thread(work: impl FnOnce() + Send + 'static) -> mpsc::Receiver<()> {
    let (done, finished) = mpsc::channel();
    let _ = std::thread::Builder::new()
        .name("computer-app-window".into())
        .spawn(move || {
            work();
            let _ = done.send(());
        });
    finished
}

/// Forget the session's window and put it back where the user left it.
fn release(session_id: &str) -> Option<Attached> {
    let released = take(session_id);
    if let Some(attached) = &released {
        hand_back(attached);
    }
    released
}

pub(crate) fn stop(session_id: &str) {
    registry().stopped.insert(session_id.to_string());
    if let Some(attached) = take(session_id) {
        off_ui_thread(move || hand_back(&attached));
    }
}

pub(crate) fn resume(session_id: &str) {
    registry().stopped.remove(session_id);
}

/// Put every parked window back. Called when EvoFlux exits so no app is
/// left stranded off-screen — but a hung app cannot hold the exit up for
/// more than a few seconds.
pub(crate) fn release_all() {
    let sessions: Vec<String> = registry().attached.keys().cloned().collect();
    let released: Vec<Attached> = sessions.iter().filter_map(|session| take(session)).collect();
    if released.is_empty() {
        return;
    }
    let finished = off_ui_thread(move || released.iter().for_each(hand_back));
    let _ = finished.recv_timeout(Duration::from_secs(3));
}

pub(crate) fn reveal(session_id: &str) -> Result<Value, String> {
    let attached = {
        let mut registry = registry();
        let entry = registry
            .attached
            .get_mut(session_id)
            .ok_or("No app is attached in this chat.")?;
        // The user is taking the app back; it stays attached but is no
        // longer kept off-screen.
        let snapshot = entry.clone();
        entry.parked = None;
        snapshot
    };
    if !unsafe { IsWindow(Some(to_hwnd(attached.hwnd))) }.as_bool() {
        return Err("The attached window was closed.".into());
    }
    // Off the UI thread: restoring waits for the app (see [`hand_back`]).
    off_ui_thread(move || {
        let hwnd = to_hwnd(attached.hwnd);
        unsafe {
            match attached.parked {
                Some(placement) => unpark(hwnd, placement, true),
                None if IsIconic(hwnd).as_bool() => {
                    let _ = ShowWindow(hwnd, SW_RESTORE);
                }
                None => {}
            }
            // The user clicked a button in EvoFlux, which is the foreground
            // process, so Windows permits handing the foreground over.
            let _ = SetForegroundWindow(hwnd);
        }
    });
    Ok(json!({ "revealed": true }))
}

// ── Parking: keep the app running but off the user's screen ─────────────
//
// A minimized window cannot be captured or clicked (it has no size), so an
// app the user wants kept out of sight is moved just outside the virtual
// desktop instead. It keeps its taskbar button and keeps rendering; on
// release it gets its exact previous placement back, and a window that was
// minimized or maximized returns minimized (restoring to maximized) rather
// than being activated behind the user's back.

fn virtual_screen() -> RECT {
    unsafe {
        let left = GetSystemMetrics(SM_XVIRTUALSCREEN);
        let top = GetSystemMetrics(SM_YVIRTUALSCREEN);
        RECT {
            left,
            top,
            right: left + GetSystemMetrics(SM_CXVIRTUALSCREEN),
            bottom: top + GetSystemMetrics(SM_CYVIRTUALSCREEN),
        }
    }
}

fn is_off_screen(hwnd: HWND) -> bool {
    let frame = frame_rect(hwnd);
    let screen = virtual_screen();
    frame.left >= screen.right
        || frame.right <= screen.left
        || frame.top >= screen.bottom
        || frame.bottom <= screen.top
}

fn move_off_screen(hwnd: HWND) {
    let screen = virtual_screen();
    unsafe {
        let _ = SetWindowPos(
            hwnd,
            None,
            screen.right + 200,
            screen.top + 40,
            0,
            0,
            SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOOWNERZORDER,
        );
    }
}

fn park(hwnd: HWND) -> Option<WINDOWPLACEMENT> {
    let mut placement = WINDOWPLACEMENT {
        length: std::mem::size_of::<WINDOWPLACEMENT>() as u32,
        ..Default::default()
    };
    unsafe {
        GetWindowPlacement(hwnd, &mut placement).ok()?;
        if IsIconic(hwnd).as_bool() || IsZoomed(hwnd).as_bool() {
            // Back to its normal size first: a maximized window is pinned to
            // its monitor and a minimized one has no size to render.
            let _ = ShowWindow(hwnd, SW_SHOWNOACTIVATE);
            std::thread::sleep(Duration::from_millis(150));
        }
    }
    move_off_screen(hwnd);
    Some(placement)
}

fn unpark(hwnd: HWND, placement: WINDOWPLACEMENT, activate: bool) {
    if !unsafe { IsWindow(Some(hwnd)) }.as_bool() {
        return;
    }
    let mut restore = placement;
    let was_maximized = placement.showCmd == SW_SHOWMAXIMIZED.0 as u32;
    let was_minimized = placement.showCmd == SW_SHOWMINIMIZED.0 as u32;
    restore.showCmd = match (activate, was_minimized, was_maximized) {
        (true, true, _) if placement.flags.0 & WPF_RESTORETOMAXIMIZED.0 != 0 => {
            SW_SHOWMAXIMIZED.0 as u32
        }
        (true, true, _) => SW_RESTORE.0 as u32,
        (true, false, _) => placement.showCmd,
        (false, true, _) => SW_SHOWMINNOACTIVE.0 as u32,
        (false, false, true) => {
            restore.flags = WINDOWPLACEMENT_FLAGS(restore.flags.0 | WPF_RESTORETOMAXIMIZED.0);
            SW_SHOWMINNOACTIVE.0 as u32
        }
        (false, false, false) => SW_SHOWNOACTIVATE.0 as u32,
    };
    unsafe {
        let _ = SetWindowPlacement(hwnd, &restore);
    }
    bring_dialogs_back(hwnd, placement.rcNormalPosition);
}

// ── Dialogs of a parked window ──────────────────────────────────────────
//
// A dialog is a top-level window of its own, and Windows (DS_CENTER) and
// frameworks (WinForms' CenterParent) keep it on a monitor: a parked app's
// dialogs opened on the user's screen. While a window is parked, a
// captioned window it owns is moved over it the moment it is shown, and
// centred back over it when the window is handed back. Captionless popups
// (menus, dropdowns) are placed by `bring_popups_along` instead.

fn is_dialog_of(hwnd: HWND, top: HWND) -> bool {
    let style = unsafe { GetWindowLongPtrW(hwnd, GWL_STYLE) } as u32;
    hwnd != top
        && style & WS_CHILD.0 == 0
        && style & WS_CAPTION.0 == WS_CAPTION.0
        && owned_by(hwnd, top, top)
}

/// Centre `window` on `over`, resized neither.
fn centre_on(window: HWND, over: RECT, min_x: i32) {
    let frame = frame_rect(window);
    let x = over.left + ((over.right - over.left) - (frame.right - frame.left)) / 2;
    let y = over.top + ((over.bottom - over.top) - (frame.bottom - frame.top)) / 2;
    unsafe {
        let _ = SetWindowPos(
            window,
            None,
            x.max(min_x),
            y,
            0,
            0,
            SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOOWNERZORDER,
        );
    }
}

/// Move a dialog of the parked `top` over it, off the user's screen.
fn park_dialog(dialog: HWND, top: HWND) {
    if !is_off_screen(dialog) {
        // Wholly past the screen's edge, even when wider than its owner.
        centre_on(dialog, frame_rect(top), virtual_screen().right + 40);
    }
}

/// `top` is back where the user left it (`normal`): bring its dialogs along.
fn bring_dialogs_back(top: HWND, normal: RECT) {
    let pid = window_pid(top);
    for dialog in top_level_windows() {
        if window_pid(dialog) == pid
            && unsafe { IsWindowVisible(dialog) }.as_bool()
            && is_off_screen(dialog)
            && is_dialog_of(dialog, top)
        {
            centre_on(dialog, normal, i32::MIN);
        }
    }
}

/// Start, once, the thread that parks dialogs as they open (see above).
fn watch_for_dialogs() {
    static STARTED: std::sync::Once = std::sync::Once::new();
    STARTED.call_once(|| {
        let _ = std::thread::Builder::new()
            .name("computer-app-dialogs".into())
            .spawn(|| unsafe {
                let hook = SetWinEventHook(
                    EVENT_OBJECT_SHOW,
                    EVENT_OBJECT_SHOW,
                    None,
                    Some(on_window_shown),
                    0,
                    0,
                    WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS,
                );
                if hook.is_invalid() {
                    return;
                }
                let mut message = MSG::default();
                while GetMessageW(&mut message, None, 0, 0).as_bool() {
                    DispatchMessageW(&message);
                }
            });
    });
}

unsafe extern "system" fn on_window_shown(
    _hook: HWINEVENTHOOK,
    _event: u32,
    hwnd: HWND,
    object: i32,
    child: i32,
    _thread: u32,
    _time: u32,
) {
    if object != OBJID_WINDOW.0 || child != CHILDID_SELF as i32 || hwnd.0.is_null() {
        return;
    }
    let parked: Vec<HWND> = registry()
        .attached
        .values()
        .filter(|attached| attached.parked.is_some())
        .map(|attached| to_hwnd(attached.hwnd))
        .collect();
    if let Some(top) = parked.into_iter().find(|top| is_dialog_of(hwnd, *top)) {
        park_dialog(hwnd, top);
    }
}

// ── Worker threads ──────────────────────────────────────────────────────
//
// Each session's actions run on a worker thread of its own (see `mod.rs`).
// UI Automation objects are COM objects bound to the apartment that created
// them, so every worker joins the multithreaded apartment first.

pub(crate) fn init_worker_thread() {
    unsafe {
        let _ = CoInitializeEx(None, COINIT_MULTITHREADED);
    }
}

/// Whether `session_id` has a window attached (its worker is still needed).
pub(crate) fn is_attached(session_id: &str) -> bool {
    registry().attached.contains_key(session_id)
}

thread_local! {
    static AUTOMATION: RefCell<Option<IUIAutomation>> = const { RefCell::new(None) };
    static REFS: RefCell<HashMap<String, SessionRefs>> = RefCell::new(HashMap::new());
}

/// The elements a session's snapshots and finds handed out refs for, each
/// with the window it was listed in (the window itself, a dialog, or a
/// popup), so a ref into a window that is no longer in front is refused.
#[derive(Default)]
struct SessionRefs {
    elements: HashMap<String, (IUIAutomationElement, isize)>,
}

/// Ref numbers are never reused, across snapshots, sessions and attaches: a
/// ref from an earlier snapshot is unknown rather than silently naming
/// whichever control got its number this time.
static NEXT_REF: AtomicU32 = AtomicU32::new(0);

fn automation() -> Result<IUIAutomation, String> {
    AUTOMATION.with(|slot| {
        if let Some(existing) = slot.borrow().as_ref() {
            return Ok(existing.clone());
        }
        let created: IUIAutomation =
            unsafe { CoCreateInstance(&CUIAutomation, None, CLSCTX_INPROC_SERVER) }
                .map_err(|error| format!("UI Automation is unavailable: {error}"))?;
        *slot.borrow_mut() = Some(created.clone());
        Ok(created)
    })
}

/// Drop every element and window the session remembers. Held UI Automation
/// elements are proxies into the app's process; keeping them after the app
/// is released (or gone) only leaves calls that can stall on a dead server.
///
/// They live on the thread that ran the action — the session's worker, in
/// the app — so a release from elsewhere (Stop, exit) also hands the
/// clean-up to that worker, behind whatever it is running.
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
    LAST_INPUT.with(|last| {
        last.borrow_mut().remove(session_id);
    });
    LAST_POINT.with(|last| {
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

fn to_hwnd(raw: isize) -> HWND {
    HWND(raw as *mut core::ffi::c_void)
}

fn hwnd_id(hwnd: HWND) -> u64 {
    hwnd.0 as isize as u64
}

// ── Windows and apps ────────────────────────────────────────────────────

struct WindowRow {
    hwnd: HWND,
    title: String,
    pid: u32,
    app: String,
    minimized: bool,
    frame: RECT,
    owner: Option<HWND>,
}

impl WindowRow {
    fn to_json(&self, foreground: HWND) -> Value {
        json!({
            "id": hwnd_id(self.hwnd),
            "title": self.title,
            "app": self.app,
            "pid": self.pid,
            "minimized": self.minimized,
            "bounds": [
                self.frame.left,
                self.frame.top,
                self.frame.right - self.frame.left,
                self.frame.bottom - self.frame.top,
            ],
            "dialog_of": self.owner.map(hwnd_id),
            "foreground": self.hwnd == foreground,
        })
    }
}

unsafe extern "system" fn collect_window(hwnd: HWND, lparam: LPARAM) -> BOOL {
    let list = unsafe { &mut *(lparam.0 as *mut Vec<HWND>) };
    list.push(hwnd);
    BOOL(1)
}

fn top_level_windows() -> Vec<HWND> {
    let mut handles: Vec<HWND> = Vec::new();
    unsafe {
        let _ = EnumWindows(
            Some(collect_window),
            LPARAM(&mut handles as *mut Vec<HWND> as isize),
        );
    }
    handles
}

fn window_title(hwnd: HWND) -> String {
    let mut buffer = [0u16; 512];
    let len = unsafe { GetWindowTextW(hwnd, &mut buffer) }.max(0) as usize;
    String::from_utf16_lossy(&buffer[..len])
}

fn class_name(hwnd: HWND) -> String {
    let mut buffer = [0u16; 256];
    let len = unsafe { GetClassNameW(hwnd, &mut buffer) }.max(0) as usize;
    String::from_utf16_lossy(&buffer[..len])
}

fn window_pid(hwnd: HWND) -> u32 {
    let mut pid = 0u32;
    unsafe { GetWindowThreadProcessId(hwnd, Some(&mut pid)) };
    pid
}

fn process_image_path(pid: u32) -> Option<String> {
    unsafe {
        let handle = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid).ok()?;
        let mut buffer = [0u16; 1024];
        let mut len = buffer.len() as u32;
        let ok = QueryFullProcessImageNameW(
            handle,
            PROCESS_NAME_WIN32,
            PWSTR(buffer.as_mut_ptr()),
            &mut len,
        )
        .is_ok();
        let _ = CloseHandle(handle);
        ok.then(|| String::from_utf16_lossy(&buffer[..len as usize]))
    }
}

fn file_name(path: &str) -> &str {
    path.rsplit(['\\', '/']).next().unwrap_or(path)
}

fn process_image_name(pid: u32) -> String {
    process_image_path(pid)
        .map(|path| file_name(&path).to_string())
        .unwrap_or_default()
}

fn is_cloaked(hwnd: HWND) -> bool {
    let mut cloaked = 0u32;
    unsafe {
        DwmGetWindowAttribute(
            hwnd,
            DWMWA_CLOAKED,
            &mut cloaked as *mut u32 as *mut core::ffi::c_void,
            std::mem::size_of::<u32>() as u32,
        )
        .is_ok()
            && cloaked != 0
    }
}

/// The window's visible frame on screen. `GetWindowRect` includes the
/// invisible resize borders DWM draws around modern windows; screenshots and
/// coordinates are relative to what the user can actually see.
fn frame_rect(hwnd: HWND) -> RECT {
    let mut rect = RECT::default();
    unsafe {
        if DwmGetWindowAttribute(
            hwnd,
            DWMWA_EXTENDED_FRAME_BOUNDS,
            &mut rect as *mut RECT as *mut core::ffi::c_void,
            std::mem::size_of::<RECT>() as u32,
        )
        .is_err()
            || rect.right <= rect.left
        {
            let _ = GetWindowRect(hwnd, &mut rect);
        }
    }
    rect
}

fn describe_window(hwnd: HWND) -> Option<WindowRow> {
    unsafe {
        if !IsWindowVisible(hwnd).as_bool() || is_cloaked(hwnd) {
            return None;
        }
        let ex_style = GetWindowLongPtrW(hwnd, GWL_EXSTYLE) as u32;
        if ex_style & WS_EX_TOOLWINDOW.0 != 0 {
            return None;
        }
    }
    let title = window_title(hwnd);
    if title.trim().is_empty() {
        return None;
    }
    let pid = window_pid(hwnd);
    let owner = unsafe { GetWindow(hwnd, GW_OWNER) }
        .ok()
        .filter(|owner| !owner.0.is_null());
    Some(WindowRow {
        hwnd,
        title,
        pid,
        app: process_image_name(pid),
        minimized: unsafe { IsIconic(hwnd) }.as_bool(),
        frame: frame_rect(hwnd),
        owner,
    })
}

fn attach_refusal(row: &WindowRow) -> Option<String> {
    if row.pid == unsafe { GetCurrentProcessId() } {
        return Some("EvoFlux cannot control its own window.".into());
    }
    if row.app.is_empty() {
        return Some(format!(
            "Windows did not let EvoFlux inspect the process behind \"{}\" (it may run as administrator), so it cannot be controlled.",
            row.title
        ));
    }
    if is_protected_process_name(&row.app) {
        return Some(format!(
            "{} is part of the Windows shell or security system and cannot be controlled.",
            row.app
        ));
    }
    if runs_above_us(row.pid) {
        return Some(format!(
            "{} runs as administrator (or as the system), and Windows blocks input from a normal EvoFlux to it. Ask the user to run it normally, or to do this part themselves.",
            row.app
        ));
    }
    None
}

/// The integrity level (the last sub-authority of the token's mandatory
/// label: 0x2000 medium, 0x3000 high, 0x4000 system) of a process.
fn integrity_level(process: windows::Win32::Foundation::HANDLE) -> Option<u32> {
    use windows::Win32::Security::{
        GetSidSubAuthority, GetSidSubAuthorityCount, GetTokenInformation, TokenIntegrityLevel,
        TOKEN_MANDATORY_LABEL, TOKEN_QUERY,
    };
    use windows::Win32::System::Threading::OpenProcessToken;
    unsafe {
        let mut token = windows::Win32::Foundation::HANDLE::default();
        OpenProcessToken(process, TOKEN_QUERY, &mut token).ok()?;
        let mut size = 0u32;
        let _ = GetTokenInformation(token, TokenIntegrityLevel, None, 0, &mut size);
        let mut buffer = vec![0u8; size.max(1) as usize];
        let read = GetTokenInformation(
            token,
            TokenIntegrityLevel,
            Some(buffer.as_mut_ptr() as *mut core::ffi::c_void),
            size,
            &mut size,
        );
        let _ = CloseHandle(token);
        read.ok()?;
        let label = &*(buffer.as_ptr() as *const TOKEN_MANDATORY_LABEL);
        let count = *GetSidSubAuthorityCount(label.Label.Sid);
        (count > 0).then(|| *GetSidSubAuthority(label.Label.Sid, u32::from(count) - 1))
    }
}

/// Whether `pid` runs at a higher integrity level than EvoFlux — elevated,
/// or a system process. Windows' UIPI drops input posted to such an app
/// and UI Automation cannot operate it, so attaching would only leave an
/// app that silently ignores every action. A token EvoFlux may not even
/// read belongs to one too.
fn runs_above_us(pid: u32) -> bool {
    use windows::Win32::System::Threading::GetCurrentProcess;
    let Some(ours) = integrity_level(unsafe { GetCurrentProcess() }) else {
        return false;
    };
    let Ok(process) = (unsafe { OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid) }) else {
        return false;
    };
    let theirs = integrity_level(process);
    unsafe {
        let _ = CloseHandle(process);
    }
    is_above(ours, theirs)
}

/// `theirs` is `None` when the process's token could not be read at all.
fn is_above(ours: u32, theirs: Option<u32>) -> bool {
    theirs.map_or(true, |level| level > ours)
}

fn list_windows(session_id: &str, params: &Value) -> Value {
    let filter = params
        .get("app")
        .or_else(|| params.get("query"))
        .and_then(Value::as_str)
        .map(|value| value.trim().to_lowercase())
        .filter(|value| !value.is_empty());
    let foreground = unsafe { GetForegroundWindow() };
    // Windows another chat controls: attaching them is refused.
    let held: HashSet<isize> = registry()
        .attached
        .iter()
        .filter(|(other, _)| other.as_str() != session_id)
        .map(|(_, attached)| attached.hwnd)
        .collect();
    let windows: Vec<Value> = top_level_windows()
        .into_iter()
        .filter_map(describe_window)
        .filter(|row| attach_refusal(row).is_none())
        .filter(|row| match &filter {
            Some(needle) => {
                row.app.to_lowercase().contains(needle) || row.title.to_lowercase().contains(needle)
            }
            None => true,
        })
        .map(|row| {
            let mut json = row.to_json(foreground);
            json["controlled_elsewhere"] = json!(held.contains(&(row.hwnd.0 as isize)));
            json
        })
        .collect();
    json!({ "count": windows.len(), "windows": windows })
}

// ── The app picker (Settings → Computer App Control) ────────────────────

struct AppEntry {
    name: String,
    path: String,
    running: bool,
}

/// A short app name from a window caption: "notes.txt - Notepad" gives
/// "Notepad", "Chat | Contoso | Microsoft Teams" gives "Microsoft Teams".
fn caption_app_name(title: &str) -> Option<String> {
    let last = [" - ", " | ", " — "]
        .iter()
        .fold(title, |text, separator| text.rsplit(separator).next().unwrap_or(text))
        .trim();
    (!last.is_empty() && last.chars().count() <= 32).then(|| last.to_string())
}

fn exe_stem(exe: &str) -> String {
    let stem = exe.strip_suffix(".exe").unwrap_or(exe);
    let mut chars = stem.chars();
    match chars.next() {
        Some(first) => first.to_uppercase().chain(chars).collect(),
        None => String::new(),
    }
}

/// Target of a `.lnk` shortcut, when it points at a program.
fn shortcut_target(link: &std::path::Path) -> Option<String> {
    use windows::core::HSTRING;
    use windows::Win32::System::Com::{IPersistFile, STGM_READ};
    use windows::Win32::UI::Shell::{IShellLinkW, ShellLink};
    unsafe {
        let shell_link: IShellLinkW = CoCreateInstance(&ShellLink, None, CLSCTX_INPROC_SERVER).ok()?;
        let file: IPersistFile = shell_link.cast().ok()?;
        file.Load(&HSTRING::from(link.as_os_str()), STGM_READ).ok()?;
        let mut buffer = [0u16; 1024];
        shell_link.GetPath(&mut buffer, std::ptr::null_mut(), 0).ok()?;
        let len = buffer.iter().position(|&unit| unit == 0).unwrap_or(buffer.len());
        let target = String::from_utf16_lossy(&buffer[..len]);
        target.to_lowercase().ends_with(".exe").then_some(target)
    }
}

fn start_menu_dirs() -> Vec<std::path::PathBuf> {
    ["ProgramData", "APPDATA"]
        .iter()
        .filter_map(|variable| std::env::var_os(variable))
        .map(|root| {
            std::path::PathBuf::from(root)
                .join("Microsoft")
                .join("Windows")
                .join("Start Menu")
                .join("Programs")
        })
        .filter(|dir| dir.is_dir())
        .collect()
}

static ICONS: Lazy<Mutex<HashMap<String, Option<String>>>> = Lazy::new(|| Mutex::new(HashMap::new()));

/// The program's own icon as a PNG data URL, cached per path.
fn icon_data_url(path: &str) -> Option<String> {
    if let Some(cached) = ICONS.lock().ok()?.get(path) {
        return cached.clone();
    }
    // Icon extraction is a shell integration; a broken icon must not take
    // the whole list down with it.
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

/// Apps a user might allow or block: everything with a window right now,
/// plus the programs in the Start menu. Keyed by executable name, which is
/// what the policy matches on.
pub(crate) fn list_apps() -> Value {
    let own = unsafe { GetCurrentProcessId() };
    let mut apps: HashMap<String, AppEntry> = HashMap::new();
    for row in top_level_windows().into_iter().filter_map(describe_window) {
        if row.pid == own || is_protected_process_name(&row.app) {
            continue;
        }
        let Some(path) = process_image_path(row.pid) else {
            continue;
        };
        let exe = file_name(&path).to_lowercase();
        let name = caption_app_name(&row.title).unwrap_or_else(|| exe_stem(&exe));
        apps.entry(exe)
            .and_modify(|entry| entry.running = true)
            .or_insert(AppEntry { name, path, running: true });
    }
    let links: Vec<(String, std::path::PathBuf)> = start_menu_dirs()
        .into_iter()
        .flat_map(|dir| walkdir::WalkDir::new(dir).max_depth(4).into_iter().filter_map(Result::ok))
        .filter(|entry| {
            entry.path().extension().and_then(|ext| ext.to_str()).map(str::to_lowercase)
                == Some("lnk".to_string())
        })
        .filter_map(|entry| {
            let name = entry.path().file_stem()?.to_str()?.to_string();
            let lower = name.to_lowercase();
            let noise = ["uninstall", "readme", "help", "website", "documentation"];
            (!name.is_empty() && !noise.iter().any(|word| lower.contains(word)))
                .then(|| (name, entry.path().to_path_buf()))
        })
        .collect();
    let resolved = in_parallel(links, |(name, link)| {
        shortcut_target(&link).map(|path| (name, path))
    });
    for (name, path) in resolved.into_iter().flatten() {
        let exe = file_name(&path).to_lowercase();
        if is_protected_process_name(&exe) {
            continue;
        }
        // The Start menu's name for a program beats one read off a caption.
        apps.entry(exe)
            .and_modify(|entry| entry.name = name.clone())
            .or_insert(AppEntry { name, path, running: false });
    }
    let mut list: Vec<(String, AppEntry)> = apps.into_iter().collect();
    list.sort_by(|(_, a), (_, b)| {
        b.running.cmp(&a.running).then_with(|| a.name.to_lowercase().cmp(&b.name.to_lowercase()))
    });
    // Icons one at a time: the shell's icon extraction is not reliable when
    // several threads ask at once (measured: some icons came back empty).
    let apps: Vec<Value> = list
        .into_iter()
        .map(|(exe, entry)| {
            json!({
                "exe": exe,
                "name": entry.name,
                "running": entry.running,
                "icon": icon_data_url(&entry.path),
            })
        })
        .collect();
    json!({ "apps": apps })
}

/// Map `items` with `work` on a few COM-initialised threads, keeping order.
/// Resolving a shortcut takes tens of milliseconds, which adds up to seconds
/// for a full Start menu.
fn in_parallel<T: Send, R: Send>(items: Vec<T>, work: impl Fn(T) -> R + Sync) -> Vec<R> {
    const THREADS: usize = 8;
    let chunk = items.len().div_ceil(THREADS).max(1);
    let mut chunks: Vec<Vec<T>> = Vec::new();
    let mut items = items.into_iter().peekable();
    while items.peek().is_some() {
        chunks.push(items.by_ref().take(chunk).collect());
    }
    std::thread::scope(|scope| {
        let handles: Vec<_> = chunks
            .into_iter()
            .map(|chunk| {
                let work = &work;
                scope.spawn(move || {
                    unsafe {
                        let _ = CoInitializeEx(None, COINIT_MULTITHREADED);
                    }
                    chunk.into_iter().map(work).collect::<Vec<R>>()
                })
            })
            .collect();
        handles
            .into_iter()
            .flat_map(|handle| handle.join().unwrap_or_default())
            .collect()
    })
}

fn status(session_id: &str) -> Value {
    let registry = registry();
    let stopped = registry.stopped.contains(session_id);
    match registry.attached.get(session_id) {
        Some(attached) => {
            let hwnd = to_hwnd(attached.hwnd);
            let open = unsafe { IsWindow(Some(hwnd)) }.as_bool();
            json!({
                "attached": true,
                "open": open,
                "window": {
                    "id": attached.hwnd as u64,
                    "app": attached.app,
                    "title": if open { window_title(hwnd) } else { attached.title.clone() },
                    "pid": attached.pid,
                    "minimized": open && unsafe { IsIconic(hwnd) }.as_bool(),
                    "hidden": attached.parked.is_some(),
                },
                "stopped": stopped,
            })
        }
        None => json!({ "attached": false, "stopped": stopped }),
    }
}

fn attach(session_id: &str, params: &Value) -> Result<Value, String> {
    if registry().stopped.contains(session_id) {
        return Err("The user stopped Computer App Control in this chat. Ask them before trying again: the preview card is showing again, and they can press Allow again there.".into());
    }
    let window_id = params.get("window_id").and_then(Value::as_u64);
    let rows: Vec<WindowRow> = top_level_windows()
        .into_iter()
        .filter_map(describe_window)
        .collect();
    let chosen = if let Some(id) = window_id {
        rows.into_iter()
            .find(|row| hwnd_id(row.hwnd) == id)
            .ok_or_else(|| format!("No visible window with id {id}. Call list_windows again."))?
    } else {
        let app = params.get("app").and_then(Value::as_str).map(str::to_lowercase);
        let title = params.get("title").and_then(Value::as_str).map(str::to_lowercase);
        if app.is_none() && title.is_none() {
            return Err("attach needs window_id (from list_windows), app, or title.".into());
        }
        rows.into_iter()
            .filter(|row| attach_refusal(row).is_none())
            .find(|row| {
                app.as_ref()
                    .map_or(true, |app| row.app.to_lowercase().contains(app))
                    && title
                        .as_ref()
                        .map_or(true, |title| row.title.to_lowercase().contains(title))
            })
            .ok_or("No controllable window matches. Call list_windows to see what is open.")?
    };
    if let Some(reason) = attach_refusal(&chosen) {
        return Err(reason);
    }
    // A dialog is driven through the window that owns it, so the card keeps
    // following the app when the dialog closes.
    let chosen = match chosen.owner {
        Some(owner) if window_pid(owner) == chosen.pid => describe_window(owner).unwrap_or(chosen),
        _ => chosen,
    };
    // One chat per window: two would interleave their input, and the second
    // would save the first one's off-screen spot as the window's own place.
    let held_elsewhere = registry()
        .attached
        .iter()
        .any(|(other, attached)| other != session_id && attached.hwnd == chosen.hwnd.0 as isize);
    if held_elsewhere {
        return Err(format!(
            "\"{}\" is already controlled from another chat. Finish or detach there first, or pick another window.",
            chosen.title
        ));
    }
    // Attaching to another window hands the previous one back first.
    release(session_id);
    let hide = params.get("hide").and_then(Value::as_bool).unwrap_or(false);
    let web = is_web_host(chosen.hwnd);
    if web {
        // Chromium only exposes a page's tree once an assistive client asks
        // for it, builds it asynchronously, and stops building it for a
        // window that is off-screen. Ask while the window is still where the
        // user left it, and wait until the page is there before parking.
        wait_for_page_tree(chosen.hwnd);
    }
    let parked = if hide {
        watch_for_dialogs();
        let parked = park(chosen.hwnd);
        if web {
            // Let Chromium finish reacting to being hidden before the first
            // action arrives: keys typed sooner were lost now and then
            // (measured: with this wait, none in repeated runs).
            pause(800);
        }
        parked
    } else {
        unsafe {
            if IsIconic(chosen.hwnd).as_bool() {
                let _ = ShowWindow(chosen.hwnd, SW_SHOWNOACTIVATE);
            }
        }
        None
    };
    // Stop pressed while this attach was parking the window: hand it back
    // instead of registering a window nobody may drive.
    if let Err(stopped) = interrupted() {
        if let Some(placement) = parked {
            unpark(chosen.hwnd, placement, false);
        }
        return Err(stopped);
    }
    let attached = Attached {
        hwnd: chosen.hwnd.0 as isize,
        pid: chosen.pid,
        app: chosen.app.clone(),
        title: chosen.title.clone(),
        parked,
    };
    registry()
        .attached
        .insert(session_id.to_string(), attached);
    let target = Target::resolve(session_id)?;
    Ok(json!({
        "attached": true,
        "window": target.describe(),
    }))
}

fn detach(session_id: &str) -> Value {
    let removed = release(session_id);
    json!({ "detached": removed.is_some() })
}

// ── The window being driven ─────────────────────────────────────────────

struct Target {
    session_id: String,
    top: HWND,
    /// `top`, or the modal dialog it is currently blocked on.
    window: HWND,
    pid: u32,
    app: String,
    frame: RECT,
    scale: f64,
    restored: bool,
    /// Parked off-screen at the user's request.
    hidden: bool,
    /// Chromium/WebView2/Electron content (see [`is_web_host`]).
    web: bool,
    /// Menus and dropdowns the window has open, topmost first. `frame`
    /// covers them too (see [`open_popups`]).
    popups: Vec<HWND>,
    /// The window's own frame, without its popups.
    window_frame: RECT,
}

impl Target {
    fn resolve(session_id: &str) -> Result<Self, String> {
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
            bring_popups_along(session_id, window_frame, &popups);
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
    fn popup_at(&self, point: POINT) -> Option<HWND> {
        self.popups.iter().copied().find(|popup| {
            let frame = frame_rect(*popup);
            point.x >= frame.left && point.x < frame.right && point.y >= frame.top && point.y < frame.bottom
        })
    }

    fn width(&self) -> i32 {
        (self.frame.right - self.frame.left).max(1)
    }

    fn height(&self) -> i32 {
        (self.frame.bottom - self.frame.top).max(1)
    }

    fn screenshot_size(&self) -> (u32, u32) {
        (
            ((self.width() as f64) * self.scale).round().max(1.0) as u32,
            ((self.height() as f64) * self.scale).round().max(1.0) as u32,
        )
    }

    fn describe(&self) -> Value {
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
    fn screen_point(&self, x: f64, y: f64) -> Result<POINT, String> {
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
    fn screenshot_point(&self, point: POINT) -> (i64, i64) {
        (
            (f64::from(point.x - self.frame.left) * self.scale).round() as i64,
            (f64::from(point.y - self.frame.top) * self.scale).round() as i64,
        )
    }

    fn emit_pointer(&self, emit: &dyn Fn(Value), point: POINT, phase: &str) {
        let x = f64::from(point.x - self.frame.left) / f64::from(self.width());
        let y = f64::from(point.y - self.frame.top) / f64::from(self.height());
        emit(json!({ "sessionId": self.session_id, "x": x, "y": y, "phase": phase }));
    }

    /// Move the preview's cursor to `point` and give it time to get there,
    /// so the user sees where the agent is about to act before it does —
    /// and can still stop it.
    fn travel(&self, emit: &dyn Fn(Value), point: POINT) -> Result<(), String> {
        self.emit_pointer(emit, point, "move");
        std::thread::sleep(POINTER_TRAVEL);
        interrupted()
    }
}

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
fn is_web_host(window: HWND) -> bool {
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
fn chromium_input_window(target: &Target, point: Option<POINT>) -> HWND {
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

/// Where a posted pointer message for `point` goes: the deepest window
/// there, lifted to its Chromium widget for web content.
fn pointer_window(target: &Target, point: POINT) -> HWND {
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

/// A window disabled by a modal dialog cannot take input; the dialog can.
fn effective_window(top: HWND, pid: u32) -> HWND {
    unsafe {
        if IsWindowEnabled(top).as_bool() {
            return top;
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
            _ => top,
        }
    }
}

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

fn owned_by(hwnd: HWND, window: HWND, top: HWND) -> bool {
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
fn is_popup_of(hwnd: HWND, window: HWND, top: HWND, pid: u32) -> bool {
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

/// The attached window's open popups, topmost first.
fn open_popups(window: HWND, top: HWND, pid: u32) -> Vec<HWND> {
    top_level_windows()
        .into_iter()
        .filter(|hwnd| is_popup_of(*hwnd, window, top, pid))
        .collect()
}

fn union(a: RECT, b: RECT) -> RECT {
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

thread_local! {
    /// Where each session last clicked or hovered: a parked app's popup
    /// is moved back there (see [`bring_popups_along`]).
    static LAST_POINT: RefCell<HashMap<String, POINT>> = RefCell::new(HashMap::new());
}

fn remember_point(session_id: &str, point: POINT) {
    LAST_POINT.with(|last| {
        last.borrow_mut().insert(session_id.to_string(), point);
    });
}

/// A popup of a parked window opens on the user's screen: Windows keeps
/// menus on a monitor, so a menu asked for at an off-screen point lands at
/// the edge of one. Move such popups next to the window, where the agent
/// clicked, so they leave the user's screen and stay in the capture.
fn bring_popups_along(session_id: &str, window_frame: RECT, popups: &[HWND]) {
    let anchor = LAST_POINT
        .with(|last| last.borrow().get(session_id).copied())
        .unwrap_or(POINT { x: window_frame.left + 40, y: window_frame.top + 40 });
    for popup in popups {
        let frame = frame_rect(*popup);
        if intersects(&frame, &window_frame) {
            continue;
        }
        let width = frame.right - frame.left;
        let height = frame.bottom - frame.top;
        let x = anchor.x.min(window_frame.right - width).max(window_frame.left);
        let y = anchor.y.min(window_frame.bottom - height).max(window_frame.top);
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

/// The window with its popups drawn over it, on a canvas covering `frame`
/// (their union). Popups are drawn bottom-most first.
fn capture_with_popups(window: HWND, popups: &[HWND], frame: RECT) -> Result<RgbaImage, String> {
    let base = capture(window)?;
    if popups.is_empty() {
        return Ok(base);
    }
    let width = (frame.right - frame.left).max(1) as u32;
    let height = (frame.bottom - frame.top).max(1) as u32;
    let mut canvas = RgbaImage::from_pixel(width, height, image::Rgba([24, 24, 24, 255]));
    let window_frame = frame_rect(window);
    imageops::overlay(
        &mut canvas,
        &base,
        i64::from(window_frame.left - frame.left),
        i64::from(window_frame.top - frame.top),
    );
    for popup in popups.iter().rev() {
        // A popup that will not render is left out rather than failing the
        // whole screenshot.
        if let Ok(image) = capture(*popup) {
            let popup_frame = frame_rect(*popup);
            imageops::overlay(
                &mut canvas,
                &image,
                i64::from(popup_frame.left - frame.left),
                i64::from(popup_frame.top - frame.top),
            );
        }
    }
    Ok(canvas)
}

// ── Capture ─────────────────────────────────────────────────────────────

/// Render `hwnd` with `PrintWindow`, cropped to its visible frame. Works for
/// windows behind other windows; the window renders itself into our bitmap.
fn capture(hwnd: HWND) -> Result<RgbaImage, String> {
    // PrintWindow asks the app to paint synchronously; a hung app would
    // block this thread (and every action queued behind it) indefinitely.
    if unsafe { IsHungAppWindow(hwnd) }.as_bool() {
        return Err("The app is not responding. Wait for it, then try again.".into());
    }
    let mut window_rect = RECT::default();
    unsafe { GetWindowRect(hwnd, &mut window_rect) }
        .map_err(|error| format!("GetWindowRect failed: {error}"))?;
    let width = window_rect.right - window_rect.left;
    let height = window_rect.bottom - window_rect.top;
    if width <= 0 || height <= 0 {
        return Err("The window has no size to capture.".into());
    }

    let pixels = unsafe {
        let screen_dc = GetDC(None);
        if screen_dc.is_invalid() {
            return Err("GetDC failed".into());
        }
        let memory_dc = CreateCompatibleDC(Some(screen_dc));
        let bitmap = CreateCompatibleBitmap(screen_dc, width, height);
        let _ = ReleaseDC(None, screen_dc);
        if memory_dc.is_invalid() || bitmap.is_invalid() {
            if !bitmap.is_invalid() {
                let _ = DeleteObject(bitmap.into());
            }
            if !memory_dc.is_invalid() {
                let _ = DeleteDC(memory_dc);
            }
            return Err("Could not allocate a capture bitmap.".into());
        }
        let previous = SelectObject(memory_dc, bitmap.into());
        let mut rendered = PrintWindow(hwnd, memory_dc, PW_RENDERFULLCONTENT).as_bool();
        if !rendered {
            let window_dc = GetWindowDC(Some(hwnd));
            if !window_dc.is_invalid() {
                rendered =
                    BitBlt(memory_dc, 0, 0, width, height, Some(window_dc), 0, 0, SRCCOPY).is_ok();
                let _ = ReleaseDC(Some(hwnd), window_dc);
            }
        }
        let pixels = if rendered {
            read_pixels(memory_dc, bitmap, width as u32, height as u32)
        } else {
            Err("The window refused to render (PrintWindow and BitBlt both failed).".into())
        };
        let _ = SelectObject(memory_dc, previous);
        let _ = DeleteObject(bitmap.into());
        let _ = DeleteDC(memory_dc);
        pixels?
    };

    let full = RgbaImage::from_raw(width as u32, height as u32, pixels)
        .ok_or("Captured pixels did not match the window size.")?;
    let frame = frame_rect(hwnd);
    let left = (frame.left - window_rect.left).clamp(0, width - 1) as u32;
    let top = (frame.top - window_rect.top).clamp(0, height - 1) as u32;
    let crop_width = ((frame.right - frame.left).max(1) as u32).min(width as u32 - left);
    let crop_height = ((frame.bottom - frame.top).max(1) as u32).min(height as u32 - top);
    Ok(imageops::crop_imm(&full, left, top, crop_width, crop_height).to_image())
}

unsafe fn read_pixels(
    memory_dc: HDC,
    bitmap: HBITMAP,
    width: u32,
    height: u32,
) -> Result<Vec<u8>, String> {
    let mut info = BITMAPINFO {
        bmiHeader: BITMAPINFOHEADER {
            biSize: std::mem::size_of::<BITMAPINFOHEADER>() as u32,
            biWidth: width as i32,
            biHeight: -(height as i32),
            biPlanes: 1,
            biBitCount: 32,
            ..Default::default()
        },
        ..Default::default()
    };
    let mut pixels = vec![0u8; (width * height * 4) as usize];
    let lines = unsafe {
        GetDIBits(
            memory_dc,
            bitmap,
            0,
            height,
            Some(pixels.as_mut_ptr() as *mut core::ffi::c_void),
            &mut info,
            DIB_RGB_COLORS,
        )
    };
    if lines == 0 {
        return Err("GetDIBits failed".into());
    }
    for pixel in pixels.chunks_exact_mut(4) {
        pixel.swap(0, 2);
        // GetDIBits leaves alpha at 0, which would read as fully transparent.
        pixel[3] = 255;
    }
    Ok(pixels)
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
    let captured = capture_with_popups(target.window, &target.popups, target.frame)?;
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
        (
            registry.attached.get(session_id).cloned(),
            registry.stopped.contains(session_id),
        )
    };
    let Some(attached) = attached else {
        return Ok(json!({ "attached": false, "stopped": stopped }));
    };
    let top = to_hwnd(attached.hwnd);
    let base = json!({
        "attached": true,
        "stopped": stopped,
        "app": attached.app,
        "title": attached.title,
    });
    if !unsafe { IsWindow(Some(top)) }.as_bool() {
        return Ok(merge(base, json!({ "closed": true })));
    }
    let title = window_title(top);
    if unsafe { IsIconic(top) }.as_bool() {
        return Ok(merge(base, json!({ "minimized": true, "title": title })));
    }
    let window = effective_window(top, attached.pid);
    let popups = open_popups(window, top, attached.pid);
    let frame = popups
        .iter()
        .fold(frame_rect(window), |frame, popup| union(frame, frame_rect(*popup)));
    let captured = capture_with_popups(window, &popups, frame)?;
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
            "dialog": window != top,
            "width": width,
            "height": height,
            "media_type": "image/jpeg",
            "data": encode_jpeg(&preview, 72)?,
        }),
    ))
}

fn merge(mut base: Value, extra: Value) -> Value {
    if let (Some(base), Value::Object(extra)) = (base.as_object_mut(), extra) {
        base.extend(extra);
    }
    base
}

// ── Pointer input (posted, background) ──────────────────────────────────

/// The deepest visible, enabled child window of `top` under `point`.
fn child_at(top: HWND, point: POINT) -> HWND {
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
fn to_logical(x: i32, y: i32, scale: f64) -> (i32, i32) {
    if (scale - 1.0).abs() < 1e-6 {
        return (x, y);
    }
    ((f64::from(x) * scale).round() as i32, (f64::from(y) * scale).round() as i32)
}

/// A screen point as `hwnd` sees screen coordinates, packed for the
/// messages that carry screen coordinates (the wheel, hit-testing).
fn screen_lparam(hwnd: HWND, point: POINT) -> LPARAM {
    use windows::Win32::UI::HiDpi::PhysicalToLogicalPointForPerMonitorDPI;
    let mut logical = point;
    unsafe {
        let _ = PhysicalToLogicalPointForPerMonitorDPI(Some(hwnd), &mut logical);
    }
    LPARAM(pack_point(logical.x, logical.y))
}

fn client_lparam(hwnd: HWND, point: POINT) -> LPARAM {
    let mut local = point;
    unsafe {
        let _ = ScreenToClient(hwnd, &mut local);
    }
    let (x, y) = to_logical(local.x, local.y, logical_scale(hwnd));
    LPARAM(pack_point(x, y))
}

fn post(hwnd: HWND, message: u32, wparam: usize, lparam: LPARAM) -> Result<(), String> {
    unsafe { PostMessageW(Some(hwnd), message, WPARAM(wparam), lparam) }.map_err(|error| {
        if error.code().0 as u32 == 0x8007_0005 {
            "Windows blocked input to this app. It probably runs as administrator, which a normal EvoFlux cannot drive.".to_string()
        } else {
            format!("Could not post input to the window: {error}")
        }
    })
}

fn pause(ms: u64) {
    std::thread::sleep(Duration::from_millis(ms));
}

/// Where a pointer action lands: a ref's centre or screenshot coordinates.
fn pointer_target(target: &Target, params: &Value) -> Result<POINT, String> {
    if let Some(reference) = params.get("ref").and_then(Value::as_str) {
        let element = element_for(target, reference)?;
        let rect = unsafe { element.CurrentBoundingRectangle() }
            .map_err(|error| format!("{reference} has no position: {error}"))?;
        if rect.right <= rect.left || rect.bottom <= rect.top {
            return Err(format!("{reference} is not visible on screen; try invoke instead."));
        }
        return Ok(POINT {
            x: (rect.left + rect.right) / 2,
            y: (rect.top + rect.bottom) / 2,
        });
    }
    let x = params.get("x").and_then(Value::as_f64);
    let y = params.get("y").and_then(Value::as_f64);
    match (x, y) {
        (Some(x), Some(y)) => target.screen_point(x, y),
        _ => Err("Give either a ref or both x and y (screenshot pixels).".into()),
    }
}

/// Refuse points on the window frame: posted clicks there would start a
/// system move/size loop or hit a caption button the app does not own.
fn ensure_client_area(target: &Target, hwnd: HWND, point: POINT) -> Result<(), String> {
    if hwnd != target.window {
        return Ok(());
    }
    let mut hit: usize = 0;
    let answered = unsafe {
        SendMessageTimeoutW(
            hwnd,
            WM_NCHITTEST,
            WPARAM(0),
            screen_lparam(hwnd, point),
            SMTO_ABORTIFHUNG,
            200,
            Some(&mut hit),
        )
    };
    let hit = hit as isize;
    if answered.0 == 0 || hit == HTCLIENT || hit == HTTRANSPARENT {
        return Ok(());
    }
    Err(format!(
        "That point is on the window's frame or title bar (hit-test {hit}). Background control only reaches the app's content; use key shortcuts or invoke for window-level commands."
    ))
}

fn button_messages(button: &str) -> Result<(u32, u32, u32, usize), String> {
    match button {
        "left" => Ok((WM_LBUTTONDOWN, WM_LBUTTONUP, WM_LBUTTONDBLCLK, MK_LBUTTON)),
        "right" => Ok((WM_RBUTTONDOWN, WM_RBUTTONUP, WM_RBUTTONDBLCLK, MK_RBUTTON)),
        "middle" => Ok((WM_MBUTTONDOWN, WM_MBUTTONUP, WM_MBUTTONDBLCLK, MK_MBUTTON)),
        other => Err(format!("Unknown mouse button {other:?}")),
    }
}

fn pointer_result(target: &Target, hwnd: HWND, point: POINT, extra: Value) -> Value {
    let (x, y) = target.screenshot_point(point);
    merge(
        json!({
            "pointer": { "x": x, "y": y },
            "delivered_to": class_name(hwnd),
            "window": window_title(target.window),
        }),
        extra,
    )
}

fn click(emit: &dyn Fn(Value), target: &Target, params: &Value) -> Result<Value, String> {
    let point = pointer_target(target, params)?;
    let button = params.get("button").and_then(Value::as_str).unwrap_or("left");
    let clicks = params.get("clicks").and_then(Value::as_u64).unwrap_or(1).clamp(1, 3);
    let (down, up, double, mask) = button_messages(button)?;
    remember_point(&target.session_id, point);

    // A plain left click goes through UI Automation when it can: always for
    // a ref (the element's own action is exact), and for coordinates in web
    // content, where posted mouse messages do not reach the page.
    if button == "left" && clicks == 1 {
        let reference = params.get("ref").and_then(Value::as_str);
        let mut chain = match reference {
            Some(reference) => vec![element_for(target, reference)?],
            None => Vec::new(),
        };
        if let Some(done) = click_via_automation(emit, target, &chain, point)? {
            return Ok(done);
        }
        if target.web {
            chain = elements_at(target, point)?;
            if let Some(done) = click_via_automation(emit, target, &chain, point)? {
                return Ok(done);
            }
        }
    }

    let hwnd = pointer_window(target, point);
    ensure_client_area(target, hwnd, point)?;
    let lparam = client_lparam(hwnd, point);

    target.travel(emit, point)?;
    target.emit_pointer(emit, point, "press");
    post(hwnd, WM_MOUSEMOVE, 0, lparam)?;
    for index in 0..clicks {
        interrupted()?;
        // The second press of a double click is WM_*BUTTONDBLCLK, as Windows
        // itself would deliver it to a CS_DBLCLKS window.
        let press = if index == 1 { double } else { down };
        post(hwnd, press, mask, lparam)?;
        pause(25);
        post(hwnd, up, 0, lparam)?;
        pause(40);
    }
    target.emit_pointer(emit, point, "click");
    remember_input_window(&target.session_id, hwnd);
    // A posted click put focus somewhere UI Automation did not report.
    forget_editable(&target.session_id);
    let mut extra = json!({ "button": button, "clicks": clicks });
    if target.web {
        extra["note"] = json!(WEB_INPUT_NOTE);
    }
    // A click that opened a menu or dropdown: say so, and for a parked app
    // take it off the user's screen straight away.
    pause(150);
    let popups = open_popups(target.window, target.top, target.pid);
    if popups.iter().any(|popup| !target.popups.contains(popup)) {
        if target.hidden {
            bring_popups_along(&target.session_id, frame_rect(target.window), &popups);
        }
        extra["note"] = json!("A menu or dropdown opened. Take a screenshot or snapshot to see its items (snapshot lists them first).");
    }
    Ok(pointer_result(target, hwnd, point, extra))
}

/// Said whenever posted input had to be used on web content.
const WEB_INPUT_NOTE: &str = "This app draws web content, which may ignore background mouse clicks. If nothing changed, use snapshot or find, then click or invoke by ref.";

fn hover(emit: &dyn Fn(Value), target: &Target, params: &Value) -> Result<Value, String> {
    let point = pointer_target(target, params)?;
    remember_point(&target.session_id, point);
    let hwnd = pointer_window(target, point);
    target.travel(emit, point)?;
    post(hwnd, WM_MOUSEMOVE, 0, client_lparam(hwnd, point))?;
    Ok(pointer_result(target, hwnd, point, json!({})))
}

fn scroll(emit: &dyn Fn(Value), target: &Target, params: &Value) -> Result<Value, String> {
    let point = if params.get("ref").is_some() || params.get("x").is_some() {
        pointer_target(target, params)?
    } else {
        POINT {
            x: (target.frame.left + target.frame.right) / 2,
            y: (target.frame.top + target.frame.bottom) / 2,
        }
    };
    let direction = params.get("direction").and_then(Value::as_str).unwrap_or("down");
    let amount = params.get("amount").and_then(Value::as_u64).unwrap_or(3).clamp(1, 50) as i32;
    let (message, delta) = match direction {
        "down" => (WM_MOUSEWHEEL, -WHEEL_DELTA),
        "up" => (WM_MOUSEWHEEL, WHEEL_DELTA),
        "right" => (WM_MOUSEHWHEEL, WHEEL_DELTA),
        "left" => (WM_MOUSEHWHEEL, -WHEEL_DELTA),
        other => return Err(format!("Unknown scroll direction {other:?}")),
    };
    if target.web {
        // Chromium reroutes wheel messages to whatever window is under the
        // user's real cursor, so a posted wheel never reaches a background
        // page. Scroll the scrollable element under the point instead.
        let chain = match params.get("ref").and_then(Value::as_str) {
            Some(reference) => with_ancestors(element_for(target, reference)?),
            None => elements_at(target, point)?,
        };
        target.travel(emit, point)?;
        if let Some(scrolled) = scroll_via_automation(&chain, direction, amount)? {
            let (x, y) = target.screenshot_point(point);
            return Ok(json!({
                "pointer": { "x": x, "y": y },
                "delivered_to": scrolled,
                "delivered_via": "ui_automation",
                "pattern": "scroll",
                "window": window_title(target.window),
                "direction": direction,
                "amount": amount,
            }));
        }
    }
    let hwnd = pointer_window(target, point);
    target.travel(emit, point)?;
    // Wheel messages carry screen coordinates, unlike the button messages.
    let wparam = ((delta as i16 as u16 as usize) << 16) as usize;
    for _ in 0..amount {
        interrupted()?;
        post(hwnd, message, wparam, screen_lparam(hwnd, point))?;
        pause(30);
    }
    Ok(pointer_result(
        target,
        hwnd,
        point,
        json!({ "direction": direction, "amount": amount }),
    ))
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

    // A hidden or fully covered page paints no frames, and Chromium drops
    // every pointer move of a drag then (see Peek). Only a Chromium
    // top-level window (Edge, Electron) tracks its own occlusion like that.
    // A WebView2 control inside another app's window (Teams) is shown and
    // hidden by its host and keeps painting when parked — and making its
    // host layered would stop it painting instead (both measured).
    let occlusion_tracked = class_name(target.window).starts_with("Chrome_WidgetWin");
    let peek = if target.web && occlusion_tracked { Peek::begin(target) } else { None };
    let (from, to) = match &peek {
        Some(peek) => (peek.offset(target, from), peek.offset(target, to)),
        None => (from, to),
    };

    // Every message of a drag goes to the window pressed on: that is the
    // window that would hold mouse capture for a real drag.
    let hwnd = pointer_window(target, from);
    let outcome = ensure_client_area(target, hwnd, from).and_then(|()| {
        post(hwnd, WM_MOUSEMOVE, 0, client_lparam(hwnd, from))?;
        post(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, client_lparam(hwnd, from))?;
        const STEPS: i32 = 14;
        for step in 1..=STEPS {
            let point = POINT {
                x: from.x + (to.x - from.x) * step / STEPS,
                y: from.y + (to.y - from.y) * step / STEPS,
            };
            pause(24);
            if let Err(stopped) = interrupted() {
                // Let go of the button rather than leave the app mid-drag.
                let _ = post(hwnd, WM_LBUTTONUP, 0, client_lparam(hwnd, point));
                return Err(stopped);
            }
            post(hwnd, WM_MOUSEMOVE, MK_LBUTTON, client_lparam(hwnd, point))?;
            target.emit_pointer(emit, point, "drag");
        }
        pause(60);
        post(hwnd, WM_LBUTTONUP, 0, client_lparam(hwnd, to))
    });
    drop(peek);
    outcome?;
    target.emit_pointer(emit, to, "click");
    let (x, y) = target.screenshot_point(to);
    Ok(pointer_result(target, hwnd, from, json!({ "to": { "x": x, "y": y } })))
}

/// Whether any part of `window` can be seen: sampled with `WindowFromPoint`
/// across its frame, since a window counts as occluded by Chromium only when
/// nothing of it shows.
fn partly_visible(window: HWND) -> bool {
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
struct Peek {
    window: HWND,
    /// Dropped after `Peek::drop` has run: the window turns opaque again
    /// last, once it is back in place.
    see_through: SeeThrough,
    was_topmost: bool,
    /// The window just above it, to slot it back under afterwards.
    above: Option<HWND>,
    repark: bool,
    session_id: String,
}

impl Peek {
    fn begin(target: &Target) -> Option<Self> {
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
            Some(Self { window, see_through, was_topmost, above, repark, session_id: target.session_id.clone() })
        }
    }

    fn offset(&self, target: &Target, point: POINT) -> POINT {
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
        // `see_through` is dropped next, restoring the window's own style.
    }
}

/// A window made fully transparent and click-through (alpha 1/255,
/// `WS_EX_LAYERED | WS_EX_TRANSPARENT`) until this is dropped.
///
/// A window that was layered already keeps its own opacity or colour key:
/// putting the style back alone left it at alpha 1 — all but invisible for
/// good.
struct SeeThrough {
    window: HWND,
    ex_style: isize,
    /// The window's own layered attributes, when it had some.
    layered: Option<(COLORREF, u8, LAYERED_WINDOW_ATTRIBUTES_FLAGS)>,
}

impl SeeThrough {
    /// `None` for a layered window without attributes to read — one drawn
    /// with `UpdateLayeredWindow`, whose drawing setting any would change.
    fn apply(window: HWND) -> Option<Self> {
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

// ── Keyboard input (posted, background) ─────────────────────────────────

thread_local! {
    /// The child window each session last clicked, used when the app's
    /// thread reports no keyboard focus of its own.
    static LAST_INPUT: RefCell<HashMap<String, isize>> = RefCell::new(HashMap::new());
}

fn remember_input_window(session_id: &str, hwnd: HWND) {
    LAST_INPUT.with(|last| {
        last.borrow_mut()
            .insert(session_id.to_string(), hwnd.0 as isize);
    });
}

fn belongs_to(target: &Target, hwnd: HWND) -> bool {
    if hwnd.0.is_null() || !unsafe { IsWindow(Some(hwnd)) }.as_bool() {
        return false;
    }
    let root = unsafe { GetAncestor(hwnd, GA_ROOT) };
    root == target.window || root == target.top
}

/// The window keystrokes should go to: the app thread's own focus (tracked
/// per thread even while the app is in the background), else the last
/// window the agent clicked, else the window itself.
fn keyboard_target(target: &Target) -> HWND {
    let thread = unsafe { GetWindowThreadProcessId(target.window, None) };
    let mut info = GUITHREADINFO {
        cbSize: std::mem::size_of::<GUITHREADINFO>() as u32,
        ..Default::default()
    };
    if unsafe { GetGUIThreadInfo(thread, &mut info) }.is_ok() && belongs_to(target, info.hwndFocus) {
        return info.hwndFocus;
    }
    let last = LAST_INPUT.with(|last| last.borrow().get(&target.session_id).copied());
    if let Some(raw) = last {
        let hwnd = to_hwnd(raw);
        if belongs_to(target, hwnd) {
            return hwnd;
        }
    }
    target.window
}

fn type_text(emit: &dyn Fn(Value), target: &Target, params: &Value) -> Result<Value, String> {
    let text = params
        .get("text")
        .and_then(Value::as_str)
        .ok_or("type needs text.")?;
    if text.chars().count() > MAX_TYPE_CHARS {
        return Err(format!("type accepts at most {MAX_TYPE_CHARS} characters per call."));
    }
    if params.get("ref").is_some() {
        // Put the caret in the field first, the way a person would.
        click(emit, target, &json!({ "ref": params["ref"] }))?;
        pause(60);
    }
    if target.web {
        // The field named by ref, else the one the agent last clicked.
        let field = match params.get("ref").and_then(Value::as_str) {
            Some(reference) => Some(element_for(target, reference)?),
            None => LAST_EDITABLE.with(|last| last.borrow().get(&target.session_id).cloned()),
        };
        return web_fill(target, field.as_ref(), text, false);
    }
    let delay = params
        .get("delay_ms")
        .and_then(Value::as_u64)
        .unwrap_or(DEFAULT_TYPE_DELAY_MS)
        .min(200);
    let hwnd = keyboard_target(target);
    let thread = unsafe { GetWindowThreadProcessId(hwnd, None) };
    // A Tab moves on to another control, so only text without one can be
    // looked for in the field it started in.
    let field = if text.contains('\t') { None } else { readable_field(hwnd) };
    let before = field.as_ref().and_then(field_value);
    let press = |name: &str| {
        let combo = KeyCombo { ctrl: false, alt: false, shift: false, win: false, cmd: false, key: name.into() };
        post_key(hwnd, thread, &combo, 1)
    };
    let mut previous = 0u16;
    for unit in text.encode_utf16() {
        let unit = match unit {
            // "\r\n" is one Enter; a lone "\n" is Enter too.
            0x0A if previous == 0x0D => {
                previous = unit;
                continue;
            }
            0x0A => 0x0D,
            other => other,
        };
        previous = unit;
        interrupted()?;
        match unit {
            // Enter and Tab as real key presses: dialogs, WPF, Qt and Java
            // act on the key-down (the default button, focus moving on), and
            // an edit control still gets its character when the app
            // translates the key as it does a typed one.
            0x0D => press("enter")?,
            0x09 => press("tab")?,
            other => post(hwnd, WM_CHAR, other as usize, LPARAM(1))?,
        }
        if delay > 0 {
            pause(delay);
        }
    }
    let mut result = json!({
        "typed_chars": text.chars().count(),
        "delivered_to": class_name(hwnd),
        "delivered_via": "keyboard",
        "window": window_title(target.window),
    });
    if let (Some(field), Some(before)) = (&field, &before) {
        // The keys are posted, so give the app a moment to take them in.
        pause(150);
        match field_value(field) {
            Some(after) if typed_landed(before, &after, text) => result["confirmed"] = json!(true),
            // An Enter may have submitted and cleared the field (a chat box)
            // or closed its dialog, so only text without one proves a miss.
            Some(_) if !text.contains(['\r', '\n']) => {
                result["confirmed"] = json!(false);
                // Never retyped: the letters may be there out of order, and
                // typing again would add them twice.
                result["note"] = json!(
                    "The field does not show the text as typed: letters may be missing or out of order. Check with snapshot before typing again, then correct it (select the text and retype, or set_value)."
                );
            }
            _ => {}
        }
    }
    Ok(result)
}

/// The control keys go to, when it reports its text through UI Automation
/// and is not a password field. A field holding a whole large document is
/// left unread: reading it twice per `type` would cost more than it tells.
fn readable_field(hwnd: HWND) -> Option<IUIAutomationElement> {
    let element = unsafe { automation().ok()?.ElementFromHandle(hwnd) }.ok()?;
    if unsafe { element.CurrentIsPassword() }.map(|password| password.as_bool()).unwrap_or(true) {
        return None;
    }
    let length = field_value(&element)?.len();
    (length <= 200_000).then_some(element)
}

/// Whether text typed into a field shows up in it: the field changed and
/// holds the text, line breaks and runs of spaces aside (an edit control
/// keeps "\r\n", a rich edit "\r", a single-line field none).
fn typed_landed(before: &str, after: &str, text: &str) -> bool {
    let wanted = squash(text);
    after != before && (wanted.is_empty() || squash(after).contains(&wanted))
}

fn resolve_key(name: &str) -> Option<(VIRTUAL_KEY, bool)> {
    let vk = match name.to_lowercase().as_str() {
        "a" => VK_A, "b" => VK_B, "c" => VK_C, "d" => VK_D, "e" => VK_E, "f" => VK_F,
        "g" => VK_G, "h" => VK_H, "i" => VK_I, "j" => VK_J, "k" => VK_K, "l" => VK_L,
        "m" => VK_M, "n" => VK_N, "o" => VK_O, "p" => VK_P, "q" => VK_Q, "r" => VK_R,
        "s" => VK_S, "t" => VK_T, "u" => VK_U, "v" => VK_V, "w" => VK_W, "x" => VK_X,
        "y" => VK_Y, "z" => VK_Z,
        "0" => VK_0, "1" => VK_1, "2" => VK_2, "3" => VK_3, "4" => VK_4,
        "5" => VK_5, "6" => VK_6, "7" => VK_7, "8" => VK_8, "9" => VK_9,
        "f1" => VK_F1, "f2" => VK_F2, "f3" => VK_F3, "f4" => VK_F4, "f5" => VK_F5,
        "f6" => VK_F6, "f7" => VK_F7, "f8" => VK_F8, "f9" => VK_F9, "f10" => VK_F10,
        "f11" => VK_F11, "f12" => VK_F12,
        "return" | "enter" => VK_RETURN,
        "escape" | "esc" => VK_ESCAPE,
        "tab" => VK_TAB,
        "backspace" | "back" => VK_BACK,
        "space" | " " => VK_SPACE,
        "delete" | "del" => VK_DELETE,
        "insert" | "ins" => VK_INSERT,
        "home" => VK_HOME,
        "end" => VK_END,
        "pageup" | "pgup" => VK_PRIOR,
        "pagedown" | "pgdn" => VK_NEXT,
        "up" | "arrowup" => VK_UP,
        "down" | "arrowdown" => VK_DOWN,
        "left" | "arrowleft" => VK_LEFT,
        "right" | "arrowright" => VK_RIGHT,
        "menu" | "apps" | "contextmenu" => VK_APPS,
        ";" => VK_OEM_1, "=" | "plus" => VK_OEM_PLUS, "," => VK_OEM_COMMA,
        "-" | "minus" => VK_OEM_MINUS, "." => VK_OEM_PERIOD, "/" => VK_OEM_2,
        "`" => VK_OEM_3, "[" => VK_OEM_4, "\\" => VK_OEM_5, "]" => VK_OEM_6, "'" => VK_OEM_7,
        "numpadadd" => VK_ADD, "numpadsubtract" => VK_SUBTRACT,
        "numpadmultiply" => VK_MULTIPLY, "numpaddivide" => VK_DIVIDE,
        "numpaddecimal" => VK_DECIMAL,
        "printscreen" | "prtsc" => VK_SNAPSHOT,
        "scrolllock" => VK_SCROLL,
        "pause" => VK_PAUSE,
        "capslock" | "caps" => VK_CAPITAL,
        "numlock" => VK_NUMLOCK,
        // A modifier on its own: Alt alone opens a Win32 menu bar.
        "alt" => VK_MENU,
        "ctrl" | "control" => VK_CONTROL,
        "shift" => VK_SHIFT,
        name if name.len() == 7 && name.starts_with("numpad") => {
            let digit = name.as_bytes()[6];
            if !digit.is_ascii_digit() {
                return None;
            }
            // VK_NUMPAD0 … VK_NUMPAD9.
            VIRTUAL_KEY(0x60 + u16::from(digit - b'0'))
        }
        name if name.starts_with('f') && matches!(name[1..].parse::<u16>(), Ok(13..=24)) => {
            // VK_F13 … VK_F24.
            VIRTUAL_KEY(0x7C + name[1..].parse::<u16>().unwrap_or(13) - 13)
        }
        other => {
            // Any other single character: ask the keyboard layout.
            let mut chars = other.chars();
            let (Some(ch), None) = (chars.next(), chars.next()) else {
                return None;
            };
            let mut units = [0u16; 2];
            if ch.encode_utf16(&mut units).len() != 1 {
                return None;
            }
            let scan = unsafe { VkKeyScanW(units[0]) };
            if scan == -1 {
                return None;
            }
            let needs_shift = (scan as u16 >> 8) & 1 == 1;
            return Some((VIRTUAL_KEY(scan as u16 & 0xff), needs_shift));
        }
    };
    Some((vk, false))
}

fn is_extended(vk: VIRTUAL_KEY) -> bool {
    matches!(
        vk,
        VK_UP | VK_DOWN | VK_LEFT | VK_RIGHT | VK_HOME | VK_END | VK_PRIOR | VK_NEXT
            | VK_INSERT | VK_DELETE | VK_DIVIDE | VK_NUMLOCK | VK_RCONTROL | VK_RMENU | VK_APPS
    )
}

fn key_lparam(vk: VIRTUAL_KEY, up: bool, alt_context: bool) -> LPARAM {
    let scan = unsafe { MapVirtualKeyW(u32::from(vk.0), MAPVK_VK_TO_VSC) } & 0xff;
    let mut value: u32 = 1 | (scan << 16);
    if is_extended(vk) {
        value |= 1 << 24;
    }
    if alt_context {
        value |= 1 << 29;
    }
    if up {
        value |= (1 << 30) | (1 << 31);
    }
    LPARAM(value as i32 as isize)
}

/// Hold modifiers in the app thread's key-state table while `post` runs.
fn with_modifiers(thread: u32, combo: &KeyCombo, post: impl FnOnce() -> Result<(), String>) -> Result<(), String> {
    let mut keys = Vec::new();
    if combo.ctrl {
        keys.extend([VK_CONTROL, VK_LCONTROL]);
    }
    if combo.shift {
        keys.extend([VK_SHIFT, VK_LSHIFT]);
    }
    if combo.alt {
        keys.extend([VK_MENU, VK_LMENU]);
    }
    with_held_keys(thread, &keys, post)
}

/// Mark `keys` as held in the app thread's key-state table while `post` runs.
///
/// Apps read Ctrl/Shift — and whether a mouse button is still down — with
/// `GetKeyState`, which posted messages do not update. Attaching to the app's
/// input queue shares its key-state table, so setting it here is what the app
/// sees, without pressing a real key or button and without moving focus. The
/// table is restored before detaching.
fn with_held_keys(thread: u32, keys: &[VIRTUAL_KEY], post: impl FnOnce() -> Result<(), String>) -> Result<(), String> {
    let me = unsafe { GetCurrentThreadId() };
    let attached = thread != me && unsafe { AttachThreadInput(me, thread, true) }.as_bool();
    if thread != me && !attached {
        // Without the shared key state the app would read the keys without
        // their modifiers: ctrl+s would type an "s". Say so instead.
        return Err("Windows would not let EvoFlux hold Ctrl/Shift/Alt for this app, so the shortcut was not sent. Look for the command as a button or menu item (snapshot or find) and invoke it instead.".into());
    }
    let mut saved = [0u8; 256];
    let have_state = unsafe { GetKeyboardState(&mut saved) }.is_ok();
    if have_state {
        let mut state = saved;
        for key in keys {
            state[key.0 as usize] |= 0x80;
        }
        let _ = unsafe { SetKeyboardState(&state) };
    }
    let outcome = post();
    // Give the app's message loop time to read the messages while the keys
    // are still held.
    pause(90);
    if have_state {
        let _ = unsafe { SetKeyboardState(&saved) };
    }
    if attached {
        let _ = unsafe { AttachThreadInput(me, thread, false) };
    }
    outcome
}

fn press_key(target: &Target, params: &Value) -> Result<Value, String> {
    let spec = params
        .get("key")
        .and_then(Value::as_str)
        .ok_or("key needs a key name such as Enter or ctrl+s.")?;
    let combo = parse_key_combo(spec)?;
    if let Some(reason) = blocked_combo_reason(&combo) {
        return Err(format!("Refused {spec}: {reason}."));
    }
    let repeat = params.get("repeat").and_then(Value::as_u64).unwrap_or(1).clamp(1, 50);
    // Chromium reads keys on its top-level window and routes them to the
    // page's focused element itself.
    let hwnd = if target.web {
        chromium_input_window(target, None)
    } else {
        keyboard_target(target)
    };
    let thread = unsafe { GetWindowThreadProcessId(hwnd, None) };
    post_key(hwnd, thread, &combo, repeat)?;
    if moves_focus(&combo) {
        forget_editable(&target.session_id);
    }
    Ok(json!({
        "key": spec,
        "repeat": repeat,
        "delivered_to": class_name(hwnd),
        "window": window_title(target.window),
    }))
}

/// Post one key chord `repeat` times to `hwnd`, holding its modifiers in the
/// owning thread's key state (see [`with_modifiers`]).
fn post_key(hwnd: HWND, thread: u32, combo: &KeyCombo, repeat: u64) -> Result<(), String> {
    let mut combo = combo.clone();
    let (vk, needs_shift) =
        resolve_key(&combo.key).ok_or_else(|| format!("Unknown key name {:?}.", combo.key))?;
    combo.shift |= needs_shift;
    // Alt without Ctrl is a menu/system shortcut, which Windows delivers as
    // WM_SYSKEY* with the context bit set — and so are F10 and Alt pressed
    // on its own, the keys that open a menu bar.
    let system = (combo.alt && !combo.ctrl) || vk == VK_F10 || vk == VK_MENU;
    // The context bit says Alt is down; for Alt itself too.
    let alt_context = combo.alt || vk == VK_MENU;
    let (down, up) = if system {
        (WM_SYSKEYDOWN, WM_SYSKEYUP)
    } else {
        (WM_KEYDOWN, WM_KEYUP)
    };
    let modifiers: Vec<VIRTUAL_KEY> = [
        (combo.ctrl, VK_CONTROL),
        (combo.shift, VK_SHIFT),
        (combo.alt, VK_MENU),
    ]
    .into_iter()
    .filter_map(|(held, key)| held.then_some(key))
    .collect();

    let send = || -> Result<(), String> {
        for key in &modifiers {
            let message = if system { WM_SYSKEYDOWN } else { WM_KEYDOWN };
            post(hwnd, message, key.0 as usize, key_lparam(*key, false, combo.alt))?;
        }
        for _ in 0..repeat {
            // Stopping between presses still releases the modifiers below.
            if interrupted().is_err() {
                break;
            }
            post(hwnd, down, vk.0 as usize, key_lparam(vk, false, alt_context))?;
            pause(20);
            // Releasing Alt itself clears the context bit, as a real key-up does.
            post(hwnd, up, vk.0 as usize, key_lparam(vk, true, alt_context && vk != VK_MENU))?;
            pause(20);
        }
        for key in modifiers.iter().rev() {
            let message = if system && *key == VK_MENU { WM_SYSKEYUP } else { WM_KEYUP };
            post(hwnd, message, key.0 as usize, key_lparam(*key, true, combo.alt && *key != VK_MENU))?;
        }
        interrupted()
    };
    if modifiers.is_empty() {
        send()
    } else {
        with_modifiers(thread, &combo, send)
    }
}

// ── UI Automation ───────────────────────────────────────────────────────

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

/// Activate a Chromium window's accessibility and wait (up to ~4 s) until a
/// render host's page tree has content.
fn wait_for_page_tree(window: HWND) {
    let Ok(automation) = automation() else {
        return;
    };
    let Ok(walker) = (unsafe { automation.ControlViewWalker() }) else {
        return;
    };
    for _ in 0..20 {
        let hosts = activate_chromium_accessibility(window);
        let ready = hosts.iter().any(|host| {
            unsafe { automation.ElementFromHandle(*host) }
                .and_then(|root| unsafe { walker.GetFirstChildElement(&root) })
                .and_then(|document| unsafe { walker.GetFirstChildElement(&document) })
                .is_ok()
        });
        // No render host at all (a composition-hosted WebView2 such as new
        // Teams): its tree hangs off the window itself; nothing to wait for.
        if ready || hosts.is_empty() {
            return;
        }
        pause(200);
    }
}

/// Where UI Automation walks start for this window: the window itself, then
/// each Chromium render host inside it (see [`activate_chromium_accessibility`]).
fn automation_roots(automation: &IUIAutomation, window: HWND) -> Result<Vec<IUIAutomationElement>, String> {
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

fn control_type_name(id: i32) -> &'static str {
    match id {
        50000 => "Button", 50001 => "Calendar", 50002 => "CheckBox", 50003 => "ComboBox",
        50004 => "Edit", 50005 => "Hyperlink", 50006 => "Image", 50007 => "ListItem",
        50008 => "List", 50009 => "Menu", 50010 => "MenuBar", 50011 => "MenuItem",
        50012 => "ProgressBar", 50013 => "RadioButton", 50014 => "ScrollBar",
        50015 => "Slider", 50016 => "Spinner", 50017 => "StatusBar", 50018 => "Tab",
        50019 => "TabItem", 50020 => "Text", 50021 => "ToolBar", 50022 => "ToolTip",
        50023 => "Tree", 50024 => "TreeItem", 50025 => "Custom", 50026 => "Group",
        50027 => "Thumb", 50028 => "DataGrid", 50029 => "DataItem", 50030 => "Document",
        50031 => "SplitButton", 50032 => "Window", 50033 => "Pane", 50034 => "Header",
        50035 => "HeaderItem", 50036 => "Table", 50037 => "TitleBar", 50038 => "Separator",
        50039 => "SemanticZoom", 50040 => "AppBar",
        _ => "Element",
    }
}

/// Containers that carry no meaning of their own when unnamed. They are
/// walked through but not listed, which keeps a snapshot readable.
fn is_structural(role: &str) -> bool {
    matches!(role, "Pane" | "Group" | "Custom" | "Element" | "Window" | "TitleBar" | "ScrollBar" | "Thumb" | "Separator")
}

fn bstr(value: windows::core::Result<BSTR>) -> String {
    value.map(|text| text.to_string()).unwrap_or_default()
}

fn element_value(element: &IUIAutomationElement, role: &str) -> Option<String> {
    if !matches!(role, "Edit" | "ComboBox" | "Document" | "Spinner" | "Slider") {
        return None;
    }
    let pattern = unsafe { element.GetCurrentPattern(UIA_ValuePatternId) }.ok()?;
    let value: IUIAutomationValuePattern = pattern.cast().ok()?;
    let text = bstr(unsafe { value.CurrentValue() });
    (!text.is_empty()).then_some(text)
}

fn toggle_state(element: &IUIAutomationElement, role: &str) -> Option<bool> {
    if !matches!(role, "CheckBox" | "Button" | "MenuItem" | "RadioButton") {
        return None;
    }
    let pattern = unsafe { element.GetCurrentPattern(UIA_TogglePatternId) }.ok()?;
    let toggle: IUIAutomationTogglePattern = pattern.cast().ok()?;
    unsafe { toggle.CurrentToggleState() }.ok().map(|state| state == ToggleState_On)
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
    walker: IUIAutomationTreeWalker,
    target: &'a Target,
    refs: &'a mut SessionRefs,
    /// The window the root being walked belongs to.
    root_window: HWND,
    max_depth: u32,
    max_elements: usize,
    /// Only list elements matching this (lower-cased) text; `None` lists all.
    query: Option<String>,
    lines: Vec<String>,
    visited: usize,
}

impl Walk<'_> {
    fn element_line(&mut self, element: &IUIAutomationElement, depth: u32) -> bool {
        let role = unsafe { element.CurrentControlType() }
            .map(|id| control_type_name(id.0))
            .unwrap_or("Element");
        let name = bstr(unsafe { element.CurrentName() });
        let rect = unsafe { element.CurrentBoundingRectangle() }.unwrap_or_default();
        // Judged against the window rather than IsOffscreen: a parked window
        // is entirely off-screen, yet every control in it is usable. Elements
        // scrolled out of the window are still skipped.
        let frame = &self.target.frame;
        if rect.right <= frame.left
            || rect.left >= frame.right
            || rect.bottom <= frame.top
            || rect.top >= frame.bottom
        {
            return false;
        }
        let listed = match &self.query {
            Some(query) => {
                let automation_id = bstr(unsafe { element.CurrentAutomationId() });
                name.to_lowercase().contains(query)
                    || automation_id.to_lowercase().contains(query)
                    || role.to_lowercase() == *query
            }
            None => !(is_structural(role) && name.trim().is_empty()),
        };
        if listed && rect.right > rect.left && rect.bottom > rect.top {
            let reference = format!("e{}", NEXT_REF.fetch_add(1, Ordering::Relaxed) + 1);
            self.refs
                .elements
                .insert(reference.clone(), (element.clone(), self.root_window.0 as isize));
            let (x, y) = self.target.screenshot_point(POINT { x: rect.left, y: rect.top });
            let width = (f64::from(rect.right - rect.left) * self.target.scale).round() as i64;
            let height = (f64::from(rect.bottom - rect.top) * self.target.scale).round() as i64;
            let indent = if self.query.is_some() { 0 } else { depth as usize };
            let mut line = format!("{}- {role}", "  ".repeat(indent.min(24)));
            if !name.trim().is_empty() {
                line.push_str(&format!(" \"{}\"", truncate(&name, 120)));
            }
            if let Some(value) = element_value(element, role) {
                line.push_str(&format!(" value=\"{}\"", truncate(&value, 200)));
            }
            if let Some(on) = toggle_state(element, role) {
                line.push_str(if on { " [checked]" } else { " [unchecked]" });
            }
            if !unsafe { element.CurrentIsEnabled() }.map(|on| on.as_bool()).unwrap_or(true) {
                line.push_str(" [disabled]");
            }
            line.push_str(&format!(" [ref={reference}] @{x},{y} {width}x{height}"));
            self.lines.push(line);
        }
        listed
    }

    fn walk(&mut self, element: &IUIAutomationElement, depth: u32) {
        if depth > self.max_depth || self.lines.len() >= self.max_elements || self.visited > 20_000 {
            return;
        }
        self.visited += 1;
        let listed = self.element_line(element, depth);
        let child_depth = if listed { depth + 1 } else { depth };
        let Ok(mut child) = (unsafe { self.walker.GetFirstChildElement(element) }) else {
            return;
        };
        loop {
            self.walk(&child, child_depth);
            if self.lines.len() >= self.max_elements {
                return;
            }
            match unsafe { self.walker.GetNextSiblingElement(&child) } {
                Ok(next) => child = next,
                Err(_) => return,
            }
        }
    }
}

fn walk_window(target: &Target, query: Option<String>, max_depth: u32, max_elements: usize, reset: bool) -> Result<(Vec<String>, bool), String> {
    let automation = automation()?;
    // Open menus and dropdowns first: they are on top, and what the agent
    // most likely wants next.
    let mut roots = Vec::new();
    for popup in &target.popups {
        if let Ok(element) = unsafe { automation.ElementFromHandle(*popup) } {
            roots.push((element, *popup));
        }
    }
    roots.extend(
        automation_roots(&automation, target.window)?
            .into_iter()
            .map(|root| (root, target.window)),
    );
    let walker = unsafe { automation.ControlViewWalker() }
        .map_err(|error| format!("UI Automation walker unavailable: {error}"))?;
    REFS.with(|refs| {
        let mut refs = refs.borrow_mut();
        let session_refs = refs.entry(target.session_id.clone()).or_default();
        if reset {
            session_refs.elements.clear();
        }
        let mut walk = Walk {
            walker,
            target,
            refs: session_refs,
            root_window: target.window,
            max_depth,
            max_elements,
            query,
            lines: Vec::new(),
            visited: 0,
        };
        for (root, window) in &roots {
            walk.root_window = *window;
            walk.walk(root, 0);
        }
        let truncated = walk.lines.len() >= max_elements;
        Ok((walk.lines, truncated))
    })
}

fn snapshot(target: &Target, params: &Value) -> Result<Value, String> {
    let max_depth = params.get("max_depth").and_then(Value::as_u64).unwrap_or(30).clamp(1, 80) as u32;
    let max_elements = params.get("max_elements").and_then(Value::as_u64).unwrap_or(400).clamp(10, 2000) as usize;
    let (lines, truncated) = walk_window(target, None, max_depth, max_elements, true)?;
    let (width, height) = target.screenshot_size();
    let mut text = format!(
        "UI of {} — \"{}\" (coordinates are screenshot pixels of a {width}x{height} screenshot)\n",
        target.app,
        window_title(target.window)
    );
    if lines.is_empty() {
        text.push_str("(This app exposes no accessibility tree; use screenshot and coordinates.)");
    } else {
        text.push_str(&lines.join("\n"));
    }
    if truncated {
        text.push_str("\n(Truncated: use find to search for a specific control.)");
    }
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
    let (lines, _) = walk_window(target, Some(query.clone()), 60, limit, false)?;
    Ok(Value::String(if lines.is_empty() {
        format!("No control matching \"{query}\" in {}.", target.app)
    } else {
        lines.join("\n")
    }))
}

/// The element a ref names, if it can still be acted on: it lives in the
/// window the agent is driving now (not the main window behind a modal
/// dialog, nor a dialog or menu since closed), and the app has not
/// destroyed it.
fn element_for(target: &Target, reference: &str) -> Result<IUIAutomationElement, String> {
    let reference = reference.trim().trim_start_matches("ref=").trim_start_matches('@');
    let (element, listed_in) = REFS
        .with(|refs| {
            refs.borrow()
                .get(&target.session_id)
                .and_then(|session| session.elements.get(reference).cloned())
        })
        .ok_or_else(|| format!("Unknown ref {reference:?}. Take a new snapshot or find, then use a ref from it."))?;
    let listed_in = to_hwnd(listed_in);
    if listed_in != target.window && !target.popups.contains(&listed_in) {
        return Err(if unsafe { IsWindow(Some(listed_in)) }.as_bool() {
            format!(
                "{reference} is in \"{}\", which is waiting on the dialog \"{}\". Take a new snapshot and use the dialog's controls first.",
                window_title(listed_in),
                window_title(target.window)
            )
        } else {
            format!("{reference} was in a dialog or menu that has closed. Take a new snapshot or find.")
        });
    }
    if unsafe { element.CurrentProcessId() }.is_err() {
        return Err(format!(
            "{reference} no longer exists: the app removed or replaced that control. Take a new snapshot or find."
        ));
    }
    Ok(element)
}

fn element_center(element: &IUIAutomationElement) -> Option<POINT> {
    let rect = unsafe { element.CurrentBoundingRectangle() }.ok()?;
    (rect.right > rect.left && rect.bottom > rect.top).then_some(POINT {
        x: (rect.left + rect.right) / 2,
        y: (rect.top + rect.bottom) / 2,
    })
}

/// The UI Automation action that "clicking" an element means.
enum UiAction {
    Invoke(IUIAutomationInvokePattern),
    Toggle(IUIAutomationTogglePattern),
    Select(IUIAutomationSelectionItemPattern),
    ExpandCollapse(IUIAutomationExpandCollapsePattern),
    Default(IUIAutomationLegacyIAccessiblePattern),
}

fn pattern<T: Interface>(element: &IUIAutomationElement, id: windows::Win32::UI::Accessibility::UIA_PATTERN_ID) -> Option<T> {
    unsafe { element.GetCurrentPattern(id) }.ok()?.cast().ok()
}

fn ui_action_for(element: &IUIAutomationElement) -> Option<UiAction> {
    if let Some(p) = pattern(element, UIA_InvokePatternId) {
        return Some(UiAction::Invoke(p));
    }
    if let Some(p) = pattern(element, UIA_TogglePatternId) {
        return Some(UiAction::Toggle(p));
    }
    if let Some(p) = pattern(element, UIA_SelectionItemPatternId) {
        return Some(UiAction::Select(p));
    }
    if let Some(p) = pattern(element, UIA_ExpandCollapsePatternId) {
        return Some(UiAction::ExpandCollapse(p));
    }
    // Every element has the legacy pattern; only one that names a default
    // action (Chromium reports "click" for clickable page elements) counts.
    let legacy: IUIAutomationLegacyIAccessiblePattern = pattern(element, UIA_LegacyIAccessiblePatternId)?;
    let default_action = bstr(unsafe { legacy.CurrentDefaultAction() });
    (!default_action.trim().is_empty()).then_some(UiAction::Default(legacy))
}

/// How long an action may take before the app is taken to be busy with it.
const UI_ACTION_WAIT: Duration = Duration::from_millis(1500);

const STILL_RUNNING_NOTE: &str = "The app is still handling this, most likely in a dialog it opened. Take a snapshot to see it; do not repeat the action.";

/// A Win32 push button (a WinForms one included): the window itself, when
/// `element` is one.
fn win32_push_button(element: &IUIAutomationElement) -> Option<HWND> {
    let hwnd = unsafe { element.CurrentNativeWindowHandle() }.ok()?;
    if hwnd.0.is_null() {
        return None;
    }
    let class = class_name(hwnd).to_lowercase();
    // WinForms draws its buttons itself (BS_OWNERDRAW on top of the kind),
    // so the style does not tell them apart; a check box among them offers
    // Toggle rather than the Invoke this is used for.
    if class.starts_with("windowsforms10.button") {
        return Some(hwnd);
    }
    // Push, default, owner-drawn, split and command-link buttons; not check
    // boxes, radio buttons or group boxes, which share the class.
    let kind = unsafe { GetWindowLongPtrW(hwnd, GWL_STYLE) } & 0xF;
    (class == "button" && matches!(kind, 0x0 | 0x1 | 0xB..=0xF)).then_some(hwnd)
}

/// Perform `action` on `element`. Returns the pattern used, and whether the
/// app is still busy with it.
///
/// A button that opens a modal dialog does not return from Invoke until the
/// dialog closes (WinForms clicks it synchronously), and meanwhile every
/// other UI Automation call into the app waits too, until a timeout of about
/// a minute — the click was then reported as refused, inviting a second one.
/// A Win32 push button is therefore clicked with a posted `BM_CLICK`, which
/// the app handles from its own message loop. Anything else runs on a thread
/// of its own; one still running after [`UI_ACTION_WAIT`] is left to finish
/// there and reported as delivered.
fn perform(element: &IUIAutomationElement, action: UiAction) -> windows::core::Result<(&'static str, bool)> {
    if matches!(action, UiAction::Invoke(_) | UiAction::Default(_)) {
        if let Some(button) = win32_push_button(element) {
            let posted = unsafe { PostMessageW(Some(button), BM_CLICK, WPARAM(0), LPARAM(0)) };
            return posted.map(|_| ("click_message", false));
        }
    }
    struct Movable(UiAction);
    // UI Automation objects are free-threaded; both threads are in the MTA.
    unsafe impl Send for Movable {}
    let label = match &action {
        UiAction::Invoke(_) => "invoke",
        UiAction::Toggle(_) => "toggle",
        UiAction::Select(_) => "select",
        UiAction::ExpandCollapse(_) => "expand",
        UiAction::Default(_) => "default_action",
    };
    let (done, outcome) = mpsc::channel();
    let action = Movable(action);
    let spawned = std::thread::Builder::new()
        .name("computer-app-ui-action".into())
        .spawn(move || {
            let action = action;
            unsafe {
                let _ = CoInitializeEx(None, COINIT_MULTITHREADED);
            }
            let result = perform_now(&action.0);
            drop(action);
            let _ = done.send(result);
            unsafe { CoUninitialize() };
        });
    if spawned.is_err() {
        return Err(windows::core::Error::from_win32());
    }
    match outcome.recv_timeout(UI_ACTION_WAIT) {
        Ok(result) => result.map(|used| (used, false)),
        Err(_) => Ok((label, true)),
    }
}

fn perform_now(action: &UiAction) -> windows::core::Result<&'static str> {
    unsafe {
        match action {
            UiAction::Invoke(p) => p.Invoke().map(|_| "invoke"),
            UiAction::Toggle(p) => p.Toggle().map(|_| "toggle"),
            UiAction::Select(p) => p.Select().map(|_| "select"),
            UiAction::ExpandCollapse(p) => {
                let state = p.CurrentExpandCollapseState().unwrap_or(ExpandCollapseState_Collapsed);
                if state == ExpandCollapseState_Collapsed || state == ExpandCollapseState_PartiallyExpanded {
                    p.Expand().map(|_| "expand")
                } else {
                    p.Collapse().map(|_| "collapse")
                }
            }
            UiAction::Default(p) => p.DoDefaultAction().map(|_| "default_action"),
        }
    }
}

fn is_editable(element: &IUIAutomationElement) -> bool {
    pattern::<IUIAutomationValuePattern>(element, UIA_ValuePatternId)
        .map(|value| !unsafe { value.CurrentIsReadOnly() }.map(|ro| ro.as_bool()).unwrap_or(true))
        .unwrap_or(false)
}

fn contains(rect: &RECT, point: POINT) -> bool {
    rect.right > rect.left
        && rect.bottom > rect.top
        && point.x >= rect.left
        && point.x < rect.right
        && point.y >= rect.top
        && point.y < rect.bottom
}

/// The chain of elements under `point` in the attached window, outermost
/// first. Walks the window's own tree rather than asking UI Automation what
/// is on screen there: the app may be behind other windows or parked
/// off-screen, where a screen hit-test would find something else.
fn elements_at(target: &Target, point: POINT) -> Result<Vec<IUIAutomationElement>, String> {
    let automation = automation()?;
    // A popup covers whatever is under it in the window: only its own tree
    // counts there.
    let roots = match target.popup_at(point) {
        Some(popup) => automation_roots(&automation, popup)?,
        None => automation_roots(&automation, target.window)?,
    };
    let walker = unsafe { automation.ControlViewWalker() }
        .map_err(|error| format!("UI Automation walker unavailable: {error}"))?;
    // The deepest chain wins: a page's own tree (under its render host) goes
    // further down than the window frame around it.
    let chains = roots.into_iter().map(|root| chain_at(&walker, root, point));
    Ok(chains.max_by_key(Vec::len).unwrap_or_default())
}

fn chain_at(
    walker: &IUIAutomationTreeWalker,
    root: IUIAutomationElement,
    point: POINT,
) -> Vec<IUIAutomationElement> {
    let mut visited = 0usize;
    deepest_chain(walker, root, point, &mut visited)
}

/// The deepest chain of elements under `point` starting at `element`.
///
/// Every child containing the point is explored, not just the first: a
/// container that covers the whole window (a frame view, an overlay host)
/// can come before or after the one that holds the content. Among equally
/// deep chains the later sibling wins, since later siblings are drawn over
/// earlier ones — a modal or a menu covers what it was opened over.
fn deepest_chain(
    walker: &IUIAutomationTreeWalker,
    element: IUIAutomationElement,
    point: POINT,
    visited: &mut usize,
) -> Vec<IUIAutomationElement> {
    let mut best: Vec<IUIAutomationElement> = Vec::new();
    let mut child = unsafe { walker.GetFirstChildElement(&element) }.ok();
    while let Some(current) = child {
        *visited += 1;
        if *visited > 20_000 {
            break;
        }
        let rect = unsafe { current.CurrentBoundingRectangle() }.unwrap_or_default();
        let next = unsafe { walker.GetNextSiblingElement(&current) }.ok();
        if contains(&rect, point) {
            let chain = deepest_chain(walker, current, point, visited);
            if chain.len() >= best.len() {
                best = chain;
            }
        }
        child = next;
    }
    let mut chain = Vec::with_capacity(best.len() + 1);
    chain.push(element);
    chain.extend(best);
    chain
}

thread_local! {
    /// The editable element each session last clicked, where `type` goes in
    /// web content that has no keyboard focus we can address.
    static LAST_EDITABLE: RefCell<HashMap<String, IUIAutomationElement>> = RefCell::new(HashMap::new());
}

fn remember_editable(session_id: &str, element: &IUIAutomationElement) {
    LAST_EDITABLE.with(|last| {
        last.borrow_mut().insert(session_id.to_string(), element.clone());
    });
}

/// Focus went somewhere other than the remembered field — a click on a
/// button, Tab, Enter — so a `type` without a ref must go where the page's
/// focus now is, not back into that field.
fn forget_editable(session_id: &str) {
    LAST_EDITABLE.with(|last| {
        last.borrow_mut().remove(session_id);
    });
}

/// Keys that move focus to another control (or submit and close a form).
fn moves_focus(combo: &KeyCombo) -> bool {
    matches!(
        combo.key.to_lowercase().as_str(),
        "tab" | "enter" | "return" | "escape" | "esc" | "f6"
    )
}

/// `element` and its ancestors, outermost first (the order [`elements_at`]
/// returns), so callers can look for the nearest one with a capability.
fn with_ancestors(element: IUIAutomationElement) -> Vec<IUIAutomationElement> {
    let mut chain = vec![element];
    if let Ok(walker) = automation().and_then(|automation| {
        unsafe { automation.ControlViewWalker() }.map_err(|error| error.to_string())
    }) {
        while chain.len() < 64 {
            match unsafe { walker.GetParentElement(chain.last().unwrap()) } {
                Ok(parent) => chain.push(parent),
                Err(_) => break,
            }
        }
    }
    chain.reverse();
    chain
}

/// Scroll the innermost element in `chain` that can scroll that way.
/// Returns its name, or `None` when nothing there scrolls.
fn scroll_via_automation(
    chain: &[IUIAutomationElement],
    direction: &str,
    amount: i32,
) -> Result<Option<String>, String> {
    let vertical = matches!(direction, "up" | "down");
    let (horizontal_step, vertical_step) = match direction {
        "down" => (ScrollAmount_NoAmount, ScrollAmount_SmallIncrement),
        "up" => (ScrollAmount_NoAmount, ScrollAmount_SmallDecrement),
        "right" => (ScrollAmount_SmallIncrement, ScrollAmount_NoAmount),
        _ => (ScrollAmount_SmallDecrement, ScrollAmount_NoAmount),
    };
    for element in chain.iter().rev() {
        let Some(scroller) = pattern::<IUIAutomationScrollPattern>(element, UIA_ScrollPatternId) else {
            continue;
        };
        let scrollable = unsafe {
            if vertical {
                scroller.CurrentVerticallyScrollable()
            } else {
                scroller.CurrentHorizontallyScrollable()
            }
        }
        .map(|flag| flag.as_bool())
        .unwrap_or(false);
        if !scrollable {
            continue;
        }
        // Three small steps per wheel notch, like a default wheel setting.
        for _ in 0..amount * 3 {
            if unsafe { scroller.Scroll(horizontal_step, vertical_step) }.is_err() {
                break;
            }
        }
        return Ok(Some(bstr(unsafe { element.CurrentName() })));
    }
    Ok(None)
}

/// Click through UI Automation: the innermost element under the point that
/// has an action gets it. Returns `None` when nothing there has one, and the
/// caller falls back to posted mouse input.
fn click_via_automation(
    emit: &dyn Fn(Value),
    target: &Target,
    chain: &[IUIAutomationElement],
    point: POINT,
) -> Result<Option<Value>, String> {
    match chain.iter().rev().find(|element| is_editable(element)) {
        Some(editable) => remember_editable(&target.session_id, editable),
        // Clicking anything else (a button, a list item) moves focus away
        // from the field clicked before.
        None if !chain.is_empty() => forget_editable(&target.session_id),
        None => {}
    }
    for element in chain.iter().rev() {
        let Some(action) = ui_action_for(element) else {
            continue;
        };
        let name = bstr(unsafe { element.CurrentName() });
        target.travel(emit, point)?;
        target.emit_pointer(emit, point, "click");
        let (used, busy) = perform(element, action).map_err(|error| format!("\"{name}\" refused the click: {error}"))?;
        let (x, y) = target.screenshot_point(point);
        let mut result = json!({
            "pointer": { "x": x, "y": y },
            "delivered_to": name,
            "delivered_via": "ui_automation",
            "pattern": used,
            "window": window_title(target.window),
            "button": "left",
            "clicks": 1,
        });
        if busy {
            result["note"] = json!(STILL_RUNNING_NOTE);
        }
        return Ok(Some(result));
    }
    // In web content a text field has no action and posted clicks cannot
    // reach it; remembering it is what makes the next `type` land there.
    // Native apps get a real (posted) click instead, which places the caret.
    if target.web && chain.iter().any(|element| is_editable(element)) {
        target.travel(emit, point)?;
        target.emit_pointer(emit, point, "click");
        let (x, y) = target.screenshot_point(point);
        return Ok(Some(json!({
            "pointer": { "x": x, "y": y },
            "delivered_to": "text field",
            "delivered_via": "ui_automation",
            "pattern": "focus_for_typing",
            "window": window_title(target.window),
            "button": "left",
            "clicks": 1,
        })));
    }
    Ok(None)
}

fn field_value(element: &IUIAutomationElement) -> Option<String> {
    let value: IUIAutomationValuePattern = pattern(element, UIA_ValuePatternId)?;
    Some(bstr(unsafe { value.CurrentValue() }))
}

/// Compare what a field holds with what was typed, ignoring the line-break
/// and whitespace differences editors introduce.
fn squash(text: &str) -> String {
    text.split_whitespace().collect::<Vec<_>>().join(" ")
}

/// Whether typing into a web field a second time is safe: the read-back is
/// live, both reads worked, the text is not there and nothing changed at
/// all. A field that reports no value (no Value pattern, a stale element)
/// reads "unchanged" every time — retyping it only doubled the text.
fn should_retype(readback_is_live: bool, before: &Option<String>, after: &Option<String>, landed: bool) -> bool {
    readback_is_live && before.is_some() && after.is_some() && !landed && after == before
}

/// Type into a web page field the way a keyboard would.
///
/// Chromium takes characters posted to its window and delivers them to the
/// page's focused element with real `beforeinput`/`input` events — which is
/// what rich editors (the Teams compose box, anything built on React) need to
/// notice the text at all. Setting the value through UI Automation changes the
/// DOM without those events, so it is never done behind the agent's back;
/// `set_value` with `direct` asks for it explicitly.
///
/// The field's value is read back to confirm, but a hidden page may report a
/// stale value (Chromium pauses accessibility updates for it), so an
/// unconfirmed result is reported as such rather than "repaired" — writing a
/// value computed from a stale read would erase what was really typed.
///
/// Focusing through UI Automation does not activate the window; the user's
/// foreground stays put.
fn web_fill(
    target: &Target,
    field: Option<&IUIAutomationElement>,
    text: &str,
    replace: bool,
) -> Result<Value, String> {
    let before = field.and_then(field_value);
    // Keys go to the Chromium widget showing the field — for a WebView2 host
    // such as Teams that is a window of the WebView2 process, not the app's.
    let input = chromium_input_window(target, field.and_then(element_center));
    let thread = unsafe { GetWindowThreadProcessId(input, None) };
    let chord = |spec: &str| -> Result<(), String> {
        let combo = parse_key_combo(spec)?;
        post_key(input, thread, &combo, 1)
    };
    let type_once = || -> Result<(), String> {
        // A window that was never activated has never been told it has
        // focus, and Chromium then has no focused view to hand keys to — the
        // first field typed into after attaching got nothing. Tell the
        // widget first (the system's focus does not move), then focus the
        // field: the widget's own focus handling would otherwise put focus
        // back on whatever it had before.
        if unsafe { GetForegroundWindow() } != target.window {
            post(input, windows::Win32::UI::WindowsAndMessaging::WM_SETFOCUS, 0, LPARAM(0))?;
            pause(80);
        }
        // A hidden Chromium page dropped the very first keys it was sent now
        // and then; a lone Shift press types nothing and gets its input
        // pipeline going before the real keys arrive.
        post(input, WM_KEYDOWN, VK_SHIFT.0 as usize, key_lparam(VK_SHIFT, false, false))?;
        post(input, WM_KEYUP, VK_SHIFT.0 as usize, key_lparam(VK_SHIFT, true, false))?;
        pause(150);
        if let Some(field) = field {
            let _ = unsafe { field.SetFocus() };
            // Wait for the field to report focus; a hidden page may never
            // say so, hence the cap.
            for _ in 0..6 {
                pause(100);
                if unsafe { field.CurrentHasKeyboardFocus() }.map(|focused| focused.as_bool()).unwrap_or(false) {
                    break;
                }
            }
        }
        // Where the text goes: over the whole field, or after what is there.
        chord(if replace { "ctrl+a" } else { "ctrl+end" })?;
        let mut previous = 0u16;
        for unit in text.encode_utf16() {
            interrupted()?;
            match unit {
                0x0A if previous == 0x0D => {}
                // A line break in a chat box must not press Enter: that sends.
                0x0A | 0x0D => chord("shift+enter")?,
                other => post(input, WM_CHAR, other as usize, LPARAM(1))?,
            }
            previous = unit;
            pause(4);
        }
        pause(300);
        Ok(())
    };
    type_once()?;

    let Some(field) = field else {
        return Ok(json!({
            "typed_chars": text.chars().count(),
            "delivered_to": "focused element",
            "delivered_via": "keyboard",
            "window": window_title(target.window),
        }));
    };
    let name = bstr(unsafe { field.CurrentName() });
    let landed = |after: &Option<String>| match (&before, after) {
        (_, None) => false,
        (_, Some(after)) if replace => squash(after).contains(&squash(text)),
        (Some(before), Some(after)) => {
            squash(after).contains(&squash(text)) && squash(after).len() > squash(before).len()
        }
        (None, Some(after)) => squash(after).contains(&squash(text)),
    };
    let mut after = field_value(field);
    // A parked Edge/Electron window reports stale values, so there a miss
    // proves nothing and retyping could double the text. Elsewhere the read
    // is live: a field that did not change at all never got the keys, and
    // one more attempt is safe.
    let readback_is_live = !(target.hidden && class_name(target.window).starts_with("Chrome_WidgetWin"));
    if should_retype(readback_is_live, &before, &after, landed(&after)) {
        type_once()?;
        after = field_value(field);
    }
    let confirmed = landed(&after);
    let mut result = json!({
        "typed_chars": text.chars().count(),
        "delivered_to": name,
        "delivered_via": "keyboard",
        "confirmed": confirmed,
        "window": window_title(target.window),
    });
    if after.is_none() {
        result["confirmed"] = Value::Null;
        result["note"] = json!(
            "The keys were delivered, but this field does not report its text, so it could not be checked. Take a screenshot before typing again."
        );
    } else if !confirmed && target.hidden {
        // Measured: a parked Chromium page keeps reporting the value it had
        // when it was hidden, while the page itself has the new text. Saying
        // "not confirmed" would only make the agent type it twice.
        result["confirmed"] = Value::Null;
        result["note"] = json!(
            "The keys were delivered. While the app is hidden its accessibility values and picture lag behind, so snapshot or screenshot may still show the old text."
        );
    } else if !confirmed {
        result["note"] = json!(
            "The field did not report the new text yet. Check with a screenshot before typing again; if the keys really did not arrive, use set_value with direct: true."
        );
    }
    Ok(result)
}

fn invoke(emit: &dyn Fn(Value), target: &Target, params: &Value) -> Result<Value, String> {
    let reference = params.get("ref").and_then(Value::as_str).ok_or("invoke needs a ref.")?;
    let element = element_for(target, reference)?;
    let name = bstr(unsafe { element.CurrentName() });
    let action = ui_action_for(&element).ok_or_else(|| {
        format!("{reference} (\"{name}\") has no invoke/toggle/select/expand action. Click it by ref or coordinates instead.")
    })?;
    if let Some(point) = element_center(&element) {
        target.travel(emit, point)?;
        target.emit_pointer(emit, point, "click");
    }
    if is_editable(&element) {
        remember_editable(&target.session_id, &element);
    } else {
        forget_editable(&target.session_id);
    }
    let (used, busy) = perform(&element, action)
        .map_err(|error| format!("{reference} (\"{name}\") refused the action: {error}"))?;
    let mut result = json!({ "ref": reference, "name": name, "pattern": used, "window": window_title(target.window) });
    if busy {
        result["note"] = json!(STILL_RUNNING_NOTE);
    }
    Ok(result)
}

fn set_value(emit: &dyn Fn(Value), target: &Target, params: &Value) -> Result<Value, String> {
    let reference = params.get("ref").and_then(Value::as_str).ok_or("set_value needs a ref.")?;
    let value = params.get("value").and_then(Value::as_str).ok_or("set_value needs a value.")?;
    let element = element_for(target, reference)?;
    let direct = params.get("direct").and_then(Value::as_bool).unwrap_or(false);
    // Sliders, spinners and progress-like controls take a number.
    if let Some(range) = pattern::<IUIAutomationRangeValuePattern>(&element, UIA_RangeValuePatternId) {
        if let Ok(number) = value.trim().parse::<f64>() {
            if let Some(point) = element_center(&element) {
                target.travel(emit, point)?;
                target.emit_pointer(emit, point, "click");
            }
            let (minimum, maximum) = unsafe { (range.CurrentMinimum(), range.CurrentMaximum()) };
            let clamped = match (minimum, maximum) {
                (Ok(minimum), Ok(maximum)) if maximum > minimum => number.clamp(minimum, maximum),
                _ => number,
            };
            unsafe { range.SetValue(clamped) }
                .map_err(|error| format!("{reference} refused the value: {error}"))?;
            return Ok(json!({
                "ref": reference,
                "value_chars": value.chars().count(),
                "delivered_via": "ui_automation",
                "pattern": "range_value",
                "window": window_title(target.window),
            }));
        }
    }
    if target.web && !direct {
        // Replace through the keyboard so the page sees input events (see
        // web_fill); `direct` writes the value without them.
        if let Some(point) = element_center(&element) {
            target.travel(emit, point)?;
            target.emit_pointer(emit, point, "click");
        }
        remember_editable(&target.session_id, &element);
        let mut result = web_fill(target, Some(&element), value, true)?;
        result["ref"] = json!(reference);
        result["value_chars"] = json!(value.chars().count());
        return Ok(result);
    }
    let pattern: IUIAutomationValuePattern = unsafe { element.GetCurrentPattern(UIA_ValuePatternId) }
        .ok()
        .and_then(|pattern| pattern.cast().ok())
        .ok_or_else(|| format!("{reference} does not accept a value. Click it and use type instead."))?;
    if unsafe { pattern.CurrentIsReadOnly() }.map(|ro| ro.as_bool()).unwrap_or(false) {
        return Err(format!("{reference} is read-only."));
    }
    if let Some(point) = element_center(&element) {
        target.travel(emit, point)?;
        target.emit_pointer(emit, point, "click");
    }
    unsafe { pattern.SetValue(&BSTR::from(value)) }
        .map_err(|error| format!("{reference} refused the value: {error}"))?;
    Ok(json!({ "ref": reference, "value_chars": value.chars().count(), "window": window_title(target.window) }))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn scales_points_into_a_dpi_unaware_window() {
        // A per-monitor aware window takes physical pixels as they are.
        assert_eq!(to_logical(300, 150, 1.0), (300, 150));
        // An unaware window on a 150% display (96 / 144).
        assert_eq!(to_logical(300, 150, 96.0 / 144.0), (200, 100));
        // A system-aware window (system 120 dpi) on a 144 dpi display.
        assert_eq!(to_logical(144, 72, 120.0 / 144.0), (120, 60));
    }

    #[test]
    fn tells_apps_running_above_evoflux() {
        use windows::Win32::System::Threading::GetCurrentProcess;
        let ours = integrity_level(unsafe { GetCurrentProcess() }).expect("own integrity level");
        assert!(ours >= 0x2000, "unexpected integrity level {ours:#x}");
        assert!(!runs_above_us(unsafe { GetCurrentProcessId() }));
        const MEDIUM: u32 = 0x2000;
        const HIGH: u32 = 0x3000;
        assert!(is_above(MEDIUM, Some(HIGH)), "an elevated app");
        assert!(is_above(MEDIUM, None), "a token EvoFlux may not read");
        assert!(!is_above(MEDIUM, Some(MEDIUM)));
        assert!(!is_above(HIGH, Some(HIGH)), "an elevated EvoFlux drives elevated apps");
    }

    #[test]
    fn resolves_lone_modifiers_numpad_and_high_function_keys() {
        assert_eq!(resolve_key("alt"), Some((VK_MENU, false)));
        assert_eq!(resolve_key("Ctrl"), Some((VK_CONTROL, false)));
        assert_eq!(resolve_key("shift"), Some((VK_SHIFT, false)));
        assert_eq!(resolve_key("numpad0"), Some((VIRTUAL_KEY(0x60), false)));
        assert_eq!(resolve_key("Numpad9"), Some((VIRTUAL_KEY(0x69), false)));
        assert_eq!(resolve_key("f13"), Some((VIRTUAL_KEY(0x7C), false)));
        assert_eq!(resolve_key("F24"), Some((VIRTUAL_KEY(0x87), false)));
        assert_eq!(resolve_key("f12"), Some((VK_F12, false)));
        assert_eq!(resolve_key("f25"), None);
        assert_eq!(resolve_key("numpadx"), None);
    }

    #[test]
    fn confirms_native_typing_only_when_the_text_arrived_in_order() {
        assert!(typed_landed("abc", "abc hidden ok", " hidden ok"));
        // A rich edit stores line breaks as "\r".
        assert!(typed_landed("", "one\rtwo", "one\ntwo"));
        assert!(typed_landed("ac", "abc", "b"));
        assert!(!typed_landed("abc", "abc hidden ko", " hidden ok"));
        assert!(!typed_landed("abc", "abc ihdden ok", " hidden ok"));
        assert!(!typed_landed("hidden ok", "hidden ok", "hidden ok"), "nothing changed");
    }

    #[test]
    fn retypes_only_a_readable_field_that_did_not_change() {
        let empty = Some(String::new());
        let typed = Some("hi".to_string());
        assert!(should_retype(true, &empty, &empty, false));
        // Unreadable field: both reads are None, which is not "unchanged".
        assert!(!should_retype(true, &None, &None, false));
        assert!(!should_retype(true, &empty, &None, false));
        // It changed, or it landed, or the read-back is stale.
        assert!(!should_retype(true, &empty, &typed, false));
        assert!(!should_retype(true, &typed, &typed, true));
        assert!(!should_retype(false, &empty, &empty, false));
    }
}

/// Drives a real Notepad window. Opt-in because it opens a window on the
/// desktop it runs on:
///
/// `cargo test computer_app -- --ignored --nocapture`
///
/// It launches its own minimized Notepad and never touches one that was
/// already open, and it checks the claim this module is built on: the
/// user's cursor and foreground window do not change while the agent works.
#[cfg(test)]
mod live_tests {
    use super::*;
    use std::cell::RefCell;
    use windows::Win32::UI::WindowsAndMessaging::GetCursorPos;

    fn notepad_windows() -> Vec<(u64, u32)> {
        list_windows("live-test", &json!({ "query": "notepad" }))["windows"]
            .as_array()
            .cloned()
            .unwrap_or_default()
            .iter()
            .filter(|window| window["app"].as_str().unwrap_or("").eq_ignore_ascii_case("notepad.exe"))
            .map(|window| (window["id"].as_u64().unwrap_or(0), window["pid"].as_u64().unwrap_or(0) as u32))
            .collect()
    }

    #[test]
    fn names_apps_from_their_captions() {
        assert_eq!(caption_app_name("notes.txt - Notepad").as_deref(), Some("Notepad"));
        assert_eq!(
            caption_app_name("Chat | Contoso | Microsoft Teams").as_deref(),
            Some("Microsoft Teams")
        );
        assert_eq!(caption_app_name("Calculator").as_deref(), Some("Calculator"));
        assert_eq!(caption_app_name("   ").as_deref(), None);
        assert_eq!(exe_stem("notepad.exe"), "Notepad");
    }

    #[test]
    #[ignore = "reads the local Start menu and running apps"]
    fn lists_apps_with_icons() {
        unsafe {
            let _ = CoInitializeEx(None, COINIT_MULTITHREADED);
        }
        let started = std::time::Instant::now();
        let listed = list_apps();
        let apps = listed["apps"].as_array().unwrap();
        let with_icons = apps.iter().filter(|app| app["icon"].is_string()).count();
        eprintln!("{} apps ({with_icons} with icons) in {:?}", apps.len(), started.elapsed());
        for app in apps.iter().take(12) {
            eprintln!("  {} — {} running={}", app["exe"], app["name"], app["running"]);
        }
        assert!(!apps.is_empty());
        assert!(with_icons * 2 >= apps.len(), "most apps should have an icon");
        assert!(apps.iter().all(|app| !is_protected_process_name(app["exe"].as_str().unwrap())));
    }

    fn snapshot_text(emit: &dyn Fn(Value), session: &str) -> String {
        run_action(emit, session, "snapshot", &json!({})).unwrap().as_str().unwrap().to_string()
    }

    fn ref_for(emit: &dyn Fn(Value), session: &str, query: &str) -> String {
        let found = run_action(emit, session, "find", &json!({ "query": query })).unwrap();
        let text = found.as_str().unwrap();
        let start = text.find("[ref=").unwrap_or_else(|| panic!("{query} not found:\n{text}")) + 5;
        let end = start + text[start..].find(']').unwrap();
        text[start..end].to_string()
    }

    /// The probe page's report (see the fixture), parsed from the caption.
    fn page_report(hwnd: HWND) -> HashMap<String, String> {
        window_title(hwnd)
            .split('|')
            .filter_map(|pair| pair.split_once('='))
            .map(|(key, value)| (key.to_string(), value.to_string()))
            .collect()
    }

    fn report_number(report: &HashMap<String, String>, key: &str) -> i64 {
        report.get(key).and_then(|value| value.parse().ok()).unwrap_or(0)
    }

    /// Screenshot coordinates of an element's centre, from a `find` line.
    fn centre_of(emit: &dyn Fn(Value), session: &str, query: &str) -> (i64, i64) {
        let found = run_action(emit, session, "find", &json!({ "query": query })).unwrap();
        let line = found
            .as_str()
            .unwrap()
            .lines()
            .find(|line| line.contains("[ref="))
            .unwrap_or_else(|| panic!("{query} not found: {found}"))
            .to_string();
        let at = line.rfind('@').unwrap_or_else(|| panic!("{query} has no position: {line}"));
        let (position, size) = line[at + 1..].split_once(' ').unwrap();
        let (x, y) = position.split_once(',').unwrap();
        let (width, height) = size.trim().split_once('x').unwrap();
        let number = |text: &str| text.trim().parse::<i64>().unwrap();
        (number(x) + number(width) / 2, number(y) + number(height) / 2)
    }

    const EDGE: &str = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe";

    fn probe_url() -> String {
        let page = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("tests")
            .join("fixtures")
            .join("computer_app_probe.html");
        format!("file:///{}", page.display().to_string().replace('\\', "/"))
    }

    fn edge_profile() -> std::path::PathBuf {
        std::env::temp_dir().join("evoflux-computer-app-probe")
    }

    /// Start a process that must not inherit the test's output pipes, or the
    /// harness waits on them for as long as any of its children lives.
    fn spawn_quiet(command: &mut std::process::Command) {
        command
            .stdin(std::process::Stdio::null())
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .spawn()
            .expect("start the probe host");
    }

    #[derive(Clone, Copy, Debug)]
    enum ProbeHost {
        /// Edge in app mode: Chromium's own top-level window.
        Edge,
        /// A WebView2 control inside a Win32 host window — the layout of
        /// Teams and other WebView2 apps (see [`webview2_host`]).
        WebView2,
        /// A native window with only a small WebView2 pane in a corner.
        WebView2Pane,
    }

    /// Open the probe page in `host`, attach to it (parked off-screen when
    /// `hide`), run `body`, and clean up whatever happens.
    fn with_probe_page(
        session: &str,
        host: ProbeHost,
        hide: bool,
        body: impl FnOnce(&dyn Fn(Value), HWND),
    ) {
        unsafe {
            let _ = CoInitializeEx(None, COINIT_MULTITHREADED);
        }
        match host {
            ProbeHost::Edge => spawn_quiet(
                std::process::Command::new(EDGE)
                    .arg(format!("--user-data-dir={}", edge_profile().display()))
                    .args(["--no-first-run", "--no-default-browser-check", "--new-window"])
                    .arg(format!("--app={}", probe_url())),
            ),
            // This same test binary, running only the host "test" below.
            ProbeHost::WebView2 | ProbeHost::WebView2Pane => {
                let mut command = std::process::Command::new(std::env::current_exe().unwrap());
                command
                    .args(["computer_app::win::live_tests::webview2_host", "--exact", "--ignored"])
                    .env("COMPUTER_APP_PROBE_URL", probe_url());
                if matches!(host, ProbeHost::WebView2Pane) {
                    command.env("COMPUTER_APP_PROBE_PANE", "1");
                }
                spawn_quiet(&mut command)
            }
        }

        let mut window = None;
        for _ in 0..60 {
            pause(250);
            window = list_windows(session, &json!({ "query": "probe" }))["windows"]
                .as_array()
                .and_then(|windows| windows.first().cloned());
            if window.is_some() {
                break;
            }
        }
        let window = window.expect("the probe page never opened");
        let window_id = window["id"].as_u64().unwrap();
        let pid = window["pid"].as_u64().unwrap();
        let hwnd = to_hwnd(window_id as isize);
        pause(1500);

        let emit = |_: Value| {};
        let outcome = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            let foreground = unsafe { GetForegroundWindow() };
            let attached = run_action(&emit, session, "attach", &json!({ "window_id": window_id, "hide": hide })).unwrap();
            eprintln!("{host:?} attached: {attached}");
            let web = !matches!(host, ProbeHost::WebView2Pane);
            assert_eq!(attached["window"]["web_content"], json!(web), "web content detection");
            assert_eq!(is_off_screen(hwnd), hide, "parking did not follow hide={hide}");
            body(&emit, hwnd);
            // A just-launched probe window often *is* the foreground window,
            // and parking it hands the foreground on; the claim under test is
            // that the user's own window keeps it.
            if foreground != hwnd {
                assert_eq!(foreground, unsafe { GetForegroundWindow() }, "the foreground window changed");
            }
        }));

        detach(session);
        let _ = std::process::Command::new("taskkill")
            .args(["/PID", &pid.to_string(), "/T", "/F"])
            .status();
        if let Err(panic) = outcome {
            std::panic::resume_unwind(panic);
        }
    }

    /// Fills every kind of field in a real Chromium page and reads back what
    /// the page received, including whether `input` events fired — what
    /// React-style apps such as Teams need to notice the text at all.
    ///
    /// `cargo test probes_chromium -- --ignored --nocapture`
    #[test]
    #[ignore = "opens an Edge window on the local desktop"]
    fn probes_chromium_fields() {
        probe_fields(ProbeHost::Edge);
    }

    #[test]
    #[ignore = "opens a WebView2 window on the local desktop"]
    fn probes_webview2_fields() {
        probe_fields(ProbeHost::WebView2);
    }

    /// A `<select>` opens its list as a popup window of its own. It must
    /// show up in the screenshot and the UI tree, and an item in it must be
    /// pickable.
    #[test]
    #[ignore = "opens an Edge window on the local desktop"]
    fn works_in_a_select_popup() {
        let session = "probe-popup";
        with_probe_page(session, ProbeHost::Edge, false, |emit, hwnd| {
            let (x, y) = centre_of(emit, session, "Color select");
            let opened = run_action(emit, session, "click", &json!({ "x": x, "y": y })).unwrap();
            eprintln!("open select: {opened}");
            let mut popups = Vec::new();
            for _ in 0..20 {
                pause(150);
                popups = Target::resolve(session).unwrap().popups;
                if !popups.is_empty() {
                    break;
                }
            }
            assert!(!popups.is_empty(), "the select's list never showed up as a popup");
            eprintln!("popups: {:?}", popups.iter().map(|popup| class_name(*popup)).collect::<Vec<_>>());

            let target = Target::resolve(session).unwrap();
            let shot = run_action(emit, session, "screenshot", &json!({})).unwrap();
            let (width, height) = target.screenshot_size();
            assert_eq!((shot["width"].as_u64(), shot["height"].as_u64()), (Some(width as u64), Some(height as u64)));

            let tree = snapshot_text(emit, session);
            let green = tree
                .lines()
                .find(|line| line.contains("\"Green\""))
                .and_then(|line| line.split("[ref=").nth(1))
                .and_then(|rest| rest.split(']').next())
                .unwrap_or_else(|| panic!("the popup's items are not in the tree:\n{tree}"))
                .to_string();
            let picked = run_action(emit, session, "click", &json!({ "ref": green })).unwrap();
            eprintln!("pick green: {picked}");
            pause(400);
            assert_eq!(page_report(hwnd).get("color").map(String::as_str), Some("Green"));
        });
    }

    /// Two buttons at the same spot: a click by coordinates reaches the one
    /// drawn on top (later in the page), not the one it covers.
    #[test]
    #[ignore = "opens an Edge window on the local desktop"]
    fn clicks_the_element_drawn_on_top() {
        let session = "probe-overlay";
        with_probe_page(session, ProbeHost::Edge, true, |emit, hwnd| {
            let (x, y) = centre_of(emit, session, "Covering button");
            let clicked = run_action(emit, session, "click", &json!({ "x": x, "y": y })).unwrap();
            eprintln!("click overlay: {clicked}");
            assert_eq!(clicked["delivered_via"], json!("ui_automation"), "the click fell back to posted input");
            assert_eq!(clicked["delivered_to"], json!("Covering button"));
            pause(300);
            let report = page_report(hwnd);
            assert_eq!(report_number(&report, "over"), 1, "the covering button was not clicked");
            assert_eq!(report_number(&report, "under"), 0, "the covered button was clicked");
        });
    }

    /// A native window with a small web pane stays a native app: attaching
    /// reports no web content, so keys go to the app's own focus.
    #[test]
    #[ignore = "opens a WebView2 window on the local desktop"]
    fn treats_a_small_web_pane_as_native() {
        with_probe_page("probe-pane", ProbeHost::WebView2Pane, false, |_, _| {});
    }

    fn probe_fields(host: ProbeHost) {
        let session = "probe-fields";
        with_probe_page(session, host, true, |emit, hwnd| {
            let caption = || window_title(hwnd);
            let name = ref_for(emit, session, "Name field");
            let clicked = run_action(emit, session, "click", &json!({ "ref": name })).unwrap();
            eprintln!("click name: {clicked}");
            let typed = run_action(emit, session, "type", &json!({ "text": "alpha" })).unwrap();
            eprintln!("type name: {typed}\n  caption: {}", caption());
            assert_eq!(typed["delivered_via"], json!("keyboard"));
            assert_ne!(typed["confirmed"], json!(false), "a hidden page's stale value was reported as a failure");

            // Tab moves the page's focus on; typing without a ref follows it
            // instead of going back into the field clicked before.
            run_action(emit, session, "key", &json!({ "key": "tab" })).unwrap();
            let typed = run_action(emit, session, "type", &json!({ "text": "tabbed" })).unwrap();
            eprintln!("type after tab: {typed}\n  caption: {}", caption());
            pause(300);
            let report = page_report(hwnd);
            assert_eq!(report.get("name").map(String::as_str), Some("alpha"), "typing after Tab went back into the name field");
            assert_eq!(report.get("notes").map(String::as_str), Some("tabbed"), "typing after Tab did not reach the next field");

            let notes = ref_for(emit, session, "Notes field");
            let set = run_action(emit, session, "set_value", &json!({ "ref": notes, "value": "beta" })).unwrap();
            eprintln!("set_value notes: {set}\n  caption: {}", caption());

            let editor = ref_for(emit, session, "Message editor");
            let typed = run_action(emit, session, "type", &json!({ "ref": editor, "text": "gamma" })).unwrap();
            eprintln!("type editor: {typed}\n  caption: {}", caption());

            // A second line in a chat editor is Shift+Enter, never a send.
            let typed = run_action(emit, session, "type", &json!({ "text": "\ndelta" })).unwrap();
            eprintln!("type editor line 2: {typed}\n  caption: {}", caption());

            let send = ref_for(emit, session, "Send");
            let clicked = run_action(emit, session, "click", &json!({ "ref": send })).unwrap();
            eprintln!("click send: {clicked}");
            pause(300);

            let report = page_report(hwnd);
            eprintln!("final report: {report:?}");
            assert_eq!(report.get("name").map(String::as_str), Some("alpha"), "input value");
            assert_eq!(report.get("notes").map(String::as_str), Some("beta"), "textarea value");
            assert_eq!(report.get("editor").map(String::as_str), Some("gamma/delta"), "contenteditable text");
            let events: Vec<i64> = report["ev"].split(',').map(|n| n.parse().unwrap_or(0)).collect();
            for (count, label) in events.iter().zip(["input", "textarea", "contenteditable"]) {
                assert!(*count > 0, "no input event reached the {label}");
            }
            assert_eq!(report_number(&report, "sent"), 1, "Send click");
        });
    }

    /// Hover, double-click, right-click, scroll, drag and a slider on a real
    /// Chromium page, parked off-screen, each checked against what the page
    /// itself saw.
    #[test]
    #[ignore = "opens an Edge window on the local desktop"]
    fn probes_chromium_pointer() {
        probe_pointer(ProbeHost::Edge);
    }

    #[test]
    #[ignore = "opens a WebView2 window on the local desktop"]
    fn probes_webview2_pointer() {
        probe_pointer(ProbeHost::WebView2);
    }

    /// A drag in a page that is on screen but completely covered by another
    /// window — Chromium treats it as hidden and would drop every move.
    #[test]
    #[ignore = "opens Edge windows on the local desktop"]
    fn drags_in_a_covered_page() {
        let session = "probe-covered";
        with_probe_page(session, ProbeHost::Edge, false, |emit, hwnd| {
            spawn_quiet(
                std::process::Command::new(EDGE)
                    .arg(format!("--user-data-dir={}", edge_profile().display()))
                    .arg("--app=data:text/html,<title>cover</title><body style=background:%23333>"),
            );
            let mut cover = None;
            for _ in 0..40 {
                pause(250);
                cover = top_level_windows().into_iter().find(|window| window_title(*window) == "cover");
                if cover.is_some() {
                    break;
                }
            }
            let cover = cover.expect("the cover window never opened");
            let frame = frame_rect(hwnd);
            unsafe {
                let _ = SetWindowPos(
                    cover,
                    Some(HWND(std::ptr::null_mut())), // HWND_TOP
                    frame.left - 40,
                    frame.top - 40,
                    frame.right - frame.left + 80,
                    frame.bottom - frame.top + 80,
                    SWP_NOACTIVATE,
                );
            }
            pause(1500);
            assert!(!partly_visible(hwnd), "the cover does not hide the page");

            let (x, y) = centre_of(emit, session, "Drag handle");
            let dragged = run_action(emit, session, "drag", &json!({ "x": x, "y": y, "to_x": x + 150, "to_y": y })).unwrap();
            pause(1300);
            let report = page_report(hwnd);
            eprintln!("covered drag: {dragged}\n  report: {report:?}");
            assert!(report_number(&report, "drag") >= 120, "the covered drag moved {:?}", report.get("drag"));
            // Put back exactly: still covered, still where it was.
            assert!(!partly_visible(hwnd), "the drag left the page uncovered");
            let after = frame_rect(hwnd);
            assert_eq!((after.left, after.top), (frame.left, frame.top), "the drag moved the window");
        });
    }

    /// Not a test on its own: the WebView2 host process that the WebView2
    /// probes start, running this binary with only this "test" selected. A
    /// tao window holding a wry (WebView2) view is laid out the way Teams is,
    /// and the page title is copied to the window caption for the probes.
    #[test]
    #[ignore = "runs only as the WebView2 host child process of other live tests"]
    fn webview2_host() {
        let Ok(url) = std::env::var("COMPUTER_APP_PROBE_URL") else {
            return;
        };
        use tao::event::Event;
        use tao::event_loop::{ControlFlow, EventLoopBuilder};
        use tao::platform::windows::EventLoopBuilderExtWindows;
        let event_loop = EventLoopBuilder::<String>::with_user_event()
            .with_any_thread(true)
            .build();
        let window = tao::window::WindowBuilder::new()
            .with_title("probe host")
            .with_inner_size(tao::dpi::LogicalSize::new(900.0, 1000.0))
            .build(&event_loop)
            .unwrap();
        let proxy = event_loop.create_proxy();
        let builder = wry::WebViewBuilder::new()
            .with_url(&url)
            .with_document_title_changed_handler(move |title| {
                let _ = proxy.send_event(title);
            });
        // A native window with only a small web pane in a corner, like an
        // Office add-in pane.
        let webview = if std::env::var("COMPUTER_APP_PROBE_PANE").is_ok() {
            builder
                .with_bounds(wry::Rect {
                    position: wry::dpi::LogicalPosition::new(600.0, 0.0).into(),
                    size: wry::dpi::LogicalSize::new(300.0, 300.0).into(),
                })
                .build_as_child(&window)
                .unwrap()
        } else {
            builder.build(&window).unwrap()
        };
        event_loop.run(move |event, _, control_flow| {
            *control_flow = ControlFlow::Wait;
            let _ = &webview;
            if let Event::UserEvent(title) = event {
                window.set_title(&title);
            }
        });
    }

    fn probe_pointer(host: ProbeHost) {
        let session = "probe-pointer";
        let hide = std::env::var("PROBE_HIDE").map(|value| value != "0").unwrap_or(true);
        with_probe_page(session, host, hide, |emit, hwnd| {
            let step =|label: &str, action: &str, params: Value| {
                let result = run_action(emit, session, action, &params);
                // Hidden pages run timers about once a second.
                pause(1300);
                eprintln!("{label}: {result:?}\n  report: {:?}", page_report(hwnd));
            };
            let _ = run_action(emit, session, "snapshot", &json!({}));
            step("hover", "hover", json!({ "ref": ref_for(emit, session, "Hover target") }));
            step("double", "click", json!({ "ref": ref_for(emit, session, "Double target"), "clicks": 2 }));
            step("context", "click", json!({ "ref": ref_for(emit, session, "Context target"), "button": "right" }));
            step("scroll", "scroll", json!({ "ref": ref_for(emit, session, "Scroll box"), "direction": "down", "amount": 3 }));
            let (x, y) = centre_of(emit, session, "Drag handle");
            step("drag", "drag", json!({ "x": x, "y": y, "to_x": x + 150, "to_y": y }));
            assert_eq!(is_off_screen(hwnd), hide, "the drag changed where the page is");
            step("slider", "set_value", json!({ "ref": ref_for(emit, session, "Volume slider"), "value": "70" }));

            let report = page_report(hwnd);
            let mut failures = Vec::new();
            for key in ["hover", "dbl", "ctx", "scroll"] {
                if report_number(&report, key) <= 0 {
                    failures.push(key);
                }
            }
            // The whole gesture, not just its first steps.
            if report_number(&report, "drag") < 120 {
                failures.push("drag");
            }
            if report_number(&report, "range") != 70 {
                failures.push("range");
            }
            assert!(failures.is_empty(), "not received by the page: {failures:?} — report {report:?}");
        });
    }

    /// Run `body` against the WinForms dialog probe (see the fixture),
    /// attached and parked.
    fn with_dialog_probe(body: impl FnOnce(&dyn Fn(Value), &str, HWND)) {
        use std::os::windows::process::CommandExt;
        unsafe {
            let _ = CoInitializeEx(None, COINIT_MULTITHREADED);
        }
        let script = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("tests")
            .join("fixtures")
            .join("computer_app_dialogs.ps1");
        let mut child = std::process::Command::new("powershell")
            .args(["-NoProfile", "-ExecutionPolicy", "Bypass", "-File"])
            .arg(&script)
            // CREATE_NO_WINDOW: no console, only the form.
            .creation_flags(0x0800_0000)
            .spawn()
            .expect("start the dialog probe");
        let session = "live-dialogs";
        let mut window = None;
        for _ in 0..50 {
            pause(200);
            window = list_windows(session, &json!({ "query": "dialog-probe" }))["windows"]
                .as_array()
                .and_then(|windows| windows.first().cloned());
            if window.is_some() {
                break;
            }
        }
        let window_id = window.expect("the dialog probe never opened")["id"].as_u64().unwrap();
        let emit = |_: Value| {};
        let outcome = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            run_action(&emit, session, "attach", &json!({ "window_id": window_id, "hide": true })).unwrap();
            body(&emit, session, to_hwnd(window_id as isize));
        }));
        detach(session);
        let _ = std::process::Command::new("taskkill")
            .args(["/PID", &child.id().to_string(), "/T", "/F"])
            .output();
        let _ = child.wait();
        if let Err(panic) = outcome {
            std::panic::resume_unwind(panic);
        }
    }

    /// The window the session is driving now: the probe, or its dialog.
    fn driven_title(session: &str) -> String {
        window_title(Target::resolve(session).unwrap().window)
    }

    fn wait_for_title(session: &str, title: &str) {
        for _ in 0..30 {
            if driven_title(session) == title {
                return;
            }
            pause(100);
        }
        panic!("expected to be driving {title:?}, driving {:?}", driven_title(session));
    }

    #[test]
    #[ignore = "opens a WinForms window on the local desktop"]
    fn refuses_refs_behind_a_modal_dialog() {
        with_dialog_probe(|emit, session, _| {
            let open = ref_for(emit, session, "Open dialog 1");
            // A posted click: Invoke would not return while the dialog is open.
            let clicked = run_action(emit, session, "click", &json!({ "ref": open })).unwrap();
            assert_eq!(clicked["pattern"], json!("click_message"), "{clicked}");
            wait_for_title(session, "probe dialog 1");

            let behind = run_action(emit, session, "click", &json!({ "ref": open }));
            assert!(
                behind.as_ref().is_err_and(|error| error.contains("waiting on the dialog")),
                "a ref behind the modal dialog was accepted: {behind:?}"
            );
            let close = ref_for(emit, session, "Close dialog 1");
            run_action(emit, session, "click", &json!({ "ref": close })).unwrap();
            wait_for_title(session, "dialog-probe");
            let gone = run_action(emit, session, "click", &json!({ "ref": close }));
            assert!(
                gone.as_ref().is_err_and(|error| error.contains("has closed")),
                "a ref into the closed dialog was accepted: {gone:?}"
            );

            // A new snapshot retires the old refs instead of renumbering.
            snapshot_text(emit, session);
            let stale = run_action(emit, session, "click", &json!({ "ref": open }));
            assert!(
                stale.as_ref().is_err_and(|error| error.contains("Unknown ref")),
                "a ref from an earlier snapshot was accepted: {stale:?}"
            );
        });
    }

    /// A shown top-level window titled `title`, once it opens.
    fn opened_window(title: &str) -> HWND {
        for _ in 0..30 {
            let found = top_level_windows()
                .into_iter()
                .find(|hwnd| unsafe { IsWindowVisible(*hwnd) }.as_bool() && window_title(*hwnd) == title);
            if let Some(hwnd) = found {
                return hwnd;
            }
            pause(100);
        }
        panic!("{title:?} never opened");
    }

    #[test]
    #[ignore = "opens a WinForms window on the local desktop"]
    fn keeps_a_parked_apps_dialogs_off_screen() {
        with_dialog_probe(|emit, session, probe| {
            // WinForms keeps a dialog on a monitor; the dialog watcher moves
            // it over its parked owner as it opens, before any action runs.
            run_action(emit, session, "click", &json!({ "ref": ref_for(emit, session, "Open dialog 1") })).unwrap();
            let first = opened_window("probe dialog 1");
            pause(300);
            assert!(is_off_screen(first), "dialog 1 opened on the user's screen at {:?}", frame_rect(first));
            wait_for_title(session, "probe dialog 1");

            // A dialog opened from the dialog is followed, and parked too.
            run_action(emit, session, "click", &json!({ "ref": ref_for(emit, session, "Open dialog 2") })).unwrap();
            let second = opened_window("probe dialog 2");
            pause(300);
            assert!(is_off_screen(second), "dialog 2 opened on the user's screen at {:?}", frame_rect(second));
            wait_for_title(session, "probe dialog 2");
            run_action(emit, session, "click", &json!({ "ref": ref_for(emit, session, "Close dialog 2") })).unwrap();
            wait_for_title(session, "probe dialog 1");

            // Released while a dialog is open: it comes back with its window,
            // or the user would face an app blocked by a dialog they cannot see.
            detach(session);
            pause(300);
            assert!(!is_off_screen(probe), "the probe was left off-screen");
            assert!(!is_off_screen(first), "dialog 1 was left off-screen at {:?}", frame_rect(first));
        });
    }

    #[test]
    #[ignore = "opens a WinForms window on the local desktop"]
    fn a_layered_window_keeps_its_opacity_after_a_peek() {
        with_dialog_probe(|_, _, probe| unsafe {
            let alpha = || {
                let mut alpha = 0u8;
                GetLayeredWindowAttributes(probe, None, Some(&mut alpha), None).map(|_| alpha)
            };
            let ex_style = GetWindowLongPtrW(probe, GWL_EXSTYLE);
            // A window with an opacity of its own, as WinForms' Opacity sets.
            SetWindowLongPtrW(probe, GWL_EXSTYLE, ex_style | WS_EX_LAYERED.0 as isize);
            SetLayeredWindowAttributes(probe, COLORREF(0), 200, LWA_ALPHA).unwrap();
            {
                let _guard = SeeThrough::apply(probe).expect("a layered window with attributes");
                assert_eq!(alpha(), Ok(1));
            }
            assert_eq!(alpha(), Ok(200), "the window's own opacity was not restored");
            assert_ne!(GetWindowLongPtrW(probe, GWL_EXSTYLE) as u32 & WS_EX_TRANSPARENT.0, WS_EX_TRANSPARENT.0);

            // Not layered before: not layered after.
            SetWindowLongPtrW(probe, GWL_EXSTYLE, ex_style);
            drop(SeeThrough::apply(probe).unwrap());
            assert_eq!(GetWindowLongPtrW(probe, GWL_EXSTYLE), ex_style);
        });
    }

    #[test]
    #[ignore = "opens a Notepad window on the local desktop"]
    fn drives_notepad_in_the_background() {
        unsafe {
            let _ = CoInitializeEx(None, COINIT_MULTITHREADED);
        }
        let before = notepad_windows();
        std::process::Command::new("cmd")
            .args(["/C", "start", "/min", "notepad.exe"])
            .status()
            .expect("start notepad");
        let mut launched = None;
        for _ in 0..50 {
            pause(200);
            launched = notepad_windows().into_iter().find(|window| !before.contains(window));
            if launched.is_some() {
                break;
            }
        }
        let Some((window_id, pid)) = launched else {
            eprintln!("skipped: Notepad opened as a tab of an existing window, not a new one");
            return;
        };
        let already_running = before.iter().any(|(_, existing)| *existing == pid);

        let session = "live-test";
        let events = RefCell::new(Vec::<Value>::new());
        let emit = |payload: Value| events.borrow_mut().push(payload);

        let outcome = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            let attached = run_action(&emit, session, "attach", &json!({ "window_id": window_id })).unwrap();
            eprintln!("attached: {attached}");
            // A second chat can neither take the window nor pick it blindly.
            let other = "live-test-other";
            let taken = run_action(&emit, other, "attach", &json!({ "window_id": window_id }));
            assert!(taken.is_err_and(|error| error.contains("another chat")), "a second chat attached the same window");
            let listed = run_action(&emit, other, "list_windows", &json!({})).unwrap();
            let row = listed["windows"].as_array().unwrap().iter().find(|row| row["id"] == json!(window_id)).cloned();
            assert_eq!(row.map(|row| row["controlled_elsewhere"].clone()), Some(json!(true)));
            pause(500);
            // Windows Notepad restores unsaved tabs from earlier sessions;
            // work in a fresh tab so none of them is touched.
            run_action(&emit, session, "key", &json!({ "key": "ctrl+n" })).unwrap();
            pause(700);

            let notepad = to_hwnd(window_id as isize);
            let notepad_was_foreground = unsafe { GetForegroundWindow() } == notepad;

            let typed = run_action(&emit, session, "type", &json!({ "text": "hello from evoflux\nsecond line" })).unwrap();
            eprintln!("typed: {typed}");
            assert_eq!(typed["confirmed"], json!(true), "typing was not confirmed: {typed}");
            pause(400);
            let first = snapshot_text(&emit, session);
            assert!(first.contains("hello from evoflux"), "text not in the UI tree:\n{first}");
            assert!(first.contains("second line"), "the line break did not type as Enter:\n{first}");

            run_action(&emit, session, "key", &json!({ "key": "ctrl+a" })).unwrap();
            run_action(&emit, session, "type", &json!({ "text": "replaced" })).unwrap();
            pause(400);
            let second = snapshot_text(&emit, session);
            assert!(second.contains("replaced"), "ctrl+a then typing failed:\n{second}");
            assert!(!second.contains("hello from evoflux"), "ctrl+a did not select all:\n{second}");

            let shot = run_action(&emit, session, "screenshot", &json!({})).unwrap();
            assert!(shot["data"].as_str().map(str::len).unwrap_or(0) > 1000);
            let (width, height) = (shot["width"].as_u64().unwrap(), shot["height"].as_u64().unwrap());
            let (x, y) = ((width / 2) as f64, (height / 2) as f64);
            let clicked = Target::resolve(session).unwrap().screen_point(x, y).unwrap();
            run_action(&emit, session, "click", &json!({ "x": x, "y": y })).unwrap();

            // A person may be using the mouse while this runs, so "the cursor
            // did not move" cannot be asserted — but a click that went through
            // the real cursor would have left it exactly on the clicked point.
            let mut cursor = POINT::default();
            unsafe { GetCursorPos(&mut cursor) }.unwrap();
            assert!(
                (cursor.x - clicked.x).abs() > 2 || (cursor.y - clicked.y).abs() > 2,
                "the real cursor sits on the clicked point {clicked:?}"
            );
            if !notepad_was_foreground {
                assert_ne!(unsafe { GetForegroundWindow() }, notepad, "Notepad was brought to the front");
            }
            let phases: Vec<String> = events
                .borrow()
                .iter()
                .filter_map(|event| event["phase"].as_str().map(str::to_string))
                .collect();
            assert!(phases.iter().any(|phase| phase == "click"), "no pointer events: {phases:?}");

            // Hidden mode: parked off-screen, still controllable, and put
            // back exactly where it was on detach.
            let mut original = WINDOWPLACEMENT {
                length: std::mem::size_of::<WINDOWPLACEMENT>() as u32,
                ..Default::default()
            };
            unsafe { GetWindowPlacement(notepad, &mut original) }.unwrap();
            let hidden = run_action(&emit, session, "attach", &json!({ "window_id": window_id, "hide": true })).unwrap();
            assert_eq!(hidden["window"]["hidden"], json!(true));
            assert!(is_off_screen(notepad), "Notepad is still on screen");
            let typed_hidden = run_action(&emit, session, "type", &json!({ "text": " hidden ok" })).unwrap();
            assert_eq!(typed_hidden["confirmed"], json!(true), "typing while parked was not confirmed: {typed_hidden}");
            pause(400);
            let hidden_tree = snapshot_text(&emit, session);
            assert!(hidden_tree.contains("hidden ok"), "typing while parked failed:\n{hidden_tree}");
            run_action(&emit, session, "detach", &json!({})).unwrap();
            pause(300);
            let mut restored = WINDOWPLACEMENT {
                length: std::mem::size_of::<WINDOWPLACEMENT>() as u32,
                ..Default::default()
            };
            unsafe { GetWindowPlacement(notepad, &mut restored) }.unwrap();
            assert_eq!(
                (original.rcNormalPosition.left, original.rcNormalPosition.top),
                (restored.rcNormalPosition.left, restored.rcNormalPosition.top),
                "detach did not restore the window's position"
            );
            assert!(
                !is_off_screen(notepad) || unsafe { IsIconic(notepad) }.as_bool(),
                "Notepad was left off-screen"
            );
        }));

        // Empty and close the test's own tab so Notepad has nothing of it to
        // restore next time, whether or not the assertions above held.
        let noop = |_: Value| {};
        let _ = run_action(&noop, session, "attach", &json!({ "window_id": window_id }));
        if Target::resolve(session).is_ok() {
            let _ = run_action(&noop, session, "key", &json!({ "key": "ctrl+a" }));
            let _ = run_action(&noop, session, "key", &json!({ "key": "delete" }));
            pause(200);
            let _ = run_action(&noop, session, "key", &json!({ "key": "ctrl+w" }));
            pause(500);
        }

        detach(session);
        if already_running {
            // A new window of the user's own Notepad: close just that window
            // (its last tab was emptied above, so nothing asks to save).
            let _ = post(to_hwnd(window_id as isize), windows::Win32::UI::WindowsAndMessaging::WM_CLOSE, 0, LPARAM(0));
        } else {
            let _ = std::process::Command::new("taskkill")
                .args(["/PID", &pid.to_string(), "/F"])
                .status();
        }
        if let Err(panic) = outcome {
            std::panic::resume_unwind(panic);
        }
    }
}
