//! Selected-window demonstration capture. This observer is intentionally
//! independent of Computer App Control: it never attaches, parks, or sends
//! input to the user's app.
use super::*;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::thread;
use std::time::Instant;

use windows::Win32::Foundation::HWND;
use windows::Win32::System::Com::{CoInitializeEx, COINIT_MULTITHREADED};
use windows::Win32::UI::Accessibility::{
    CUIAutomation, IUIAutomation, IUIAutomationValuePattern, UIA_ValuePatternId,
};
use windows::Win32::UI::Accessibility::{SetWinEventHook, UnhookWinEvent, HWINEVENTHOOK};
use windows::Win32::UI::WindowsAndMessaging::{
    DispatchMessageW, GetAncestor, PeekMessageW, EVENT_OBJECT_CREATE, EVENT_OBJECT_DESTROY,
    EVENT_OBJECT_FOCUS, EVENT_OBJECT_INVOKED, EVENT_OBJECT_SELECTION, EVENT_OBJECT_SHOW,
    EVENT_OBJECT_STATECHANGE, EVENT_OBJECT_VALUECHANGE, GA_ROOTOWNER, MSG, PM_REMOVE,
    WINEVENT_OUTOFCONTEXT, WINEVENT_SKIPOWNPROCESS,
};

use crate::computer_app::recording::{
    normalize_observation, CaptureKind, CaptureObservation, SelectedTarget,
};
use tauri::Emitter;

static RECORDINGS: Lazy<Mutex<HashMap<String, Arc<Session>>>> =
    Lazy::new(|| Mutex::new(HashMap::new()));

fn event_source_is_valid(hwnd_is_valid: bool, _object: i32, _child: i32) -> bool {
    hwnd_is_valid
}

struct Session {
    id: String,
    hwnd: isize,
    pid: u32,
    app: tauri::AppHandle,
    started: Instant,
    sequence: AtomicU64,
    emit_lock: Mutex<()>,
    paused: AtomicBool,
    stopped: AtomicBool,
}

impl Session {
    fn emit(&self, kind: CaptureKind, is_password: Option<bool>, value: Option<String>) {
        let _emit_guard = self
            .emit_lock
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        if self.paused.load(Ordering::Relaxed) || self.stopped.load(Ordering::Relaxed) {
            return;
        }
        let sequence = self.sequence.fetch_add(1, Ordering::Relaxed) + 1;
        let input = CaptureObservation {
            root_window_id: hwnd_id(HWND(self.hwnd as *mut core::ffi::c_void)),
            kind,
            point: None,
            button: None,
            scroll_delta: None,
            target: None,
            is_password,
            value,
            screenshot: None,
        };
        if let Some(event) = normalize_observation(
            sequence,
            self.started.elapsed().as_millis() as u64,
            &SelectedTarget {
                window_id: hwnd_id(HWND(self.hwnd as *mut core::ffi::c_void)),
            },
            input,
        ) {
            let _ = self.app.emit(
                crate::computer_app::SKILL_RECORDING_EVENT,
                json!({"recording_id": self.id, "event": event}),
            );
        }
    }

    fn emit_value_from(&self, source_hwnd: HWND) {
        unsafe {
            // ValueChanged is the trigger; inspect that event's HWND inside
            // this selected app, and check IsPassword before CurrentValue.
            let automation: IUIAutomation =
                match CoCreateInstance(&CUIAutomation, None, CLSCTX_INPROC_SERVER) {
                    Ok(automation) => automation,
                    Err(_) => {
                        self.emit(CaptureKind::ValueChanged, None, None);
                        return;
                    }
                };
            let element = match automation.ElementFromHandle(source_hwnd) {
                Ok(element) => element,
                Err(_) => {
                    self.emit(CaptureKind::ValueChanged, None, None);
                    return;
                }
            };
            let element_hwnd = element.CurrentNativeWindowHandle().unwrap_or_default();
            if hwnd_id(GetAncestor(element_hwnd, GA_ROOTOWNER))
                != hwnd_id(HWND(self.hwnd as *mut core::ffi::c_void))
            {
                return;
            }
            let password = element.CurrentIsPassword().ok().map(|flag| flag.as_bool());
            let value = if password == Some(false) {
                element
                    .GetCurrentPatternAs::<IUIAutomationValuePattern>(UIA_ValuePatternId)
                    .ok()
                    .and_then(|pattern| pattern.CurrentValue().ok())
                    .map(|value| value.to_string())
            } else {
                None
            };
            self.emit(CaptureKind::ValueChanged, password, value);
        }
    }
}

