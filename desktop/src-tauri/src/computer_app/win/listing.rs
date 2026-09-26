//! Top-level windows and the processes behind them: what `list_windows`
//! reports, and which windows may never be attached.

use super::*;

pub(super) fn to_hwnd(raw: isize) -> HWND {
    HWND(raw as *mut core::ffi::c_void)
}

pub(super) fn hwnd_id(hwnd: HWND) -> u64 {
    hwnd.0 as isize as u64
}

// ── Windows and apps ────────────────────────────────────────────────────

pub(super) struct WindowRow {
    pub(super) hwnd: HWND,
    pub(super) title: String,
    pub(super) pid: u32,
    pub(super) app: String,
    pub(super) minimized: bool,
    pub(super) frame: RECT,
    pub(super) owner: Option<HWND>,
}

impl WindowRow {
    pub(super) fn to_json(&self, foreground: HWND) -> Value {
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

pub(super) fn top_level_windows() -> Vec<HWND> {
    let mut handles: Vec<HWND> = Vec::new();
    unsafe {
        let _ = EnumWindows(
            Some(collect_window),
            LPARAM(&mut handles as *mut Vec<HWND> as isize),
        );
    }
    handles
}

pub(super) fn window_title(hwnd: HWND) -> String {
    let mut buffer = [0u16; 512];
    let len = unsafe { GetWindowTextW(hwnd, &mut buffer) }.max(0) as usize;
    String::from_utf16_lossy(&buffer[..len])
}

pub(super) fn class_name(hwnd: HWND) -> String {
    let mut buffer = [0u16; 256];
    let len = unsafe { GetClassNameW(hwnd, &mut buffer) }.max(0) as usize;
    String::from_utf16_lossy(&buffer[..len])
}

pub(super) fn window_pid(hwnd: HWND) -> u32 {
    let mut pid = 0u32;
    unsafe { GetWindowThreadProcessId(hwnd, Some(&mut pid)) };
    pid
}

pub(super) fn process_image_path(pid: u32) -> Option<String> {
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

pub(super) fn file_name(path: &str) -> &str {
    path.rsplit(['\\', '/']).next().unwrap_or(path)
}

fn process_image_name(pid: u32) -> String {
    process_image_path(pid)
        .map(|path| file_name(&path).to_string())
        .unwrap_or_default()
}

pub(super) fn is_cloaked(hwnd: HWND) -> bool {
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
pub(super) fn frame_rect(hwnd: HWND) -> RECT {
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

pub(super) fn describe_window(hwnd: HWND) -> Option<WindowRow> {
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
        app: app_name(hwnd, pid),
        minimized: unsafe { IsIconic(hwnd) }.as_bool(),
        frame: frame_rect(hwnd),
        owner,
    })
}

/// The host process of every Store (UWP) app's window.
pub(super) const FRAME_HOST: &str = "ApplicationFrameHost.exe";

/// The executable a window belongs to, as the user knows the app.
///
/// A Store app's window belongs to ApplicationFrameHost, whichever app it
/// frames — so allowing Calculator in Settings allowed Settings too. The app
/// itself is the process behind the frame's CoreWindow child. A minimized
/// (suspended) app takes that child out of the frame, and the frame then
/// keeps the host's name: [`attach_refusal`] refuses it rather than let an
/// unidentified app through the allow and block lists.
fn app_name(hwnd: HWND, pid: u32) -> String {
    process_image_name(app_process(hwnd, pid))
}

/// The process of the app a window shows: `pid`, or for a Store app's
/// frame the process behind its CoreWindow (see [`app_name`]).
pub(super) fn app_process(hwnd: HWND, pid: u32) -> u32 {
    if !process_image_name(pid).eq_ignore_ascii_case(FRAME_HOST) {
        return pid;
    }
    let core = unsafe {
        windows::Win32::UI::WindowsAndMessaging::FindWindowExW(
            Some(hwnd),
            None,
            windows::core::w!("Windows.UI.Core.CoreWindow"),
            None,
        )
    };
    match core {
        Ok(core) if !core.0.is_null() && !process_image_name(window_pid(core)).is_empty() => window_pid(core),
        _ => pid,
    }
}

pub(super) fn attach_refusal(row: &WindowRow) -> Option<String> {
    if row.pid == unsafe { GetCurrentProcessId() } {
        return Some("EvoFlux cannot control its own window.".into());
    }
    if row.app.eq_ignore_ascii_case(FRAME_HOST) {
        return Some(format!(
            "Windows does not say which Store app \"{}\" is while it is minimized, so it cannot be checked against Settings. Ask the user to restore it, then list windows again.",
            row.title
        ));
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
pub(super) fn integrity_level(process: windows::Win32::Foundation::HANDLE) -> Option<u32> {
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
pub(super) fn runs_above_us(pid: u32) -> bool {
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
pub(super) fn is_above(ours: u32, theirs: Option<u32>) -> bool {
    theirs.map_or(true, |level| level > ours)
}

pub(super) fn list_windows(session_id: &str, params: &Value) -> Value {
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
