//! Which window each chat session drives, and the session-level controls
//! the user holds over it: Stop, Resume, Reveal, release on exit. Also the
//! element refs a session's snapshots handed out.

use super::*;

// ── Session registry ────────────────────────────────────────────────────

#[derive(Clone)]
pub(super) struct Attached {
    pub(super) hwnd: isize,
    pub(super) pid: u32,
    pub(super) app: String,
    pub(super) title: String,
    /// Where the window was before it was parked off-screen, while it is.
    pub(super) parked: Option<WINDOWPLACEMENT>,
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

/// Per-session gate between typing and the preview card's captures.
///
/// A capture has the app paint itself into EvoFlux's bitmap (`PrintWindow`)
/// from another thread, whenever the card asks. Arriving while Excel was
/// opening the editor for a cell, it dropped the cell's first characters or
/// the whole cell ("May" became "ay", "=SUM(B7:D7)" became "M(B7:D7)"), in
/// three runs out of four; with no captures every run was exact. Typing
/// holds the gate and opens it only where the app has taken everything in
/// (see `type_text`); a capture waits for it.
static INPUT_GATES: Lazy<Mutex<HashMap<String, Arc<Mutex<()>>>>> = Lazy::new(|| Mutex::new(HashMap::new()));

pub(super) fn input_gate(session_id: &str) -> Arc<Mutex<()>> {
    let mut gates = INPUT_GATES.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
    gates.entry(session_id.to_string()).or_default().clone()
}

pub(super) fn hold_gate(gate: &Mutex<()>) -> std::sync::MutexGuard<'_, ()> {
    gate.lock().unwrap_or_else(|poisoned| poisoned.into_inner())
}

/// How many characters of one run typing posts before letting a waiting
/// preview capture in.
pub(super) const GATE_EVERY_CHARS: usize = 64;

/// How often typing lets a capture in at most: about four preview frames a
/// second while it types. Letting one in at every cell slowed a 120-cell
/// table from 20 to 45 seconds.
pub(super) const GATE_INTERVAL: Duration = Duration::from_millis(250);

/// Let a preview capture that is waiting at `gate` run, then take it back.
/// The short rest gives the waiting thread the lock; the lock itself is not
/// fair, and would otherwise go straight back to typing.
pub(super) fn open_gate<'a>(gate: &'a Mutex<()>, held: std::sync::MutexGuard<'a, ()>) -> std::sync::MutexGuard<'a, ()> {
    drop(held);
    pause(2);
    hold_gate(gate)
}

/// Forget the session's window, without touching the window yet.
pub(super) fn take(session_id: &str) -> Option<Attached> {
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

pub(super) fn off_ui_thread(work: impl FnOnce() + Send + 'static) -> mpsc::Receiver<()> {
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
pub(super) fn release(session_id: &str) -> Option<Attached> {
    let released = take(session_id);
    if let Some(attached) = &released {
        hand_back(attached);
    }
    released
}

pub(super) fn stop(session_id: &str) {
    registry().stopped.insert(session_id.to_string());
    if let Some(attached) = take(session_id) {
        off_ui_thread(move || hand_back(&attached));
    }
}

pub(super) fn resume(session_id: &str) {
    registry().stopped.remove(session_id);
}

/// Put every parked window back. Called when EvoFlux exits so no app is
/// left stranded off-screen — but a hung app cannot hold the exit up for
/// more than a few seconds.
pub(super) fn release_all() {
    let sessions: Vec<String> = registry().attached.keys().cloned().collect();
    let released: Vec<Attached> = sessions.iter().filter_map(|session| take(session)).collect();
    if released.is_empty() {
        return;
    }
    let finished = off_ui_thread(move || released.iter().for_each(hand_back));
    let _ = finished.recv_timeout(Duration::from_secs(3));
}

pub(super) fn reveal(session_id: &str) -> Result<Value, String> {
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

// ── Element refs ────────────────────────────────────────────────────────
//
// Each session's actions run on a worker thread of its own (see
// `workers.rs`), which joined COM in `WindowsBackend::init_worker_thread`.
// The UI Automation objects below are bound to that thread.

thread_local! {
    static AUTOMATION: RefCell<Option<IUIAutomation>> = const { RefCell::new(None) };
    pub(super) static REFS: RefCell<HashMap<String, SessionRefs>> = RefCell::new(HashMap::new());
}

/// The elements a session's snapshots and finds handed out refs for, each
/// with the window it was listed in (the window itself, a dialog, or a
/// popup), so a ref into a window that is no longer in front is refused.
#[derive(Default)]
pub(super) struct SessionRefs {
    pub(super) elements: HashMap<String, (IUIAutomationElement, isize)>,
}

/// Ref numbers are never reused, across snapshots, sessions and attaches: a
/// ref from an earlier snapshot is unknown rather than silently naming
/// whichever control got its number this time.
pub(super) static NEXT_REF: AtomicU32 = AtomicU32::new(0);

pub(super) fn automation() -> Result<IUIAutomation, String> {
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
    LAST_INPUT.with(|last| {
        last.borrow_mut().remove(session_id);
    });
    last_points().remove(session_id);
}
