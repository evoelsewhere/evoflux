//! Keeping a controlled app running but off the user's screen, and putting
//! it back exactly where it was — also after EvoFlux crashed.

use super::*;

// ── Parking: keep the app running but off the user's screen ─────────────
//
// A minimized window cannot be captured or clicked (it has no size), so an
// app the user wants kept out of sight is moved just outside the virtual
// desktop instead. It keeps its taskbar button and keeps rendering; on
// release it gets its exact previous placement back, and a window that was
// minimized or maximized returns minimized (restoring to maximized) rather
// than being activated behind the user's back.

pub(super) fn virtual_screen() -> RECT {
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

pub(super) fn is_off_screen(hwnd: HWND) -> bool {
    let frame = frame_rect(hwnd);
    let screen = virtual_screen();
    frame.left >= screen.right
        || frame.right <= screen.left
        || frame.top >= screen.bottom
        || frame.bottom <= screen.top
}

pub(super) fn move_off_screen(hwnd: HWND) {
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

// ── The stage: a fixed-size screen for a parked window ──────────────────
//
// Off every monitor, a parked window is sized like a screen of its own:
// the same size every time, and small enough that its screenshot reaches
// the agent pixel for pixel (see `screenshot_scale`). The agent's
// coordinates are then the window's, with no scaling to round them, and the
// app lays itself out the same way in every session instead of by however
// the user last sized it. On release it gets its own placement back.

/// The stage in physical pixels: 1280×800 — within the screenshot limits —
/// unless that is less than 1024×640 logical pixels on a scaled display,
/// where an app laid out in less (a ribbon, a dialog) starts to fold away.
pub(super) fn stage_size(dpi: u32) -> (i32, i32) {
    const STAGE: (i32, i32) = (1280, 800);
    const MIN_LOGICAL: (i32, i32) = (1024, 640);
    let scale = f64::from(dpi.max(96)) / 96.0;
    let at_least = |logical: i32| (f64::from(logical) * scale).round() as i32;
    (STAGE.0.max(at_least(MIN_LOGICAL.0)), STAGE.1.max(at_least(MIN_LOGICAL.1)))
}

/// Give a parked window the stage's size. Only a window the user could
/// resize themselves is resized: a fixed-size dialog or tool window lays
/// itself out for its own size and nothing else.
fn fit_to_stage(hwnd: HWND) {
    let style = unsafe { GetWindowLongPtrW(hwnd, GWL_STYLE) } as u32;
    if style & WS_THICKFRAME.0 == 0 {
        return;
    }
    let (width, height) = stage_size(unsafe { GetDpiForWindow(hwnd) });
    let mut window_rect = RECT::default();
    unsafe {
        let _ = GetWindowRect(hwnd, &mut window_rect);
    }
    // The stage is the visible frame; the window rectangle adds the
    // invisible resize borders around it.
    let frame = frame_rect(hwnd);
    let borders_x = (window_rect.right - window_rect.left) - (frame.right - frame.left);
    let borders_y = (window_rect.bottom - window_rect.top) - (frame.bottom - frame.top);
    unsafe {
        let _ = SetWindowPos(
            hwnd,
            None,
            0,
            0,
            width + borders_x.max(0),
            height + borders_y.max(0),
            SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOOWNERZORDER,
        );
    }
}

pub(super) fn park(hwnd: HWND) -> Option<WINDOWPLACEMENT> {
    let mut placement = WINDOWPLACEMENT {
        length: std::mem::size_of::<WINDOWPLACEMENT>() as u32,
        ..Default::default()
    };
    unsafe {
        GetWindowPlacement(hwnd, &mut placement).ok()?;
        // On disk first, so no moment passes with the window off-screen
        // and its place known only in memory.
        remember_parked(hwnd, placement);
        if IsIconic(hwnd).as_bool() || IsZoomed(hwnd).as_bool() {
            // Back to its normal size first: a maximized window is pinned to
            // its monitor and a minimized one has no size to render.
            let _ = ShowWindow(hwnd, SW_SHOWNOACTIVATE);
            std::thread::sleep(Duration::from_millis(150));
        }
    }
    move_off_screen(hwnd);
    // Sized once it is off-screen: moving there can change its DPI, and the
    // app rescales itself to the new one first.
    std::thread::sleep(Duration::from_millis(100));
    fit_to_stage(hwnd);
    Some(placement)
}

// ── Parked windows on disk ──────────────────────────────────────────────
//
// Where a parked window belongs lived only in memory: if EvoFlux crashed or
// was killed, the app stayed off-screen, reachable only by keyboard tricks.
// Every parked window is also written to a file, and taken out of it once
// it is back; the next start puts back whatever a previous run left behind.

#[derive(Clone, Copy)]
pub(super) struct Stranded {
    pub(super) hwnd: isize,
    pid: u32,
    placement: WINDOWPLACEMENT,
}

static STRANDED: Lazy<Mutex<Vec<Stranded>>> = Lazy::new(|| Mutex::new(Vec::new()));
static STRANDED_FILE: once_cell::sync::OnceCell<std::path::PathBuf> = once_cell::sync::OnceCell::new();

pub(super) fn stranded() -> std::sync::MutexGuard<'static, Vec<Stranded>> {
    STRANDED.lock().unwrap_or_else(|poisoned| poisoned.into_inner())
}

pub(super) fn placement_json(placement: &WINDOWPLACEMENT) -> Value {
    let normal = placement.rcNormalPosition;
    json!({
        "flags": placement.flags.0,
        "show": placement.showCmd,
        "min": [placement.ptMinPosition.x, placement.ptMinPosition.y],
        "max": [placement.ptMaxPosition.x, placement.ptMaxPosition.y],
        "normal": [normal.left, normal.top, normal.right, normal.bottom],
    })
}

pub(super) fn placement_from_json(value: &Value) -> Option<WINDOWPLACEMENT> {
    let numbers = |key: &str| -> Option<Vec<i32>> {
        value.get(key)?.as_array()?.iter().map(|n| n.as_i64().map(|n| n as i32)).collect()
    };
    let (min, max, normal) = (numbers("min")?, numbers("max")?, numbers("normal")?);
    if min.len() != 2 || max.len() != 2 || normal.len() != 4 {
        return None;
    }
    Some(WINDOWPLACEMENT {
        length: std::mem::size_of::<WINDOWPLACEMENT>() as u32,
        flags: WINDOWPLACEMENT_FLAGS(value.get("flags")?.as_u64()? as u32),
        showCmd: value.get("show")?.as_u64()? as u32,
        ptMinPosition: POINT { x: min[0], y: min[1] },
        ptMaxPosition: POINT { x: max[0], y: max[1] },
        rcNormalPosition: RECT { left: normal[0], top: normal[1], right: normal[2], bottom: normal[3] },
    })
}

fn save_stranded(list: &[Stranded]) {
    let Some(path) = STRANDED_FILE.get() else {
        return;
    };
    let entries: Vec<Value> = list
        .iter()
        .map(|entry| json!({ "hwnd": entry.hwnd, "pid": entry.pid, "placement": placement_json(&entry.placement) }))
        .collect();
    if let Err(error) = std::fs::write(path, Value::Array(entries).to_string()) {
        log::warn!("computer app: could not record parked windows: {error}");
    }
}

fn remember_parked(hwnd: HWND, placement: WINDOWPLACEMENT) {
    let mut list = stranded();
    list.retain(|entry| entry.hwnd != hwnd.0 as isize);
    list.push(Stranded { hwnd: hwnd.0 as isize, pid: window_pid(hwnd), placement });
    save_stranded(&list);
}

pub(super) fn forget_parked(hwnd: HWND) {
    let mut list = stranded();
    let before = list.len();
    list.retain(|entry| entry.hwnd != hwnd.0 as isize);
    if list.len() != before {
        save_stranded(&list);
    }
}

/// Start recording parked windows in `dir`, and put back any window that a
/// previous run left parked: still open, still the same process's, still
/// off-screen. Runs on a thread of its own, since moving a window waits for
/// its app.
pub(super) fn recover_stranded(dir: std::path::PathBuf) {
    let path = dir.join("computer_app_parked.json");
    let leftovers = load_stranded(&path);
    let _ = std::fs::create_dir_all(&dir);
    if STRANDED_FILE.set(path).is_err() {
        return;
    }
    // Recorded until put back, in case this run does not get that far.
    stranded().extend(leftovers.iter().copied());
    off_ui_thread(move || put_back(leftovers));
}

pub(super) fn load_stranded(path: &std::path::Path) -> Vec<Stranded> {
    let recorded: Vec<Value> = std::fs::read_to_string(path)
        .ok()
        .and_then(|text| serde_json::from_str(&text).ok())
        .unwrap_or_default();
    recorded
        .iter()
        .filter_map(|entry| {
            Some(Stranded {
                hwnd: entry.get("hwnd")?.as_i64()? as isize,
                pid: entry.get("pid")?.as_u64()? as u32,
                placement: placement_from_json(entry.get("placement")?)?,
            })
        })
        .collect()
}

pub(super) fn put_back(leftovers: Vec<Stranded>) {
    for entry in leftovers {
        let hwnd = to_hwnd(entry.hwnd);
        // A window handle can be reused once its window is gone.
        let same = unsafe { IsWindow(Some(hwnd)) }.as_bool() && window_pid(hwnd) == entry.pid;
        if same && is_off_screen(hwnd) {
            log::info!("computer app: putting back a window left off-screen by a previous run");
            unpark(hwnd, entry.placement, false);
        } else {
            forget_parked(hwnd);
        }
    }
}

pub(super) fn unpark(hwnd: HWND, placement: WINDOWPLACEMENT, activate: bool) {
    if !unsafe { IsWindow(Some(hwnd)) }.as_bool() {
        forget_parked(hwnd);
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
    forget_parked(hwnd);
    bring_dialogs_back(hwnd, placement.rcNormalPosition);
    bring_moved_back(hwnd);
}

// ── Dialogs of a parked window ──────────────────────────────────────────
//
// A dialog is a top-level window of its own, and Windows (DS_CENTER) and
// frameworks (WinForms' CenterParent) keep it on a monitor: a parked app's
// dialogs opened on the user's screen. So did its menus, floating panes and
// palettes, opened by a key or a command as often as by a click. While a
// window is parked, every window it opens (see `opened_by`) leaves the
// user's screen the moment it is shown: a captioned window it owns is moved
// over it, anything else next to it (`bring_popups_along`). When the window
// is handed back, its dialogs are centred on it again and its panes and
// palettes go back where they opened.

pub(super) fn is_dialog_of(hwnd: HWND, top: HWND) -> bool {
    let style = unsafe { GetWindowLongPtrW(hwnd, GWL_STYLE) } as u32;
    hwnd != top
        && style & WS_CHILD.0 == 0
        && style & WS_CAPTION.0 == WS_CAPTION.0
        && (owned_by(hwnd, top, top) || owned_by_hidden_window_of(hwnd, top))
}

/// Whether `hwnd` is owned by a window of `top`'s process that is never
/// shown. Apps often own their dialogs by such a window rather than by the
/// window the dialog is about: a spreadsheet's Create Table dialog, owned
/// that way, opened on the user's screen while its workbook was parked. A
/// dialog owned by another window the user can see (a second document
/// window) is that window's, and is left alone.
pub(super) fn owned_by_hidden_window_of(hwnd: HWND, top: HWND) -> bool {
    match unsafe { GetWindow(hwnd, GW_OWNER) } {
        Ok(owner) if !owner.0.is_null() && owner != top => {
            !unsafe { IsWindowVisible(owner) }.as_bool() && window_pid(owner) == window_pid(top)
        }
        _ => false,
    }
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
pub(super) fn park_dialog(dialog: HWND, top: HWND) {
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
pub(super) fn watch_for_dialogs() {
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
    let parked: Vec<(String, HWND, u32)> = registry()
        .attached
        .iter()
        .filter(|(_, attached)| attached.parked.is_some())
        .map(|(session, attached)| (session.clone(), to_hwnd(attached.hwnd), attached.pid))
        .collect();
    if let Some((session, top, pid)) = parked.into_iter().find(|(_, top, pid)| opened_by(hwnd, *top, *pid)) {
        keep_along(&session, top, pid, hwnd);
    }
}
