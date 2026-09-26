//! Windows as the window server lists them and the processes behind them:
//! what `list_windows` reports, and which windows may never be attached.

use super::*;

extern "C" {
    fn proc_pidpath(pid: i32, buffer: *mut c_void, size: u32) -> i32;
}

// ── Windows and apps ────────────────────────────────────────────────────

/// One window as the window server lists it.
pub(super) struct CgWindow {
    pub(super) id: u32,
    pub(super) pid: i32,
    pub(super) owner: String,
    pub(super) name: String,
    pub(super) bounds: Rect,
    pub(super) layer: i64,
    pub(super) onscreen: bool,
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
pub(super) fn cg_windows(option: u32, relative_to: u32) -> Vec<CgWindow> {
    let Some(array) = copy_window_info(option, relative_to) else {
        return Vec::new();
    };
    array.iter().filter_map(|item| parse_cg_window(*item)).collect()
}

pub(super) fn window_id_array(ids: &[u32]) -> CFArray {
    let values: Vec<*const c_void> = ids.iter().map(|&id| id as usize as *const c_void).collect();
    CFArray::from_copyable(&values)
}

/// The window server's description of one window, if it still exists.
pub(super) fn cg_window(id: u32) -> Option<CgWindow> {
    let ids = window_id_array(&[id]);
    let raw = unsafe { CGWindowListCreateDescriptionFromArray(ids.as_concrete_TypeRef()) };
    if raw.is_null() {
        return None;
    }
    let array: CFArray = unsafe { CFArray::wrap_under_create_rule(raw) };
    let first = array.iter().next().and_then(|item| parse_cg_window(*item));
    first
}

pub(super) fn process_path(pid: i32) -> Option<String> {
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
pub(super) fn bundle_of(path: &str) -> Option<std::path::PathBuf> {
    let index = path.find(".app/")?;
    Some(std::path::PathBuf::from(&path[..index + 4]))
}

/// Whether the app renders its UI with Chromium (Chrome, Edge, Electron
/// apps such as Slack or VS Code). Such apps keep their accessibility tree
/// off until an assistive client turns it on.
pub(super) fn is_chromium_app(pid: i32) -> bool {
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

pub(super) fn ax_window(app: &Ax, id: u32) -> Option<Ax> {
    app.elements("AXWindows").into_iter().find(|window| window.window_id() == Some(id))
}

pub(super) fn frontmost_pid() -> Option<i32> {
    Ax::system_wide()?.element("AXFocusedApplication")?.pid()
}

pub(super) struct WindowRow {
    pub(super) id: u32,
    pub(super) pid: i32,
    pub(super) app: String,
    pub(super) title: String,
    pub(super) minimized: bool,
    pub(super) frame: Rect,
    /// The app's main window, when this one is a dialog of it.
    pub(super) owner: Option<u32>,
    pub(super) focused: bool,
}

impl WindowRow {
    pub(super) fn to_json(&self, front: Option<i32>) -> Value {
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

pub(super) fn is_dialog(window: &Ax) -> bool {
    matches!(
        window.string("AXSubrole").as_deref(),
        Some("AXDialog" | "AXSystemDialog")
    )
}

/// Every app window a person would call a window: normal-level windows the
/// app also reports through accessibility (which drops the invisible helper
/// windows many apps keep), on this Space or minimized.
pub(super) fn window_rows() -> Vec<WindowRow> {
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

pub(super) fn attach_refusal(row: &WindowRow) -> Option<String> {
    if row.pid == std::process::id() as i32 {
        return Some("EvoFlux cannot control its own window.".into());
    }
    if row.app.is_empty() {
        return Some(format!(
            "macOS did not let EvoFlux inspect the process behind \"{}\", so it cannot be controlled.",
            row.title
        ));
    }
    if is_command_runner(&row.app) {
        return Some(format!(
            "{} runs commands and scripts, which would let the agent do anything outside Computer App Control's limits, so it cannot be controlled. Use the agent's own tools for commands, or ask the user.",
            row.app
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

pub(super) fn list_windows(session_id: &str, params: &Value) -> Value {
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
