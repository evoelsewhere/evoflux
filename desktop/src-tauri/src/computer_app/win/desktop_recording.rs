//! Target-independent Windows pointer observation for skill demonstrations.
//!
//! The low-level hook only copies bounded mouse metadata into a queue. Event
//! serialization and Tauri emission happen on the observer thread. It never
//! reads keystrokes, clipboard contents, or target-window text.

use super::*;
use crate::computer_app::recording::{
    normalize_observation, CaptureKind, CaptureObservation, ElementTarget, PointerButton,
    PointerPoint, ScrollDelta, SelectedTarget, WindowContext,
};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::mpsc::{self, SyncSender, TryRecvError, TrySendError};
use std::thread;
use std::time::Instant;
use tauri::Emitter;
use windows::Win32::Foundation::{LPARAM, LRESULT, POINT, WPARAM};
use windows::Win32::System::Com::{
    CoCreateInstance, CoInitializeEx, CoUninitialize, CLSCTX_INPROC_SERVER, COINIT_MULTITHREADED,
};
use windows::Win32::UI::Accessibility::{
    CUIAutomation, IUIAutomation, IUIAutomationValuePattern, SetWinEventHook, UIA_ValuePatternId,
    UnhookWinEvent, HWINEVENTHOOK,
};
use windows::Win32::UI::WindowsAndMessaging::{
    CallNextHookEx, DispatchMessageW, PeekMessageW, SetWindowsHookExW, UnhookWindowsHookEx,
    HC_ACTION, MSLLHOOKSTRUCT, PM_REMOVE, WH_MOUSE_LL, WM_LBUTTONDBLCLK, WM_LBUTTONDOWN,
    WM_MBUTTONDBLCLK, WM_MBUTTONDOWN, WM_MOUSEHWHEEL, WM_MOUSEWHEEL, WM_RBUTTONDBLCLK,
    WM_RBUTTONDOWN,
};
use windows::Win32::UI::WindowsAndMessaging::{
    GetAncestor, GetForegroundWindow, WindowFromPoint, EVENT_OBJECT_FOCUS,
    EVENT_OBJECT_VALUECHANGE, EVENT_SYSTEM_FOREGROUND, GA_ROOTOWNER, WINEVENT_OUTOFCONTEXT,
    WINEVENT_SKIPOWNPROCESS,
};

const MOUSE_QUEUE_CAPACITY: usize = 256;

static HOOK_ACTIVE: AtomicBool = AtomicBool::new(false);
static MOUSE_SINK: Lazy<Mutex<Option<SyncSender<RawDesktopEvent>>>> =
    Lazy::new(|| Mutex::new(None));
static MOUSE_DROPPED: AtomicBool = AtomicBool::new(false);
static MOUSE_PAUSED: AtomicBool = AtomicBool::new(false);
static DESKTOP_SESSIONS: Lazy<Mutex<HashMap<String, Arc<DesktopSession>>>> =
    Lazy::new(|| Mutex::new(HashMap::new()));