unsafe extern "system" fn event_callback(
    _hook: HWINEVENTHOOK,
    event: u32,
    hwnd: HWND,
    object: i32,
    child: i32,
    _thread: u32,
    _time: u32,
) {
    if !event_source_is_valid(!hwnd.is_invalid(), object, child) {
        return;
    }
    let active = match RECORDINGS.lock() {
        Ok(active) => active,
        Err(_) => return,
    };
    let sessions: Vec<Arc<Session>> = active.values().cloned().collect();
    drop(active);
    for session in sessions {
        if session.stopped.load(Ordering::Relaxed) {
            continue;
        }
        // Chromium and other apps can raise WinEvents from a renderer process
        // that differs from the selected top-level window's process. Scope
        // them by root-owner HWND, which keeps capture inside that one window.
        let root = unsafe { GetAncestor(hwnd, GA_ROOTOWNER) };
        if hwnd_id(root) != hwnd_id(HWND(session.hwnd as *mut core::ffi::c_void)) {
            continue;
        }
        let kind = match event {
            EVENT_OBJECT_FOCUS => CaptureKind::Focus,
            EVENT_OBJECT_INVOKED => CaptureKind::Invoked,
            EVENT_OBJECT_SELECTION => CaptureKind::Selected,
            EVENT_OBJECT_STATECHANGE => CaptureKind::StateChange,
            EVENT_OBJECT_CREATE | EVENT_OBJECT_SHOW => CaptureKind::WindowOpened,
            EVENT_OBJECT_DESTROY => CaptureKind::WindowClosed,
            EVENT_OBJECT_VALUECHANGE => CaptureKind::ValueChanged,
            _ => continue,
        };
        // WinEvent focus records deliberately carry no UIA text/name/value.
        // Values are only sourced from the event HWND's UIA Value pattern,
        // after the password bit has been positively read as false.
        if kind == CaptureKind::ValueChanged {
            session.emit_value_from(hwnd);
        } else {
            session.emit(kind, None, None);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::event_source_is_valid;

    #[test]
    fn keeps_accessible_child_events() {
        assert!(event_source_is_valid(true, -4, 1));
    }
}

pub(in crate::computer_app) fn list_windows() -> Result<Value, String> {
    let foreground = unsafe { GetForegroundWindow() };
    let mut rows: Vec<_> = top_level_windows()
        .into_iter()
        .filter_map(describe_window)
        .filter(|row| row.pid != unsafe { GetCurrentProcessId() } && !row.minimized)
        .filter(|row| attach_refusal(row).is_none())
        .collect();
    rows.sort_by(|a, b| {
        a.app
            .to_lowercase()
            .cmp(&b.app.to_lowercase())
            .then(a.title.to_lowercase().cmp(&b.title.to_lowercase()))
    });
    Ok(json!(rows
        .iter()
        .map(|row| row.to_json(foreground))
        .collect::<Vec<_>>()))
}

pub(in crate::computer_app) fn start(
    app: tauri::AppHandle,
    id: String,
    window_id: u64,
) -> Result<Value, String> {
    if id.is_empty()
        || id.len() > 80
        || !id
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
    {
        return Err("Invalid recording id.".into());
    }
    let hwnd = to_hwnd(window_id as isize);
    let row = describe_window(hwnd).ok_or("Selected window is no longer available.")?;
    if row.minimized
        || attach_refusal(&row).is_some()
        || row.pid == unsafe { GetCurrentProcessId() }
    {
        return Err("This window cannot be recorded.".into());
    }
    let session = Arc::new(Session {
        id: id.clone(),
        hwnd: hwnd.0 as isize,
        pid: row.pid,
        app,
        started: Instant::now(),
        sequence: AtomicU64::new(0),
        emit_lock: Mutex::new(()),
        paused: AtomicBool::new(false),
        stopped: AtomicBool::new(false),
    });
    {
        let mut active = RECORDINGS
            .lock()
            .map_err(|_| "Recorder registry unavailable.")?;
        if active.contains_key(&id) {
            return Err("Recording id is already active.".into());
        }
        active.insert(id.clone(), session.clone());
    }
    let observer = session.clone();
    thread::Builder::new()
        .name("skill-recording-observer".into())
        .spawn(move || observer_loop(observer))
        .map_err(|error| {
            if let Ok(mut active) = RECORDINGS.lock() {
                active.remove(&id);
            }
            format!("Could not start observer: {error}")
        })?;
    Ok(
        json!({"recording_id": session.id, "window_id": window_id, "process_id": session.pid, "status": "recording"}),
    )
}

fn observer_loop(session: Arc<Session>) {
    unsafe {
        let _ = CoInitializeEx(None, COINIT_MULTITHREADED);
        let hooks: Vec<HWINEVENTHOOK> = [
            EVENT_OBJECT_FOCUS,
            EVENT_OBJECT_INVOKED,
            EVENT_OBJECT_SELECTION,
            EVENT_OBJECT_VALUECHANGE,
            EVENT_OBJECT_STATECHANGE,
            EVENT_OBJECT_CREATE,
            EVENT_OBJECT_DESTROY,
            EVENT_OBJECT_SHOW,
        ]
        .into_iter()
        .filter_map(|event| {
            let hook = SetWinEventHook(
                event,
                event,
                None,
                Some(event_callback),
                0,
                0,
                WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS,
            );
            (!hook.0.is_null()).then_some(hook)
        })
        .collect();

        // Poll messages so stop and shutdown cannot leave a blocked observer.
        let mut message = MSG::default();
        while !session.stopped.load(Ordering::Acquire) {
            if !IsWindow(Some(HWND(session.hwnd as *mut core::ffi::c_void))).as_bool() {
                session.emit(CaptureKind::WindowClosed, None, None);
                session.stopped.store(true, Ordering::Release);
                break;
            }
            while PeekMessageW(&mut message, None, 0, 0, PM_REMOVE).as_bool() {
                let _ = DispatchMessageW(&message);
            }
            thread::sleep(Duration::from_millis(25));
        }
        for hook in hooks {
            let _ = UnhookWinEvent(hook);
        }
        windows::Win32::System::Com::CoUninitialize();
    }
    if let Ok(mut active) = RECORDINGS.lock() {
        active.remove(&session.id);
    }
}

pub(in crate::computer_app) fn pause(id: &str) -> Result<Value, String> {
    let session = lookup(id)?;
    session.paused.store(true, Ordering::Release);
    Ok(json!({"status":"paused"}))
}
pub(in crate::computer_app) fn resume(id: &str) -> Result<Value, String> {
    let session = lookup(id)?;
    session.paused.store(false, Ordering::Release);
    Ok(json!({"status":"recording"}))
}
pub(in crate::computer_app) fn checkpoint(id: &str) -> Result<Value, String> {
    let session = lookup(id)?;
    if session.paused.load(Ordering::Acquire) {
        return Err("Resume recording before taking a checkpoint.".into());
    }
    let hwnd = HWND(session.hwnd as *mut core::ffi::c_void);
    let image = capture(hwnd)?;
    let encoded = encode_png(&image)?;
    if encoded.len() > 3 * 1024 * 1024 {
        return Err("Screenshot exceeds the recording size limit.".into());
    }
    session.emit_screenshot(encoded)?;
    Ok(json!({"captured":true}))
}
pub(in crate::computer_app) fn stop(id: &str) -> Result<Value, String> {
    let session = lookup(id)?;
    session.stopped.store(true, Ordering::Release);
    Ok(json!({"status":"stopping"}))
}
pub(in crate::computer_app) fn stop_all() {
    let sessions: Vec<_> = RECORDINGS
        .lock()
        .map(|active| active.values().cloned().collect())
        .unwrap_or_default();
    for session in sessions {
        session.stopped.store(true, Ordering::Release);
    }
}
fn lookup(id: &str) -> Result<Arc<Session>, String> {
    RECORDINGS
        .lock()
        .map_err(|_| "Recorder registry unavailable.".to_string())?
        .get(id)
        .cloned()
        .ok_or_else(|| "Recording session not found.".into())
}

impl Session {
    fn emit_screenshot(&self, screenshot: String) -> Result<(), String> {
        let _emit_guard = self
            .emit_lock
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        if self.stopped.load(Ordering::Acquire) {
            return Err("Recording has stopped.".into());
        }
        let event = normalize_observation(
            self.sequence.fetch_add(1, Ordering::Relaxed) + 1,
            self.started.elapsed().as_millis() as u64,
            &SelectedTarget {
                window_id: hwnd_id(HWND(self.hwnd as *mut core::ffi::c_void)),
            },
            CaptureObservation {
                root_window_id: hwnd_id(HWND(self.hwnd as *mut core::ffi::c_void)),
                kind: CaptureKind::Screenshot,
                point: None,
                button: None,
                scroll_delta: None,
                target: None,
                is_password: None,
                value: None,
                screenshot: Some(screenshot),
            },
        )
        .ok_or("Checkpoint did not match the selected app.")?;
        self.app
            .emit(
                crate::computer_app::SKILL_RECORDING_EVENT,
                json!({"recording_id": self.id, "event": event}),
            )
            .map_err(|error| error.to_string())
    }
}
