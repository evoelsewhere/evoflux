//! Interrupting an action.
//!
//! Stop has to end what the agent is doing now, not only refuse what comes
//! next: a `type` of a long text or a drag runs for seconds on the worker.
//! Each action takes a ticket (its session's generation) when it arrives,
//! before it waits in the worker's queue; interrupting a session bumps the
//! generation, and the action's loops check their ticket between steps.

use std::cell::RefCell;
use std::collections::HashMap;
use std::sync::Mutex;

use once_cell::sync::Lazy;

static GENERATIONS: Lazy<Mutex<HashMap<String, u64>>> = Lazy::new(Default::default);

thread_local! {
    /// The ticket of the action running on this thread, if any.
    static TICKET: RefCell<Option<(String, u64)>> = const { RefCell::new(None) };
}

/// The ticket an action arriving for `session_id` now takes.
pub(crate) fn generation(session_id: &str) -> u64 {
    GENERATIONS
        .lock()
        .map(|generations| generations.get(session_id).copied().unwrap_or(0))
        .unwrap_or(0)
}

/// End whatever the session's actions are doing, including ones still
/// waiting their turn.
pub(crate) fn interrupt(session_id: &str) {
    if let Ok(mut generations) = GENERATIONS.lock() {
        *generations.entry(session_id.to_string()).or_insert(0) += 1;
    }
}

/// Run `action` holding `ticket`, so [`interrupted`] can tell whether its
/// session was interrupted since the ticket was taken.
pub(crate) fn with_ticket<T>(session_id: &str, ticket: u64, action: impl FnOnce() -> Result<T, String>) -> Result<T, String> {
    TICKET.with(|slot| *slot.borrow_mut() = Some((session_id.to_string(), ticket)));
    let outcome = interrupted().and_then(|()| action());
    TICKET.with(|slot| *slot.borrow_mut() = None);
    outcome
}

/// `Err` once the running action's session was interrupted. Long actions
/// call this between steps; outside an action it never fails.
pub(crate) fn interrupted() -> Result<(), String> {
    let ticket = TICKET.with(|slot| slot.borrow().clone());
    match ticket {
        Some((session_id, ticket)) if generation(&session_id) != ticket => Err(
            "Interrupted: the user stopped Computer App Control (or the action was cancelled). Nothing after this point was done.".into(),
        ),
        _ => Ok(()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn interrupting_a_session_ends_only_its_actions() {
        // The running action notices at its next check.
        let running = with_ticket("stop-running", generation("stop-running"), || {
            interrupt("stop-running");
            interrupted()
        });
        assert!(running.is_err());
        // An action still queued when Stop came never starts.
        let queued = generation("stop-queued");
        interrupt("stop-queued");
        let mut started = false;
        assert!(with_ticket("stop-queued", queued, || {
            started = true;
            Ok(())
        })
        .is_err());
        assert!(!started);
        // Other sessions, and code outside an action, are unaffected.
        interrupt("stop-other");
        assert!(with_ticket("stop-mine", generation("stop-mine"), interrupted).is_ok());
        assert!(interrupted().is_ok());
    }
}