struct DesktopSession {
    id: String,
    app: tauri::AppHandle,
    started: Instant,
    sequence: AtomicU64,
    paused: AtomicBool,
    stopped: AtomicBool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct RawMouseEvent {
    message: u32,
    x: i32,
    y: i32,
    wheel_delta: i16,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum RawDesktopEvent {
    Mouse(RawMouseEvent),
    ForegroundChanged,
    Accessibility { kind: CaptureKind, hwnd: isize },
}

fn classify_mouse_event(raw: RawMouseEvent) -> Option<CaptureObservation> {
    let (kind, point, button, scroll_delta) = match raw.message {
        WM_LBUTTONDOWN => (
            CaptureKind::Click,
            Some(PointerPoint {
                x: raw.x,
                y: raw.y,
                display_id: None,
            }),
            Some(PointerButton::Left),
            None,
        ),
        WM_LBUTTONDBLCLK => (
            CaptureKind::DoubleClick,
            Some(PointerPoint {
                x: raw.x,
                y: raw.y,
                display_id: None,
            }),
            Some(PointerButton::Left),
            None,
        ),
        WM_MBUTTONDOWN => (
            CaptureKind::Click,
            Some(PointerPoint {
                x: raw.x,
                y: raw.y,
                display_id: None,
            }),
            Some(PointerButton::Middle),
            None,
        ),
        WM_MBUTTONDBLCLK => (
            CaptureKind::DoubleClick,
            Some(PointerPoint {
                x: raw.x,
                y: raw.y,
                display_id: None,
            }),
            Some(PointerButton::Middle),
            None,
        ),
        WM_RBUTTONDOWN => (
            CaptureKind::Click,
            Some(PointerPoint {
                x: raw.x,
                y: raw.y,
                display_id: None,
            }),
            Some(PointerButton::Right),
            None,
        ),
        WM_RBUTTONDBLCLK => (
            CaptureKind::DoubleClick,
            Some(PointerPoint {
                x: raw.x,
                y: raw.y,
                display_id: None,
            }),
            Some(PointerButton::Right),
            None,
        ),
        WM_MOUSEWHEEL => (
            CaptureKind::Scroll,
            Some(PointerPoint {
                x: raw.x,
                y: raw.y,
                display_id: None,
            }),
            None,
            Some(ScrollDelta {
                x: 0,
                y: i32::from(raw.wheel_delta),
            }),
        ),
        WM_MOUSEHWHEEL => (
            CaptureKind::Scroll,
            Some(PointerPoint {
                x: raw.x,
                y: raw.y,
                display_id: None,
            }),
            None,
            Some(ScrollDelta {
                x: i32::from(raw.wheel_delta),
                y: 0,
            }),
        ),
        _ => return None,
    };

    Some(CaptureObservation {
        root_window_id: 0,
        window: None,
        kind,
        point,
        button,
        scroll_delta,
        target: None,
        is_password: None,
        value: None,
        screenshot: None,
    })
}

unsafe extern "system" fn mouse_hook_callback(
    code: i32,
    wparam: WPARAM,
    lparam: LPARAM,
) -> LRESULT {
    if code == HC_ACTION as i32 && !MOUSE_PAUSED.load(Ordering::Acquire) {
        let message = wparam.0 as u32;
        if matches!(
            message,
            WM_LBUTTONDOWN
                | WM_LBUTTONDBLCLK
                | WM_MBUTTONDOWN
                | WM_MBUTTONDBLCLK
                | WM_RBUTTONDOWN
                | WM_RBUTTONDBLCLK
                | WM_MOUSEWHEEL
                | WM_MOUSEHWHEEL
        ) {
            let event = unsafe { &*(lparam.0 as *const MSLLHOOKSTRUCT) };
            let wheel_delta = (event.mouseData >> 16) as u16 as i16;
            let raw = RawDesktopEvent::Mouse(RawMouseEvent {
                message,
                x: event.pt.x,
                y: event.pt.y,
                wheel_delta,
            });
            let sink = MOUSE_SINK
                .lock()
                .ok()
                .and_then(|guard| guard.as_ref().cloned());
            if let Some(sink) = sink {
                if matches!(sink.try_send(raw), Err(TrySendError::Full(_))) {
                    MOUSE_DROPPED.store(true, Ordering::Release);
                }
            }
        }
    }
    unsafe { CallNextHookEx(None, code, wparam, lparam) }
}

unsafe extern "system" fn foreground_event_callback(
    _hook: HWINEVENTHOOK,
    event: u32,
    _hwnd: HWND,
    _object: i32,
    _child: i32,
    _thread: u32,
    _time: u32,
) {
    if event != EVENT_SYSTEM_FOREGROUND {
        return;
    }
    let sink = MOUSE_SINK
        .lock()
        .ok()
        .and_then(|guard| guard.as_ref().cloned());
    if let Some(sink) = sink {
        if matches!(
            sink.try_send(RawDesktopEvent::ForegroundChanged),
            Err(TrySendError::Full(_))
        ) {
            MOUSE_DROPPED.store(true, Ordering::Release);
        }
    }
}

unsafe extern "system" fn accessibility_event_callback(
    _hook: HWINEVENTHOOK,
    event: u32,
    hwnd: HWND,
    _object: i32,
    _child: i32,
    _thread: u32,
    _time: u32,
) {
    if MOUSE_PAUSED.load(Ordering::Acquire) || hwnd.is_invalid() {
        return;
    }
    let kind = match event {
        EVENT_OBJECT_FOCUS => CaptureKind::Focus,
        EVENT_OBJECT_VALUECHANGE => CaptureKind::ValueChanged,
        _ => return,
    };
    let sink = MOUSE_SINK
        .lock()
        .ok()
        .and_then(|guard| guard.as_ref().cloned());
    if let Some(sink) = sink {
        if matches!(
            sink.try_send(RawDesktopEvent::Accessibility {
                kind,
                hwnd: hwnd.0 as isize,
            }),
            Err(TrySendError::Full(_))
        ) {
            MOUSE_DROPPED.store(true, Ordering::Release);
        }
    }
}

fn window_context(hwnd: HWND) -> Option<WindowContext> {
    let root = unsafe { GetAncestor(hwnd, GA_ROOTOWNER) };
    if root.is_invalid() {
        return None;
    }
    let row = super::listing::describe_window(root)?;
    Some(WindowContext {
        app: Some(row.app),
        title: Some(row.title),
    })
}

fn target_from_element(
    element: &windows::Win32::UI::Accessibility::IUIAutomationElement,
) -> Option<ElementTarget> {
    unsafe {
        let control_type = element
            .CurrentControlType()
            .ok()
            .map(|id| super::uia_tree::control_type_name(id.0).to_string());
        let name = element.CurrentName().ok().map(|value| value.to_string());
        let automation_id = element
            .CurrentAutomationId()
            .ok()
            .map(|value| value.to_string());
        let label = element
            .CurrentLabeledBy()
            .ok()
            .and_then(|label| label.CurrentName().ok())
            .map(|value| value.to_string());
        Some(ElementTarget {
            automation_id: automation_id.filter(|value| !value.trim().is_empty()),
            control_type,
            name: name.filter(|value| !value.trim().is_empty()),
            label: label.filter(|value| !value.trim().is_empty()),
        })
    }
}

fn focused_element_context(
    event_hwnd: HWND,
    kind: CaptureKind,
) -> (Option<ElementTarget>, Option<bool>, Option<String>) {
    unsafe {
        let automation: IUIAutomation =
            match CoCreateInstance(&CUIAutomation, None, CLSCTX_INPROC_SERVER) {
                Ok(automation) => automation,
                Err(_) => return (target_from_window(event_hwnd), None, None),
            };
        let element = match automation.GetFocusedElement() {
            Ok(element) => element,
            Err(_) => return (target_from_window(event_hwnd), None, None),
        };
        let event_root = GetAncestor(event_hwnd, GA_ROOTOWNER);
        let element_hwnd = element.CurrentNativeWindowHandle().unwrap_or_default();
        if !element_hwnd.is_invalid() && GetAncestor(element_hwnd, GA_ROOTOWNER) != event_root {
            return (target_from_window(event_hwnd), None, None);
        }

        let password = element
            .CurrentIsPassword()
            .ok()
            .map(|value| value.as_bool());
        let editable_control = element
            .CurrentControlType()
            .ok()
            .map(|control_type| matches!(control_type.0, 50003 | 50004))
            .unwrap_or(false);
        let value = if kind == CaptureKind::ValueChanged
            && password == Some(false)
            && editable_control
        {
            element
                .GetCurrentPatternAs::<IUIAutomationValuePattern>(UIA_ValuePatternId)
                .ok()
                .and_then(|pattern| pattern.CurrentValue().ok())
                .map(|value| value.to_string())
                .filter(|value| value.len() <= 16_384)
        } else {
            None
        };
        (target_from_element(&element), password, value)
    }
}

fn target_from_point(point: POINT) -> Option<ElementTarget> {
    unsafe {
        let automation: IUIAutomation =
            CoCreateInstance(&CUIAutomation, None, CLSCTX_INPROC_SERVER).ok()?;
        let element = automation.ElementFromPoint(point).ok()?;
        target_from_element(&element)
    }
}

fn target_from_window(hwnd: HWND) -> Option<ElementTarget> {
    unsafe {
        let automation: IUIAutomation =
            CoCreateInstance(&CUIAutomation, None, CLSCTX_INPROC_SERVER).ok()?;
        let element = automation.ElementFromHandle(hwnd).ok()?;
        target_from_element(&element)
    }
}

impl DesktopSession {
    fn emit(&self, observation: CaptureObservation) {
        if self.paused.load(Ordering::Acquire) || self.stopped.load(Ordering::Acquire) {
            return;
        }
        let sequence = self.sequence.fetch_add(1, Ordering::Relaxed) + 1;
        let event = match normalize_observation(
            sequence,
            self.started.elapsed().as_millis() as u64,
            &SelectedTarget { window_id: 0 },
            observation,
        ) {
            Some(event) => event,
            None => return,
        };
        let _ = self.app.emit(
            crate::computer_app::SKILL_RECORDING_EVENT,
            json!({"recording_id": self.id, "event": event}),
        );
    }
}

pub(in crate::computer_app) fn start(app: tauri::AppHandle, id: String) -> Result<Value, String> {
    if id.is_empty()
        || id.len() > 80
        || !id.chars().all(|character| {
            character.is_ascii_alphanumeric() || character == '-' || character == '_'
        })
    {
        return Err("Invalid recording id.".into());
    }
    if HOOK_ACTIVE
        .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
        .is_err()
    {
        return Err("A desktop recording is already active.".into());
    }

    let session = Arc::new(DesktopSession {
        id: id.clone(),
        app,
        started: Instant::now(),
        sequence: AtomicU64::new(0),
        paused: AtomicBool::new(false),
        stopped: AtomicBool::new(false),
    });
    let id_is_active = match DESKTOP_SESSIONS.lock() {
        Ok(sessions) => sessions.contains_key(&id),
        Err(_) => {
            HOOK_ACTIVE.store(false, Ordering::Release);
            return Err("Desktop recorder registry is unavailable.".into());
        }
    };
    if id_is_active {
        HOOK_ACTIVE.store(false, Ordering::Release);
        return Err("Recording id is already active.".into());
    }
    MOUSE_DROPPED.store(false, Ordering::Release);
    MOUSE_PAUSED.store(false, Ordering::Release);
    let (ready_tx, ready_rx) = mpsc::sync_channel(1);
    let observer = session.clone();
    if let Err(error) = thread::Builder::new()
        .name("skill-desktop-pointer-observer".into())
        .spawn(move || observer_loop(observer, ready_tx))
    {
        HOOK_ACTIVE.store(false, Ordering::Release);
        return Err(format!("Could not start desktop pointer observer: {error}"));
    }

    match ready_rx.recv_timeout(Duration::from_secs(3)) {
        Ok(Ok(())) => {
            match DESKTOP_SESSIONS.lock() {
                Ok(mut sessions) => {
                    sessions.insert(id.clone(), session);
                }
                Err(_) => {
                    session.stopped.store(true, Ordering::Release);
                    return Err("Desktop recorder registry is unavailable.".into());
                }
            }
            Ok(json!({"recording_id": id, "status": "recording"}))
        }
        Ok(Err(error)) => {
            session.stopped.store(true, Ordering::Release);
            HOOK_ACTIVE.store(false, Ordering::Release);
            Err(error)
        }
        Err(error) => {
            session.stopped.store(true, Ordering::Release);
            Err(format!(
                "Desktop pointer observer did not become ready: {error}"
            ))
        }
    }
}

fn observer_loop(session: Arc<DesktopSession>, ready: SyncSender<Result<(), String>>) {
    unsafe {
        let _ = CoInitializeEx(None, COINIT_MULTITHREADED);
    }
    let (sender, receiver) = mpsc::sync_channel(MOUSE_QUEUE_CAPACITY);
    if let Ok(mut sink) = MOUSE_SINK.lock() {
        *sink = Some(sender);
    } else {
        let _ = ready.send(Err("Desktop pointer queue is unavailable.".into()));
        HOOK_ACTIVE.store(false, Ordering::Release);
        return;
    }
    let hook = unsafe { SetWindowsHookExW(WH_MOUSE_LL, Some(mouse_hook_callback), None, 0) };
    let hook = match hook {
        Ok(hook) => hook,
        Err(error) => {
            if let Ok(mut sink) = MOUSE_SINK.lock() {
                *sink = None;
            }
            let _ = ready.send(Err(format!(
                "Could not start desktop pointer hook: {error}"
            )));
            HOOK_ACTIVE.store(false, Ordering::Release);
            return;
        }
    };
    let foreground_hook = unsafe {
        SetWinEventHook(
            EVENT_SYSTEM_FOREGROUND,
            EVENT_SYSTEM_FOREGROUND,
            None,
            Some(foreground_event_callback),
            0,
            0,
            WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS,
        )
    };
    let foreground_hook = (!foreground_hook.0.is_null()).then_some(foreground_hook);
    let accessibility_hooks: Vec<HWINEVENTHOOK> = [EVENT_OBJECT_FOCUS, EVENT_OBJECT_VALUECHANGE]
        .into_iter()
        .filter_map(|event| {
            let hook = unsafe {
                SetWinEventHook(
                    event,
                    event,
                    None,
                    Some(accessibility_event_callback),
                    0,
                    0,
                    WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS,
                )
            };
            (!hook.0.is_null()).then_some(hook)
        })
        .collect();
    let _ = ready.send(Ok(()));

    let mut message = MSG::default();
    while !session.stopped.load(Ordering::Acquire) {
        while unsafe { PeekMessageW(&mut message, None, 0, 0, PM_REMOVE) }.as_bool() {
            let _ = unsafe { DispatchMessageW(&message) };
        }
        loop {
            match receiver.try_recv() {
                Ok(raw) => {
                    if MOUSE_DROPPED.swap(false, Ordering::AcqRel) {
                        session.emit(CaptureObservation {
                            root_window_id: 0,
                            window: None,
                            kind: CaptureKind::Gap,
                            point: None,
                            button: None,
                            scroll_delta: None,
                            target: None,
                            is_password: None,
                            value: None,
                            screenshot: None,
                        });
                    }
                    match raw {
                        RawDesktopEvent::Mouse(mouse) => {
                            if let Some(mut observation) = classify_mouse_event(mouse) {
                                if let Some(point) = observation.point.as_ref() {
                                    let screen_point = POINT {
                                        x: point.x,
                                        y: point.y,
                                    };
                                    let hwnd = unsafe { WindowFromPoint(screen_point) };
                                    observation.window = window_context(hwnd);
                                    observation.target = target_from_point(screen_point);
                                }
                                session.emit(observation);
                            }
                        }
                        RawDesktopEvent::ForegroundChanged => {
                            let foreground = unsafe { GetForegroundWindow() };
                            session.emit(CaptureObservation {
                                root_window_id: 0,
                                window: window_context(foreground),
                                kind: CaptureKind::WindowChange,
                                point: None,
                                button: None,
                                scroll_delta: None,
                                target: None,
                                is_password: None,
                                value: None,
                                screenshot: None,
                            });
                        }
                        RawDesktopEvent::Accessibility { kind, hwnd } => {
                            let hwnd = HWND(hwnd as *mut core::ffi::c_void);
                            let (target, is_password, value) = focused_element_context(hwnd, kind);
                            session.emit(CaptureObservation {
                                root_window_id: unsafe { hwnd_id(GetAncestor(hwnd, GA_ROOTOWNER)) },
                                window: window_context(hwnd),
                                kind,
                                point: None,
                                button: None,
                                scroll_delta: None,
                                target,
                                is_password,
                                value,
                                screenshot: None,
                            });
                        }
                    }
                }
                Err(TryRecvError::Empty | TryRecvError::Disconnected) => break,
            }
        }
        thread::sleep(Duration::from_millis(8));
    }

    let _ = unsafe { UnhookWindowsHookEx(hook) };
    if let Some(foreground_hook) = foreground_hook {
        let _ = unsafe { UnhookWinEvent(foreground_hook) };
    }
    for hook in accessibility_hooks {
        let _ = unsafe { UnhookWinEvent(hook) };
    }
    if let Ok(mut sink) = MOUSE_SINK.lock() {
        *sink = None;
    }
    HOOK_ACTIVE.store(false, Ordering::Release);
    unsafe {
        CoUninitialize();
    }
}

pub(in crate::computer_app) fn contains(id: &str) -> bool {
    DESKTOP_SESSIONS
        .lock()
        .map(|sessions| sessions.contains_key(id))
        .unwrap_or(false)
}

pub(in crate::computer_app) fn pause(id: &str) -> Result<Value, String> {
    let session = lookup(id)?;
    session.paused.store(true, Ordering::Release);
    MOUSE_PAUSED.store(true, Ordering::Release);
    Ok(json!({"status":"paused"}))
}

pub(in crate::computer_app) fn resume(id: &str) -> Result<Value, String> {
    let session = lookup(id)?;
    session.paused.store(false, Ordering::Release);
    MOUSE_PAUSED.store(false, Ordering::Release);
    Ok(json!({"status":"recording"}))
}

pub(in crate::computer_app) fn stop(id: &str) -> Result<Value, String> {
    let session = lookup(id)?;
    session.stopped.store(true, Ordering::Release);
    if let Ok(mut sessions) = DESKTOP_SESSIONS.lock() {
        sessions.remove(id);
    }
    Ok(json!({"status":"stopping"}))
}

pub(in crate::computer_app) fn stop_all() {
    let sessions = DESKTOP_SESSIONS
        .lock()
        .map(|sessions| sessions.values().cloned().collect::<Vec<_>>())
        .unwrap_or_default();
    for session in sessions {
        session.stopped.store(true, Ordering::Release);
    }
}

fn lookup(id: &str) -> Result<Arc<DesktopSession>, String> {
    DESKTOP_SESSIONS
        .lock()
        .map_err(|_| "Desktop recorder registry is unavailable.".to_string())?
        .get(id)
        .cloned()
        .ok_or_else(|| "Desktop recording session not found.".into())
}

#[cfg(test)]
mod tests {
    use super::{classify_mouse_event, RawMouseEvent};
    use crate::computer_app::recording::{CaptureKind, PointerButton};
    use windows::Win32::UI::WindowsAndMessaging::{
        WM_LBUTTONDBLCLK, WM_LBUTTONDOWN, WM_MOUSEHWHEEL, WM_MOUSEWHEEL,
    };

    fn raw(message: u32, x: i32, y: i32, wheel_delta: i16) -> RawMouseEvent {
        RawMouseEvent {
            message,
            x,
            y,
            wheel_delta,
        }
    }

    #[test]
    fn captures_clicks_and_double_clicks_with_signed_desktop_coordinates() {
        let click = classify_mouse_event(raw(WM_LBUTTONDOWN, -10, 42, 0)).unwrap();
        assert_eq!(click.kind, CaptureKind::Click);
        assert_eq!(click.point.unwrap().x, -10);
        assert_eq!(click.button, Some(PointerButton::Left));

        let double = classify_mouse_event(raw(WM_LBUTTONDBLCLK, 10, 42, 0)).unwrap();
        assert_eq!(double.kind, CaptureKind::DoubleClick);
    }

    #[test]
    fn maps_vertical_and_horizontal_wheel_deltas_without_key_data() {
        let vertical = classify_mouse_event(raw(WM_MOUSEWHEEL, 12, 34, -120)).unwrap();
        assert_eq!(vertical.kind, CaptureKind::Scroll);
        assert_eq!(vertical.scroll_delta.unwrap().y, -120);

        let horizontal = classify_mouse_event(raw(WM_MOUSEHWHEEL, 12, 34, 120)).unwrap();
        assert_eq!(horizontal.scroll_delta.unwrap().x, 120);
    }
}
