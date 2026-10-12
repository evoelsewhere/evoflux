//! Target-independent Windows pointer observation for skill demonstrations.
//!
//! The low-level hook only copies bounded mouse metadata into a queue. Event
//! serialization and Tauri emission happen on the observer thread. It never
//! reads keystrokes, clipboard contents, or target-window text.

use super::*;
use crate::computer_app::recording::{
    normalize_observation, CaptureKind, CaptureObservation, PointerButton, PointerPoint,
    ScrollDelta, SelectedTarget,
};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::mpsc::{self, SyncSender, TryRecvError, TrySendError};
use std::thread;
use std::time::Instant;
use tauri::Emitter;
use windows::Win32::Foundation::{LPARAM, LRESULT, WPARAM};
use windows::Win32::UI::Accessibility::{SetWinEventHook, UnhookWinEvent, HWINEVENTHOOK};
use windows::Win32::UI::WindowsAndMessaging::{
    CallNextHookEx, DispatchMessageW, PeekMessageW, SetWindowsHookExW, UnhookWindowsHookEx,
    HC_ACTION, MSLLHOOKSTRUCT, PM_REMOVE, WH_MOUSE_LL, WM_LBUTTONDBLCLK, WM_LBUTTONDOWN,
    WM_MBUTTONDBLCLK, WM_MBUTTONDOWN, WM_MOUSEHWHEEL, WM_MOUSEWHEEL, WM_RBUTTONDBLCLK,
    WM_RBUTTONDOWN,
};
use windows::Win32::UI::WindowsAndMessaging::{
    EVENT_SYSTEM_FOREGROUND, WINEVENT_OUTOFCONTEXT, WINEVENT_SKIPOWNPROCESS,
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
                            if let Some(observation) = classify_mouse_event(mouse) {
                                session.emit(observation);
                            }
                        }
                        RawDesktopEvent::ForegroundChanged => session.emit(CaptureObservation {
                            root_window_id: 0,
                            kind: CaptureKind::WindowChange,
                            point: None,
                            button: None,
                            scroll_delta: None,
                            target: None,
                            is_password: None,
                            value: None,
                            screenshot: None,
                        }),
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
    if let Ok(mut sink) = MOUSE_SINK.lock() {
        *sink = None;
    }
    HOOK_ACTIVE.store(false, Ordering::Release);
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
