//! Which window each chat session drives, and the session-level controls
//! the user holds over it: Stop, Resume, Reveal, release on exit. Also the
//! element refs a session's snapshots handed out.

use super::*;

// ── Session registry ────────────────────────────────────────────────────

#[derive(Clone, Copy)]
pub(super) struct Parked {
    /// Where the window's top-left corner was before it was parked.
    pub(super) origin: (f64, f64),
    /// It was minimized, and goes back to the Dock on release.
    pub(super) minimized: bool,
}

#[derive(Clone)]
pub(super) struct Attached {
    pub(super) window_id: u32,
    pub(super) pid: i32,
    pub(super) app: String,
    pub(super) title: String,
    pub(super) parked: Option<Parked>,
    /// Chromium/Electron content, whose accessibility tree EvoFlux turned on.
    pub(super) web: bool,
}

#[derive(Default)]
pub(super) struct Registry {
    pub(super) attached: HashMap<String, Attached>,
    /// Sessions whose user pressed Stop. Attaching is refused until the user
    /// resumes from the preview card; the agent cannot lift this itself.
    pub(super) stopped: HashSet<String>,
}

static REGISTRY: Lazy<Mutex<Registry>> = Lazy::new(|| Mutex::new(Registry::default()));

pub(super) fn registry() -> std::sync::MutexGuard<'static, Registry> {
    REGISTRY.lock().unwrap_or_else(|poisoned| poisoned.into_inner())
}

/// Forget the session's window and put it back where the user left it.
pub(super) fn release(session_id: &str) -> Option<Attached> {
    let released = registry().attached.remove(session_id);
    clear_refs(session_id);
    if let Some(attached) = &released {
        let still_used = registry().attached.values().any(|other| other.pid == attached.pid);
        if let Some(app) = Ax::application(attached.pid) {
            // Chromium does extra accessibility work while its enhanced
            // interface is on (and window managers stop animating it); it is
            // handed back off unless another chat still drives the app.
            match attached.parked {
                Some(parked) => match reach_window(&app, attached.window_id) {
                    Some(window) => hand_back(&app, &window, parked, false, attached.web, still_used),
                    None => put_back_later(attached.pid, attached.window_id, parked, attached.web),
                },
                None if attached.web && !still_used => {
                    let _ = app.set_flag("AXEnhancedUserInterface", false);
                }
                None => {}
            }
        }
    }
    released
}

/// The window, asked for a few times: accessibility can fail for a moment
/// (see [`Target::resolve`]). `None` at once for a window that is gone.
pub(super) fn reach_window(app: &Ax, id: u32) -> Option<Ax> {
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
fn put_back_later(pid: i32, window_id: u32, parked: Parked, web: bool) {
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
                let Some(app) = Ax::application(pid) else {
                    continue;
                };
                if let Some(window) = ax_window(&app, window_id) {
                    let still_used = registry().attached.values().any(|attached| attached.pid == pid);
                    hand_back(&app, &window, parked, false, web, still_used);
                    return;
                }
            }
        });
}

pub(super) fn stop(session_id: &str) {
    registry().stopped.insert(session_id.to_string());
    release(session_id);
}

pub(super) fn resume(session_id: &str) {
    registry().stopped.remove(session_id);
}

/// Put every parked window back. Called when EvoFlux exits so no app is
/// left stranded in a corner of the screen.
pub(super) fn release_all() {
    let sessions: Vec<String> = registry().attached.keys().cloned().collect();
    for session in sessions {
        release(&session);
    }
}

pub(super) fn reveal(session_id: &str) -> Result<Value, String> {
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
        // Still attached, so the app keeps its enhanced interface.
        Some(parked) => hand_back(&app, &window, parked, true, attached.web, true),
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

// ── Element refs ────────────────────────────────────────────────────────
//
// Element refs are Core Foundation objects that have to outlive a single
// command and are not `Send`. Each session's worker thread (see
// `workers.rs`) owns its own and runs its actions one at a time; nothing
// needs setting up.

thread_local! {
    pub(super) static REFS: RefCell<HashMap<String, SessionRefs>> = RefCell::new(HashMap::new());
    /// The editable element each session last clicked, where `type` goes
    /// when the app reports no focused field of its own.
    pub(super) static LAST_EDITABLE: RefCell<HashMap<String, Ax>> = RefCell::new(HashMap::new());
}

#[derive(Default)]
pub(super) struct SessionRefs {
    pub(super) next: u32,
    pub(super) elements: HashMap<String, Ax>,
}

/// Drop the session's element refs. They live on the thread that ran the
/// action — the session's worker, in the app — so a release from elsewhere
/// (Stop, exit) also hands the clean-up to that worker, behind whatever it
/// is running.
pub(super) fn clear_refs(session_id: &str) {
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
