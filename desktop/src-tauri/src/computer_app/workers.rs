//! Worker threads.
//!
//! Element refs (UI Automation COM objects, macOS `AXUIElement`s) are bound
//! to the thread that created them and outlive a single command, so each
//! chat session has a worker thread of its own that runs its actions one at
//! a time. One per session rather than one for all: an app that hangs, or a
//! snapshot of a huge tree, only holds up the chat driving it. The app
//! picker in Settings gets its own worker too. A worker retires after a
//! while without work once its session has nothing attached.

use std::cell::RefCell;
use std::collections::HashMap;
use std::sync::mpsc::{self, RecvTimeoutError};
use std::sync::Mutex;
use std::time::Duration;

use once_cell::sync::Lazy;

use super::backend::backend;

type Job = Box<dyn FnOnce() + Send + 'static>;

const IDLE_RETIRE: Duration = Duration::from_secs(10 * 60);

/// The key the app picker's worker runs under; no session id has it.
pub(crate) const APP_PICKER: &str = "\u{0}app-picker";

static WORKERS: Lazy<Mutex<HashMap<String, mpsc::Sender<Job>>>> = Lazy::new(Default::default);

thread_local! {
    static WORKER_KEY: RefCell<Option<String>> = const { RefCell::new(None) };
}

fn workers() -> std::sync::MutexGuard<'static, HashMap<String, mpsc::Sender<Job>>> {
    WORKERS.lock().unwrap_or_else(|poisoned| poisoned.into_inner())
}

/// Whether this thread is the worker for `key`.
#[cfg_attr(not(any(target_os = "windows", target_os = "macos")), allow(dead_code))]
pub(crate) fn on_worker(key: &str) -> bool {
    WORKER_KEY.with(|slot| slot.borrow().as_deref() == Some(key))
}

fn spawn(key: &str) -> Result<mpsc::Sender<Job>, String> {
    let (sender, receiver) = mpsc::channel::<Job>();
    let owned = key.to_string();
    std::thread::Builder::new()
        .name("computer-app".into())
        .spawn(move || {
            WORKER_KEY.with(|slot| *slot.borrow_mut() = Some(owned.clone()));
            backend().init_worker_thread();
            loop {
                match receiver.recv_timeout(IDLE_RETIRE) {
                    Ok(job) => job(),
                    Err(RecvTimeoutError::Timeout) => {
                        let mut map = workers();
                        if backend().is_attached(&owned) {
                            continue;
                        }
                        // A job sent just before the lock was taken still runs.
                        if let Ok(job) = receiver.try_recv() {
                            drop(map);
                            job();
                            continue;
                        }
                        map.remove(&owned);
                        return;
                    }
                    Err(RecvTimeoutError::Disconnected) => return,
                }
            }
        })
        .map_err(|error| format!("could not start the Computer App Control worker: {error}"))?;
    Ok(sender)
}

fn send(key: &str, job: Job) -> Result<(), String> {
    let mut job = job;
    // Twice at most: a worker that retired between being looked up and
    // being sent to is replaced by a fresh one.
    for _ in 0..2 {
        let sender = {
            let mut map = workers();
            match map.get(key) {
                Some(sender) => sender.clone(),
                None => {
                    let sender = spawn(key)?;
                    map.insert(key.to_string(), sender.clone());
                    sender
                }
            }
        };
        match sender.send(job) {
            Ok(()) => return Ok(()),
            Err(mpsc::SendError(returned)) => {
                job = returned;
                workers().remove(key);
            }
        }
    }
    Err("Computer App Control worker is not running".into())
}

/// Queue `job` behind whatever `key`'s worker is running, if that worker
/// exists. For clean-up of thread-bound state from another thread.
#[cfg_attr(not(any(target_os = "windows", target_os = "macos")), allow(dead_code))]
pub(crate) fn post(key: &str, job: impl FnOnce() + Send + 'static) {
    let sender = workers().get(key).cloned();
    if let Some(sender) = sender {
        let _ = sender.send(Box::new(job));
    }
}

/// Run `job` on `key`'s worker and wait for its result.
pub(crate) async fn run<T: Send + 'static>(
    key: &str,
    job: impl FnOnce() -> Result<T, String> + Send + 'static,
) -> Result<T, String> {
    let (reply, result) = tokio::sync::oneshot::channel();
    send(
        key,
        Box::new(move || {
            let outcome = std::panic::catch_unwind(std::panic::AssertUnwindSafe(job))
                .unwrap_or_else(|_| Err("Computer App Control action panicked".to_string()));
            let _ = reply.send(outcome);
        }),
    )?;
    result
        .await
        .map_err(|_| "Computer App Control worker dropped the action".to_string())?
}
